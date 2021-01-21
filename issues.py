import os
from flask import Flask, request, jsonify
from flask.logging import default_handler
from requests import HTTPError
import json
import hashlib
import hmac
import logging
from datetime import datetime
from types import SimpleNamespace
import util
import jiralib
import ghlib


GH_API_URL = os.getenv("GH_API_URL")
assert GH_API_URL != None

GH_USERNAME = os.getenv("GH_USERNAME", "").encode("utf-8")
assert GH_USERNAME != "".encode("utf-8")

GH_TOKEN = os.getenv("GH_TOKEN", "").encode("utf-8")
assert GH_TOKEN != "".encode("utf-8")

KEY = os.getenv("SECRET_TOKEN", "").encode("utf-8")
assert KEY != "".encode("utf-8")

JIRA_URL = os.getenv("JIRA_URL")
assert JIRA_URL != None

JIRA_USERNAME = os.getenv("JIRA_USERNAME")
assert JIRA_USERNAME != None

JIRA_PASSWORD = os.getenv("JIRA_PASSWORD")
assert JIRA_PASSWORD != None

JIRA_PROJECT = os.getenv("JIRA_PROJECT")
assert JIRA_PROJECT != None

REPO_SYNC_INTERVAL = 60 * 60 * 24     # full sync once a day

app = Flask(__name__)
#logging.getLogger('jiralib').addHandler(default_handler)
#logging.getLogger('ghlib').addHandler(default_handler)
logging.basicConfig(level=logging.INFO)

jiraProject = jiralib.Jira(JIRA_URL, JIRA_USERNAME, JIRA_PASSWORD).getProject(JIRA_PROJECT)
github = ghlib.GitHub(GH_API_URL, GH_USERNAME, GH_TOKEN)


def auth_is_valid(signature, request_body):
    if app.debug:
        return True
    return hmac.compare_digest(
        signature.encode('utf-8'), ('sha256=' + hmac.new(KEY, request_body, hashlib.sha256).hexdigest()).encode('utf-8')
    )


last_repo_syncs = {}


@app.route("/jira", methods=["POST"])
def jira_webhook():
    """Handle POST requests coming from JIRA, and pass a translated request to GitHub"""

    # Apparently, JIRA does not support an authentication mechanism for webhooks.
    # To make it slightly more secure, we will just pass a secret token as a URL parameter
    # In addition to that, it might be sensible to only whitelist the JIRA IP address
    if not hmac.compare_digest(request.args.get('secret_token', '').encode('utf-8'), KEY):
        return jsonify({"code": 403, "error": "Unauthorized"}), 403

    payload = json.loads(request.data.decode('utf-8'), object_hook=lambda p: SimpleNamespace(**p))
    event = payload.webhookEvent
    issue = jiralib.JiraIssue(jiraProject, payload.issue)

    app.logger.debug('Received JIRA webhook for event "{event}"'.format(event=event))

    if not issue.is_managed():
        app.logger.debug('Ignoring JIRA webhook for issue not related to a code scanning alert.')
        return jsonify({}), 200

    # we only care about updates and deletions
    if event not in [jiralib.UPDATE_EVENT, jiralib.DELETE_EVENT]:
        app.logger.debug('Ignoring JIRA webhook for event "{event}".'.format(event=event))
        return jsonify({}), 200

    repo_id, alert_num, _, _ = issue.get_alert_info()
    ghrepo = ghlib.GHRepository(github, repo_id)

    try:
        if event == jiralib.UPDATE_EVENT:
            if issue.is_open():
                ghrepo.open_alert(alert_num)
            elif issue.is_closed():
                ghrepo.close_alert(alert_num)
        else:
            ghrepo.close_alert(alert_num)
    except HTTPError as httpe:
        # A 404 suggests that the alert doesn't exist on the
        # Github side and that the JIRA issue is orphaned.
        # We simply ignore this, since it will be fixed during
        # the next scheduled full sync.
        if httpe.response.status_code != 404:
            # propagate everything else
            raise

    return jsonify({}), 200


@app.route("/github", methods=["POST"])
def github_webhook():
    """
    Handle POST requests coming from GitHub, and pass a translated request to JIRA
    By default, flask runs in single-threaded mode, so we don't need to worry about
    any race conditions.
    """

    app.logger.debug('Received GITHUB webhook for event "{event}"'.format(event=request.headers.get("X-GitHub-Event", "")))

    if not auth_is_valid(request.headers.get("X-Hub-Signature-256", "not-provided"), request.data):
        return jsonify({"code": 403, "error": "Unauthorized"}), 403

    json_dict = request.get_json()
    repo_id = json_dict.get("repository", {}).get("full_name")
    transition = json_dict.get("action")

    # When creating a webhook, GitHub will send a 'ping' to check whether the
    # instance is up. If we return a friendly code, the hook will mark as green in the UI.
    if request.headers.get("X-GitHub-Event", "") == "ping":
        return jsonify({}), 200

    githubrepository = ghlib.GHRepository(github, repo_id)

    if request.headers.get("X-GitHub-Event", "") == "repository":
        if transition == 'deleted':
            util.sync_repo(githubrepository, jiraProject)
        return jsonify({"code": 400, "error": "Wrong event type: " + request.headers.get("X-GitHub-Event", "")}), 400

    if request.headers.get("X-GitHub-Event", "") != "code_scanning_alert":
        return jsonify({"code": 400, "error": "Wrong event type: " + request.headers.get("X-GitHub-Event", "")}), 400

    alert = json_dict.get("alert")
    alert_url = alert.get("html_url")
    alert_num = alert.get("number")
    rule_id = alert.get("rule").get("id")
    rule_desc = alert.get("rule").get("id")

    # TODO: We might want to do the following asynchronously, as it could
    # take time to do a full sync on a repo with many alerts / issues
    last_sync = last_repo_syncs.get(repo_id, 0)
    now = datetime.now().timestamp()
    if now - last_sync >= REPO_SYNC_INTERVAL:
        last_repo_syncs[repo_id] = now
        util.sync_repo(githubrepository, jiraProject)

    return update_jira(repo_id,
                       transition,
                       alert_url,
                       alert_num,
                       rule_id,
                       rule_desc)


def update_jira(repo_id, transition,
                alert_url, alert_num,
                rule_id, rule_desc):
    app.logger.debug('Received GITHUB webhook {action} for {alert_url}'.format(action=transition, alert_url=alert_url))

    # we deal with each action type individually, showing the expected
    # behaviour and response codes explicitly
    if transition == "appeared_in_branch":
        app.logger.debug('Nothing to do for "appeared_in_branch"')
        return jsonify({}), 200

    existing_issues = jiraProject.fetch_issues(repo_id, alert_num)

    if transition == "created":
        if not existing_issues:
            jiraProject.create_issue(repo_id, rule_id, rule_desc, alert_url, alert_num)
        else:
            app.logger.info('Issue already exists. Will not recreate it.')
        return jsonify({}), 200

    if not existing_issues:
        return jsonify({"code": 400, "error": "Issue not found"}), 400

    if len(existing_issues) > 1:
        app.logger.warning('Multiple issues found. Selecting by min id.')
        existing_issues.sort(key=lambda i: i.id())

    issue = existing_issues[0]

    if transition in ["closed_by_user", "fixed"]:
        issue.close()
        return jsonify({}), 200

    if transition in ["reopened_by_user", "reopened"]:
        issue.open()
        return jsonify({}), 200

    # when the transition is not recognised, we return a bad request response
    return (
        jsonify({"code": 400, "error": "unknown transition type - %s" % transition}),
        400,
    )



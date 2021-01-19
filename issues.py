import os
from flask import Flask, request, jsonify
from flask.logging import default_handler
import requests
from requests import HTTPError
import json
import hashlib
import hmac
import logging
import itertools
from datetime import datetime
from types import SimpleNamespace
import util
import jiralib


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

REQUEST_TIMEOUT = 10
REPO_SYNC_INTERVAL = 60 * 60 * 24     # full sync once a day

app = Flask(__name__)
logging.getLogger('jiralib').addHandler(default_handler)
logging.basicConfig(level=logging.INFO)

jiraProject = jiralib.Jira(JIRA_URL, JIRA_USERNAME, JIRA_PASSWORD).getProject(JIRA_PROJECT)


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

    try:
        if event == jiralib.UPDATE_EVENT:
            if issue.is_open():
                open_alert(repo_id, alert_num)
            elif issue.is_closed():
                close_alert(repo_id, alert_num)
        else:
            close_alert(repo_id, alert_num)
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

    # When creating a webhook, GitHub will send a 'ping' to check whether the
    # instance is up. If we return a friendly code, the hook will mark as green in the UI.
    if request.headers.get("X-GitHub-Event", "") == "ping":
        return jsonify({}), 200

    if request.headers.get("X-GitHub-Event", "") != "code_scanning_alert":
        return jsonify({"code": 400, "error": "Wrong event type: " + request.headers.get("X-GitHub-Event", "")}), 400

    json_dict = request.get_json()
    repo_name = json_dict.get("repository").get("full_name")
    alert = json_dict.get("alert")
    transition = json_dict.get("action")
    alert_url = alert.get("html_url")
    alert_num = alert.get("number")
    rule_id = alert.get("rule").get("id")
    rule_desc = alert.get("rule").get("id")

    # TODO: We might want to do the following asynchronously, as it could
    # take time to do a full sync on a repo with many alerts / issues
    last_sync = last_repo_syncs.get(repo_name, 0)
    now = datetime.now().timestamp()
    if now - last_sync >= REPO_SYNC_INTERVAL:
        last_repo_syncs[repo_name] = now
        sync_repo(repo_name)

    return update_jira(repo_name,
                       transition,
                       alert_url,
                       alert_num,
                       rule_id,
                       rule_desc)


def update_jira(repo_name, transition,
                alert_url, alert_num,
                rule_id, rule_desc):
    app.logger.debug('Received GITHUB webhook {action} for {alert_url}'.format(action=transition, alert_url=alert_url))

    # we deal with each action type individually, showing the expected
    # behaviour and response codes explicitly
    if transition == "appeared_in_branch":
        app.logger.debug('Nothing to do for "appeared_in_branch"')
        return jsonify({}), 200

    if transition == "created":
        jiraProject.create_issue(repo_name, rule_id, rule_desc, alert_url, alert_num)
        return jsonify({}), 200

    # if not creating a ticket, there should be an issue_id defined
    existing_issues = jiraProject.fetch_issues(repo_name, alert_num)

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


def get_alerts(repo_id, state = None):
    if state:
        state = '&state=' + state
    else:
        state = ''

    for page in itertools.count(start=1):
        headers = {'Accept': 'application/vnd.github.v3+json'}
        resp = requests.get('{api_url}/repos/{repo_id}/code-scanning/alerts?per_page=100&page={page}{state}'.format(
                                api_url=GH_API_URL,
                                repo_id=repo_id,
                                page=page,
                                state=state
                            ),
                            headers=headers,
                            auth=(GH_USERNAME, GH_TOKEN),
                            timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()

        if not resp.json():
            break

        for a in resp.json():
            yield a


def get_alert(repo_id, alert_num):
    headers = {'Accept': 'application/vnd.github.v3+json'}
    resp = requests.get('{api_url}/repos/{repo_id}/code-scanning/alerts/{alert_num}'.format(
                            api_url=GH_API_URL,
                            repo_id=repo_id,
                            alert_num=alert_num
                        ),
                        headers=headers,
                        auth=(GH_USERNAME, GH_TOKEN),
                        timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def open_alert(repo_id, alert_num):
    state = get_alert(repo_id, alert_num)['state']
    if state != 'open':
        app.logger.info('Reopen alert {alert_num} of repository "{repo_id}".'.format(alert_num=alert_num, repo_id=repo_id))
        update_alert(repo_id, alert_num, 'open')


def close_alert(repo_id, alert_num):
    state = get_alert(repo_id, alert_num)['state']
    if state != 'dismissed':
        app.logger.info('Closing alert {alert_num} of repository "{repo_id}".'.format(alert_num=alert_num, repo_id=repo_id))
        update_alert(repo_id, alert_num, 'dismissed')


def update_alert(repo_id, alert_num, state):
    headers = {'Accept': 'application/vnd.github.v3+json'}
    reason = ''
    if state == 'dismissed':
        reason = ', "dismissed_reason": "won\'t fix"'
    data = '{{"state": "{state}"{reason}}}'.format(state=state, reason=reason)
    resp = requests.patch('{api_url}/repos/{repo_id}/code-scanning/alerts/{alert_num}'.format(
                              api_url=GH_API_URL,
                              repo_id=repo_id,
                              alert_num=alert_num
                          ),
                          data=data,
                          headers=headers,
                          auth=(GH_USERNAME, GH_TOKEN),
                          timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()


def sync_repo(repo_name):
    app.logger.info('Starting full sync for repository "{repo_name}"...'.format(repo_name=repo_name))

    # fetch code scanning alerts from GitHub
    cs_alerts = []
    try:
        cs_alerts = {util.make_key(repo_name + '/' + str(a['number'])): a for a in get_alerts(repo_name)}
    except HTTPError as httpe:
        # if we receive a 404, the repository does not exist,
        # so we will delete all related JIRA alert issues
        if httpe.response.status_code != 404:
            # propagate everything else
            raise

    # fetch issues from JIRA and delete duplicates and ones which can't be matched
    jira_issues = {}
    for i in jiraProject.fetch_issues(repo_name):
        _, _, _, key = i.get_alert_info()
        if key in jira_issues:
            app.logger.info('Deleting duplicate jira alert issue {key}.'.format(key=i.key()))
            i.delete()   # TODO - seems scary, are we sure....
        elif key not in cs_alerts:
            app.logger.info('Deleting orphaned jira alert issue {key}.'.format(key=i.key()))
            i.delete()   # TODO - seems scary, are we sure....
        else:
            jira_issues[key] = i

    # create missing issues
    for key in cs_alerts:
        if key not in jira_issues:
            alert = cs_alerts[key]
            rule = alert['rule']

            jira_issues[key] = jiraProject.create_issue(
                repo_name,
                rule['id'],
                rule['description'],
                alert['html_url'],
                alert['number']
            )

    # adjust issue states
    for key in cs_alerts:
        alert = cs_alerts[key]
        issue = jira_issues[key]
        astatus = alert['state']

        if astatus == 'open':
            issue.open()
        else:
            issue.close()

import os
from flask import Flask, request, jsonify

import requests
import json
import hashlib
import hmac
import logging
from jira import JIRA
import itertools
import re
from datetime import datetime


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

# May need to be changed depending on JIRA project type
CLOSE_TRANSITION = "Done"
REOPEN_TRANSITION = "To Do"

REQUEST_TIMEOUT = 10
REPO_SYNC_INTERVAL = 60 * 60 * 24     # full sync once a day

jira = JIRA(JIRA_URL, auth=(JIRA_USERNAME, JIRA_PASSWORD))

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

def auth_is_valid(signature, request_body):
    if app.debug:
        return True
    return hmac.compare_digest(
        signature.encode('utf-8'), ('sha256=' + hmac.new(KEY, request_body, hashlib.sha256).hexdigest().encode('utf-8').decode('utf-8')).encode('utf-8')
    )

DESC_TEMPLATE="""
{rule_desc}

{alert_url}

----
This issue was automatically generated from a GitHub alert, and will be automaticall resolved once underlying problem is fixed.
DO NOT MODIFY DESCRIPTION BELOW LINE.
GH_ALERT_LOOKUP={repo_name}/code_scanning/{alert_num}
"""

last_repo_syncs = {}


@app.route("/jira", methods=["POST"])
def jira_webhook():
    """Handle POST requests coming from JIRA, and pass a translated request to GitHub"""

    # Apparently, JIRA does not support an authentication mechanism for webhooks.
    # To make it slightly more secure, we will just pass a secret token as a URL parameter
    # In addition to that, it might be sensible to only whitelist the JIRA IP address
    app.logger.info(request.args['secret_token'])

    #TODO: Implementation

    return jsonify({}), 200


@app.route("/github", methods=["POST"])
def github_webhook():
    """
    Handle POST requests coming from GitHub, and pass a translated request to JIRA
    By default, flask runs in single-threaded mode, so we don't need to worry about
    any race conditions.
    """

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
    app.logger.info('Received {action} for {alert_url}'.format(action=transition, alert_url=alert_url))

    # we deal with each action type individually, showing the expected
    # behaviour and response codes explicitly
    if transition == "appeared_in_branch":
        app.logger.info('Nothing to do for appeared_in_branch')
        return jsonify({}), 200

    if transition == "created":
        app.logger.info('Creating new issue')
        jira_issue = jira.create_issue(
            project=JIRA_PROJECT,
            summary='{rule} in {repo}'.format(rule=rule_id, repo=repo_name),
            description=DESC_TEMPLATE.format(
                rule_desc=rule_desc,
                alert_url=alert_url,
                repo_name=repo_name,
                alert_num=alert_num,
            ),
            issuetype={'name': 'Bug'}
        )
        app.logger.info('Created issue ' + jira_issue.key)
        return jsonify({}), 200

    # if not creating a ticket, there should be an issue_id defined
    issue_search = 'project={jira_project} and description ~ "\\"GH_ALERT_LOOKUP={repo_name}/code_scanning/{alert_num}\\""'.format(
        jira_project=JIRA_PROJECT,
        repo_name=repo_name,
        alert_num=alert_num,
    )
    app.logger.info('Searching for issue to update: ' + issue_search)
    existing_issues = jira.search_issues(issue_search)

    if not existing_issues:
        app.logger.error('No issues found for query: ' + issue_search)
        return jsonify({"code": 400, "error": "Issue not found"}), 400

    if len(existing_issues) > 1:
        app.logger.warning('Multiple issues found for: ' + issue_search + '. Selecting by min id.')
        existing_issues.sort(key=lambda i: i.id)

    issue = existing_issues[0]
    app.logger.info('Found issue to update: ' + issue.key)

    jira_transitions = {t['name'] : t['id'] for t in jira.transitions(issue)}

    if transition in ["closed_by_user", "fixed"]:
        if CLOSE_TRANSITION not in jira_transitions:
            app.logger.error('Transition "{close_transition}" not available for {issue_key}. Valid transition: {jira_transitions}'.format(
                close_transition=CLOSE_TRANSITION,
                issue_key=issue.key,
                jira_transitions=list(jira_transitions)
            ))
            return jsonify({"code": 400, "error": "Close transition not found"}), 400
        else:
            jira.transition_issue(issue, jira_transitions[CLOSE_TRANSITION])
            return jsonify({}), 200

    if transition in ["reopened_by_user", "reopened"]:
        if REOPEN_TRANSITION not in jira_transitions:
            app.logger.error('Transition "{reopen_transition}" not available for {issue_key}. Valid transition: {jira_transitions}'.format(
                reopen_transition=REOPEN_TRANSITION,
                issue_key=issue.key,
                jira_transitions=list(jira_transitions)
            ))
            return jsonify({"code": 400, "error": "Close transition not found"}), 400
        else:
            jira.transition_issue(issue, jira_transitions[REOPEN_TRANSITION])
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


def get_issue_id(issue):
    result = re.search('GH_ALERT_LOOKUP=.*$', issue.fields.description, re.MULTILINE)
    return '' if result is None else result[0][16:]


def transition_issue(issue, transition):
    jira_transitions = {t['name'] : t['id'] for t in jira.transitions(issue)}
    jira.transition_issue(issue, jira_transitions[transition])


def create_issue(repo_name, rule_id, rule_desc, alert_url, alert_num):
    return jira.create_issue(
        project=JIRA_PROJECT,
        summary='{rule} in {repo}'.format(rule=rule_id, repo=repo_name),
        description=DESC_TEMPLATE.format(
            rule_desc=rule_desc,
            alert_url=alert_url,
            repo_name=repo_name,
            alert_num=alert_num,
        ),
        issuetype={'name': 'Bug'}
    )


def sync_repo(repo_name):
    app.logger.info('Starting full sync for repository "{repo_name}"...'.format(repo_name=repo_name))

    # fetch code scanning alerts from GitHub
    cs_alerts = {repo_name + '/code_scanning/' + str(a['number']): a for a in get_alerts(repo_name)}

    # fetch issues from JIRA and delete duplicates and ones which can't be matched
    issue_search = 'project={jira_project} and description ~ "\\"GH_ALERT_LOOKUP={repo_name}/\\""'.format(
        jira_project=JIRA_PROJECT,
        repo_name=repo_name,
    )
    jira_issues = {}
    for i in jira.search_issues(issue_search, maxResults=0):
        key = get_issue_id(i)
        if key in jira_issues:
            app.logger.info('Deleting duplicate jira alert issue.')
            i.delete()
        elif key not in cs_alerts:
            app.logger.info('Deleting orphaned jira alert issue.')
            i.delete()
        else:
            jira_issues[key] = i

    # create missing issues
    for key in cs_alerts:
        if key not in jira_issues:
          alert = cs_alerts[key]
          rule = alert['rule']

          app.logger.info(
              'Creating missing issue for alert {num} in {repo_name}.'.format(
                  num=alert['number'],
                  repo_name=repo_name
              )
          )
          jira_issues[key] = create_issue(
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
        istatus = str(issue.fields.status)
        astatus = alert['state']

        if astatus == 'open' and istatus != REOPEN_TRANSITION:
            app.logger.info(
                '{repo_name}: Adjusting issue status from "{old}" to "{new}"'.format(
                    repo_name=repo_name,
                    old=istatus,
                    new=REOPEN_TRANSITION
                )
            )
            transition_issue(issue, REOPEN_TRANSITION)
        elif astatus != 'open' and istatus != CLOSE_TRANSITION:
            app.logger.info(
                '{repo_name}: Adjusting issue status from "{old}" to "{new}"'.format(
                    repo_name=repo_name,
                    old=istatus,
                    new=CLOSE_TRANSITION
                )
            )
            transition_issue(issue, CLOSE_TRANSITION)

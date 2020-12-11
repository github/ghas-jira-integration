import os
from flask import Flask, request, jsonify

import requests
import json
import hashlib
import hmac
import logging
from jira import JIRA


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

jira = JIRA(JIRA_URL, auth=(JIRA_USERNAME, JIRA_PASSWORD))

app = Flask(__name__)

logging.basicConfig(level=logging.DEBUG)

def auth_is_valid(signature, request_body):
    if app.debug:
        return True
    return hmac.compare_digest(
        signature.encode('utf-8'), 'sha256=' + hmac.new(KEY, request_body, hashlib.sha256).hexdigest().encode('utf-8')
    )

DESC_TEMPLATE="""
{rule_desc}

{alert_url}

----
This issue was automatically generated from a GitHub alert, and will be automaticall resolved once underlying problem is fixed.
DO NOT MODIFY DESCRIPTION BELOW LINE.
GH_ALERT_LOOKUP={repo_name}/code_scanning/{alert_num}
"""

@app.route("/github", methods=["POST"])
def github_webhook():
    """Handle POST requests coming from GitHub, and pass a translated request to JIRA"""

    if not auth_is_valid(request.headers.get("X-Hub-Signature-256", "not-provided"), request.data):
        return jsonify({"code": 403, "error": "Unauthorized"}), 403

    if request.headers.get("X-GitHub-Event", "") != "code_scanning_alert":
        return jsonify({"code": 400, "error": "Wrong event type: " + request.headers.get("X-GitHub-Event", "")}), 400

    json_dict = request.get_json()

    transition = json_dict.get("action")
    alert_url = json_dict.get("alert").get("html_url")
    alert_num = json_dict.get("alert").get("number")
    rule_id = json_dict.get("alert").get("rule").get("id")
    rule_desc = json_dict.get("alert").get("rule").get("id")
    repo_name = json_dict.get("repository").get("full_name")

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

    if transition in ["closed_by_user", "fixed"] :
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

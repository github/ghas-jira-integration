import os
from flask import Flask, request, jsonify

import requests
from requests import HTTPError
import json
import hashlib
import hmac
import logging
from jira import JIRA
import itertools
import re
from datetime import datetime
from types import SimpleNamespace


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
JIRA_CLOSE_TRANSITION = "Done"
JIRA_REOPEN_TRANSITION = "To Do"
JIRA_OPEN_STATUS = "To Do"
JIRA_CLOSED_STATUS = "Done"

# JIRA Webhook events
JIRA_DELETE_EVENT = 'jira:issue_deleted'
JIRA_UPDATE_EVENT = 'jira:issue_updated'

REQUEST_TIMEOUT = 10
REPO_SYNC_INTERVAL = 60 * 60 * 24     # full sync once a day

jira = JIRA(JIRA_URL, auth=(JIRA_USERNAME, JIRA_PASSWORD))

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

def auth_is_valid(signature, request_body):
    if app.debug:
        return True
    return hmac.compare_digest(
        signature.encode('utf-8'), ('sha256=' + hmac.new(KEY, request_body, hashlib.sha256).hexdigest()).encode('utf-8')
    )

JIRA_DESC_TEMPLATE="""
{rule_desc}

{alert_url}

----
This issue was automatically generated from a GitHub alert, and will be automatically resolved once the underlying problem is fixed.
DO NOT MODIFY DESCRIPTION BELOW LINE.
REPOSITORY_NAME={repo_name}
ALERT_NUMBER={alert_num}
REPOSITORY_KEY={repo_key}
ALERT_KEY={alert_key}
"""

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
    issue = payload.issue

    app.logger.debug('Received JIRA webhook for event "{event}"'.format(event=event))

    if not is_managed(issue):
        app.logger.debug('Ignoring JIRA webhook for issue not related to a code scanning alert.')
        return jsonify({}), 200

    # we only care about updates and deletions
    if event not in [JIRA_UPDATE_EVENT, JIRA_DELETE_EVENT]:
        app.logger.debug('Ignoring JIRA webhook for event "{event}".'.format(event=event))
        return jsonify({}), 200

    repo_id, alert_num, _, _ = get_alert_info(issue)

    try:
        if event == JIRA_UPDATE_EVENT:
            istatus = issue.fields.status.name
            if istatus == JIRA_OPEN_STATUS:
                open_alert(repo_id, alert_num)
            elif istatus == JIRA_CLOSED_STATUS:
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
        jira_issue = create_issue(repo_name, rule_id, rule_desc, alert_url, alert_num)
        return jsonify({}), 200

    # if not creating a ticket, there should be an issue_id defined
    existing_issues = fetch_issues(repo_name, alert_num)

    if not existing_issues:
        return jsonify({"code": 400, "error": "Issue not found"}), 400

    if len(existing_issues) > 1:
        app.logger.warning('Multiple issues found. Selecting by min id.')
        existing_issues.sort(key=lambda i: i.id)

    issue = existing_issues[0]

    if transition in ["closed_by_user", "fixed"]:
        close_issue(issue)
        return jsonify({}), 200

    if transition in ["reopened_by_user", "reopened"]:
        open_issue(issue)
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


def is_managed(issue):
    if parse_alert_info(issue.fields.description)[0] is None:
        return False
    return True


def parse_alert_info(desc):
    '''
    Parse all the fieldsin an issue's description and return
    them as a tuple. If parsing fails for one of the fields,
    return a tuple of None's.
    '''
    failed = None, None, None, None
    m = re.search('REPOSITORY_NAME=(.*)$', desc, re.MULTILINE)
    if m is None:
        return failed
    repo_id = m.group(1)
    m = re.search('ALERT_NUMBER=(.*)$', desc, re.MULTILINE)
    if m is None:
        return failed
    alert_num = m.group(1)
    m = re.search('REPOSITORY_KEY=(.*)$', desc, re.MULTILINE)
    if m is None:
        return failed
    repo_key = m.group(1)
    m = re.search('ALERT_KEY=(.*)$', desc, re.MULTILINE)
    if m is None:
        return failed
    alert_key = m.group(1)
    return repo_id, alert_num, repo_key, alert_key


def get_alert_info(issue):
    return parse_alert_info(issue.fields.description)


def fetch_issues(repo_name, alert_num=None):
    key = make_key(repo_name + (('/' + str(alert_num)) if alert_num is not None else ''))
    issue_search = 'project={jira_project} and description ~ "{key}"'.format(
        jira_project=JIRA_PROJECT,
        key=key
    )
    result = list(filter(is_managed, jira.search_issues(issue_search, maxResults=0)))
    app.logger.debug('Search {search} returned {num_results} results.'.format(
        search=issue_search,
        num_results=len(result)
    ))
    return result


def open_issue(issue):
    transition_issue(issue, JIRA_REOPEN_TRANSITION)


def close_issue(issue):
    transition_issue(issue, JIRA_CLOSE_TRANSITION)


def transition_issue(issue, transition):
    jira_transitions = {t['name'] : t['id'] for t in jira.transitions(issue)}
    if transition not in jira_transitions:
        app.logger.error('Transition "{transition}" not available for {issue_key}. Valid transitions: {jira_transitions}'.format(
            transition=transition,
            issue_key=issue.key,
            jira_transitions=list(jira_transitions)
        ))
        raise Exception("Invalid JIRA transition")

    old_issue_status = str(issue.fields.status)

    if old_issue_status == JIRA_OPEN_STATUS and transition == JIRA_REOPEN_TRANSITION or \
       old_issue_status == JIRA_CLOSED_STATUS and transition == JIRA_CLOSE_TRANSITION:
        # nothing to do
        return

    jira.transition_issue(issue, jira_transitions[transition])

    app.logger.info(
        'Adjusted status for issue {issue_key} from "{old_issue_status}" to "{new_issue_status}".'.format(
            issue_key=issue.key,
            old_issue_status=old_issue_status,
            new_issue_status=JIRA_CLOSED_STATUS if (old_issue_status == JIRA_OPEN_STATUS) else JIRA_OPEN_STATUS
        )
    )


def create_issue(repo_id, rule_id, rule_desc, alert_url, alert_num):
    result = jira.create_issue(
        project=JIRA_PROJECT,
        summary='{rule} in {repo}'.format(rule=rule_id, repo=repo_id),
        description=JIRA_DESC_TEMPLATE.format(
            rule_desc=rule_desc,
            alert_url=alert_url,
            repo_name=repo_id,
            alert_num=alert_num,
            repo_key=make_key(repo_id),
            alert_key=make_key(repo_id + '/' + str(alert_num))
        ),
        issuetype={'name': 'Bug'}
    )
    app.logger.info('Created issue {issue_key} for alert {alert_num} in {repo_id}.'.format(
        issue_key=result.key,
        alert_num=alert_num,
        repo_id=repo_id
    ))

    return result


def sync_repo(repo_name):
    app.logger.info('Starting full sync for repository "{repo_name}"...'.format(repo_name=repo_name))

    # fetch code scanning alerts from GitHub
    cs_alerts = []
    try:
        cs_alerts = {make_key(repo_name + '/' + str(a['number'])): a for a in get_alerts(repo_name)}
    except HTTPError as httpe:
        # if we receive a 404, the repository does not exist,
        # so we will delete all related JIRA alert issues
        if httpe.response.status_code != 404:
            # propagate everything else
            raise

    # fetch issues from JIRA and delete duplicates and ones which can't be matched
    jira_issues = {}
    for i in fetch_issues(repo_name):
        _, _, _, key = get_alert_info(i)
        if key in jira_issues:
            app.logger.info('Deleting duplicate jira alert issue {key}.'.format(key=i.key))
            i.delete()   # TODO - seems scary, are we sure....
        elif key not in cs_alerts:
            app.logger.info('Deleting orphaned jira alert issue {key}.'.format(key=i.key))
            i.delete()   # TODO - seems scary, are we sure....
        else:
            jira_issues[key] = i

    # create missing issues
    for key in cs_alerts:
        if key not in jira_issues:
            alert = cs_alerts[key]
            rule = alert['rule']

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

        if astatus == 'open':
            open_issue(issue)
        else:
            close_issue(issue)


def make_key(s):
    sha_1 = hashlib.sha1()
    sha_1.update(s.encode('utf-8'))
    return sha_1.hexdigest()

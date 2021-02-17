from jira import JIRA
import hashlib
import re
import util
import logging
import requests
import json

REQUEST_TIMEOUT = 10

# May need to be changed depending on JIRA project type
CLOSE_TRANSITION = "Done"
REOPEN_TRANSITION = "To Do"
CLOSED_STATUS = "Done"

# JIRA Webhook events
UPDATE_EVENT = 'jira:issue_updated'
CREATE_EVENT = 'jira:issue_created'
DELETE_EVENT = 'jira:issue_deleted'

TITLE_PREFIX = '[Code Scanning Alert]:'

DESC_TEMPLATE="""
{rule_desc}

{alert_url}

----
This issue was automatically generated from a GitHub alert, and will be automatically resolved once the underlying problem is fixed.
DO NOT MODIFY DESCRIPTION BELOW LINE.
REPOSITORY_NAME={repo_id}
ALERT_NUMBER={alert_num}
REPOSITORY_KEY={repo_key}
ALERT_KEY={alert_key}
"""

logger = logging.getLogger(__name__)


class Jira:
    def __init__(self, url, user, token):
        self.url = url
        self.user = user
        self.token = token
        self.j = JIRA(url, basic_auth=(user, token))


    def auth(self):
        return self.user, self.token


    def getProject(self, projectkey):
        return JiraProject(self, projectkey)


    def list_hooks(self):
        resp = requests.get(
            '{api_url}/rest/webhooks/1.0/webhook'.format(api_url=self.url),
            headers={'Content-Type': 'application/json'},
            auth=self.auth(),
            timeout=util.REQUEST_TIMEOUT
        )
        resp.raise_for_status()

        for h in resp.json():
            yield h


    def create_hook(
        self, name, url, secret,
        events=[CREATE_EVENT, DELETE_EVENT, UPDATE_EVENT],
        filters={'issue-related-events-section': ''},
        exclude_body=False
    ):
        data = json.dumps({
            'name': name,
            'url': url + '?secret_token=' + secret,
            'events': events,
            'filters': filters,
            'excludeBody': exclude_body
        })
        resp = requests.post(
            '{api_url}/rest/webhooks/1.0/webhook'.format(api_url=self.url),
            headers={'Content-Type': 'application/json'},
            data=data,
            auth=self.auth(),
            timeout=util.REQUEST_TIMEOUT
        )
        resp.raise_for_status()

        return resp.json()


class JiraProject:
    def __init__(self, jira, projectkey):
        self.jira = jira
        self.projectkey = projectkey
        self.j = self.jira.j


    def create_issue(self, repo_id, rule_id, rule_desc, alert_url, alert_num):
        raw = self.j.create_issue(
            project=self.projectkey,
            summary='{prefix} {rule} in {repo}'.format(
                prefix=TITLE_PREFIX,
                rule=rule_id,
                repo=repo_id
            ),
            description=DESC_TEMPLATE.format(
                rule_desc=rule_desc,
                alert_url=alert_url,
                repo_id=repo_id,
                alert_num=alert_num,
                repo_key=util.make_key(repo_id),
                alert_key=util.make_alert_key(repo_id, alert_num)
            ),
            issuetype={'name': 'Bug'}
        )
        logger.info('Created issue {issue_key} for alert {alert_num} in {repo_id}.'.format(
            issue_key=raw.key,
            alert_num=alert_num,
            repo_id=repo_id
        ))

        return JiraIssue(self, raw)


    def fetch_issues(self, repo_id, alert_num=None):
        if alert_num is None:
            key = util.make_key(repo_id)
        else:
            key = util.make_alert_key(repo_id, alert_num)
        issue_search = 'project={jira_project} and description ~ "{key}"'.format(
            jira_project=self.projectkey,
            key=key
        )
        issues = list(filter(lambda i: i.is_managed(), [JiraIssue(self, raw) for raw in self.j.search_issues(issue_search, maxResults=0)]))
        logger.debug('Search {search} returned {num_results} results.'.format(
            search=issue_search,
            num_results=len(issues)
        ))
        return issues


class JiraIssue:
    def __init__(self, project, rawissue):
        self.project = project
        self.rawissue = rawissue
        self.j = self.project.j


    def is_managed(self):
        if parse_alert_info(self.rawissue.fields.description)[0] is None:
            return False
        return True


    def get_alert_info(self):
        return parse_alert_info(self.rawissue.fields.description)


    def key(self):
        return self.rawissue.key


    def id(self):
        return self.rawissue.id


    def delete(self):
        logger.info('Deleting issue {ikey}.'.format(ikey=self.key()))
        self.rawissue.delete()


    def get_state(self):
        return parse_state(self.rawissue.fields.status.name)


    def adjust_state(self, state):
        if state:
            self.transition(REOPEN_TRANSITION)
        else:
            self.transition(CLOSE_TRANSITION)


    def transition(self, transition):
        old_issue_status = str(self.rawissue.fields.status.name)

        if self.get_state() and transition == REOPEN_TRANSITION or \
        not self.get_state() and transition == CLOSE_TRANSITION:
            # nothing to do
            return

        jira_transitions = {t['name'] : t['id'] for t in self.j.transitions(self.rawissue)}
        if transition not in jira_transitions:
            logger.error('Transition "{transition}" not available for {issue_key}. Valid transitions: {jira_transitions}'.format(
                transition=transition,
                issue_key=self.rawissue.key,
                jira_transitions=list(jira_transitions)
            ))
            raise Exception("Invalid JIRA transition")

        self.j.transition_issue(self.rawissue, jira_transitions[transition])

        action = 'Reopening' if transition == REOPEN_TRANSITION else 'Closing'
        logger.info(
            '{action} issue {issue_key}'.format(
                action=action,
                issue_key=self.rawissue.key
            )
        )


def parse_alert_info(desc):
    '''
    Parse all the fields in an issue's description and return
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

    # consistency checks:
    if repo_key != util.make_key(repo_id) \
    or alert_key != util.make_alert_key(repo_id, alert_num):
        return failed

    return repo_id, alert_num, repo_key, alert_key


def parse_state(raw_state):
    return raw_state != CLOSED_STATUS

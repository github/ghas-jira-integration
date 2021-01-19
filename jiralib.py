from jira import JIRA
import hashlib
import re
import util
import logging

# May need to be changed depending on JIRA project type
CLOSE_TRANSITION = "Done"
REOPEN_TRANSITION = "To Do"
OPEN_STATUS = "To Do"
CLOSED_STATUS = "Done"

# JIRA Webhook events
DELETE_EVENT = 'jira:issue_deleted'
UPDATE_EVENT = 'jira:issue_updated'

DESC_TEMPLATE="""
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

logger = logging.getLogger(__name__)


class Jira:
    def __init__(self, url, user, token):
        self.url = url
        self.user = user
        self.token = token
        self.j = JIRA(url, auth=(user, token))

    def getProject(self, projectkey):
        return JiraProject(self, projectkey)


class JiraProject:
    def __init__(self, jira, projectkey):
        self.jira = jira
        self.projectkey = projectkey
        self.j = self.jira.j


    def create_issue(self, repo_id, rule_id, rule_desc, alert_url, alert_num):
        raw = self.j.create_issue(
            project=self.projectkey,
            summary='{rule} in {repo}'.format(rule=rule_id, repo=repo_id),
            description=DESC_TEMPLATE.format(
                rule_desc=rule_desc,
                alert_url=alert_url,
                repo_name=repo_id,
                alert_num=alert_num,
                repo_key=util.make_key(repo_id),
                alert_key=util.make_key(repo_id + '/' + str(alert_num))
            ),
            issuetype={'name': 'Bug'}
        )
        logger.info('Created issue {issue_key} for alert {alert_num} in {repo_id}.'.format(
            issue_key=raw.key,
            alert_num=alert_num,
            repo_id=repo_id
        ))

        return JiraIssue(raw)


    def fetch_issues(self, repo_name, alert_num=None):
        key = util.make_key(repo_name + (('/' + str(alert_num)) if alert_num is not None else ''))
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


    def key():
        return self.rawissue.key


    def id():
        return self.rawissue.id


    def delete(self):
        self.rawissue.delete()


    def is_open(self):
        return self.rawissue.fields.status.name == OPEN_STATUS


    def is_closed(self):
        return self.rawissue.fields.status.name == CLOSED_STATUS


    def open(self):
        self.transition(REOPEN_TRANSITION)


    def close(self):
        self.transition(CLOSE_TRANSITION)


    def transition(self, transition):
        jira_transitions = {t['name'] : t['id'] for t in self.j.transitions(self.rawissue)}
        if transition not in jira_transitions:
            logger.error('Transition "{transition}" not available for {issue_key}. Valid transitions: {jira_transitions}'.format(
                transition=transition,
                issue_key=self.rawissue.key,
                jira_transitions=list(jira_transitions)
            ))
            raise Exception("Invalid JIRA transition")

        old_issue_status = str(self.rawissue.fields.status)

        if old_issue_status == OPEN_STATUS and transition == REOPEN_TRANSITION or \
          old_issue_status == CLOSED_STATUS and transition == CLOSE_TRANSITION:
            # nothing to do
            return

        self.j.transition_issue(self.rawissue, jira_transitions[transition])

        logger.info(
            'Adjusted status for issue {issue_key} from "{old_issue_status}" to "{new_issue_status}".'.format(
                issue_key=self.rawissue.key,
                old_issue_status=old_issue_status,
                new_issue_status=CLOSED_STATUS if (old_issue_status == OPEN_STATUS) else OPEN_STATUS
            )
        )


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

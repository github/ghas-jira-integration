import hashlib
from requests import HTTPError
import logging
from datetime import datetime
import jiralib
import ghlib
import json
import os.path


REQUEST_TIMEOUT = 10

logger = logging.getLogger(__name__)

DIRECTION_G2J = 1
DIRECTION_J2G = 2
DIRECTION_BOTH = 3


def make_key(s):
    sha_1 = hashlib.sha1()
    sha_1.update(s.encode('utf-8'))
    return sha_1.hexdigest()


def make_alert_key(repo_id, alert_num):
    return make_key(repo_id + '/' + str(alert_num))


def json_accept_header():
    return {'Accept': 'application/vnd.github.v3+json'}


def states_from_file(states_file):
    if not os.path.isfile(states_file):
        states_to_file(states_file, {})   # create a file if it doesn't yet exist
    with open(states_file, 'r') as f:
        return json.load(f)


def states_to_file(states_file, states):
    with open(states_file, 'w') as f:
        return json.dump(
            states,
            f,
            indent=2,
            sort_keys=True
        )


class Sync:
    def __init__(
        self,
        github,
        jira_project,
        states=None,
        direction=DIRECTION_BOTH
    ):
        self.github = github
        self.jira = jira_project
        self.states = {} if states is None else states
        self.direction = direction


    def alert_created(self, repo_id, alert_num):
        self.sync(
            self.github.getRepository(repo_id).get_alert(alert_num),
            self.jira.fetch_issues(repo_id, alert_num),
            DIRECTION_G2J
        )


    def alert_changed(self, repo_id, alert_num):
        self.sync(
            self.github.getRepository(repo_id).get_alert(alert_num),
            self.jira.fetch_issues(repo_id, alert_num),
            DIRECTION_G2J
        )


    def alert_fixed(self, repo_id, alert_num):
        self.sync(
            self.github.getRepository(repo_id).get_alert(alert_num),
            self.jira.fetch_issues(repo_id, alert_num),
            DIRECTION_G2J
        )


    def issue_created(self, desc):
        repo_id, alert_num, _, _ = jiralib.parse_alert_info(desc)
        self.sync(
            self.github.getRepository(repo_id).get_alert(alert_num),
            self.jira.fetch_issues(repo_id, alert_num),
            DIRECTION_J2G
        )


    def issue_changed(self, desc):
        repo_id, alert_num, _, _ = jiralib.parse_alert_info(desc)
        self.sync(
            self.github.getRepository(repo_id).get_alert(alert_num),
            self.jira.fetch_issues(repo_id, alert_num),
            DIRECTION_J2G
        )


    def issue_deleted(self, desc):
        repo_id, alert_num, _, _ = jiralib.parse_alert_info(desc)
        self.sync(
            self.github.getRepository(repo_id).get_alert(alert_num),
            self.jira.fetch_issues(repo_id, alert_num),
            DIRECTION_J2G
        )


    def sync(self, alert, issues, in_direction):
        if alert is None:
            # there is no alert, so we have to remove all issues
            # that have ever been associated with it
            for i in issues:
                i.delete()
            return None

        # make sure that each alert has at least
        # one issue associated with it
        if len(issues) == 0:
            newissue = self.jira.create_issue(
                alert.github_repo.repo_id,
                alert.json['rule']['id'],
                alert.json['rule']['description'],
                alert.json['html_url'],
                alert.json['number']
            )
            newissue.adjust_state(alert.get_state())
            return alert.get_state()

        # make sure that each alert has at max
        # one issue associated with it
        if len(issues) > 1:
            issues.sort(key=lambda i: i.id())
            for i in issues[1:]:
                i.delete()

        issue = issues[0]

        # make sure alert and issue are in the same state
        if self.direction & DIRECTION_G2J and self.direction & DIRECTION_J2G:
            d = in_direction
        else:
            d = self.direction

        if d & DIRECTION_G2J or alert.is_fixed():
            # The user treats GitHub as the source of truth.
            # Also, if the alert to be synchronized is already "fixed"
            # then even if the user treats JIRA as the source of truth,
            # we have to push back the state to JIRA, because "fixed"
            # alerts cannot be transitioned to "open"
            issue.adjust_state(alert.get_state())
            return alert.get_state()
        else:
            # The user treats JIRA as the source of truth
            alert.adjust_state(issue.get_state())
            return issue.get_state()


    def sync_repo(self, repo_id):
        logger.info('Performing full sync on repository {repo_id}...'.format(
            repo_id=repo_id
        ))

        pairs = {}

        # gather alerts
        for a in self.github.getRepository(repo_id).get_alerts():
            k = make_alert_key(repo_id, a.json['number'])
            pairs[k] = (a, [])

        # gather issues
        for i in self.jira.fetch_issues(repo_id):
            _, _, _, akey = i.get_alert_info()
            if not akey in pairs:
                pairs[akey] = (None, [])
            pairs[akey][1].append(i)

        for _, (alert, issues) in pairs.items():
            k = alert.github_repo.repo_id + '/' + str(alert.json['number'])
            past_state = self.states.get(k, None)
            if alert.get_state() != past_state:
                d = DIRECTION_G2J
            else:
                d = DIRECTION_J2G

            new_state = self.sync(alert, issues, d)

            if new_state is None:
                self.states.pop(k, None)
            else:
                self.states[k] = new_state

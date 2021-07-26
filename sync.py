import jiralib
import ghlib
import logging

logger = logging.getLogger(__name__)

DIRECTION_G2J = 1
DIRECTION_J2G = 2
DIRECTION_BOTH = 3


class Sync:
    def __init__(self, github, jira_project, direction=DIRECTION_BOTH):
        self.github = github
        self.jira = jira_project
        self.direction = direction

    def alert_created(self, repo_id, alert_num):
        self.sync(
            self.github.getRepository(repo_id).get_alert(alert_num),
            self.jira.fetch_issues(repo_id, alert_num),
            DIRECTION_G2J,
        )

    def alert_changed(self, repo_id, alert_num):
        self.sync(
            self.github.getRepository(repo_id).get_alert(alert_num),
            self.jira.fetch_issues(repo_id, alert_num),
            DIRECTION_G2J,
        )

    def alert_fixed(self, repo_id, alert_num):
        self.sync(
            self.github.getRepository(repo_id).get_alert(alert_num),
            self.jira.fetch_issues(repo_id, alert_num),
            DIRECTION_G2J,
        )

    def issue_created(self, desc):
        repo_id, alert_num, _, _ = jiralib.parse_alert_info(desc)
        self.sync(
            self.github.getRepository(repo_id).get_alert(alert_num),
            self.jira.fetch_issues(repo_id, alert_num),
            DIRECTION_J2G,
        )

    def issue_changed(self, desc):
        repo_id, alert_num, _, _ = jiralib.parse_alert_info(desc)
        self.sync(
            self.github.getRepository(repo_id).get_alert(alert_num),
            self.jira.fetch_issues(repo_id, alert_num),
            DIRECTION_J2G,
        )

    def issue_deleted(self, desc):
        repo_id, alert_num, _, _ = jiralib.parse_alert_info(desc)
        self.sync(
            self.github.getRepository(repo_id).get_alert(alert_num),
            self.jira.fetch_issues(repo_id, alert_num),
            DIRECTION_J2G,
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
                alert.json["rule"]["id"],
                alert.json["rule"]["description"],
                alert.json["html_url"],
                alert.number(),
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

    def sync_repo(self, repo_id, states=None):
        logger.info(
            "Performing full sync on repository {repo_id}...".format(repo_id=repo_id)
        )

        states = {} if states is None else states
        pairs = {}

        # gather alerts
        for a in self.github.getRepository(repo_id).get_alerts():
            pairs[a.number()] = (a, [])

        # gather issues
        for i in self.jira.fetch_issues(repo_id):
            _, anum, _, _ = i.get_alert_info()
            if not anum in pairs:
                pairs[anum] = (None, [])
            pairs[anum][1].append(i)

        # remove unused states
        for k in list(states.keys()):
            if not k in pairs:
                del states[k]

        # perform sync
        for anum, (alert, issues) in pairs.items():
            past_state = states.get(anum, None)
            if alert is None or alert.get_state() != past_state:
                d = DIRECTION_G2J
            else:
                d = DIRECTION_J2G

            new_state = self.sync(alert, issues, d)

            if new_state is None:
                states.pop(anum, None)
            else:
                states[anum] = new_state

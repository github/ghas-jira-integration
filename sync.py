import jiralib
import logging
import itertools

logger = logging.getLogger(__name__)

DIRECTION_G2J = 1
DIRECTION_J2G = 2
DIRECTION_BOTH = 3


class Sync:
    def __init__(self, github, jira_project, direction=DIRECTION_BOTH):
        self.github = github
        self.jira = jira_project
        self.direction = direction
        self.labels = self.jira.labels

    def alert_created(self, repo_id, alert_num):
        a = self.github.getRepository(repo_id).get_alert(alert_num)
        self.sync(a, self.jira.fetch_issues(a.get_key()), DIRECTION_G2J)

    def alert_changed(self, repo_id, alert_num):
        a = self.github.getRepository(repo_id).get_alert(alert_num)
        self.sync(a, self.jira.fetch_issues(a.get_key()), DIRECTION_G2J)

    def alert_fixed(self, repo_id, alert_num):
        a = self.github.getRepository(repo_id).get_alert(alert_num)
        self.sync(a, self.jira.fetch_issues(a.get_key()), DIRECTION_G2J)

    def issue_created(self, desc):
        repo_id, alert_num, _, _, _ = jiralib.parse_alert_info(desc)
        a = self.github.getRepository(repo_id).get_alert(alert_num)
        self.sync(a, self.jira.fetch_issues(a.get_key()), DIRECTION_J2G)

    def issue_changed(self, desc):
        repo_id, alert_num, _, _, _ = jiralib.parse_alert_info(desc)
        a = self.github.getRepository(repo_id).get_alert(alert_num)
        self.sync(a, self.jira.fetch_issues(a.get_key()), DIRECTION_J2G)

    def issue_deleted(self, desc):
        repo_id, alert_num, _, _, _ = jiralib.parse_alert_info(desc)
        a = self.github.getRepository(repo_id).get_alert(alert_num)
        self.sync(a, self.jira.fetch_issues(a.get_key()), DIRECTION_J2G)

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
                alert.short_desc(),
                alert.long_desc(),
                alert.hyperlink(),
                alert.get_type(),
                alert.number(),
                alert.github_repo.get_key(),
                alert.get_key(),
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

        if d & DIRECTION_G2J or not alert.can_transition():
            # The user treats GitHub as the source of truth.
            # Also, if the alert to be synchronized is already "fixed"
            # then even if the user treats JIRA as the source of truth,
            # we have to push back the state to JIRA, because "fixed"
            # alerts cannot be transitioned to "open"
            issue.adjust_state(alert.get_state())
            issue.persist_labels(self.labels)
            return alert.get_state()
        else:
            # The user treats JIRA as the source of truth
            alert.adjust_state(issue.get_state())
            issue.persist_labels(self.labels)
            return issue.get_state()

    def sync_repo(self, repo_id, states=None):
        logger.info(
            "Performing full sync on repository {repo_id}...".format(repo_id=repo_id)
        )

        repo = self.github.getRepository(repo_id)
        states = {} if states is None else states
        pairs = {}

        # gather alerts
        for a in itertools.chain(repo.get_secrets(), repo.get_alerts()):
            pairs[a.get_key()] = (a, [])

        # gather issues
        for i in self.jira.fetch_issues(repo.get_key()):
            _, _, _, alert_key, _ = i.get_alert_info()
            if alert_key not in pairs:
                pairs[alert_key] = (None, [])
            pairs[alert_key][1].append(i)

        # remove unused states
        for k in list(states.keys()):
            if k not in pairs:
                del states[k]

        # perform sync
        for akey, (alert, issues) in pairs.items():
            past_state = states.get(akey, None)
            if alert is None or alert.get_state() != past_state:
                d = DIRECTION_G2J
            else:
                d = DIRECTION_J2G

            new_state = self.sync(alert, issues, d)

            if new_state is None:
                states.pop(akey, None)
            else:
                states[akey] = new_state

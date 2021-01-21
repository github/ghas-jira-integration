import hashlib
from requests import HTTPError
import logging

REQUEST_TIMEOUT = 10

logger = logging.getLogger(__name__)


def make_key(s):
    sha_1 = hashlib.sha1()
    sha_1.update(s.encode('utf-8'))
    return sha_1.hexdigest()


def json_accept_header():
    return {'Accept': 'application/vnd.github.v3+json'}


def sync_repo(ghrepository, jiraproject):
    repo_id = ghrepository.repo_id

    logger.info('Starting full sync for repository "{repo_id}"...'.format(repo_id=repo_id))

    # fetch code scanning alerts from GitHub
    cs_alerts = []
    try:
        cs_alerts = {make_key(repo_id + '/' + str(a['number'])): a for a in ghrepository.get_alerts()}
    except HTTPError as httpe:
        # if we receive a 404, the repository does not exist,
        # so we will delete all related JIRA alert issues
        if httpe.response.status_code != 404:
            # propagate everything else
            raise

    # fetch issues from JIRA and delete duplicates and ones which can't be matched
    jira_issues = {}
    for i in jiraproject.fetch_issues(repo_id):
        _, _, _, akey = i.get_alert_info()
        if akey in jira_issues:
            logger.warning(
                'JIRA alert issues {ikey1} and {ikey2} have identical alert key {akey}!'.format(
                    ikey1=i.key(),
                    ikey2=jira_issues[akey].key(),
                    akey=akey
                )
            )
            i.delete()   # TODO - seems scary, are we sure....
        elif akey not in cs_alerts:
            logger.warning('JIRA alert issue {ikey} has no corresponding alert!'.format(ikey=i.key()))
            i.delete()   # TODO - seems scary, are we sure....
        else:
            jira_issues[akey] = i

    # create missing issues
    for akey in cs_alerts:
        if akey not in jira_issues:
            alert = cs_alerts[akey]
            rule = alert['rule']

            jira_issues[akey] = jiraproject.create_issue(
                repo_id,
                rule['id'],
                rule['description'],
                alert['html_url'],
                alert['number']
            )

    # adjust issue states
    for akey in cs_alerts:
        alert = cs_alerts[akey]
        issue = jira_issues[akey]
        astatus = alert['state']

        if astatus == 'open':
            issue.open()
        else:
            issue.close()

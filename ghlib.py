import requests
import itertools
import logging
import json
import util
from requests import HTTPError


WEBHOOK_CONFIG = '''
{
    "url": "{url}",
    "content_type": "{content_type}",
    "secret": "{secret}",
    "insecure_ssl": "{insecure_ssl}",
    "events": "{envents}",
    "active": "{active}"
}
'''

logger = logging.getLogger(__name__)


class GitHub:
    def __init__(self, url, user, token):
        self.url = url
        self.user = user
        self.token = token


    def auth(self):
        return self.user, self.token


    def getRepository(self, repo_id):
        return GHRepository(self, repo_id)


    def list_org_hooks(self, org):
        '''requires a token with "admin:org_hook" permission!'''
        return self.list_hooks_helper(org)


    def list_hooks_helper(self, entity):
        if '/' in entity:
            etype = 'repos'
        else:
            etype = 'orgs'
        for page in itertools.count(start=1):
            resp = requests.get(
                '{api_url}/{etype}/{ename}/hooks?per_page=100&page={page}'.format(
                    api_url=self.url,
                    etype=etype,
                    ename=entity,
                    page=page
                ),
                headers=util.json_accept_header(),
                auth=self.auth(),
                timeout=util.REQUEST_TIMEOUT
            )
            resp.raise_for_status()

            if not resp.json():
                break

            for h in resp.json():
                yield h

    def create_org_hook(
        self, org, url,
        secret, active=True,
        events=['code_scanning_alert', 'repository'],
        insecure_ssl='0',
        content_type='json'
    ):
        return self.create_hook_helper(
            org, url,
            secret, active,
            events, insecure_ssl,
            content_type
        )


    def create_hook_helper(
        self, entity, url, secret, active=True,
        events=['code_scanning_alert', 'repository'],
        insecure_ssl='0',
        content_type='json'
    ):

        if '/' in entity:
            etype = 'repos'
        else:
            etype = 'orgs'

        data = json.dumps({
            'config': {
                'url': url,
                'insecure_ssl': insecure_ssl,
                'secret': secret,
                'content_type': content_type,
            },
            'events': events,
            'active': active,
            'name': 'web'
        })
        resp = requests.post(
            '{api_url}/{etype}/{ename}/hooks'.format(
                etype=etype,
                ename=entity,
                api_url=self.url
            ),
            headers=util.json_accept_header(),
            data=data,
            auth=self.auth(),
            timeout=util.REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()


class GHRepository:
    def __init__(self, github, repo_id):
        self.gh = github
        self.repo_id = repo_id


    def list_hooks(self):
        return self.gh.list_hooks_helper(self.repo_id)


    def create_hook(
        self, url,
        secret, active=True,
        events=['code_scanning_alert', 'repository'],
        insecure_ssl='0',
        content_type='json'
    ):
        return self.gh.create_hook_helper(
            self.repo_id, url,
            secret, active,
            events, insecure_ssl,
            content_type
        )


    def get_alerts(self, state = None):
        if state:
            state = '&state=' + state
        else:
            state = ''

        for page in itertools.count(start=1):
            resp = requests.get(
                '{api_url}/repos/{repo_id}/code-scanning/alerts?per_page=100&page={page}{state}'.format(
                    api_url=self.gh.url,
                    repo_id=self.repo_id,
                    page=page,
                    state=state
                ),
                headers=util.json_accept_header(),
                auth=self.gh.auth(),
                timeout=util.REQUEST_TIMEOUT
            )
            try:
                resp.raise_for_status()
                if not resp.json():
                    break

                for a in resp.json():
                    yield GHAlert(self, a)
            except HTTPError as httpe:
                if httpe.response.status_code == 404:
                    # A 404 suggests that the repository doesn't exist
                    break
                else:
                    # propagate everything else
                    raise


    def get_alert(self, alert_num):
        resp = requests.get(
            '{api_url}/repos/{repo_id}/code-scanning/alerts/{alert_num}'.format(
                api_url=self.gh.url,
                repo_id=self.repo_id,
                alert_num=alert_num
            ),
            headers=util.json_accept_header(),
            auth=self.gh.auth(),
            timeout=util.REQUEST_TIMEOUT
        )
        try:
            resp.raise_for_status()
            return GHAlert(self, resp.json())
        except HTTPError as httpe:
            if httpe.response.status_code == 404:
                # A 404 suggests that the alert doesn't exist
                return None
            else:
                # propagate everything else
                raise


class GHAlert:
    def __init__(self, github_repo, json):
        self.github_repo =  github_repo
        self.gh = github_repo.gh
        self.json = json


    def get_state(self):
        return parse_alert_state(self.json['state'])


    def adjust_state(self, state):
        if state:
            self.update('open')
        else:
            self.update('dismissed')


    def is_fixed(self):
        return self.json['state'] == 'fixed'


    def update(self, alert_state):
        if self.json['state'] == alert_state:
            return

        action = 'Reopening' if parse_alert_state(alert_state) else 'Closing'
        logger.info(
            '{action} alert {alert_num} of repository "{repo_id}".'.format(
                action=action,
                alert_num=self.json['number'],
                repo_id=self.github_repo.repo_id
            )
        )
        reason = ''
        if alert_state == 'dismissed':
            reason = ', "dismissed_reason": "won\'t fix"'
        data = '{{"state": "{state}"{reason}}}'.format(state=alert_state, reason=reason)
        resp = requests.patch(
            '{api_url}/repos/{repo_id}/code-scanning/alerts/{alert_num}'.format(
                api_url=self.gh.url,
                repo_id=self.github_repo.repo_id,
                alert_num=self.json['number']
            ),
            data=data,
            headers=util.json_accept_header(),
            auth=self.gh.auth(),
            timeout=util.REQUEST_TIMEOUT
        )
        resp.raise_for_status()


def parse_alert_state(state_string):
    return state_string not in ['dismissed', 'fixed']

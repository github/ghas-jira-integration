import requests
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

RESULTS_PER_PAGE = 100

logger = logging.getLogger(__name__)


class GitHub:
    def __init__(self, url, token):
        self.url = url
        self.token = token


    def default_headers(self):
        auth = {'Authorization': 'token ' + self.token}
        auth.update(util.json_accept_header())
        return auth


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

        resp = requests.get(
            '{api_url}/{etype}/{ename}/hooks?per_page={results_per_page}'.format(
                api_url=self.url,
                etype=etype,
                ename=entity,
                results_per_page=RESULTS_PER_PAGE
            ),
            headers=self.default_headers(),
            timeout=util.REQUEST_TIMEOUT
        )

        while True:
            resp.raise_for_status()

            for h in resp.json():
                yield h

            nextpage = resp.links.get('next', {}).get('url', None)
            if not nextpage:
                break

            resp = requests.get(
                nextpage,
                headers=self.default_headers(),
                timeout=util.REQUEST_TIMEOUT
            )


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
            headers=self.default_headers(),
            data=data,
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


    def get_key(self):
        return util.make_key(self.repo_id)


    def alerts_helper(self, api_segment, state=None):
        if state:
            state = '&state=' + state
        else:
            state = ''

        try:
            resp = requests.get(
                '{api_url}/repos/{repo_id}/{api_segment}/alerts?per_page={results_per_page}{state}'.format(
                    api_url=self.gh.url,
                    repo_id=self.repo_id,
                    api_segment=api_segment,
                    state=state,
                    results_per_page=RESULTS_PER_PAGE
                ),
                headers=self.gh.default_headers(),
                timeout=util.REQUEST_TIMEOUT
            )

            while True:
                resp.raise_for_status()

                for a in resp.json():
                    yield a

                nextpage = resp.links.get('next', {}).get('url', None)
                if not nextpage:
                    break

                resp = requests.get(
                    nextpage,
                    headers=self.gh.default_headers(),
                    timeout=util.REQUEST_TIMEOUT
                )

        except HTTPError as httpe:
            if httpe.response.status_code == 404:
                # A 404 suggests that the repository doesn't exist
                # so we return an empty list
                pass
            else:
                # propagate everything else
                raise


    def get_info(self):
        resp = requests.get(
            '{api_url}/repos/{repo_id}'.format(
                api_url=self.gh.url,
                repo_id=self.repo_id
            ),
            headers=self.gh.default_headers(),
            timeout=util.REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()


    def isprivate(self):
        return self.get_info()['private']


    def get_alerts(self, state=None):
        for a in self.alerts_helper('code-scanning', state):
            yield Alert(self, a)


    def get_secrets(self, state=None):
        # secret scanning alerts are only accessible on private repositories, so
        # we return an empty list on public ones
        if not self.isprivate():
            return
        for a in self.alerts_helper('secret-scanning', state):
            yield Secret(self, a)


    def get_alert(self, alert_num):
        resp = requests.get(
            '{api_url}/repos/{repo_id}/code-scanning/alerts/{alert_num}'.format(
                api_url=self.gh.url,
                repo_id=self.repo_id,
                alert_num=alert_num
            ),
            headers=self.gh.default_headers(),
            timeout=util.REQUEST_TIMEOUT
        )
        try:
            resp.raise_for_status()
            return Alert(self, resp.json())
        except HTTPError as httpe:
            if httpe.response.status_code == 404:
                # A 404 suggests that the alert doesn't exist
                return None
            else:
                # propagate everything else
                raise


class AlertBase:
    def __init__(self, github_repo, json):
        self.github_repo =  github_repo
        self.gh = github_repo.gh
        self.json = json

    def get_state(self):
        return self.json['state'] == 'open'

    def get_type(self):
        return type(self).__name__

    def number(self):
        return int(self.json['number'])

    def short_desc(self):
        raise NotImplementedError

    def long_desc(self):
        raise NotImplementedError

    def hyperlink(self):
        return self.json['html_url']

    def can_transition(self):
        return True

    def get_key(self):
        raise NotImplementedError

    def adjust_state(self, target_state):
        if self.get_state() == target_state:
            return

        logger.info(
            '{action} {atype} {alert_num} of repository "{repo_id}".'.format(
                atype=self.get_type(),
                action='Reopening' if target_state else 'Closing',
                alert_num=self.number(),
                repo_id=self.github_repo.repo_id
            )
        )
        self.do_adjust_state(target_state)


class Alert(AlertBase):
    def __init__(self, github_repo, json):
        AlertBase.__init__(self, github_repo, json)

    def can_transition(self):
        return self.json['state'] != 'fixed'

    def long_desc(self):
        return self.json['rule']['description']

    def short_desc(self):
        return self.json['rule']['id']

    def get_key(self):
        return util.make_key(
            self.github_repo.repo_id + '/' + str(self.number())
        )

    def do_adjust_state(self, target_state):
        state = 'open'
        reason = ''
        if not target_state:
            state = 'dismissed'
            reason = ', "dismissed_reason": "won\'t fix"'
        data = '{{"state": "{state}"{reason}}}'.format(state=state, reason=reason)
        resp = requests.patch(
            '{api_url}/repos/{repo_id}/code-scanning/alerts/{alert_num}'.format(
                api_url=self.gh.url,
                repo_id=self.github_repo.repo_id,
                alert_num=self.number()
            ),
            data=data,
            headers=self.gh.default_headers(),
            timeout=util.REQUEST_TIMEOUT
        )
        resp.raise_for_status()


class Secret(AlertBase):
    def __init__(self, github_repo, json):
        AlertBase.__init__(self, github_repo, json)

    def can_transition(self):
        return True

    def long_desc(self):
        return self.json['secret_type']

    def short_desc(self):
        return self.long_desc()

    def get_key(self):
        return util.make_key(
            self.github_repo.repo_id + '/' + self.get_type() + '/' + str(self.number())
        )

    def do_adjust_state(self, target_state):
        state = 'open'
        resolution = ''
        if not target_state:
            state = 'resolved'
            resolution = ', "resolution": "wont_fix"'
        data = '{{"state": "{state}"{resolution}}}'.format(state=state, resolution=resolution)
        resp = requests.patch(
            '{api_url}/repos/{repo_id}/secret-scanning/alerts/{alert_num}'.format(
                api_url=self.gh.url,
                repo_id=self.github_repo.repo_id,
                alert_num=self.number()
            ),
            data=data,
            headers=self.gh.default_headers(),
            timeout=util.REQUEST_TIMEOUT
        )
        resp.raise_for_status()

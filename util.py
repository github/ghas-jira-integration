import hashlib

REQUEST_TIMEOUT = 10


def make_key(s):
    sha_1 = hashlib.sha1()
    sha_1.update(s.encode('utf-8'))
    return sha_1.hexdigest()


def make_alert_key(repo_id, alert_num):
    return make_key(repo_id + '/' + str(alert_num))


def json_accept_header():
    return {'Accept': 'application/vnd.github.v3+json'}

import hashlib
import os.path
import json

REQUEST_TIMEOUT = 10


def state_from_json(s):
    # convert string keys into int keys
    # this is necessary because JSON doesn't allow
    # int keys and json.dump() automatically converts
    # int keys into string keys.
    return {int(k): v for k, v in json.loads(s).items()}


def state_to_json(state):
    return json.dumps(
        state,
        indent=2,
        sort_keys=True
    )


def state_from_file(fpath):
    if os.path.isfile(fpath):
        with open(fpath, 'r') as f:
            return state_from_json(f.read())
    return {}


def state_to_file(fpath, state):
    with open(fpath, 'w') as f:
        f.write(state_to_json(state))


def make_key(s):
    sha_3 = hashlib.sha3_256()
    sha_3.update(s.encode("utf-8"))
    return sha_3.hexdigest()


def make_alert_key(repo_id, alert_num):
    return make_key(repo_id + '/' + str(alert_num))


def json_accept_header():
    return {'Accept': 'application/vnd.github.v3+json'}

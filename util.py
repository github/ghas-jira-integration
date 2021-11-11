import hashlib
import os.path
import json

REQUEST_TIMEOUT = 10


def state_from_json(s):
    j = json.loads(s)
    if not "version" in j:
        return {}
    return j["states"]


def state_to_json(state):
    final = {"version": 2, "states": state}
    return json.dumps(final, indent=2, sort_keys=True)


def state_from_file(fpath):
    if os.path.isfile(fpath):
        with open(fpath, "r") as f:
            return state_from_json(f.read())
    return {}


def state_to_file(fpath, state):
    with open(fpath, "w") as f:
        f.write(state_to_json(state))


def make_key(s):
    sha_3 = hashlib.sha3_256()
    sha_3.update(s.encode("utf-8"))
    return sha_3.hexdigest()


def json_accept_header():
    return {"Accept": "application/vnd.github.v3+json"}

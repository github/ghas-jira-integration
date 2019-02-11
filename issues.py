import os
from flask import Flask, request, jsonify

import requests
import json
import hmac

URL = os.getenv("GIT_REPO_URL")
assert URL != None

ACCESS_TOKEN = os.getenv("GIT_ACCESS_TOKEN")
assert ACCESS_TOKEN != None

KEY = os.getenv("LGTM_SECRET", "").encode("utf-8")
assert KEY != "".encode("utf-8")


session = requests.Session()
session.headers.update(
    {"content-type": "application/json", "Authorization": "Bearer %s" % ACCESS_TOKEN}
)

SUPPRESSION_LABEL = "wontfix"

app = Flask(__name__)


def get_issue_dict(alert, project):

    title = "%s (%s)" % (alert["query"]["name"], project["name"])

    lines = []
    lines.append("[%s](%s)" % (alert["query"]["name"], alert["query"]["url"]))
    lines.append("")
    lines.append("In %s:" % alert["file"])
    lines.append("> " + "\n> ".join(alert["message"].split("\n")))
    lines.append("[View alert on LGTM](%s)" % alert["url"])

    return {"title": title, "body": "\n".join(lines), "labels": ["LGTM"]}


@app.route("/lgtm", methods=["POST"])
def lgtm_webhook():

    if not app.debug:

        digest = hmac.new(KEY, request.data, "sha1").hexdigest()
        signature = request.headers.get("X-LGTM-Signature", "not-provided")

        if not hmac.compare_digest(signature, digest):
            return jsonify({"message": "Unauthorized"}), 401

    json_dict = request.get_json()

    transition = json_dict.get("transition")

    if transition == "create":

        data = get_issue_dict(json_dict.get("alert"), json_dict.get("project"))

        r = session.post(URL, data=json.dumps(data))

        issue_id = r.json()["number"]

    else:  # transition acts on exsiting ticket

        issue_id = json_dict.get("issue-id", None)

        if issue_id is None:
            return jsonify({"message": "no issue-id provided"}), 400

        if transition in ["close", "reopen"]:

            # handle a mistmatch between terminology on LGTM and Github
            if transition == "reopen":
                transition = "open"

            r = session.patch(
                os.path.sep.join([URL, str(issue_id)]),
                data=json.dumps({"state": transition}),
            )

        elif transition == "suppress":

            r = session.post(
                "/".join([URL, str(issue_id), "labels"]),
                data=json.dumps([SUPPRESSION_LABEL]),
            )

        elif transition == "unsuppress":

            r = session.delete(
                "/".join([URL, str(issue_id), "labels", SUPPRESSION_LABEL])
            )

            # if the label was not present on the issue, we don't let this worry us
            if not r.ok and r.json().get("message") == "Label does not exist":
                r.status_code = 200

        else:  # no matching transitions found
            return (
                jsonify({"message": "unknown transition type - %s" % transition}),
                400,
            )

    if not r.ok:  # handle unknown error conditions by fowarding Github message
        return app.response_class(
            response=r.content, status=r.status_code, mimetype="application/json"
        )

    return jsonify({"issue-id": issue_id}), r.status_code


@app.route("/github", methods=["POST"])
def github_webhook():

    if not app.debug:

        digest = hmac.new(KEY, request.data, "sha1").hexdigest()
        sig_header = request.headers.get("X-Hub-Signature", "not-provided")

        if not hmac.compare_digest(sig_header.split("=")[-1], digest):
            return jsonify({"message": "Unauthorized"}), 401

    json_dict = request.get_json()

    action = json_dict.get("action")

    if action not in ["labeled", "unlabeled"]:
        return jsonify({"status": 200}), 200  # we don't care about other actions

    label = json_dict.get("label")

    if label["name"] != SUPPRESSION_LABEL:
        return jsonify({"status": 200}), 200  # we don't care about other labels

    translator = {"labeled": "suppress", "unlabeled": "unsuppress"}

    payload = {
        "issue-id": json_dict["issue"]["number"],
        "transition": translator[action],
    }

    # placeholder for webhook request sent back to LGTM-E
    print(json.dumps(payload))

    return jsonify({"status": 200}), 200

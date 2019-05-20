import os
from flask import Flask, request, jsonify

import requests
import json
import hashlib
import hmac

LGTM_URL = os.getenv("LGTM_WEBHOOK_URL")
assert LGTM_URL != None

GITHUB_URL = os.getenv("GIT_REPO_URL")
assert GITHUB_URL != None

GITHUB_BOT_USERNAME = os.getenv("GIT_BOT_USERNAME")
assert GITHUB_BOT_USERNAME != None

GITHUB_TOKEN = os.getenv("GIT_ACCESS_TOKEN")
assert GITHUB_TOKEN != None

KEY = os.getenv("SECRET", "").encode("utf-8")
assert KEY != "".encode("utf-8")

sess_github = requests.Session()
sess_github.headers.update(
    {"content-type": "application/json", "Authorization": "Bearer %s" % GITHUB_TOKEN}
)

sess_lgtm = requests.Session()
sess_lgtm.headers.update({"content-type": "application/json"})

SUPPRESSION_LABEL = "wontfix"

app = Flask(__name__)


def get_issue_dict(alert, project):
    """Generate payload for creating ticket in GitHub Issues"""

    title = "%s (%s)" % (alert["query"]["name"], project["name"])

    lines = []
    lines.append("[%s](%s)" % (alert["query"]["name"], alert["query"]["url"]))
    lines.append("")
    lines.append("In %s:" % alert["file"])
    lines.append("> " + "\n> ".join(alert["message"].split("\n")))
    lines.append("[View alert on LGTM](%s)" % alert["url"])

    labels = ["LGTM"]

    if alert.get("suppressed"):
        labels.append(SUPPRESSION_LABEL)

    return {"title": title, "body": "\n".join(lines), "labels": labels}


def auth_is_valid(signature):
    if app.debug:
        return True

    return hmac.compare_digest(
        signature, hmac.new(KEY, request.data, hashlib.sha1).hexdigest()
    )


@app.route("/lgtm", methods=["POST"])
def lgtm_webhook():
    """Handle POST requests coming from LGTM, and pass a translated request to GitHub"""

    if not auth_is_valid(request.headers.get("X-LGTM-Signature", "not-provided")):
        return jsonify({"code": 403, "error": "Unauthorized"}), 403

    json_dict = request.get_json()

    transition = json_dict.get("transition")

    # we deal with each transition type individually, showing the expected
    # behaviour and response codes explicitly

    if transition == "create":

        data = get_issue_dict(json_dict.get("alert"), json_dict.get("project"))

        r = sess_github.post(GITHUB_URL, data=json.dumps(data))

        issue_id = str(r.json().get("number", None))

        if r.ok:
            return jsonify({"issue-id": issue_id}), 201
        else:
            return jsonify({"code": 500, "error": "Internal server error"}), 500

    # if not creating a ticket, there should be an issue_id defined
    issue_id = json_dict.get("issue-id", None)
    if issue_id is None:
        return jsonify({"code": 400, "error": "No issue-id provided"}), 400

    if transition == "close":

        r = sess_github.patch(
            GITHUB_URL + "/" + str(issue_id), data=json.dumps({"state": transition})
        )
        if r.ok:
            return jsonify({"issue-id": issue_id}), 200
        if r.status_code == 404 and r.json()["message"] == "Not Found":
            # if we were trying to close, we don't worry about not finding it
            return jsonify({"issue-id": issue_id}), 200
        else:
            return jsonify({"code": 500, "error": "Internal server error"}), 500

    if transition == "reopen":

        r = sess_github.patch(
            GITHUB_URL + "/" + str(issue_id), data=json.dumps({"state": "open"})
        )
        if r.ok:
            return jsonify({"issue-id": issue_id}), 200
        if r.status_code == 404 and r.json()["message"] == "Not Found":
            # using 410 we indicate to LGTM that the issue needs to be recreated
            return jsonify({"code": 410, "error": "Ticket has been removed."}), 410
        else:
            return jsonify({"code": 500, "error": "Internal server error"}), 500

    if transition == "suppress":

        r = sess_github.post(
            GITHUB_URL + "/" + str(issue_id) + "/" + "labels",
            data=json.dumps([SUPPRESSION_LABEL]),
        )
        if r.ok:
            return jsonify({"issue-id": issue_id}), 200
        if r.status_code == 404 and r.json()["message"] == "Not Found":
            # if we were trying to suppress, we don't worry about not finding it
            return jsonify({"issue-id": issue_id}), 200
        else:
            return jsonify({"code": 500, "error": "Internal server error"}), 500

    if transition == "unsuppress":

        r = sess_github.delete(
            "/".join([GITHUB_URL, str(issue_id), "labels", SUPPRESSION_LABEL])
        )

        # if the label was not present on the issue, we don't let this worry us
        if not r.ok and r.json().get("message") == "Label does not exist":
            r.status_code = 200

        if r.ok:  # we ensure that the ticket is open in the issue tracker
            r = sess_github.patch(
                GITHUB_URL + "/" + str(issue_id), data=json.dumps({"state": "open"})
            )

        if r.ok:
            return jsonify({"issue-id": issue_id}), 200
        if r.status_code == 404 and r.json()["message"] == "Not Found":
            # using 410 we indicate to LGTM that the issue needs to be recreated
            return jsonify({"code": 410, "error": "Ticket has been removed."}), 410
        else:
            return jsonify({"code": 500, "error": "Internal server error"}), 500

    # when the transition is not recognised, we return a bad request response
    return (
        jsonify({"code": 400, "error": "unknown transition type - %s" % transition}),
        400,
    )


@app.route("/github", methods=["POST"])
def github_webhook():
    """Handle POST requests coming from GitHub, and pass a translated request to LGTM"""

    if not auth_is_valid(
        request.headers.get("X-Hub-Signature", "not-provided").split("=")[-1]
    ):
        return jsonify({"code": 403, "error": "Unauthorized"}), 403

    json_dict = request.get_json()

    action = json_dict.get("action")

    if action not in ["labeled", "unlabeled"]:
        return jsonify({"status": 200}), 200

    label = json_dict.get("label", {})

    if label.get("name", "") != SUPPRESSION_LABEL:
        return jsonify({"status": 200}), 200

    issue_id = str(json_dict["issue"]["number"])

    # When we were responsible for changing the tag, we don't want to pass the webhook back again.
    if json_dict["sender"]["login"] == GITHUB_BOT_USERNAME:
        return jsonify({"status": 200}), 200

    translator = {"labeled": "suppress", "unlabeled": "unsuppress"}

    payload = json.dumps({"issue-id": issue_id, "transition": translator[action]})

    headers = {
        "X-LGTM-Signature": hmac.new(
            KEY, payload.encode("utf-8"), hashlib.sha1
        ).hexdigest()
    }

    r = sess_lgtm.post(LGTM_URL, data=payload, headers=headers)

    if r.ok:
        return jsonify({"status": 200}), 200
    else:
        return app.response_class(
            response=r.content, status=r.status_code, mimetype="application/json"
        )

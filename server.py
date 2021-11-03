from flask import Flask, request, jsonify
from flask.logging import default_handler
import json
import hashlib
import hmac
import logging
from datetime import datetime
import jiralib
import threading


sync = None
repo_sync_interval = None
app = Flask(__name__)
sync_lock = threading.Lock()
last_repo_syncs = {}
secret = None


def run_server(
    sync_object, webhook_secret, repository_sync_interval=60 * 60 * 24, port=5000
):
    global sync
    sync = sync_object
    global secret
    secret = webhook_secret.encode("utf-8")
    global repo_sync_interval
    repo_sync_interval = repository_sync_interval
    app.run(port=port)


# logging.getLogger('jiralib').addHandler(default_handler)
# logging.getLogger('ghlib').addHandler(default_handler)
# logging.basicConfig(level=logging.INFO)


def auth_is_valid(signature, request_body):
    if app.debug:
        return True
    return hmac.compare_digest(
        signature.encode("utf-8"),
        ("sha256=" + hmac.new(secret, request_body, hashlib.sha256).hexdigest()).encode(
            "utf-8"
        ),
    )


@app.route("/jira", methods=["POST"])
def jira_webhook():
    """Handle POST requests coming from JIRA, and pass a translated request to GitHub"""

    if not hmac.compare_digest(
        request.args.get("secret_token", "").encode("utf-8"), secret
    ):
        return jsonify({"code": 403, "error": "Unauthorized"}), 403

    payload = json.loads(request.data.decode('utf-8'))
    event = payload['webhookEvent']
    desc = payload['issue']['fields']['description']
    repo_id, _, _, _, _ = jiralib.parse_alert_info(desc)

    app.logger.debug('Received JIRA webhook for event "{event}"'.format(event=event))

    if repo_id is None:
        app.logger.debug(
            "Ignoring JIRA webhook for issue not related to a code scanning alert."
        )
        return jsonify({}), 200

    with sync_lock:
        # we only care about updates to issues
        if event == jiralib.CREATE_EVENT:
            sync.issue_created(desc)
        elif event == jiralib.DELETE_EVENT:
            sync.issue_deleted(desc)
        elif event == jiralib.UPDATE_EVENT:
            sync.issue_changed(desc)
        else:
            app.logger.debug(
                'Ignoring JIRA webhook for event "{event}".'.format(event=event)
            )
            return jsonify({}), 200

    return jsonify({}), 200


@app.route("/github", methods=["POST"])
def github_webhook():
    """
    Handle POST requests coming from GitHub, and pass a translated request to JIRA
    By default, flask runs in single-threaded mode, so we don't need to worry about
    any race conditions.
    """

    app.logger.debug(
        'Received GITHUB webhook for event "{event}"'.format(
            event=request.headers.get("X-GitHub-Event", "")
        )
    )

    if not auth_is_valid(
        request.headers.get("X-Hub-Signature-256", "not-provided"), request.data
    ):
        return jsonify({"code": 403, "error": "Unauthorized"}), 403

    # When creating a webhook, GitHub will send a 'ping' to check whether the
    # instance is up. If we return a friendly code, the hook will mark as green in the UI.
    if request.headers.get("X-GitHub-Event", "") == "ping":
        return jsonify({}), 200

    json_dict = request.get_json()
    repo_id = json_dict.get("repository", {}).get("full_name")
    transition = json_dict.get("action")

    if request.headers.get("X-GitHub-Event", "") == "repository":
        if transition == "deleted":
            with sync_lock:
                sync.sync_repo(repo_id)
        return (
            jsonify(
                {
                    "code": 400,
                    "error": "Wrong event type: "
                    + request.headers.get("X-GitHub-Event", ""),
                }
            ),
            400,
        )

    if request.headers.get("X-GitHub-Event", "") != "code_scanning_alert":
        return (
            jsonify(
                {
                    "code": 400,
                    "error": "Wrong event type: "
                    + request.headers.get("X-GitHub-Event", ""),
                }
            ),
            400,
        )

    alert = json_dict.get("alert")
    alert_url = alert.get("html_url")
    alert_num = alert.get("number")
    rule_id = alert.get("rule").get("id")
    rule_desc = alert.get("rule").get("description")

    # TODO: We might want to do the following asynchronously, as it could
    # take time to do a full sync on a repo with many alerts / issues
    last_sync = last_repo_syncs.get(repo_id, 0)
    now = datetime.now().timestamp()
    if now - last_sync >= repo_sync_interval:
        last_repo_syncs[repo_id] = now
        with sync_lock:
            sync.sync_repo(repo_id)

    app.logger.debug(
        "Received GITHUB webhook {action} for {alert_url}".format(
            action=transition, alert_url=alert_url
        )
    )

    # we deal with each action type individually, showing the expected
    # behaviour and response codes explicitly
    with sync_lock:
        if transition == "appeared_in_branch":
            app.logger.debug('Nothing to do for "appeared_in_branch"')
        elif transition == "created":
            sync.alert_created(repo_id, alert_num)
        elif transition in ["closed_by_user", "reopened_by_user", "reopened"]:
            sync.alert_changed(repo_id, alert_num)
        elif transition == "fixed":
            sync.alert_fixed(repo_id, alert_num)
        else:
            # when the transition is not recognised, we return a bad request response
            return (
                jsonify(
                    {"code": 400, "error": "unknown transition type - %s" % transition}
                ),
                400,
            )

    return jsonify({}), 200

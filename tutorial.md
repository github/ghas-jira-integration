
# Integrating a 3rd-party issue tracker with LGTM

To enable the creation of tickets in 3rd-party issue trackers, LGTM Enterprise offers a lightweight webhook integration. When enabled this will send outgoing POST requests to a specified endpoint, detailing new and changed alerts.

We are going to outline a barebones implementation of a webapp that will process incoming requests from LGTM Enterprise, create issues in a specified Github repository and pass an appropriate response back to LGTM. We will implement our example for python 3.5+ and use two 3rd-party modules, `Flask` (a micro web framework) and `requests` (a user-friendly HTTP library). Both are extremely widely used and can be easily installed using `pip`.
```bash
pip install flask
pip install requests
```

## Basic Flask app

For production-ready deployment it is important to consider both robustness and security, but in this tutorial we will focus on a minimal functioning implementation, demonstrating how to process the data from LGTM and integrate this with an example issue tracker. Similarly, we will avoid validation and error handling in this basic tutorial, and just assume for now that all the requests to the webhook are valid.

The following is a basic 'hello world'-esque Flask app, which accepts POST requests and echoes the incoming JSON back to the sender.

```python
from flask import Flask, request

app = Flask(__name__)

@app.route('/', methods=["POST"])
def issues_webhook():
    return request.data, 200

if __name__ == "__main__":
    app.run()
```
Using the built-in WSGI development server that comes with Flask, this application can be run by simply saving the code to a file and executing it as follows.
```bash
python flask_testing.py
```
When successfully exectued, a service will be operating on localhost:5000 that will echo all POSTed JSON.

## Format of webhook request

All requests from LGTM to the specified webhook endpoint are of HTTP method POST, and they fall into five categories.
- `create`
- `close`
- `reopen`
- `suppress`
- `unsuppress`

For this tutorial we will focus just on the basic operations of opening and closing tickets.

### Creating a new ticket

A full example of a `create` request payload is given below.

```json
{
    "transition": "create",
    "project": {
        "id": 1000001,
        "url-identifier": "Git/example_user/example_repo",
        "name": "example_user/example_repo",
        "url": "http://lgtm.com/projects/Git/example_user/example_repo"
    },
    "alert": {
        "file": "/example.py",
        "message": "Import of \"re\" is not used.\n",
        "url": "http://lgtm.com/issues/1000001/python/8cdXzW+PyA3qiHBbWFomoMGtiIE=",
        "query": {
            "name": "Unused import",
            "url": "http://lgtm.com/rules/1000678"
        }
    }
}
```
With Flask, the payload of an incoming request can be accessed using the following utility function.
```python
json_dict = request.get_json()
```
The Github API expects JSON with fields `title`, `body` and `labels`, and the body of the ticket can be formatted as markdown. For our example application, the following function takes `alert` and `project` from the LGTM payload and creates a dictionary that can be JSON serialized and then sent on to the correct Github endpoint. In this case we choose to just apply the single default label `LGTM` to all tickets.

```python
def get_issue_dict(alert, project):

    title = "%s (%s)" % (alert["query"]["name"], project["name"])

    lines = []
    lines.append("[%s](%s)" % (alert["query"]["name"], alert["query"]["url"]))
    lines.append("")
    lines.append("In %s:" % alert["file"])
    lines.append("> " + "\n> ".join(alert["message"].split("\n")))
    lines.append("[View alert on LGTM](%s)" % alert["url"])

    return {"title": title, "body": "\n".join(lines), "labels": ["LGTM"]}
```

To interact with the Github API we use the `requests` module, and define the following details for the target Github repository, pulling the access token from an environment variable.
```python
URL     = 'https://github.com/api/v3/repos/user/repo/issues'
HEADERS = {'content-type': 'application/json',
           'Authorization': 'Bearer %s' % os.getenv("GIT_ACCESS_TOKEN")
          }
```

LGTM expects a 2XX HTTP response of the form shown below, where the `issue_id` provided will be stored and used in future requests to change the state of the ticket.
```json
{
	"issue-id": external_issue_id
}
```

Putting all of this together, in order to handle incoming `create` requests our example app becomes...

```python
import os
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

URL     = 'https://github.com/api/v3/repos/user/repo/issues'
HEADERS = {'content-type': 'application/json',
           'Authorization': 'Bearer %s' % os.getenv("GIT_ACCESS_TOKEN")
          }

def get_issue_dict(alert, project):

    title = "%s (%s)" % (alert["query"]["name"], project["name"])

    lines = []
    lines.append("[%s](%s)" % (alert["query"]["name"], alert["query"]["url"]))
    lines.append("")
    lines.append("In %s:" % alert["file"])
    lines.append("> " + "\n> ".join(alert["message"].split("\n")))
    lines.append("[View alert on LGTM](%s)" % alert["url"])

    return {"title": title, "body": "\n".join(lines), "labels": ["LGTM"]}

@app.route('/', methods=["POST"])
def issues_webhook():

    json_dict = request.get_json()

    transition = json_dict.get('transition')

    if transition == 'create':

        data = get_issue_dict(json_dict.get('alert'), json_dict.get('project'))

        r = requests.post(URL, json=data, headers=HEADERS)

        issue_id = r.json()['number']

        return jsonify({'issue-id': issue_id}), r.status_code

if __name__ == "__main__":
    app.run()
```

### Changing an existing ticket

When closing an existing ticket, LGTM will send a request of the form...

```json
{
	"issue-id": external_issue_id,
    "transition": "close"
}
```
This can be handled by sending a `PATCH` request to the existing Github issue.
```python
if transition == 'create':
   ########
if transition == 'close':

    issue_id = json_dict.get('issue-id')

    r = requests.patch(URL + '/' + issue_id,
                        json={"state": transition},
                        headers=HEADERS)

    return jsonify({'issue-id': issue_id}), r.status_code
```
When reopening a ticket, the request will be of the same form, except with the transition `reopen`. This can be handled in a similar way to closing a ticket, but with Github expecting the state to be given as `open`.
```python
if transition == 'create':
   ########
if transition == 'close':
   ########
if transition == 'reopen':

    issue_id = json_dict.get('issue-id')

    r = requests.patch(URL + '/' + issue_id,
                        json={"state": 'open'}, # github expects `open`
                        headers=HEADERS)

    return jsonify({'issue-id': issue_id}), r.status_code
```

### Authorization

When setting up the issue tracker integration a secret key is automatically generated, and this is used to crytographically sign all outgoing requests. These are signed in the same way as callbacks for pull request integrations, documentation for which can be viewed in LGTM's [verify-callback-signature documentation](https://lgtm.com/help/lgtm/api/run-code-review#verify-callback-signature). Verification of the incoming requests can therefore be easily achieved as follows.

```python
import hmac

KEY = os.getenv("LGTM_SECRET", '').encode('utf-8')

digest = hmac.new(KEY, request.data, "sha1").hexdigest()
signature = request.headers.get('X-LGTM-Signature', "not-provided")

if not hmac.compare_digest(signature, digest):
    return jsonify({'message': "Unauthorized"}), 401
```

## Full example

Finally, putting all these piece together we have the following example Flask app, which will handle webhook requests from the LGTM issue tracker integration, and create tickets in the issue tracker of a specified Github repository.

```python
import os
from flask import Flask, request, jsonify
import requests
import hmac

app = Flask(__name__)

URL     = 'https://github.com/api/v3/repos/user/repo/issues'
HEADERS = {'content-type': 'application/json',
           'Authorization': 'Bearer %s' % os.getenv("GIT_ACCESS_TOKEN")}
KEY     = os.getenv("LGTM_SECRET", '').encode('utf-8')

def get_issue_dict(alert, project):

    title = "%s (%s)" % (alert["query"]["name"], project["name"])

    lines = []
    lines.append("[%s](%s)" % (alert["query"]["name"], alert["query"]["url"]))
    lines.append("")
    lines.append("In %s:" % alert["file"])
    lines.append("> " + "\n> ".join(alert["message"].split("\n")))
    lines.append("[View alert on LGTM](%s)" % alert["url"])

    return {"title": title, "body": "\n".join(lines), "labels": ["LGTM"]}

@app.route('/', methods=["POST"])
def issues_webhook():

    digest = hmac.new(KEY, request.data, "sha1").hexdigest()
    signature = request.headers.get('X-LGTM-Signature', "not-provided")

    if not hmac.compare_digest(signature, digest):
        return jsonify({'message': "Unauthorized"}), 401

    json_dict = request.get_json()

    transition = json_dict.get('transition')

    if transition == 'create':

        data = get_issue_dict(json_dict.get('alert'), json_dict.get('project'))

        r = requests.post(URL, json=data, headers=HEADERS)

        issue_id = r.json()['number']

        return jsonify({'issue-id': issue_id}), r.status_code

    if transition == 'close':

        issue_id = json_dict.get('issue-id')

        r = requests.patch(URL + '/' + issue_id,
                            json={"state": transition},
                            headers=HEADERS)

        return jsonify({'issue-id': issue_id}), r.status_code

    if transition == 'reopen':

        issue_id = json_dict.get('issue-id')

        r = requests.patch(URL + '/' + issue_id,
                            json={"state": 'open'}, # github expects `open`
                            headers=HEADERS)

        return jsonify({'issue-id': issue_id}), r.status_code

    # this example only supports the above three transition types
    # if transition is unmatched we return an error response
    return (
        jsonify({"code": 400, "error": "unknown transition type - %s" % transition}),
        400,
    )

if __name__ == "__main__":
    app.run()
```

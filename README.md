# LGTM Issue Tracker Example
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ambv/black) [![Total alerts](https://img.shields.io/lgtm/alerts/g/Semmle/lgtm-issue-tracker-example.svg?logo=lgtm&logoWidth=18)](https://lgtm.com/projects/g/Semmle/lgtm-issue-tracker-example/alerts/)

This project gives a quick illustrative example showing how to integrate LGTM Enterprise with a 3rd-party issue tracker. This code is intended as a proof-of-concept only, showing the basic operations necessary to handle incoming requests from LGTM. It is not intended for production use. Please feel free to use this as a starting point for your own integration, but if you are using Atlassian Jira see also the [LGTM Jira Add-on](https://github.com/Semmle/lgtm-jira-addon).

We use a lightweight `Flask` server to handle incoming requests, which in turn writes to the issue tracker of a specified Github repository. When not run in debug mode, incoming requests are verified using the secret specified when configuring the integration. For a more detailed explanation please see the associated [tutorial](tutorial.md).

For instructions on configuring your LGTM Enterprise instance please see the relevant [LGTM help pages](https://help.semmle.com/lgtm-enterprise/admin/help/adding-issue-trackers.html).

Requires an access token for the github installation with appropriate permissions.

## Configuration

When run through `pipenv` the app will pull config from the `.env` file, for which an example is provided....
```bash
FLASK_APP=issues.py
FLASK_DEBUG=0

GIT_REPO_URL=https://github.com/api/v3/repos/USERNAME/REPO/issues
GIT_ACCESS_TOKEN=PERSONAL_ACCESS_TOKEN

LGTM_SECRET=SECRET_AS_SPECIFIED_IN_LGTM_INTEGRATION_PANEL
```

## Running
Easiest way to just get it running is with `pipenv`. Obviously a proper deployment would require something other than the built-in `Flask` development server, but for POC purposes...

N.B. This example project requires a minimum of `python3.5`.

```bash
pipenv install
pipenv run flask run
```

## Contributing

We welcome contributions to our example LGTM Issue Tracker. While we intend this project to remain a minimal pedagogical example, if you have an idea how it could be made clearer or more valuable to other users, then please go ahead an open a Pull Request! Before you do, though, please take the time to read our [contributing guidelines](CONTRIBUTING.md).

## License

The LGTM Jira Add-on is licensed under [Apache License 2.0](LICENSE) by [Semmle](https://semmle.com).

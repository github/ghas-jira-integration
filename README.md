# LGTM issue tracker integration example
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ambv/black) [![Total alerts](https://img.shields.io/lgtm/alerts/g/Semmle/lgtm-issue-tracker-example.svg?logo=lgtm&logoWidth=18)](https://lgtm.com/projects/g/Semmle/lgtm-issue-tracker-example/alerts/)

## Issue tracking in LGTM Enterprise

[LGTM Enterprise](https://semmle.com/lgtm) gives customers the option of exporting alerts to any issue tracker, by sending webhook POST requests to the external service. Semmle provides an existing full-featured [add-on for Atlassian Jira](https://github.com/Semmle/lgtm-jira-addon), but other issue trackers need a lightweight application to act as translator for LGTM. This repository provides a basic example of how such an application might be implemented.

Integration with external issue trackers is not available to users of [LGTM.com](https://lgtm.com).

## This repository

This project gives a quick illustrative example of how to integrate LGTM Enterprise with a third-party issue tracker. This code is intended as a proof-of-concept only, showing the basic operations necessary to handle incoming requests from LGTM. It is not intended for production use. Please feel free to use this as a starting point for your own integration, but if you are using Atlassian Jira see also the [LGTM Jira add-on](https://github.com/Semmle/lgtm-jira-addon).

We use a lightweight `Flask` server to handle incoming requests, which in turn writes to the issue tracker of a specified GitHub repository. When not run in debug mode, incoming requests are verified using the secret specified when configuring the integration. For a more detailed explanation please see the associated [tutorial](tutorial.md).

For instructions on configuring your LGTM Enterprise instance, please see the relevant [LGTM help pages](https://help.semmle.com/lgtm-enterprise/admin/help/adding-issue-trackers.html).

Integration with the GitHub issue tracker requires an access token for the GitHub installation, with appropriate permissions.

## Configuration

When run through `pipenv` the app pull its configuration from the `.env` file, for which an example is provided:
```bash
FLASK_APP=issues.py
FLASK_DEBUG=0

GIT_REPO_URL=https://github.com/api/v3/repos/USERNAME/REPO/issues
GIT_ACCESS_TOKEN=PERSONAL_ACCESS_TOKEN

LGTM_SECRET=SECRET_AS_SPECIFIED_IN_LGTM_INTEGRATION_PANEL
```

## Running
The easiest way to get the app running is with `pipenv`. Obviously a proper deployment would require something other than the built-in `Flask` development server.

Note: This example project requires a minimum of `python3.5`.

```bash
pipenv install
pipenv run flask run
```

## Contributing

We welcome contributions to our example LGTM issue tracker integration. While we intend this project to remain a minimal pedagogical example, if you have an idea how it could be made clearer or more valuable to other users, then please go ahead an open a pull request! Before you do, though, please take the time to read our [contributing guidelines](CONTRIBUTING.md).

## License

The LGTM issue tracker integration example is licensed under [Apache License 2.0](LICENSE) by [Semmle](https://semmle.com).


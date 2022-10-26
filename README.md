# Synchronize GitHub Code Scanning alerts to Jira issues

[GitHub's REST API](https://docs.github.com/en/rest) and [webhooks](https://docs.github.com/en/developers/webhooks-and-events/about-webhooks) give customers the option of exporting alerts to any issue tracker, by allowing users to fetch the data via API endpoints and/or by receiving webhook POST requests to a hosted server.

## This repository

This repository gives a quick illustrative example of how to integrate GitHub Code Scanning with Jira. The code is intended as a proof-of-concept, showing the basic operations necessary to handle incoming requests from GitHub. Please feel free to use this as a starting point for your own integration.

## Using the GitHub Action

The easiest way to use this tool is via its GitHub Action, which you can add to your workflows. Here is what you need before you can start:

* A GitHub repository with Code Scanning enabled and a few alerts. Follow [this guide](https://docs.github.com/en/github/finding-security-vulnerabilities-and-errors-in-your-code/setting-up-code-scanning-for-a-repository) to set up Code Scanning.
* The URL of your Jira Server instance.
* A [Jira project](https://confluence.atlassian.com/adminjiraserver/creating-a-project-938846813.html) to store your issues. You will need to provide its `project key` to the action.
* A Jira Server account (username + password) with the following permissions for the abovementioned project:
  * `Browse Projects`
  * `Close Issues`
  * `Create Issues`
  * `Delete Issues`
  * `Edit Issues`
  * `Transition Issues`
* Depending on where you run your workflow, the Jira Server instance must be accessible from either the [GitHub.com IP addresses](https://docs.github.com/en/github/authenticating-to-github/about-githubs-ip-addresses) or the address of your GitHub Enterprise Server instance.

Make sure you safely store all credentials as [GitHub Secrets](https://docs.github.com/en/actions/reference/encrypted-secrets). For accessing the Code Scanning alert data, the action uses the [GITHUB_TOKEN](https://docs.github.com/en/actions/reference/authentication-in-a-workflow#using-the-github_token-in-a-workflow) which is automatically created for you, so you don't need to provide it. Finally, set up the following workflow in your repository, e.g. by adding the file `.github/workflows/jira-sync.yml`:

```yaml
name: "Sync GHAS to Jira"

on:
  schedule:
    - cron: '*/10 * * * *'    # trigger synchronization every 10 minutes

jobs:
  test_job:
    runs-on: ubuntu-latest
    steps:
      - name: Sync alerts to Jira issues
        uses: github/ghas-jira-integration@v1
        with:
          jira_url: '<INSERT JIRA SERVER URL>'
          jira_user: '${{ secrets.JIRA_USER }}'
          jira_token: '${{ secrets.JIRA_TOKEN }}'
          jira_project: '<INSERT JIRA PROJECT KEY>'
          sync_direction: 'gh2jira'
```

This action will push any changes (new alerts, alerts deleted, alert states changed) to Jira, by creating, deleting or changing the state of the corresponding Jira issues. There are two sync directions for the field `sync_direction`:

- `gh2jira`
- `jira2gh`


Using `gh2jira` means the alerts will sync from GitHub to Jira. If you set `sync_direction` to `jira2gh`, it will synchronize the other way. 
Currently, two-way integration is not yet possible via the action. If you need it, use the CLI's `serve` command (see below).


#### Using this Action to synchronize secret scanning alerts
Secret scanning alerts can only be queried with the API in private repositories. For public repositories, there will just be an empty results list. You'll need to pass in a PAT via `github_token` that has admin rights to access secret scanning alerts.

The PAT needs the following scope to retrieve secret scanning alerts:

**Fine-grained tokens:** `Secret scanning alerts - Read-only`  
**Tokens (classic):** `security_events`

```
        with:
          jira_url: '<INSERT JIRA SERVER URL>'
          jira_user: '${{ secrets.JIRA_USER }}'
          jira_token: '${{ secrets.JIRA_TOKEN }}'
          jira_project: '<INSERT JIRA PROJECT KEY>'
          github_token: '${{ secrets.PERSONAL_ACCESS_TOKEN }}'
          sync_direction: 'gh2jira'
 ```     

#### Other optional features for this Action

##### Labels
You can also create labels for the Jira issues that are created. By using the example yaml below in your workflow, you can use multiple labels, and spaces will be respected. For example, if you add `red-team, blue team`, the labels would be created 'red-team' and 'blue team'. If this input is updated in the workflow, the existing JIRE issues will also be updated with the same labels.

```yaml
with:
  jira_labels: 'red-team,blue-team,green-team'
```

##### Custom transition states (end, reopen)
You can customize the end and reopen states if your Jira workflows don't use the default close/reopen states.

```yaml
with:
  issue_end_state: 'Closed'
  issue_reopen_state: 'red-team-followup'
```


## Using the CLI's `sync` command

### Installation

The easiest way to get the CLI running is with `pipenv`:

```bash
pipenv install
pipenv run ./gh2jira --help
```

Note: `gh2jira` requires a minimum of `python3.5`.

In addition to the [usual requirements](#using-the-github-action) you also need:
* the URL for the GitHub API, which is
  * https://api.github.com if your repository is located on GitHub.com
  * https://your-hostname/api/v3/ if your repository is located on a GitHub Server instance
* a GitHub `personal access token`, so that the program can fetch alerts from your repository. Follow [this guide](https://docs.github.com/en/github/authenticating-to-github/creating-a-personal-access-token) to obtain a dedicated token. It will have to have at least the `security_events` scope and muist have admin rights to access secret scanning alerts.

```bash
pipenv run ./gh2jira sync \
                 --gh-url "<INSERT GITHUB API URL>" \
                 --gh-token "<INSERT GITHUB PERSONAL ACCESS TOKEN>" \
                 --gh-org "<INSERT REPO ORGANIZATON>" \
                 --gh-repo "<INSERT REPO NAME>" \
                 --jira-url "<INSERT JIRA SERVER INSTANCE URL>" \
                 --jira-user "<INSERT JIRA USER>" \
                 --jira-token "<INSERT JIRA PASSWORD>" \
                 --jira-project "<INSERT JIRA PROJECT KEY>" \
                 --direction gh2jira
```

Note: Instead of the `--gh-token` and `--jira-token` options, you may also set the `GH2JIRA_GH_TOKEN` and `GH2JIRA_JIRA_TOKEN` environment variables. The above command could be invoked via a cronjob every X minutes, to make sure issues and alerts are kept in sync.

#### Other optional features for the CLI

There is an optional parameter you can use for creating labels in your Jira issues. As previously mentioned, spaces within the double quotes will be respected and saved. Just like the GitHub Actions way, the custom transition states are also optional when using the CLI.


```bash
--jira-labels "red-team,blue-team,green-team"
--issue-end-state "Closed"
--issue-reopen-state "blue-team-reopen"
```

Here's an example for a two-way integration:

```bash
pipenv run ./gh2jira sync \
                 --gh-url "<INSERT GITHUB API URL>" \
                 --gh-token "<INSERT GITHUB PERSONAL ACCESS TOKEN>" \
                 --gh-org "<INSERT REPO ORGANIZATON>" \
                 --gh-repo "<INSERT REPO NAME>" \
                 --jira-url "<INSERT JIRA SERVER INSTANCE URL>" \
                 --jira-user "<INSERT JIRA USER>" \
                 --jira-token "<INSERT JIRA PASSWORD>" \
                 --jira-project "<INSERT JIRA PROJECT KEY>" \
                 --state-file myrepository-state.json \
                 --direction both
```

In this case the repository's state is stored in a JSON file (which will be created if it doesn't already exist). Alternatively, the state can also be stored in a dedicated Jira issue via `--state-issue -` (this will automatically generate and update a storage issue within the same Jira project). If the storage issue should be in a separate Jira project, you can specify `--state-issue KEY-OF-THE-STORAGE-ISSUE`.

## Other CLI sync options

<details>
<summary>The serve command</summary>

## Using the CLI's `serve` command

The following method is the most involved one, but currently the only one which allows two-way integration (i.e. changes to Code Scanning alerts trigger changes to Jira issues and vice versa). It uses a lightweight `Flask` server to handle incoming Jira and GitHub webhooks. The server is meant to be an example and not production-ready.

In addition to the [usual requirements](#using-the-github-action) you also need:
* A machine with an address that can be reached from GitHub.com or your GitHub Enterprise Server instance and your Jira Server instance. This machine will run the server.
* Webhooks set up, both, on GitHub and Jira. On GitHub only repository or organization owners can do so. On Jira, it requires administrator access.
* A secret which will be used to verify webhook requests.

First, [create a GitHub webhook](https://docs.github.com/en/developers/webhooks-and-events/creating-webhooks) with the following event triggers:
* [Code scanning alerts](https://docs.github.com/en/developers/webhooks-and-events/webhook-events-and-payloads#code_scanning_alert)
* [Repositories](https://docs.github.com/en/developers/webhooks-and-events/webhook-events-and-payloads#repository)

This can be either a repository or an organization-wide hook. Set the `Payload URL` to `https://<the machine>/github`, the `Content type` to `application/json` and insert your webhook `Secret`. Make sure to `Enable SSL verification`.

Second, [register a webhook on Jira](https://developer.atlassian.com/server/jira/platform/webhooks/#registering-a-webhook). Give your webhook a `Name` and enter the `URL`: `https://<the machine>/jira?secret_token=<INSERT WEBHOOK SECRET>`. In the `Events` section specify `All issues` and mark the boxes `created`, `updated` and `deleted`. Click `Save`.

Finally, start the server:

```bash
pipenv run ./gh2jira serve \
                 --gh-url "<INSERT GITHUB API URL>" \
                 --gh-token "<INSERT GITHUB PERSONAL ACCESS TOKEN>" \
                 --jira-url "<INSERT JIRA SERVER INSTANCE URL>" \
                 --jira-user "<INSERT JIRA USER>" \
                 --jira-token "<INSERT JIRA PASSWORD>" \
                 --jira-project "<INSERT JIRA PROJECT KEY>" \
                 --secret "<INSERT WEBHOOK SECRET>" \
                 --port 5000 \
                 --direction both
```

This will enable two-way integration between GitHub and Jira. Note: Instead of the `--secret` option, you may also set the `GH2JIRA_SECRET` environment variable.
 
</details>

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

## License

[Apache V2](LICENSE)

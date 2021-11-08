#!/bin/sh
pip3 install pipenv
pipenv install
REPOSITORY_NAME="$(echo "$GITHUB_REPOSITORY" | cut -d/ -f 2)"
./gh2jira sync \
  --gh-url "$GITHUB_API_URL" \
  --gh-token "$INPUT_GITHUB_TOKEN" \
  --gh-org "$GITHUB_REPOSITORY_OWNER" \
  --gh-repo "$REPOSITORY_NAME" \
  --jira-url "$INPUT_JIRA_URL" \
  --jira-user "$INPUT_JIRA_USER" \
  --jira-token "$INPUT_JIRA_TOKEN" \
  --jira-project "$INPUT_JIRA_PROJECT" \
  --jira-labels "$INPUT_JIRA_LABELS" \
  --direction "$INPUT_SYNC_DIRECTION" \
  --issue-end-state "$INPUT_ISSUE_END_STATE" \
  --issue-reopen-state "$INPUT_ISSUE_REOPEN_STATE" \
  --state-issue -

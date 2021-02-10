#!/bin/sh
REPOSITORY_NAME="$(echo "$GITHUB_REPOSITORY" | cut -d/ -f 2)"
cd / && pipenv run /gh2jira sync \
                            --gh-url "$GITHUB_API_URL" \
                            --gh-token "$INPUT_GITHUB_TOKEN" \
                            --gh-org "$GITHUB_REPOSITORY_OWNER" \
                            --gh-repo "$REPOSITORY_NAME" \
                            --jira-url "$INPUT_JIRA_URL" \
                            --jira-user "$INPUT_JIRA_USER" \
                            --jira-token "$INPUT_JIRA_TOKEN" \
                            --jira-project "$INPUT_JIRA_PROJECT" \
                            --direction "$INPUT_SYNC_DIRECTION"

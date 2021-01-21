import argparse
import ghlib
import jiralib
import os
import sys
import json
import util


def fail(msg):
    print(msg)
    sys.exit(1)


def serve(args):
    pass


def sync(args):
    if not args.gh_url or not args.jira_url:
        fail('Both GitHub and JIRA URL have to be specified!')

    if not args.gh_user or not args.gh_token:
        fail('No GitHub credentials specified!')

    if not args.jira_user or not args.jira_token:
        fail('No JIRA credentials specified!')

    if not args.gh_org:
        fail('No GitHub organization specified!')

    if not args.gh_repo:
        fail('No GitHub repository specified!')

    github = ghlib.GitHub(args.gh_url, args.gh_user, args.gh_token)
    jira = jiralib.Jira(args.jira_url, args.jira_user, args.jira_token)
    util.sync_repo(github.getRepository(args.gh_org + '/' + args.gh_repo), jira.getProject(args.jira_project))


def check_hooks(args):
    pass


def install_hooks(args):
    if not args.hook_url:
        fail('No hook URL specified!')

    if not args.hook_secret:
        fail('No hook secret specified!')

    if not args.gh_url and not args.jira_url:
        fail('Neither GitHub nor JIRA URL specified!')

    # user wants to install a github hook
    if args.gh_url:
        if not args.gh_user or not args.gh_token:
            fail('No GitHub credentials specified!')

        if not args.gh_org:
            fail('No GitHub organization specified!')

        github = ghlib.GitHub(args.gh_url, args.gh_user, args.gh_token)

        if args.gh_repo:
            ghrepo = github.getRepository(args.gh_org + '/' + args.gh_repo)
            ghrepo.create_hook(url=args.hook_url, secret=args.hook_secret)
        else:
            github.create_org_hook(url=args.hook_url, secret=args.hook_secret)

    # user wants to install a JIRA hook
    if args.jira_url:
        if not args.jira_user or not args.jira_token:
            fail('No JIRA credentials specified!')
        jira = jiralib.Jira(args.jira_url, args.jira_user, args.jira_token)
        jira.create_hook('github_jira_synchronization_hook', args.hook_url, args.hook_secret)


def list_hooks(args):
    if not args.gh_url and not args.jira_url:
        fail('Neither GitHub nor JIRA URL specified!')

    # user wants to list github hooks
    if args.gh_url:
        if not args.gh_user or not args.gh_token:
            fail('No GitHub credentials specified!')

        if not args.gh_org:
            fail('No GitHub organization specified!')

        github = ghlib.GitHub(args.gh_url, args.gh_user, args.gh_token)

        if args.gh_repo:
            for h in github.getRepository(args.gh_org + '/' + args.gh_repo).list_hooks():
                print(json.dumps(h, indent=4))
        else:
            for h in github.list_org_hooks(args.gh_org):
                print(json.dumps(h, indent=4))

    # user wants to list JIRA hooks
    if args.jira_url:
        if not args.jira_user or not args.jira_token:
            fail('No JIRA credentials specified!')

        jira = jiralib.Jira(args.jira_url, args.jira_user, args.jira_token)

        for h in jira.list_hooks():
            print(json.dumps(h, indent=4))


def main():
    credential_base = argparse.ArgumentParser(add_help=False)
    credential_base.add_argument(
        '--gh-org',
        help='GitHub organization'
    )
    credential_base.add_argument(
        '--gh-repo',
        help='GitHub repository'
    )
    credential_base.add_argument(
        '--gh-url',
        help='API URL of GitHub instance',
    )
    credential_base.add_argument(
        '--gh-user',
        help='GitHub user name'
    )
    credential_base.add_argument(
        '--gh-token',
        help='GitHub API token'
    )
    credential_base.add_argument(
        '--jira-url',
        help='URL of JIRA instance'
    )
    credential_base.add_argument(
        '--jira-user',
        help='GitHub user name'
    )
    credential_base.add_argument(
        '--jira-token',
        help='JIRA password'
    )
    credential_base.add_argument(
        '--jira-project',
        help='JIRA project key'
    )

    parser = argparse.ArgumentParser(prog='cs2jira')
    subparsers = parser.add_subparsers()

    # serve
    serve = subparsers.add_parser(
        'serve',
        parents=[credential_base],
        help='Spawn a webserver which keeps GitHub alerts and JIRA tickets in sync',
        description='Spawn a webserver which keeps GitHub alerts and JIRA tickets in sync'
    )
    serve.set_defaults(func=serve)

    # sync
    sync_parser = subparsers.add_parser(
        'sync',
        parents=[credential_base],
        help='Synchronize GitHub alerts and JIRA tickets for a given repository',
        description='Synchronize GitHub alerts and JIRA tickets for a given repository'
    )
    sync_parser.set_defaults(func=sync)

    # hooks
    hooks = subparsers.add_parser(
        'hooks',
        help='Manage JIRA and GitHub webhooks',
        description='Manage JIRA and GitHub webhooks'
    )


    hooks_subparsers = hooks.add_subparsers()

    # list hooks
    hooks_list = hooks_subparsers.add_parser(
        'list',
        parents=[credential_base],
        help='List existing GitHub or JIRA webhooks',
        description='List existing GitHub or JIRA webhooks'
    )
    hooks_list.set_defaults(func=list_hooks)

    # install hooks
    hooks_install = hooks_subparsers.add_parser(
        'install',
        parents=[credential_base],
        help='Install existing GitHub or JIRA webhooks',
        description='Install GitHub or JIRA webhooks'
    )
    hooks_install.add_argument(
        '--hook-secret',
        help='Webhook secret'
    )
    hooks_install.add_argument(
        '--hook-url',
        help='Webhook target url'
    )
    hooks_install.add_argument(
        '--insecure-ssl',
        action='store_true',
        help='Install GitHub hook without SSL check'
    )
    hooks_install.set_defaults(func=install_hooks)

    # check hooks
    hooks_check = hooks_subparsers.add_parser(
        'check',
        parents=[credential_base],
        help='Check that hooks are installed properly',
        description='Check that hooks are installed properly'
    )
    hooks_check.set_defaults(func=check_hooks)


    def print_usage(args):
        print(parser.format_usage())

    parser.set_defaults(func=print_usage)
    args = parser.parse_args()

    # run the given action
    args.func(args)

main()

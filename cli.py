import argparse
import ghlib
import jiralib
import os
import sys
import json
import util
import logging
import issues

root = logging.getLogger()
root.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
root.addHandler(handler)


def fail(msg):
    print(msg)
    sys.exit(1)


def direction_str_to_num(dstr):
    if dstr == 'gh2jira':
        return util.DIRECTION_G2J
    elif dstr == 'jira2gh':
        return util.DIRECTION_J2G
    elif dstr == 'both':
        return util.DIRECTION_BOTH
    else:
        fail('Unknown direction argument "{direction}"!'.format(direction=dstr))


def serve(args):
    if not args.gh_url or not args.jira_url:
        fail('Both GitHub and JIRA URL have to be specified!')

    if not args.gh_token:
        fail('No GitHub token specified!')

    if not args.jira_user or not args.jira_token:
        fail('No JIRA credentials specified!')

    if not args.jira_project:
        fail('No JIRA project specified!')

    if not args.secret:
        fail('No Webhook secret specified!')

    github = ghlib.GitHub(args.gh_url, args.gh_token)
    jira = jiralib.Jira(args.jira_url, args.jira_user, args.jira_token)
    sync = util.Sync(
        github,
        jira.getProject(args.jira_project),
        direction=direction_str_to_num(args.direction)
    )
    issues.run_server(sync, args.secret)


def sync(args):
    if not args.gh_url or not args.jira_url:
        fail('Both GitHub and JIRA URL have to be specified!')

    if not args.gh_token:
        fail('No GitHub credentials specified!')

    if not args.jira_user or not args.jira_token:
        fail('No JIRA credentials specified!')

    if not args.jira_project:
        fail('No JIRA project specified!')

    if not args.gh_org:
        fail('No GitHub organization specified!')

    if not args.gh_repo:
        fail('No GitHub repository specified!')

    github = ghlib.GitHub(args.gh_url, args.gh_token)
    jira = jiralib.Jira(args.jira_url, args.jira_user, args.jira_token)
    util.Sync(
        github,
        jira.getProject(args.jira_project),
        direction=direction_str_to_num(args.direction)
    ).sync_repo(args.gh_org + '/' + args.gh_repo)


def check_hooks(args):
    pass


def install_hooks(args):
    if not args.hook_url:
        fail('No hook URL specified!')

    if not args.secret:
        fail('No hook secret specified!')

    if not args.gh_url and not args.jira_url:
        fail('Neither GitHub nor JIRA URL specified!')

    # user wants to install a github hook
    if args.gh_url:
        if not args.gh_token:
            fail('No GitHub token specified!')

        if not args.gh_org:
            fail('No GitHub organization specified!')

        github = ghlib.GitHub(args.gh_url, args.gh_token)

        if args.gh_repo:
            ghrepo = github.getRepository(args.gh_org + '/' + args.gh_repo)
            ghrepo.create_hook(url=args.hook_url, secret=args.secret)
        else:
            github.create_org_hook(url=args.hook_url, secret=args.secret)

    # user wants to install a JIRA hook
    if args.jira_url:
        if not args.jira_user or not args.jira_token:
            fail('No JIRA credentials specified!')
        jira = jiralib.Jira(args.jira_url, args.jira_user, args.jira_token)
        jira.create_hook('github_jira_synchronization_hook', args.hook_url, args.secret)


def list_hooks(args):
    if not args.gh_url and not args.jira_url:
        fail('Neither GitHub nor JIRA URL specified!')

    # user wants to list github hooks
    if args.gh_url:
        if not args.gh_token:
            fail('No GitHub token specified!')

        if not args.gh_org:
            fail('No GitHub organization specified!')

        github = ghlib.GitHub(args.gh_url, args.gh_token)

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
        '--gh-token',
        help='GitHub API token'
    )
    credential_base.add_argument(
        '--jira-url',
        help='URL of JIRA instance'
    )
    credential_base.add_argument(
        '--jira-user',
        help='JIRA user name'
    )
    credential_base.add_argument(
        '--jira-token',
        help='JIRA password'
    )
    credential_base.add_argument(
        '--jira-project',
        help='JIRA project key'
    )
    credential_base.add_argument(
        '--secret',
        help='Webhook secret'
    )

    direction_base = argparse.ArgumentParser(add_help=False)
    direction_base.add_argument(
        '--direction',
        help='Sync direction. Possible values are "gh2jira" (alert states have higher priority than issue states),'
           + '"jira2gh" (issue states have higher priority than alert states) and "both" (adjust in both directions)',
        default='both'
    )

    parser = argparse.ArgumentParser(prog='cs2jira')
    subparsers = parser.add_subparsers()

    # serve
    serve_parser = subparsers.add_parser(
        'serve',
        parents=[credential_base, direction_base],
        help='Spawn a webserver which keeps GitHub alerts and JIRA tickets in sync',
        description='Spawn a webserver which keeps GitHub alerts and JIRA tickets in sync'
    )
    serve_parser.set_defaults(func=serve)

    # sync
    sync_parser = subparsers.add_parser(
        'sync',
        parents=[credential_base, direction_base],
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

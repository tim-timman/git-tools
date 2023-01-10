#!/usr/bin/env python3

from __future__ import annotations

import argparse
import functools
from concurrent.futures import as_completed, ThreadPoolExecutor
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Iterator, Optional


if sys.version_info <= (3, 11):
    print("ERROR: Requires Python 3.11 or higher", file=sys.stderr)
    raise SystemExit(1)


def is_git_repo(d: Path):
    assert d.is_dir(), "path is a directory"

    cmd = ["git", "-C", shlex.quote(str(d)), "rev-parse"]
    p = subprocess.run(cmd,
                       stderr=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL)
    return p.returncode == 0


def find_git_repos(parent: Path) -> Iterator[Path]:
    assert parent.is_dir(), "path is a directory"
    if is_git_repo(parent):
        yield parent
        return

    for child in parent.iterdir():
        if child.is_dir():
            yield from find_git_repos(child)


class GitError(Exception):
    pass


COLOR_GREEN = "\033[32m"
COLOR_RESET = "\033[0m"

# ---[ git grep ] ---

# Convenience git grep args to use
DEFAULT_GIT_GREP_ARGS = ["-n"]


def add_grep_options(parser: argparse.ArgumentParser):
    parser.add_argument("-x", "--exclude", metavar="PATTERN", default=[],
                        action="extend", type=str, nargs=1,
                        help="convenience for git grep's exclude files (e.g. '*.lock')")
    parser.add_argument("--no-defaults", dest="use_defaults",
                        action="store_false",
                        help=f"don't use default git args: {shlex.join(DEFAULT_GIT_GREP_ARGS)}")

    parser.usage = f"{parser.format_usage()[7:].rstrip()} [--] [git grep args ...]"

    parser.set_defaults(func=grep_command)


def grep_command(args, git_args):
    if args.use_color:
        git_args.insert(0, "--color=always")

    if args.prefix is None:
        args.prefix = "line"

    # @Robustness: Maybe inserting at the start isn't always correct
    if args.use_defaults:
        for idx, arg in enumerate(DEFAULT_GIT_GREP_ARGS):
            git_args.insert(idx, arg)

    if args.exclude:
        git_excludes = [f":!{x}" for x in args.exclude]
        # pathspecs must be clarified by '--' and put last
        if "--" not in git_args:
            git_args.append("--")
        git_args.extend(git_excludes)

    print(f"=> git grep {shlex.join(git_args)}", file=sys.stderr)

    def command(repo: Path):
        return run_git(["git", "-C", shlex.quote(str(repo)), "grep", *git_args],
                       ignore_returncodes=(1,))
    return command


# ---[ git XXX ] ---
def default_command(args, git_args):
    print(f"=> git {shlex.join(git_args)}", file=sys.stderr)

    def command(repo: Path):
        return run_git(["git", "-C", shlex.quote(str(repo)), *git_args])
    return command


def run_git(command: list[str], *,
            ok_returncodes: tuple[int] = (0,),
            ignore_returncodes: tuple[int] = ()) -> Optional[list[bytes]]:
    p = subprocess.run(command, capture_output=True)
    if p.returncode in ok_returncodes:
        return p.stdout.splitlines(keepends=True)
    elif p.returncode in ignore_returncodes:
        return None
    else:
        raise GitError(p.stderr.decode())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-X", "--exclude-repo", metavar="PATTERN",  default=[],
                        action="extend", type=str, nargs=1,
                        help="glob pattern of repos to exclude")
    parser.add_argument("--list-repos", action="store_true",
                        help="just list repos and exit (for piping)")
    parser.add_argument("--prefix", choices=("repo", "line", "no"),
                        default=None,
                        help="prefix git output with repo path "
                             "(default changes with command)")

    subparser = parser.add_subparsers(dest="command", required=False)

    grep_parser = subparser.add_parser("grep")
    add_grep_options(grep_parser)
    default_parser = subparser.add_parser("--")
    default_parser.set_defaults(func=default_command)

    args, git_args = parser.parse_known_args()

    if args.list_repos:
        for d in find_git_repos(Path.cwd()):
            if any(d.match(pattern) for pattern in args.exclude_repo):
                continue
            print(d)
        return 0

    # Remove "--" separator if used for disambiguating our args and those to git
    try:
        if "--" == git_args[0]:
            git_args.pop(0)
    except IndexError:
        pass

    if "--color=never" in git_args or \
            (not sys.stdout.isatty() and "--color=always" in git_args):
        args.use_color = False
    else:
        args.use_color = True

    if "func" not in args:
        parser.print_usage()
        return 1

    git_command = args.func(args, git_args)

    try:
        repos = [d for d in find_git_repos(Path.cwd())
                 if not any(d.match(pattern) for pattern in args.exclude_repo)]

        with ThreadPoolExecutor() as ex:
            future_to_repo = {ex.submit(git_command, d): d for d in repos}

            for future in as_completed(future_to_repo):
                repo = future_to_repo[future]
                try:
                    results = future.result()
                except GitError as e:
                    print(f"ERROR: in repo {repo}:\n{e}", file=sys.stderr)
                    return 1
                if results is None:
                    continue

                repo_path = repo.relative_to(Path.cwd())

                if args.use_color:
                    repo_prefix = f"{COLOR_GREEN}{repo_path!s}{COLOR_RESET}/".encode()
                else:
                    repo_prefix = f"{repo_path!s}/".encode()

                prefix = args.prefix or "repo"
                if prefix == "repo":
                    sys.stdout.buffer.write(repo_prefix + b"\n")

                try:
                    for result in results:
                        if prefix == "line":
                            sys.stdout.buffer.write(repo_prefix)
                        sys.stdout.buffer.write(result)
                    sys.stdout.flush()
                except BrokenPipeError:
                    devnull = os.open(os.devnull, os.O_WRONLY)
                    os.dup2(devnull, sys.stdout.fileno())
                    raise SystemExit(1)

    except KeyboardInterrupt:
        print("Caught Ctrl-C, exiting.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

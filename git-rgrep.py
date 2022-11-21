#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Iterator, Optional

# Convenience git grep args to use
DEFAULT_GIT_GREP_ARGS = ["-n"]


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


def git_grep(repo: Path, args: list[str]) -> Optional[list[bytes]]:
    command = ["git", "-C", shlex.quote(str(repo)), "grep"]
    command.extend(args)

    p = subprocess.run(command, capture_output=True)
    if p.returncode == 0:
        return p.stdout.splitlines(keepends=True)
    elif p.returncode == 1:
        # No match
        return None
    else:
        raise GitError(f"git grep error in repo {repo}\n{p.stderr.decode()}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exclude-dir", type=Path, action="extend",
                        metavar="PATH", nargs="+", default=[],
                        help="repos directories to exclude")
    parser.add_argument("-x", "--exclude", metavar="pattern", default=[],
                        action="extend", type=str, nargs=1,
                        help="convenience for git grep's exclude files")
    parser.add_argument("--no-defaults", dest="use_defaults",
                        action="store_false",
                        help=f"use default git args: {shlex.join(DEFAULT_GIT_GREP_ARGS)}")

    parser.usage = f"{parser.format_usage().rstrip()} [--] [git grep args ...]"

    args, git_grep_args = parser.parse_known_args()

    # Remove "--" separator if used for disambiguating our args and those to git grep
    try:
        if "--" == git_grep_args[0]:
            git_grep_args.pop(0)
    except IndexError:
        pass

    # @Robustness: Maybe inserting at the start isn't always correct
    if args.use_defaults:
        for idx, arg in enumerate(DEFAULT_GIT_GREP_ARGS):
            git_grep_args.insert(idx, arg)

    if "--color=never" in git_grep_args or \
            (not sys.stdout.isatty() and "--color=always" in git_grep_args):
        use_color = False
    else:
        git_grep_args.insert(0, "--color=always")
        use_color = True

    if args.exclude:
        git_excludes = [f":!{x}" for x in args.exclude]
        # pathspecs must be clarified by '--' and put last
        if "--" not in git_grep_args:
            git_grep_args.append("--")
        git_grep_args.extend(git_excludes)

    print(f"=> git grep {shlex.join(git_grep_args)}", file=sys.stderr)

    try:
        for d in find_git_repos(Path.cwd()):
            if any(d.is_relative_to(x_dir) for x_dir in args.exclude_dir):
                continue

            # @Robustness: this matching is a bit naive. But we want simple
            # exclude filters to work on repo names too since we print them.
            # Makes it more intuitive.
            rel_repo_path = str(d.relative_to(Path.cwd()))
            if any(re.search(pattern, rel_repo_path) for pattern in args.exclude):
                continue

            try:
                results = git_grep(d, git_grep_args)
            except GitError as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return 1
            else:
                if results is None:
                    continue

                repo_path = d.relative_to(Path.cwd())
                if use_color:
                    repo_prefix = f"{COLOR_GREEN}{repo_path!s}{COLOR_RESET}/".encode()
                else:
                    repo_prefix = f"{repo_path!s}/".encode()

                for result in results:
                    sys.stdout.buffer.write(repo_prefix)
                    sys.stdout.buffer.write(result)

    except KeyboardInterrupt:
        print("Caught Ctrl-C, exiting.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

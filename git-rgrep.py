#!/usr/bin/env python3

import argparse
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Iterator, Optional

check_git_repo = """git -C "{}" rev-parse"""


def is_git_repo(d: Path):
    assert d.is_dir(), "path is a directory"
    cmd = shlex.split(check_git_repo.format(d))
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


def git_grep(repo: Path, args: list[str]) -> Optional[Iterator[str]]:
    command = ["git", "-C", f"{repo}", "grep"]
    command.extend(args)

    p = subprocess.run(command, capture_output=True)
    if p.returncode == 0:
        repo_path = repo.relative_to(Path.cwd())
        return (f"{COLOR_GREEN}{repo_path}{COLOR_RESET}/{line}" for line in p.stdout.decode().splitlines())
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
    parser.add_argument("git_grep_args",
                        metavar="arg", default=[],
                        nargs="*", help="passthru args to git grep")
    args = parser.parse_args()

    git_grep_args = ["-n"]
    git_grep_args.extend(args.git_grep_args)

    if "--color=never" in git_grep_args or \
            (not sys.stdout.isatty() and "--color=always" in git_grep_args):
        # HACK: just noop our global color codes
        for k in g:
            if k.startswith("COLOR_"):
                g[k] = ""
    else:
        git_grep_args.insert(0, "--color=always")

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

            try:
                results = git_grep(d, git_grep_args)
            except GitError as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return 1
            else:
                if results is not None:
                    print(*results, sep="\n")
    except KeyboardInterrupt:
        print("Caught Ctrl-C, exiting.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

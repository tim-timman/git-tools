#!/usr/bin/env python3

from __future__ import annotations

import argparse
from concurrent.futures import as_completed, ThreadPoolExecutor
import os
from pathlib import Path
import pty
import re
import select
import shlex
import signal
import subprocess
import sys
import threading
from typing import Optional


die = threading.Event()

if sys.version_info <= (3, 9):
    print("ERROR: Requires Python 3.9 or higher", file=sys.stderr)
    raise SystemExit(1)


def is_git_repo(d: Path):
    cmd = ["git", "-C", str(d), "rev-parse"]
    p = subprocess.run(cmd,
                       stderr=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL)
    return p.returncode == 0


def find_git_repos(parent: Path, depth: int = 3) -> list[Path]:
    assert parent.is_dir(), f"{parent} is not a directory"
    if is_git_repo(parent):
        return [parent]

    if depth < 1:
        return []

    repos: list[Path] = []
    with ThreadPoolExecutor() as ex:
        futures_repo_map = {ex.submit(is_git_repo, d): (d, depth - 1)
                            for d in parent.iterdir()
                            if d.is_dir()}

        while futures_repo_map:
            for future in as_completed(list(futures_repo_map)):
                is_repo = future.result()
                directory, cur_depth = futures_repo_map.pop(future)
                if is_repo:
                    repos.append(directory)
                elif cur_depth > 0:
                    futures_repo_map.update({
                        ex.submit(is_git_repo, d): (d, cur_depth - 1)
                        for d in directory.iterdir()
                        if d.is_dir()
                    })
    return repos


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
        return run_git(["git", "--no-pager", "-C", str(repo), "grep", *git_args],
                       ignore_returncodes=(1,))
    return command


# ---[ git XXX ] ---
def default_command(args, git_args):
    print(f"=> git {shlex.join(git_args)}", file=sys.stderr)

    def command(repo: Path):
        return run_git(["git", "--no-pager", "-C", str(repo), *git_args])
    return command


def run_git(command: list[str], *,
            ok_returncodes: tuple[int] = (0,),
            ignore_returncodes: tuple[int] = ()) -> Optional[tuple[list[bytes], list[bytes]]]:

    masters, slaves = zip(*(pty.openpty() for _ in range(3)))

    p = subprocess.Popen(command, close_fds=True, env={"TERM": os.getenv("TERM", "xterm")},
                         stdin=slaves[0], stdout=slaves[1], stderr=slaves[2])
    for fd in slaves:
        os.close(fd)

    results = {
        masters[1]: bytearray(),
        masters[2]: bytearray(),
    }
    readable = [masters[1], masters[2]]
    try:
        while readable:
            if die.is_set():
                p.send_signal(signal.SIGINT)
                return None

            ready, _, _ = select.select(readable, [], [])
            for fd in ready:
                data = os.read(fd, 512)
                if not data:
                    readable.remove(fd)
                    continue
                results[fd] += data
    finally:
        if p.poll() is None:
            p.kill()
        p.wait()
        for fd in masters:
            os.close(fd)

    stdout, stderr = results[masters[1]], results[masters[2]]

    if p.returncode in ok_returncodes:
        return stdout.splitlines(keepends=True), stderr.splitlines(keepends=True)
    elif p.returncode in ignore_returncodes:
        return None
    else:
        raise GitError(stderr.decode())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-X", "--exclude-repo", metavar="PATTERN", default=[],
                        action="extend", type=str, nargs=1,
                        help="regex pattern of repos to exclude")
    parser.add_argument("-I", "--include-repo", metavar="PATTERN", default=[],
                        action="extend", type=str, nargs=1,
                        help="regex pattern of repos to include")
    parser.add_argument("-d", "--depth", type=int, default=3,
                        help="max recurse depth (DEFAULT: %(default)s)")
    parser.add_argument("-C", "--cwd", type=Path, default=Path.cwd(), metavar="PATH",
                        help="change current working directory")
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

    if not args.cwd.is_absolute():
        args.cwd = args.cwd.absolute()
    args.cwd = args.cwd.resolve()

    include_patterns = [re.compile(p) for p in args.include_repo]
    exclude_patterns = [re.compile(p) for p in args.exclude_repo]

    repos = []
    for repo in find_git_repos(args.cwd, args.depth):
        repo_str = str(repo)
        if include_patterns and not any(pattern.search(repo_str) for pattern in include_patterns):
            continue
        if any(pattern.search(repo_str) for pattern in exclude_patterns):
            continue
        repos.append(repo)

    if args.list_repos:
        for d in repos:
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
        with ThreadPoolExecutor() as ex:
            future_to_repo = {ex.submit(git_command, d): d for d in repos}

            for future in as_completed(future_to_repo):
                repo = future_to_repo[future]
                try:
                    results = future.result()
                except GitError as e:
                    print(f"ERROR: in repo {repo}:\n{e}", file=sys.stderr)
                    # cancel futures
                    die.set()
                    for f in future_to_repo:
                        f.cancel()
                    return 1

                if results is None:
                    continue

                repo_path = repo.relative_to(args.cwd)

                if args.use_color:
                    repo_prefix = f"{COLOR_GREEN}{repo_path!s}{COLOR_RESET}/".encode()
                else:
                    repo_prefix = f"{repo_path!s}/".encode()

                prefix = args.prefix or "repo"
                if prefix == "repo":
                    sys.stdout.buffer.write(repo_prefix + b"\n")

                for output, stream in zip(results, (sys.stdout, sys.stderr)):
                    try:
                        for result in output:
                            if prefix == "line":
                                stream.buffer.write(repo_prefix)
                            stream.buffer.write(result)
                        stream.flush()
                    except BrokenPipeError:
                        devnull = os.open(os.devnull, os.O_WRONLY)
                        os.dup2(devnull, stream.fileno())
                        raise SystemExit(1)

    except KeyboardInterrupt:
        print("Caught Ctrl-C, exiting.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# git-tools

## git-r

**git-r** is a tool that from your current working directory
recursively searches for directories that are git repos. It then
runs the provided git command in every repo and prints the results.

### Setup

Clone repo and cd into it.
Add as git alias:


```shell
git config --global alias.rgrep "\!python3.11 '$(pwd)/git-r.py'"
```

Or (maybe better) symlink it and run it as a script `gir`:
```shell
ln -s /usr/local/bin/gir "$(pwd)/git-r.py"
```

Usage:

```
$ gir --help
usage: gir [-h] [-X PATTERN] [-I PATTERN] [-d DEPTH] [-C PATH] [--list-repos] [--prefix {repo,line,no}] {grep,--} ...

positional arguments:
  {grep,--}

options:
  -h, --help            show this help message and exit
  -X PATTERN, --exclude-repo PATTERN
                        regex pattern of repos to exclude
  -I PATTERN, --include-repo PATTERN
                        regex pattern of repos to include
  -d DEPTH, --depth DEPTH
                        max recurse depth (DEFAULT: 3)
  -C PATH, --cwd PATH   change current working directory
  --list-repos          just list repos and exit (for piping)
  --prefix {repo,line,no}
                        prefix git output with repo path (default changes with command)
```

Usage `git r grep':

```
$ gir grep --help
usage: git-r.py grep [-h] [-x PATTERN] [--no-defaults] [--] [git grep args ...]

options:
  -h, --help            show this help message and exit
  -x PATTERN, --exclude PATTERN
                        convenience for git grep's exclude files (e.g. '*.lock')
  --no-defaults         don't use default git args: -n
```

Run arbitrary git command (e.g. `git fetch`):

```
gir -- fetch
```

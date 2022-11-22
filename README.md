# git-tools

## git-rgrep

**git-rgrep** is a tool that from your current working directory
recursivly searches for directories that are git repos. It then
runs `git grep` for every repo it finds and reports the results.

### Setup

Clone repo and cd into it.
Add as git alias:


```shell
git config --global alias.rgrep "\!python3.10 '$(pwd)/git-rgrep.py'"
```

Usage:

```
$ git rgrep -h
'rgrep' is aliased to '!python3.10 '<...>/git-tools/git-rgrep.py''
usage: git-rgrep.py [-h] [-X PATTERN] [-x PATTERN] [--no-defaults] [--] [git grep args ...]

options:
  -h, --help            show this help message and exit
  -X PATTERN, --exclude-repo PATTERN
                        glob pattern of repos to exclude
  -x PATTERN, --exclude PATTERN
                        convenience for git grep's exclude files
  --no-defaults         don't use default git args: -n
```

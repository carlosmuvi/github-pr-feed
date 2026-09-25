# GitHub PR Feed

Local GitHub PR Atom feeds for browsers with RSS Live Folders, including Zen. GitHub authentication uses existing `gh` login.

## Install

```sh
gh auth status
python3 install_launch_agent.py install
```

Installer creates local `.venv` and installs pinned dependencies.

Zen RSS URL:

```text
http://127.0.0.1:8787/feeds/my-prs.atom
```

`launchd` starts service at login and after reboot. It restarts service after an unexpected exit.

## Add feeds

`install_launch_agent.py install` creates local `feeds.yaml` from `feeds.example.yaml`. Add named GitHub search queries there:

```yaml
my-prs:
  query: is:pr is:open repo:owner/repository
```

Restart after changing configuration:

```sh
launchctl kickstart -k gui/$(id -u)/com.carlosmuvi.github-pr-feed
```

## Status and logs

```sh
launchctl print gui/$(id -u)/com.carlosmuvi.github-pr-feed
tail -f ~/Library/Logs/github-pr-feed.log
```

## Remove

```sh
python3 install_launch_agent.py uninstall
```

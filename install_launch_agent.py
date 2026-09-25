import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


LABEL = "com.carlosmuvi.github-pr-feed"


def launch_agent_plist(python_path: Path, script_path: Path, config_path: Path, log_path: Path) -> bytes:
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": [
                str(python_path),
                str(script_path),
                "--config",
                str(config_path),
            ],
            "RunAtLoad": True,
            "KeepAlive": True,
            "EnvironmentVariables": {
                "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            },
            "StandardOutPath": str(log_path),
            "StandardErrorPath": str(log_path),
        }
    )


def agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def install() -> None:
    root = Path(__file__).resolve().parent
    destination = agent_path()
    log_path = Path.home() / "Library" / "Logs" / "github-pr-feed.log"
    config_path = root / "feeds.yaml"
    if not config_path.exists():
        shutil.copyfile(root / "feeds.example.yaml", config_path)
    environment = root / ".venv"
    python = environment / "bin" / "python"
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt")], check=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], check=False)
    destination.write_bytes(launch_agent_plist(python, root / "github_pr_feed.py", config_path, log_path))
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(destination)], check=True)


def uninstall() -> None:
    destination = agent_path()
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], check=False)
    destination.unlink(missing_ok=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("install", "uninstall"))
    arguments = parser.parse_args()
    {"install": install, "uninstall": uninstall}[arguments.command]()

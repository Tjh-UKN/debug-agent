"""Manage the opt-in session reminder preference; does not run experiments."""
import argparse
import json
from pathlib import Path
import sys

from case import atomic_write, locked


def config_path(path=None):
    return Path(path).expanduser().resolve() if path else Path.home() / ".debug-agent" / "config.json"


def read_config(path=None):
    path = config_path(path)
    if not path.exists():
        return {"always_on": False}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict) or type(value.get("always_on", False)) is not bool:
        raise ValueError("invalid reminder config")
    return value


def set_mode(enabled, path=None):
    path = config_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked(path.parent):
        value = read_config(path)
        value["always_on"] = enabled
        atomic_write(path, value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("on", "off", "status"))
    parser.add_argument("--config", help="optional isolated config path")
    args = parser.parse_args()
    try:
        value = read_config(args.config) if args.mode == "status" else set_mode(args.mode == "on", args.config)
        print(json.dumps({"always_on": value.get("always_on", False), "config": str(config_path(args.config)),
                          "scope": "Claude Code SessionStart reminder when this plugin hook is installed; no scheduler"}, ensure_ascii=False))
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Install the Codex skill or an optional Claude Code /debug-agent alias."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def replace_file(path, value):
    """Prepare in the destination filesystem, then atomically replace one file."""
    fd, name = tempfile.mkstemp(prefix=".install-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def install(target, home=None, update=False):
    home = Path(home).resolve() if home else Path.home()
    if target == "codex":
        codex = Path(os.environ.get("CODEX_HOME", home / ".codex")) if home == Path.home() else home / ".codex"
        destination = codex / "skills" / "debug-agent"
        source = ROOT / "skills" / "debug-agent"
        require_safe = destination.resolve() == source.resolve()
        if require_safe:
            raise ValueError("installation destination is the source directory")
        files = {path.relative_to(source): path.read_bytes() for path in source.rglob("*")
                 if path.is_file() and "__pycache__" not in path.parts}
    else:
        destination = home / ".claude" / "commands"
        skill = (ROOT / "skills" / "debug-agent" / "SKILL.md").as_posix()
        text = ("---\ndescription: Professional precision diagnosis, status, evidence and recovery\n"
                "argument-hint: '[status|evidence|again|done-check|resume|on|off|help|问题描述]'\n---\n\n"
                f"直接读取 `{skill}`，按其中的命令路由与展示协议执行。不要递归调用同名 Skill。\n\n"
                "用户参数：$ARGUMENTS\n")
        files = {Path("debug-agent.md"): text.encode("utf-8")}
    previous = {p: (destination / p).read_bytes() if (destination / p).exists() else None for p in files}
    changed = [p for p, value in files.items() if previous[p] is not None and previous[p] != value]
    if changed and not update:
        raise ValueError("existing files differ; use --update to back up and replace managed files")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = home / ".debug-agent" / "install-backups" / stamp / target
    for relative in changed:
        saved = backup / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination / relative, saved)
    written = []
    try:
        for relative, value in files.items():
            if previous[relative] == value:
                continue
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            replace_file(path, value)
            written.append(relative)
    except OSError as exc:
        failures = []
        for relative in reversed(written):
            try:
                path = destination / relative
                if previous[relative] is None:
                    path.unlink(missing_ok=True)
                else:
                    replace_file(path, previous[relative])
            except OSError:
                failures.append(str(relative))
        if failures:
            raise OSError(f"update failed; rollback incomplete for {failures}; backup: {backup}") from exc
        raise
    return destination, backup if changed else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=("codex", "claude-alias"))
    parser.add_argument("--home", help="override home directory for isolated installation")
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    try:
        destination, backup = install(args.target, args.home, args.update)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Install failed: {exc}\n")
    print(f"Installed: {destination}")
    if backup:
        print(f"Previous managed files backed up: {backup}")
    if args.target == "claude-alias":
        print("Alias points to this checkout. Moving it requires reinstalling the alias. No hooks installed by this command.")


if __name__ == "__main__":
    main()

"""Install the Codex/Pi skill or an optional Claude Code /debug-agent alias."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import unquote, urlsplit

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


def broken_references(source):
    """Check local Markdown file routes, excluding code examples and web URLs."""
    source = Path(source).resolve()
    broken = []
    for path in sorted(source.rglob("*.md")):
        text = path.read_text(encoding="utf-8-sig")
        text = re.sub(r"(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1[^\n]*$", "", text)
        for link in re.findall(r"\[[^\]\n]*\]\(([^)\s]+)\)", text):
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            resolved = (path.parent / unquote(parsed.path)).resolve()
            if not resolved.is_relative_to(source) or not resolved.is_file():
                broken.append({"file": str(path.relative_to(source)), "target": link})
    return broken


def installation_files(target, home=None):
    if target not in {"codex", "pi", "claude-alias"}:
        raise ValueError("unknown installation target")
    home = Path(home).resolve() if home else Path.home()
    if target in {"codex", "pi"}:
        codex = Path(os.environ.get("CODEX_HOME", home / ".codex")) if home == Path.home() else home / ".codex"
        destination = codex / "skills" / "debug-agent" if target == "codex" else home / ".pi" / "agent" / "skills" / "debug-agent"
        source = ROOT / "skills" / "debug-agent"
        require_safe = destination.resolve() == source.resolve()
        if require_safe:
            raise ValueError("installation destination is the source directory")
        broken = broken_references(source)
        if broken:
            raise ValueError(f"broken Skill references: {broken}")
        files = {path.relative_to(source): path.read_bytes() for path in source.rglob("*")
                 if path.is_file() and "__pycache__" not in path.parts}
    else:
        destination = home / ".claude" / "commands"
        skill = (ROOT / "skills" / "debug-agent" / "SKILL.md").as_posix()
        text = ("---\ndescription: Diagnose AI correctness issues with evidence and optional recovery\n"
                "argument-hint: '[status|evidence|again|done-check|resume|on|off|help|问题描述]'\n---\n\n"
                f"直接读取 `{skill}` 并诊断当前问题；显式查询状态或恢复时才读取辅助路由。不要递归调用同名 Skill。\n\n"
                "用户参数：$ARGUMENTS\n")
        files = {Path("debug-agent.md"): text.encode("utf-8")}
    return home, destination, files


def check_installation(target, home=None):
    """Read-only comparison against source content, not just a version label."""
    _, destination, files = installation_files(target, home)
    missing, changed = [], []
    digest = hashlib.sha256()
    for relative, value in sorted(files.items()):
        name = relative.as_posix()
        digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256(value).digest())
        installed = destination / relative
        if not installed.is_file():
            missing.append(name)
        elif installed.read_bytes() != value:
            changed.append(name)
    return {"target": target, "destination": str(destination), "managed_files": len(files),
            "source_sha256": digest.hexdigest(), "missing": missing, "changed": changed,
            "matches": not missing and not changed,
            "scope": "Managed source files only; unrelated installed files are not removed or compared."}


def install(target, home=None, update=False):
    home, destination, files = installation_files(target, home)
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
    parser.add_argument("target", choices=("codex", "pi", "claude-alias"))
    parser.add_argument("--home", help="override home directory for isolated installation")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--update", action="store_true")
    mode.add_argument("--check", action="store_true", help="read-only source/installation and local-reference check")
    args = parser.parse_args()
    try:
        if args.check:
            result = check_installation(args.target, args.home)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            raise SystemExit(0 if result["matches"] else 1)
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

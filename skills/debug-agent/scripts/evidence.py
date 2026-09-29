"""Snapshot explicit existing artifacts and verify exact bytes; never execute commands."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import socket
import stat
import sys

DEFAULT_MAX_BYTES = 16 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
MAX_EXCERPT_BYTES = 32 * 1024


def file_bytes(path, limit):
    """Bound the read and reject sources changing while being captured."""
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError(f"regular file within remaining byte budget required: {path}")
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    after = path.stat()
    if len(value) > limit or (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino) or len(value) != before.st_size:
        raise ValueError(f"source changed during capture or exceeds byte budget: {path}")
    return value


def capture(files, out, context=None, max_bytes=DEFAULT_MAX_BYTES):
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    if not files or (context is not None and not isinstance(context, dict)):
        raise ValueError("explicit files and an optional context object are required")
    json.dumps(context or {}, allow_nan=False)
    paths = [Path(p).expanduser().resolve(strict=True) for p in files]
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate source file")
    if sum(p.stat().st_size for p in paths) > max_bytes:
        raise ValueError("sources exceed total byte budget; select smaller artifacts")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    records, used = [], 0
    for index, path in enumerate(paths):
        value = file_bytes(path, max_bytes - used)
        used += len(value)
        name = f"{index:03d}-{path.name}"
        with (out / name).open("xb") as stream:
            stream.write(value)
        records.append({"index": index, "source_path": str(path), "snapshot": name,
                        "size": len(value), "sha256": hashlib.sha256(value).hexdigest()})
    manifest = {"schema": 1, "captured_at": datetime.now(timezone.utc).isoformat(),
                "capture_host": socket.gethostname(), "capture_python": sys.executable,
                "declared_context": context or {}, "artifacts": records}
    # Only a fully captured bundle gets a manifest; partial output is never usable.
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with (out / "manifest.json").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded)
    return {"bundle": str(out), "manifest": str(out / "manifest.json"), "files": len(records), "bytes": used}


def load_bundle(bundle):
    folder = Path(bundle).resolve()
    data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("artifacts"), list):
        raise ValueError("unsupported evidence manifest")
    if not data["artifacts"]:
        raise ValueError("empty evidence manifest")
    seen = set()
    for index, record in enumerate(data["artifacts"]):
        if not isinstance(record, dict):
            raise ValueError("invalid artifact record")
        name, digest = record.get("snapshot"), record.get("sha256")
        if (not isinstance(name, str) or not name or Path(name).name != name or name in seen
                or (folder / name).resolve().parent != folder):
            raise ValueError("snapshot must be a unique file inside the evidence bundle")
        if (record.get("index") != index or type(record.get("size")) is not int or record["size"] < 0
                or not isinstance(record.get("source_path"), str)
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)):
            raise ValueError("invalid artifact identity, size or digest")
        seen.add(name)
    return folder, data


def matches(path, record):
    # Size mismatch avoids hashing a now much larger, growing source file.
    if not path.is_file() or path.stat().st_size != record["size"]:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        remaining = record["size"]
        while remaining:
            chunk = stream.read(min(CHUNK_BYTES, remaining))
            if not chunk:
                return False
            digest.update(chunk)
            remaining -= len(chunk)
        if stream.read(1):
            return False
    return digest.hexdigest() == record["sha256"]


def verify(bundle, sources=False):
    folder, data = load_bundle(bundle)
    records = []
    for record in data["artifacts"]:
        try:
            intact = matches(folder / record["snapshot"], record)
        except OSError:
            intact = False
        result = {"index": record["index"], "snapshot": record["snapshot"], "intact": intact}
        if sources:
            try:
                result["source_matches"] = matches(Path(record["source_path"]), record)
            except OSError:
                result["source_matches"] = False
        records.append(result)
    result = {"intact": all(r["intact"] for r in records), "artifacts": records,
              "meaning": "Snapshot byte integrity only; context and causal claims are not verified."}
    if sources:
        result["sources_match"] = all(r["source_matches"] for r in records)
    return result


def show(bundle, index, lines):
    folder, data = load_bundle(bundle)
    if not 0 <= index < len(data["artifacts"]):
        raise ValueError("artifact index out of range")
    record = data["artifacts"][index]
    if not matches(folder / record["snapshot"], record):
        raise ValueError("snapshot missing or changed; cannot quote it as captured evidence")
    parts = lines.split(":")
    if len(parts) != 2:
        raise ValueError("lines must be START:END (1-based, inclusive)")
    start, end = map(int, parts)
    if start < 1 or end < start or end - start >= 200:
        raise ValueError("select an ordered range of at most 200 lines")
    raw = file_bytes(folder / record["snapshot"], record["size"])
    if hashlib.sha256(raw).hexdigest() != record["sha256"]:
        raise ValueError("snapshot changed while reading")
    text = [line.rstrip("\r\n") for line in io.StringIO(raw.decode("utf-8-sig"), newline=None)]
    if end > len(text):
        raise ValueError("line range exceeds the snapshot")
    if len("\n".join(text[start - 1:end]).encode("utf-8")) > MAX_EXCERPT_BYTES:
        raise ValueError("excerpt exceeds 32 KiB; select a smaller range or use a structured query")
    return {"source": str(folder / record["snapshot"]), "original_source": record["source_path"],
            "sha256": record["sha256"], "lines": [{"line": i, "text": text[i - 1]} for i in range(start, end + 1)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    cap = commands.add_parser("capture")
    cap.add_argument("--file", action="append", required=True)
    cap.add_argument("--out", required=True)
    cap.add_argument("--context", help="JSON object of caller-declared execution context; never executed")
    cap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    check = commands.add_parser("verify")
    check.add_argument("--bundle", required=True)
    check.add_argument("--sources", action="store_true")
    quote = commands.add_parser("show")
    quote.add_argument("--bundle", required=True)
    quote.add_argument("--index", type=int, required=True)
    quote.add_argument("--lines", required=True)
    args = parser.parse_args()
    try:
        if args.command == "capture":
            context = json.loads(Path(args.context).read_text(encoding="utf-8-sig")) if args.context else None
            result = capture(args.file, args.out, context, args.max_bytes)
        elif args.command == "verify":
            result = verify(args.bundle, args.sources)
        else:
            result = show(args.bundle, args.index, args.lines)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("intact") is False or result.get("sources_match") is False else 0
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Evidence error: {exc}\n")


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())

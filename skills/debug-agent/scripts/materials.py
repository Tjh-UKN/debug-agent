"""List only supplied local materials, including archive members; never extract or run them."""
import argparse
import json
import os
from pathlib import Path
import sys
import tarfile
import zipfile


def inventory(paths):
    items, errors = {}, []

    def add_file(path):
        source = path.as_posix()
        try:
            name = path.name.lower()
            if name.endswith((".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
                with tarfile.open(path) as archive:
                    for member in archive:
                        if member.isfile():
                            key = source + "!" + member.name
                            if key in items:
                                raise ValueError("duplicate archive member: " + member.name)
                            items[key] = {"source": key, "bytes": member.size}
            elif name.endswith(".zip"):
                with zipfile.ZipFile(path) as archive:
                    for member in archive.infolist():
                        if not member.is_dir():
                            key = source + "!" + member.filename
                            if key in items:
                                raise ValueError("duplicate archive member: " + member.filename)
                            items[key] = {"source": key, "bytes": member.file_size}
            else:
                items[source] = {"source": source, "bytes": path.stat().st_size}
        except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile, EOFError) as exc:
            errors.append({"source": source, "error": str(exc)})

    roots, seen = [], set()
    for value in paths:
        path = Path(value).expanduser().absolute()
        roots.append(path.as_posix())
        if path.is_symlink():
            errors.append({"source": path.as_posix(), "error": "symlink not followed"})
        elif path.is_file():
            if path not in seen:
                seen.add(path)
                add_file(path)
        elif path.is_dir():
            def onerror(exc):
                errors.append({"source": str(exc.filename), "error": str(exc)})
            for folder, dirs, files in os.walk(path, followlinks=False, onerror=onerror):
                for name in list(dirs):
                    child = Path(folder) / name
                    if child.is_symlink():
                        dirs.remove(name)
                        errors.append({"source": child.as_posix(), "error": "symlink not followed"})
                for name in files:
                    child = Path(folder) / name
                    if child.is_symlink():
                        errors.append({"source": child.as_posix(), "error": "symlink not followed"})
                    elif child not in seen:
                        seen.add(child)
                        add_file(child)
        else:
            errors.append({"source": path.as_posix(), "error": "not an available local file or directory"})
    return {"roots": roots, "items": sorted(items.values(), key=lambda item: item["source"]),
            "complete": not errors, "errors": errors,
            "meaning": "File/member inventory only. Listed does not mean inspected; content and tensor coverage are not verified."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    result = inventory(args.paths)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["complete"] else 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

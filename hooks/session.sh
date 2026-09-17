#!/usr/bin/env bash
# Prefer Python 3 on Linux/WSL, where the unversioned python often does not exist.
script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 0
for executable in python3 python; do
  if command -v "$executable" >/dev/null 2>&1; then
    exec "$executable" "$script_dir/session.py"
  fi
done
printf '%s\n' 'Debug Agent: Python 3 is unavailable; session reminder skipped.' >&2
exit 0

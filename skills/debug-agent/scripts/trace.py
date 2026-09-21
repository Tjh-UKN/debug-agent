"""Read-only investigation trace CLI. JSON output for stable agent consumption.

Commands and the single relation each one is allowed to use:

- tree      current investigation space with derived branch health (investigates)
- path      why was this node investigated at all (investigates only, no parents)
- why       what makes this conclusion believable (parents + evidence only)
- impact    who would lose support if this evidence/hypothesis failed (registered refs)
- frontier  active candidates with no deeper active child (derived, never persisted)

All commands only read the case; none of them creates tasks, writes state or
starts experiments. Missing relations are reported as missing, never guessed.
"""
import argparse
import json
import sys

import investigation
from case import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, help="case directory, e.g. .debug-agent/nan-001")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("tree")
    for name in ("path", "why"):
        child = commands.add_parser(name)
        child.add_argument("--hypothesis", required=True)
    child = commands.add_parser("impact")
    child.add_argument("--kind", choices=("hypothesis", "evidence"), required=True)
    child.add_argument("--id", required=True)
    commands.add_parser("frontier")
    args = parser.parse_args()
    try:
        state = execute(args.case, "show")
        if args.command == "tree":
            result = investigation.investigation_tree(state)
        elif args.command == "path":
            result = {"hypothesis": args.hypothesis, "path": investigation.investigation_path(state, args.hypothesis)}
        elif args.command == "why":
            result = investigation.why_trace(state, args.hypothesis)
        elif args.command == "impact":
            result = investigation.impact_trace(state, args.kind, args.id)
        else:
            result = {"frontier": investigation.active_frontier(state)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    for output in (sys.stdout, sys.stderr):
        if hasattr(output, "reconfigure"):
            output.reconfigure(encoding="utf-8")
    sys.exit(main())

"""Read and align msprobe JSON statistics by execution order, call stack and shape.

Standard library only. Archives are read in place; inputs are never extracted or edited.
"""
import argparse
from collections import defaultdict
from fnmatch import fnmatchcase
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import zipfile

STATS = ("Norm", "Max", "Min", "Mean")
FIELDS = ("input_args", "input_kwargs", "input", "output")
FRAME = re.compile(r"^File (.*?), line (\d+), in ([^,\n]+),?\s*(.*)$", re.S)


def clean_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {k: clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    return value


def encode(value, *, sort_keys=False):
    return json.dumps(clean_json(value), ensure_ascii=False, allow_nan=False, sort_keys=sort_keys)


def pointer(path, key):
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


def read_object(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def scope_from_path(name):
    parts = PurePosixPath(name.replace("\\", "/")).parts
    def last(pattern):
        hits = [m.group(1) for part in parts if (m := re.fullmatch(pattern, part))]
        return hits[-1] if hits else "unknown"
    return last(r"step_?(\d+)"), last(r"rank_?(\d+)")


class Source:
    """One explicit directory, dump.json, tar or zip; one dump per (step, rank)."""
    def __init__(self, value):
        self.path = Path(value).expanduser().resolve()
        self.archive = None
        self.entries = {}
        self.files = {}
        try:
            if self.path.is_dir():
                self.files = {p.as_posix(): p for p in sorted(self.path.rglob("dump.json")) if p.is_file()}
                for name in list(self.files):
                    stack = Path(name).with_name("stack.json")
                    if stack.is_file():
                        self.files[stack.as_posix()] = stack
            elif self.path.name == "dump.json":
                self.files = {self.path.as_posix(): self.path}
                stack = self.path.with_name("stack.json")
                if stack.is_file():
                    self.files[stack.as_posix()] = stack
            elif self.path.suffix.lower() == ".zip":
                self.archive = zipfile.ZipFile(self.path)
                for member in self.archive.infolist():
                    if not member.is_dir() and PurePosixPath(member.filename).name in {"dump.json", "stack.json"}:
                        self.add_member(member.filename, member)
            else:
                self.archive = tarfile.open(self.path)
                for member in self.archive.getmembers():
                    if member.isfile() and PurePosixPath(member.name).name in {"dump.json", "stack.json"}:
                        self.add_member(member.name, member)
            for name in self.files:
                if PurePosixPath(name).name != "dump.json":
                    continue
                scope = scope_from_path(name)
                if scope in self.entries:
                    raise ValueError(f"multiple dumps for step/rank {scope}; select a narrower source directory")
                self.entries[scope] = name
            if not self.entries:
                raise ValueError("no dump.json found in supplied source")
        except Exception:
            self.close()
            raise

    def add_member(self, name, member):
        name = PurePosixPath(name).as_posix()
        if name in self.files:
            raise ValueError("duplicate archive member: " + name)
        self.files[name] = member

    def close(self):
        if self.archive:
            self.archive.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def source_id(self, name):
        if self.archive:
            member = self.files[name]
            return self.path.as_posix() + "!" + (member.filename if isinstance(member, zipfile.ZipInfo) else member.name)
        return name

    def read(self, name):
        item = self.files[name]
        if isinstance(self.archive, tarfile.TarFile):
            with self.archive.extractfile(item) as stream:
                return stream.read()
        if isinstance(self.archive, zipfile.ZipFile):
            return self.archive.read(item)
        return item.read_bytes()

    def load(self, scope, code_root=None):
        name = self.entries[scope]
        stack_name = str(PurePosixPath(name).with_name("stack.json"))
        raw = self.read(name)
        stack_raw = self.read(stack_name) if stack_name in self.files else None
        return Dump(read_object(raw), read_object(stack_raw) if stack_raw is not None else {},
                    {"dump": self.source_id(name), "dump_sha256": hashlib.sha256(raw).hexdigest(),
                     "stack": self.source_id(stack_name) if stack_raw is not None else None,
                     "stack_sha256": hashlib.sha256(stack_raw).hexdigest() if stack_raw is not None else None,
                     "step": scope[0], "rank": scope[1]}, code_root)


def stack_index(stack):
    """Group IDs are opaque. Only the explicit API name list defines membership."""
    index = {}
    for group, entry in stack.items():
        if not isinstance(entry, list) or len(entry) != 2:
            raise ValueError(f"stack group {group}: expected [api_names, frames]")
        names, frames = entry
        if not isinstance(names, list) or not isinstance(frames, list) or not all(isinstance(v, str) for v in names + frames):
            raise ValueError(f"stack group {group}: invalid names/frames")
        for name in names:
            if name in index and index[name]["frames"] != frames:
                raise ValueError("conflicting stack memberships for " + name)
            index[name] = {"group": group, "frames": frames}
    return index


def normalize_frame(frame, code_root=None):
    match = FRAME.match(frame.strip())
    if not match:
        return ("raw", frame.strip())
    filename, line, function, code = match.groups()
    filename = filename.replace("\\", "/")
    if code_root:
        root = code_root.replace("\\", "/").rstrip("/") + "/"
        if filename.startswith(root):
            filename = "project/" + filename[len(root):]
    for marker in ("/site-packages/", "/dist-packages/"):
        if marker in filename:
            filename = "python-packages/" + filename.split(marker, 1)[1]
            break
    # Keep the full relative module path, function and source text. Source line
    # offsets may change between checkouts; raw frames/line numbers remain available.
    return filename, function.strip(), code.strip()


def tensor_fields(value, path="", inherited=None):
    if isinstance(value, dict):
        context = dict(inherited or {})
        for key in ("device_mesh", "placements"):
            if key in value:
                context[key] = value[key]
        if "DTensor" in str(value.get("type", "")):
            context["view"] = "DTensor_local_record"
        if isinstance(value.get("shape"), list) and "dtype" in value:
            yield {"path": path, "shape": value["shape"], "dtype": value["dtype"],
                   "type": value.get("type"), "distribution": context,
                   "statistics": {k: value[k] for k in STATS if k in value}}
        for key, child in value.items():
            if isinstance(child, (list, dict)) and key not in {"shape", "device_mesh", "placements"}:
                yield from tensor_fields(child, pointer(path, key), context)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from tensor_fields(child, pointer(path, i), inherited)


def scalar_fields(value, path=""):
    if isinstance(value, dict):
        if "value" in value and not isinstance(value["value"], (dict, list)):
            yield pointer(path, "value"), value["value"]
        elif "group_ranks" in value:
            yield pointer(path, "group_ranks"), value["group_ranks"]
        elif "shape" not in value:
            for key, child in value.items():
                yield from scalar_fields(child, pointer(path, key))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from scalar_fields(child, pointer(path, i))


def port_layout(value):
    if isinstance(value, dict):
        if "shape" in value:
            return {"tensor_shape": value["shape"]}
        return {k: port_layout(v) for k, v in sorted(value.items()) if k != "value"}
    if isinstance(value, list):
        return [port_layout(v) for v in value]
    return None if value is None else type(value).__name__


class Dump:
    def __init__(self, payload, stacks, source, code_root=None):
        self.data = payload.get("data")
        if not isinstance(self.data, dict) or not all(isinstance(v, dict) for v in self.data.values()):
            raise ValueError("dump.data must map API names to records")
        self.source, self.code_root = source, code_root
        self.stack = stack_index(stacks)
        self.keys = list(self.data)  # Guaranteed execution order; never sort API IDs.
        self.records = []
        self.by_name = {}
        self.mesh_ranks = set()
        for position, (api, raw) in enumerate(self.data.items()):
            direction = api.rsplit(".", 1)[-1]
            family = re.sub(r"\.\d+\.(forward|backward)$", "", api)
            forward = api[:-len("backward")] + "forward" if direction == "backward" else api
            call = self.data.get(forward, raw)
            stack_api = api if api in self.stack else forward if forward in self.stack else None
            entry = self.stack.get(stack_api, {})
            tensors = [t for field in FIELDS if field in raw for t in tensor_fields(raw[field], "/" + field)]
            for tensor in tensors:
                def ranks(mesh):
                    if type(mesh) is int:
                        self.mesh_ranks.add(str(mesh))
                    elif isinstance(mesh, list):
                        for item in mesh:
                            ranks(item)
                ranks(tensor["distribution"].get("device_mesh"))
            call_shapes = [(t["path"], t["shape"], t["distribution"])
                           for field in FIELDS if field in call for t in tensor_fields(call[field], "/" + field)]
            call_shapes.sort(key=lambda t: t[0])
            gradient = next((t for t in tensors if t["path"].startswith("/input/")), None)
            reason = None
            if direction not in {"forward", "backward"}:
                reason = "unknown_direction"
            elif not entry.get("frames"):
                reason = "missing_stack"
            elif not call_shapes or (direction == "backward" and gradient is None):
                reason = "missing_shape"
            recompute = bool(call.get("is_recompute", False))
            signature = None if reason else encode([family, direction, recompute,
                [normalize_frame(f, code_root) for f in entry["frames"]], call_shapes,
                [gradient["path"], gradient["shape"], gradient["distribution"]] if direction == "backward" else None], sort_keys=True)
            record = {"api": api, "position": position, "direction": direction, "is_recompute": recompute,
                      "stack_api": stack_api, "stack_group": entry.get("group"), "frames": entry.get("frames", []),
                      "tensors": tensors, "signature": signature, "unmatched_reason": reason,
                      "port_layout": {k: port_layout(raw[k]) for k in FIELDS if k in raw},
                      "scalars": dict(scalar_fields({k: raw[k] for k in FIELDS if k in raw}))}
            self.records.append(record)
            self.by_name[api] = record

    def inspect(self, api, around=2):
        record = self.by_name[api]
        position = record["position"]
        return {"source": self.source, "json_pointer": pointer("/data", api),
                **{k: v for k, v in record.items() if k != "signature"},
                "execution_neighbours": [{"position": i, "api": self.keys[i]} for i in
                     range(max(0, position-around), min(len(self.keys), position+around+1))],
                "raw_record": self.data[api]}


def align(left, right):
    groups = []
    for dump in (left, right):
        group = defaultdict(list)
        for record in dump.records:
            if record["signature"] is not None:
                group[record["signature"]].append(record)
        groups.append(group)
    mapping = {}
    for signature, records in groups[0].items():
        other = groups[1].get(signature, [])
        if len(records) == len(other):
            for occurrence, (a, b) in enumerate(zip(records, other)):
                mapping[a["api"]] = (b, occurrence, len(records))
    used = set()
    for a in left.records:
        if a["api"] in mapping:
            b, occurrence, count = mapping[a["api"]]
            used.add(b["api"])
            yield {"status": "matched", "left": a, "right": b, "occurrence": occurrence,
                   "repeat_count": count, "basis": "call_stack+call_shapes+direction+recompute+execution_occurrence"}
        else:
            candidates = groups[1].get(a["signature"], []) if a["signature"] else []
            yield {"status": "ambiguous" if candidates else "left_only", "left": a, "right": None,
                   "reason": a["unmatched_reason"] or ("unequal_repeat_counts" if candidates else "no_stack_shape_match"),
                   "candidate_apis": [r["api"] for r in candidates]}
    for b in right.records:
        if b["api"] not in used:
            yield {"status": "right_only", "left": None, "right": b,
                   "reason": b["unmatched_reason"] or "not_uniquely_aligned"}


def difference(a, b):
    if a is None or b is None:
        return {"status": "unavailable", "left": a, "right": b}
    if any(isinstance(v, str) and v.lower() in {"nan", "inf", "+inf", "-inf", "infinity", "-infinity"} for v in (a, b)):
        return {"status": "nonfinite", "left": a, "right": b}
    if type(a) in (int, float) and type(b) in (int, float):
        if not math.isfinite(a) or not math.isfinite(b):
            return {"status": "nonfinite", "left": a, "right": b}
        if a == b:
            return None
        return {"status": "different", "left": a, "right": b, "absolute_difference": abs(a-b),
                "relative_to_right": abs(a-b)/abs(b) if b != 0 else None,
                "ratio_to_right": a/b if b != 0 else None}
    return None if type(a) is type(b) and a == b else {"status": "different", "left": a, "right": b}


def compare_records(a, b):
    tensors = [{t["path"]: t for t in record["tensors"]} for record in (a, b)]
    changes = []
    compared = 0
    for path in sorted(tensors[0].keys() | tensors[1].keys()):
        x, y = tensors[0].get(path), tensors[1].get(path)
        if x is None or y is None:
            changes.append({"path": path, "status": "unpaired_tensor_port", "left": x, "right": y})
            continue
        if x["shape"] != y["shape"] or x["distribution"] != y["distribution"]:
            changes.append({"path": path, "status": "incomparable_tensor_view", "left": x, "right": y})
            continue
        if x["dtype"] != y["dtype"]:
            changes.append({"path": path + "/dtype", "status": "different", "left": x["dtype"], "right": y["dtype"]})
        for metric in STATS:
            xv, yv = x["statistics"].get(metric), y["statistics"].get(metric)
            compared += int(xv is not None and yv is not None)
            delta = difference(xv, yv)
            if delta is not None:
                changes.append({"path": path + "/" + metric, **delta})
    for path in sorted(a["scalars"].keys() | b["scalars"].keys()):
        delta = difference(a["scalars"].get(path), b["scalars"].get(path))
        if delta:
            changes.append({"path": path, **delta})
    return {"compared_statistic_fields": compared, "changes": changes,
            "role_check_required": a["direction"] == "backward" and a["port_layout"] != b["port_layout"],
            "meaning": "Statistics/metadata comparison only; matching summaries do not establish tensor equality or causality."}


def reference(dump, record):
    return None if record is None else {"source": dump.source["dump"], "api": record["api"],
                                       "position": record["position"], "direction": record["direction"],
                                       "is_recompute": record["is_recompute"], "stack_api": record["stack_api"]}


def boundary_evidence(a, b, comparison):
    """Compact recorded input/output evidence, with no accuracy verdict."""
    groups = {name: {"paired_ports": 0, "incomparable_ports": 0, "unpaired_ports": 0,
                     "statistics": {k: 0 for k in ("equal", "different", "unavailable", "nonfinite")},
                     "largest_norm_absolute": None, "largest_norm_relative": None}
              for name in ("input", "output")}
    ports = [{t["path"]: t for t in r["tensors"]} for r in (a, b)]
    for path in ports[0].keys() | ports[1].keys():
        group = groups["output" if path == "/output" or path.startswith("/output/") else "input"]
        x, y = ports[0].get(path), ports[1].get(path)
        if x is None or y is None:
            group["unpaired_ports"] += 1
            continue
        if x["shape"] != y["shape"] or x["distribution"] != y["distribution"]:
            group["incomparable_ports"] += 1
            continue
        group["paired_ports"] += 1
        for metric in STATS:
            delta = difference(x["statistics"].get(metric), y["statistics"].get(metric))
            group["statistics"][delta["status"] if delta else "equal"] += 1
    metadata = []
    for delta in comparison["changes"]:
        path = delta["path"]
        if path.endswith("/Norm") and "absolute_difference" in delta:
            group = groups["output" if path.startswith("/output/") else "input"]
            for name, score in (("largest_norm_absolute", "absolute_difference"),
                                ("largest_norm_relative", "relative_to_right")):
                if delta.get(score) is not None and (group[name] is None or delta[score] > group[name][score]):
                    group[name] = delta
        elif path.rsplit("/", 1)[-1] not in STATS and delta["status"] in {"different", "nonfinite"}:
            metadata.append(delta)
    return {**groups, "metadata_change_count": len(metadata), "metadata_changes": metadata[:8],
            "metadata_changes_truncated": len(metadata) > 8}


def query_scan(folder, api="*", rank=None, step=None, phase=None, limit=3, offset=0):
    """Page cached evidence per rank without reopening original archives."""
    if limit < 1 or offset < 0:
        raise ValueError("limit must be positive and offset nonnegative")
    folder = Path(folder).expanduser().resolve()
    summary = read_object((folder / "summary.json").read_bytes())
    expected_counts = {(r["step"], r["rank"]): sum(r["counts"].values()) for r in summary["ranks"]}
    seen_counts = defaultdict(int)
    groups = {}
    for item in summary["ranks"]:
        if rank is not None and item["rank"] != rank or step is not None and item["step"] != step:
            continue
        groups[(item["step"], item["rank"])] = {
            "step": item["step"], "rank": item["rank"], "match_count": 0, "status_counts": {},
            "rows": [], "matched_rows_without_boundary_evidence": 0,
            "sources": {side: item.get(side) for side in ("left", "right")}}
    if not groups:
        raise ValueError("requested step/rank is not present in the scan summary")
    total_rows = 0
    with (folder / "alignment.jsonl").open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            row = json.loads(line)
            total_rows += 1
            seen_counts[(row["step"], row["rank"])] += 1
            group = groups.get((row["step"], row["rank"]))
            if group is None:
                continue
            refs = [row[side] for side in ("left", "right") if row.get(side)]
            def selected(ref):
                observed_phase = "recompute" if ref["direction"] == "forward" and ref.get("is_recompute") else ref["direction"]
                return fnmatchcase(ref["api"], api) and (phase is None or observed_phase == phase)
            if not any(selected(ref) for ref in refs):
                continue
            index = group["match_count"]
            group["match_count"] += 1
            state = row["status"]
            group["status_counts"][state] = group["status_counts"].get(state, 0) + 1
            group["matched_rows_without_boundary_evidence"] += int(state == "matched" and "boundary_evidence" not in row)
            if offset <= index < offset + limit:
                group["rows"].append({**row, "alignment_line": line_number})
    if any(seen_counts.get(key, 0) != expected_counts.get(key, 0) for key in seen_counts.keys() | expected_counts.keys()):
        raise ValueError("alignment row counts disagree with summary; incomplete or inconsistent scan snapshot")
    for group in groups.values():
        group["next_offset"] = offset + len(group["rows"]) if offset + len(group["rows"]) < group["match_count"] else None
    return {"scan": str(folder), "filters": {"api": api, "rank": rank, "step": step, "phase": phase},
            "pagination": {"limit_per_rank": limit, "offset_per_rank": offset},
            "alignment_rows_read": total_rows, "ranks": list(groups.values()),
            "scan_coverage": {k: summary.get(k) for k in
                ("coverage_complete", "errors", "missing_rank_pairs", "missing_mesh_ranks", "unscoped_sources")},
            "meaning": "Cached statistics, not tensor equality or causality. Input slots may include weights or pre-write buffers. "
                       "Rows follow the scan's left order, with unmatched right rows appended; not data-flow edges. "
                       "Zero matches does not prove non-execution. Older scans lack boundary_evidence: use compare/inspect. "
                       "Original source freshness is not checked; retain the scan's source hashes as the checkpoint."}


def scan(left, right, output, left_root=None, right_root=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    summary = {"scope": "all supplied steps/ranks; expected participants additionally checked against DTensor mesh metadata",
               "left": str(left.path), "right": str(right.path), "ranks": [], "errors": [],
               "thresholds": "none; small differences are not discarded as noise",
               "meaning": "Earliest differences are in recorded execution order, not proven causal origins. Unmatched records require investigation."}
    discovered = [set(left.entries), set(right.entries)]
    mesh = [defaultdict(set), defaultdict(set)]
    with (output / "alignment.jsonl").open("w", encoding="utf-8") as stream:
        line = 0
        for scope in sorted(discovered[0] | discovered[1]):
            item = {"step": scope[0], "rank": scope[1], "counts": {}, "first_differences": {},
                    "largest_norm_differences": {}, "largest_relative_norm_differences": {},
                    "comparison": {"statistic_fields_compared": 0, "unavailable_fields": 0,
                        "records_without_statistic_comparison": 0, "role_check_required_records": 0,
                        "order_changed_records": 0}}
            summary["ranks"].append(item)
            dumps = [None, None]
            for side, source, code_root in ((0, left, left_root), (1, right, right_root)):
                label = ("left", "right")[side]
                if scope not in source.entries:
                    item[label] = "missing_rank"
                    continue
                try:
                    dumps[side] = source.load(scope, code_root)
                    mesh[side][scope[0]].update(dumps[side].mesh_ranks)
                    item[label] = {**dumps[side].source, "records": len(dumps[side].records)}
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    item[label] = "read_error"
                    summary["errors"].append({"step": scope[0], "rank": scope[1], "side": label, "error": str(exc)})
            if any(dump is None for dump in dumps):
                for side, available in enumerate(dumps):
                    if available is None:
                        continue
                    state = ("left_only", "right_only")[side]
                    other_label = ("right", "left")[side]
                    reason = "peer_rank_missing" if item[other_label] == "missing_rank" else "peer_rank_unreadable"
                    for record in available.records:
                        line += 1
                        item["counts"][state] = item["counts"].get(state, 0) + 1
                        row = {"step": scope[0], "rank": scope[1], "status": state, "reason": reason,
                               "left": reference(available, record) if side == 0 else None,
                               "right": reference(available, record) if side == 1 else None}
                        stream.write(encode(row) + "\n")
                continue
            a, b = dumps
            prior_right = -1
            for pair in align(a, b):
                line += 1
                state = pair["status"]
                item["counts"][state] = item["counts"].get(state, 0) + 1
                row = {"step": scope[0], "rank": scope[1], "status": state,
                       "left": reference(a, pair["left"]), "right": reference(b, pair["right"])}
                if state == "matched":
                    result = compare_records(pair["left"], pair["right"])
                    row.update(basis=pair["basis"], occurrence=pair["occurrence"], repeat_count=pair["repeat_count"],
                               boundary_evidence=boundary_evidence(pair["left"], pair["right"], result),
                               compared_statistic_fields=result["compared_statistic_fields"],
                               changed_fields=sum(c["status"] != "unavailable" for c in result["changes"]),
                               unavailable_fields=sum(c["status"] == "unavailable" for c in result["changes"]),
                               role_check_required=result["role_check_required"],
                               order_changed=pair["right"]["position"] < prior_right)
                    prior_right = max(prior_right, pair["right"]["position"])
                    item["comparison"]["statistic_fields_compared"] += row["compared_statistic_fields"]
                    item["comparison"]["unavailable_fields"] += row["unavailable_fields"]
                    item["comparison"]["records_without_statistic_comparison"] += int(not row["compared_statistic_fields"])
                    item["comparison"]["role_check_required_records"] += int(row["role_check_required"])
                    item["comparison"]["order_changed_records"] += int(row["order_changed"])
                    stage = pair["left"]["direction"] + ("_recompute" if pair["left"]["is_recompute"] else "")
                    numeric = [c for c in result["changes"] if c.get("status") != "unavailable"]
                    if numeric and stage not in item["first_differences"]:
                        item["first_differences"][stage] = {**row, "alignment_line": line, "examples": numeric[:3]}
                    norms = [{"left_api": pair["left"]["api"], "right_api": pair["right"]["api"],
                              "direction": stage, "alignment_line": line, **delta}
                             for delta in result["changes"] if delta["path"].endswith("/Norm") and "absolute_difference" in delta]
                    # One representative per invocation; forward magnitudes must
                    # not hide a different backward scale in an overall top list.
                    for field, score in (("largest_norm_differences", "absolute_difference"),
                                         ("largest_relative_norm_differences", "relative_to_right")):
                        candidates = [n for n in norms if n.get(score) is not None]
                        if candidates:
                            top = item[field].setdefault(stage, [])
                            top.append(max(candidates, key=lambda n: n[score]))
                            top.sort(key=lambda n: n[score], reverse=True)
                            del top[10:]
                else:
                    row.update(reason=pair["reason"], candidate_apis=pair.get("candidate_apis", []))
                stream.write(encode(row) + "\n")
    summary["missing_rank_pairs"] = [list(v) for v in sorted(discovered[0] ^ discovered[1])]
    summary["missing_mesh_ranks"] = {label: {step: sorted(ranks - {rank for st, rank in discovered[i] if st == step})
        for step, ranks in mesh[i].items() if ranks - {rank for st, rank in discovered[i] if st == step}}
        for i, label in enumerate(("left", "right"))}
    summary["unscoped_sources"] = [list(v) for v in sorted(discovered[0] | discovered[1]) if "unknown" in v]
    summary["all_available_shards_read"] = not summary["errors"]
    summary["coverage_complete"] = (not summary["errors"] and not summary["missing_rank_pairs"] and
                                    not any(summary["missing_mesh_ranks"].values()) and not summary["unscoped_sources"])
    (output / "summary.json").write_text(encode(summary) + "\n", encoding="utf-8")
    return summary


def select_scope(source, rank, step=None):
    matches = [scope for scope in source.entries if scope[1] == rank and (step is None or scope[0] == step)]
    if len(matches) != 1:
        raise ValueError(f"rank/step selection must identify one dump; candidates: {matches}")
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("inspect")
    show.add_argument("--data", required=True)
    show.add_argument("--rank", required=True)
    show.add_argument("--step")
    show.add_argument("--api", required=True)
    query = commands.add_parser("query", help="query an existing scan; no source archive access")
    query.add_argument("--scan", required=True)
    query.add_argument("--api", default="*", help="glob against either side's API name; quote wildcards")
    query.add_argument("--rank", help="all scanned ranks by default")
    query.add_argument("--step", help="all scanned steps by default")
    query.add_argument("--phase", choices=("forward", "backward", "recompute"))
    query.add_argument("--limit", type=int, default=3, help="records per rank per page")
    query.add_argument("--offset", type=int, default=0, help="matching records to skip per rank")
    for command in ("scan", "compare"):
        child = commands.add_parser(command)
        child.add_argument("--left", required=True)
        child.add_argument("--right", required=True)
        child.add_argument("--left-code-root")
        child.add_argument("--right-code-root")
        if command == "scan":
            child.add_argument("--out", required=True, help="new output directory")
        else:
            child.add_argument("--rank", required=True)
            child.add_argument("--step")
            child.add_argument("--api", required=True, help="API name on the left; counterpart resolved by stack+shape+order")
    args = parser.parse_args()
    try:
        if args.command == "query":
            result = query_scan(args.scan, args.api, args.rank, args.step, args.phase, args.limit, args.offset)
        elif args.command == "inspect":
            with Source(args.data) as source:
                result = source.load(select_scope(source, args.rank, args.step)).inspect(args.api)
        else:
            with Source(args.left) as left, Source(args.right) as right:
                if args.command == "scan":
                    summary = scan(left, right, args.out, args.left_code_root, args.right_code_root)
                    result = {"output": str(Path(args.out).resolve()), "rank_pairs": len(summary["ranks"]),
                              "coverage_complete": summary["coverage_complete"], "errors": summary["errors"],
                              "rank_overview": [{"step": r["step"], "rank": r["rank"], "counts": r["counts"],
                                  "comparison": r["comparison"],
                                  "norm_peaks_by_stage": {stage: top[0] for stage, top in r["largest_norm_differences"].items()}}
                                  for r in summary["ranks"][:64]],
                              "additional_rank_rows_in_summary": max(0, len(summary["ranks"]) - 64),
                              "missing_rank_pairs": summary["missing_rank_pairs"], "missing_mesh_ranks": summary["missing_mesh_ranks"],
                              "unscoped_sources": summary["unscoped_sources"],
                              "next": "Read summary.json for every rank, then compare/inspect relevant APIs. Coverage is not alignment; unmatched records remain in alignment.jsonl."}
                else:
                    scope = select_scope(left, args.rank, args.step)
                    a, b = left.load(scope, args.left_code_root), right.load(scope, args.right_code_root)
                    pair = next(p for p in align(a, b) if p["left"] and p["left"]["api"] == args.api)
                    result = {k: v for k, v in pair.items() if k not in {"left", "right"}}
                    result["left"] = a.inspect(args.api)
                    if pair["right"]:
                        result["right"] = b.inspect(pair["right"]["api"])
                        result["comparison"] = compare_records(pair["left"], pair["right"])
        print(encode(result))
        return 0
    except (ValueError, OSError, KeyError, TypeError, StopIteration, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(encode({"error": str(exc) or "API not found"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())

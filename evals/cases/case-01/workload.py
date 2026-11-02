"""Standard-library execution/collective model; emits records, never communicates."""
import json


def workload():
    batches = {0: [(41, 2.0), (42, 2.0)], 1: [(41, 2.0), (42, float("nan"))]}
    records = []
    for rank, steps in batches.items():
        sequence = 0
        for step, loss in steps:
            records.append({"job": "fixture", "rank": rank, "step": step,
                            "event": "forward", "loss": "NaN" if loss != loss else loss})
            if loss != loss:
                records.append({"job": "fixture", "rank": rank, "step": step, "event": "continue"})
                continue
            records.append({"job": "fixture", "rank": rank, "step": step,
                            "event": "submitted", "group": "dp", "seq": sequence, "op": "all_reduce"})
            sequence += 1
    participants = {0, 1}
    submitted = [r for r in records if r["event"] == "submitted"]
    for event in submitted:
        joined = {r["rank"] for r in submitted if (r["group"], r["seq"]) == (event["group"], event["seq"])}
        records.append({**event, "event": "completed" if joined == participants else "timeout"})
    return records


if __name__ == "__main__":
    for record in workload():
        print(json.dumps(record, sort_keys=True, allow_nan=False))

"""Small deterministic civil application-message fixtures, never network routes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCENARIOS = ("stable", "burst", "slow_service")
MIN_MESSAGES, MAX_MESSAGES = 16, 64


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def make_workload(scenario: str, count: int = 24) -> dict:
    if scenario not in SCENARIOS or type(count) is not int or not MIN_MESSAGES <= count <= MAX_MESSAGES:
        raise ValueError("invalid_scenario_or_message_count")
    tasks = []
    for i in range(count):
        if scenario == "stable":
            arrival, kind, service, budget = i * 8, "standard", 18 + i % 3 * 2, 100
        elif scenario == "burst":
            arrival = (i // 8) * 70
            kind = ("slow", "standard", "fast", "fast")[i % 4]
            service = {"slow": 55, "standard": 27, "fast": 12}[kind] + i % 3
            budget = {"slow": 180, "standard": 90, "fast": 65}[kind]
        else:
            arrival = (i // 8) * 45
            kind = ("slow", "slow", "standard", "fast")[i % 4]
            service = {"slow": 90, "standard": 45, "fast": 12}[kind] + i % 3 * 5
            budget = {"slow": 220, "standard": 140, "fast": 100}[kind]
        tasks.append({"task_id": f"msg-{i:04d}", "arrival_ms": arrival,
                      "deadline_ms": arrival + budget, "service_class": kind,
                      "service_ms": service, "payload_bytes": 64})
    return {"schema": "civil-message-workload/v1", "scenario": scenario, "tasks": tasks}


def public_workload(workload: dict) -> dict:
    """The fixture's actual future service duration is never sent to ODVL."""
    return {"schema": workload["schema"], "scenario": workload["scenario"],
            "tasks": [{key: value for key, value in row.items() if key != "service_ms"}
                      for row in workload["tasks"]]}


def export_workloads(count: int = 24) -> dict:
    workloads = {name: public_workload(make_workload(name, count)) for name in SCENARIOS}
    return {"schema": "civil-message-workloads/v1", "message_count": count,
            "purpose": "civil application queue only", "future_service_durations_included": False,
            "scenarios": workloads}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = export_workloads(args.count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=True, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"output_sha256": digest(result), "scenarios": len(SCENARIOS), "messages_each": args.count}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

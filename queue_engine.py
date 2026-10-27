"""Civil application queue: bounded local HTTP benchmark, no IP routing or RF.

All policies share arrivals, payloads, fixture service times and concurrency 4.
ODVL orders are loaded before the message loop; this program has no Cloud client.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
import hashlib
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import statistics
import threading
import time
import uuid

from workloads import SCENARIOS, canonical, digest, export_workloads, make_workload, public_workload

POLICIES = ("fifo", "deadline_first", "ewma", "odvl", "ewma_odvl")
CONCURRENCY = 4
EWMA_ALPHA, EWMA_PRIOR_MS, ODVL_WEIGHT_MS = 0.35, 40.0, 25.0
HOST, ENDPOINT = "127.0.0.1", "/messages"
MAX_TRIAL_SECONDS = 5.0


class QueueError(Exception):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise QueueError("duplicate_json_key")
        result[key] = value
    return result


def _json(raw):
    def invalid(_):
        raise QueueError("invalid_json_number")
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=invalid)


def identity_orders(workloads: dict) -> dict:
    return {"schema": "civil-odvl-orders/v1", "source": "offline_identity", "scenarios": {
        name: {"task_ids": [x["task_id"] for x in workload["tasks"]], "proof": None, "response": None}
        for name, workload in workloads.items()}}


def validate_orders(document: dict, workloads: dict) -> dict:
    if (not isinstance(document, dict) or set(document) != {"schema", "source", "scenarios"}
            or document["schema"] != "civil-odvl-orders/v1"
            or document["source"] not in {"offline_identity", "basira_cloud"}
            or not isinstance(document["scenarios"], dict) or set(document["scenarios"]) != set(SCENARIOS)):
        raise QueueError("invalid_order_envelope")
    for name in SCENARIOS:
        row = document["scenarios"][name]
        expected = [task["task_id"] for task in workloads[name]["tasks"]]
        if (not isinstance(row, dict) or set(row) != {"task_ids", "proof", "response"}
                or not isinstance(row["task_ids"], list)
                or not all(isinstance(x, str) for x in row["task_ids"])
                or len(row["task_ids"]) != len(expected) or len(set(row["task_ids"])) != len(expected)
                or set(row["task_ids"]) != set(expected)):
            raise QueueError("order_not_exact_task_permutation")
        if document["source"] == "offline_identity":
            if row["task_ids"] != expected or row["proof"] is not None or row["response"] is not None:
                raise QueueError("offline_order_must_be_identity")
            continue
        response, proof = row["response"], row["proof"]
        if (not isinstance(proof, dict) or not isinstance(response, dict)
                or proof.get("response_sha256") != digest(response)
                or proof.get("workload_sha256") != digest(public_workload(workloads[name]))
                or not isinstance(proof.get("analysis_id"), str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", proof["analysis_id"])
                or not isinstance(proof.get("entity_id"), str) or not re.fullmatch(r"ent_[0-9a-f]{32}", proof["entity_id"])
                or not isinstance(proof.get("memory_space_id"), str)
                or not re.fullmatch(r"mem_[A-Za-z0-9_-]{1,156}", proof["memory_space_id"])):
            raise QueueError("invalid_order_source_proof")
        if (set(response) != {"schema", "memory_space_id", "entity_id", "ranking", "count", "reordered", "ranking_applied"}
                or response["schema"] != "basira-odvl-ranking/v1"
                or response["memory_space_id"] != proof["memory_space_id"] or response["entity_id"] != proof["entity_id"]
                or type(response["count"]) is not int or response["count"] != len(expected)
                or not isinstance(response["ranking"], list) or len(response["ranking"]) != len(expected)
                or type(response["reordered"]) is not bool or type(response["ranking_applied"]) is not bool
                or type(proof.get("ranking_applied")) is not bool or proof["ranking_applied"] != response["ranking_applied"]):
            raise QueueError("invalid_odvl_response")
        order = []
        for rank, item in enumerate(response["ranking"], 1):
            if (not isinstance(item, dict) or set(item) != {"candidate_id", "rank", "score"}
                    or item["candidate_id"] not in expected or item["candidate_id"] in order
                    or type(item["rank"]) is not int or item["rank"] != rank
                    or type(item["score"]) not in (int, float) or not math.isfinite(item["score"])
                    or not 0 <= item["score"] <= 1):
                raise QueueError("invalid_odvl_ranking")
            order.append(item["candidate_id"])
        if order != row["task_ids"]:
            raise QueueError("order_differs_from_odvl_response")
    return document


def load_orders(path: Path | None, workloads: dict) -> dict:
    if path is None:
        return identity_orders(workloads)
    with path.open("rb") as stream:
        raw = stream.read(262145)
    if len(raw) > 262144:
        raise QueueError("orders_file_too_large")
    return validate_orders(_json(raw.decode("utf-8")), workloads)


class EWMA:
    def __init__(self, alpha: float = EWMA_ALPHA):
        if type(alpha) not in (int, float) or not math.isfinite(alpha) or not 0.1 <= alpha <= 0.9:
            raise QueueError("invalid_ewma_alpha")
        self.alpha = float(alpha)
        self.values = {}
        self.samples = {}

    def estimate(self, service_class: str) -> float:
        return self.values.get(service_class, EWMA_PRIOR_MS)

    def observe(self, service_class: str, http_ms: float) -> None:
        if not math.isfinite(http_ms) or http_ms < 0:
            raise QueueError("invalid_http_latency")
        self.values[service_class] = self.alpha * http_ms + (1 - self.alpha) * self.estimate(service_class)
        self.samples[service_class] = self.samples.get(service_class, 0) + 1


def choose(policy: str, eligible: list[dict], model: EWMA, positions: dict) -> dict:
    if policy not in POLICIES or not eligible:
        raise QueueError("invalid_policy_or_empty_queue")
    def score(task):
        tie = (task["arrival_ms"], task["task_id"])
        if policy == "fifo": return tie
        if policy == "deadline_first": return (task["deadline_ms"], *tie)
        if policy == "ewma": return (model.estimate(task["service_class"]), *tie)
        rank = positions[task["task_id"]] / max(1, len(positions) - 1)
        if policy == "odvl": return (rank, *tie)
        return (model.estimate(task["service_class"]) + ODVL_WEIGHT_MS * rank, *tie)
    # service_ms is intentionally absent from every scheduling decision.
    return min(eligible, key=score)


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True

    def __init__(self, workload: dict, run_id: str):
        self.tasks = {row["task_id"]: row for row in workload["tasks"]}
        self.run_id = run_id
        self.receipts = {}
        self.seen = set()
        self.guard = threading.Lock()
        self.active = 0
        self.max_active = 0
        super().__init__((HOST, 0), FixtureHandler)


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def answer(self, status, body):
        data = canonical(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.connection.settimeout(1.0)
        if self.path != ENDPOINT or self.client_address[0] != HOST:
            self.answer(404, {"error": "fixture_route_only"}); return
        released = False
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 4096: raise ValueError()
            body = _json(self.rfile.read(length))
            if not isinstance(body, dict) or set(body) != {"run_id", "task_id", "payload"}: raise ValueError()
            task = self.server.tasks.get(body["task_id"])
            if (task is None or body["run_id"] != self.server.run_id
                    or body["payload"] != "x" * task["payload_bytes"]): raise ValueError()
        except Exception:
            self.answer(400, {"error": "invalid_fixture_message"}); return
        with self.server.guard:
            if task["task_id"] in self.server.seen:
                self.answer(409, {"error": "duplicate_task"}); return
            if self.server.active >= CONCURRENCY:
                self.answer(429, {"error": "fixture_concurrency_limit"}); return
            self.server.seen.add(task["task_id"])
            self.server.active += 1
            self.server.max_active = max(self.server.max_active, self.server.active)
        try:
            time.sleep(task["service_ms"] / 1000)
            receipt = {"schema": "civil-message-receipt/v1", "run_id": self.server.run_id,
                       "task_id": task["task_id"], "payload_bytes": task["payload_bytes"],
                       "receipt_id": "rcpt_" + hashlib.sha256((self.server.run_id + ":" + task["task_id"]).encode()).hexdigest()[:32]}
            with self.server.guard:
                self.server.receipts[task["task_id"]] = receipt["receipt_id"]
                self.server.active -= 1
                released = True
            self.answer(200, receipt)
        finally:
            if not released:
                with self.server.guard:
                    self.server.active -= 1


@contextmanager
def fixture(workload, run_id):
    server = FixtureServer(workload, run_id)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _deliver(port: int, run_id: str, task: dict) -> dict:
    start = time.perf_counter()
    connection = HTTPConnection(HOST, port, timeout=1.0)
    try:
        body = canonical({"run_id": run_id, "task_id": task["task_id"], "payload": "x" * task["payload_bytes"]})
        connection.request("POST", ENDPOINT, body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(4097)
        if response.status != 200 or len(raw) > 4096:
            raise QueueError("http_receipt_failed")
        receipt = _json(raw)
        expected_id = "rcpt_" + hashlib.sha256((run_id + ":" + task["task_id"]).encode()).hexdigest()[:32]
        if receipt != {"schema": "civil-message-receipt/v1", "run_id": run_id, "task_id": task["task_id"],
                       "payload_bytes": task["payload_bytes"], "receipt_id": expected_id}:
            raise QueueError("invalid_receipt")
        return {"ok": True, "receipt_id": receipt["receipt_id"], "http_ms": (time.perf_counter() - start) * 1000,
                "finished": time.perf_counter()}
    except Exception:
        return {"ok": False, "error": "http_delivery_failed", "finished": time.perf_counter()}
    finally:
        connection.close()


def percentile(values: list[float], fraction: float) -> float | None:
    if not values: return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower, upper = math.floor(index), math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def run_trial(workload: dict, policy: str, order: list[str], *, ewma_alpha: float = EWMA_ALPHA) -> dict:
    run_id = uuid.uuid4().hex
    model = EWMA(ewma_alpha)
    positions = {task_id: i for i, task_id in enumerate(order)}
    tasks = workload["tasks"]
    if policy not in POLICIES or set(positions) != {t["task_id"] for t in tasks} or len(order) != len(tasks):
        raise QueueError("invalid_trial_policy_or_order")
    results, dispatches = [], []
    with fixture(workload, run_id) as server, ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        start = time.perf_counter()
        cursor, pending, active = 0, [], {}
        client_max_active = 0
        while cursor < len(tasks) or pending or active:
            now = time.perf_counter()
            if now - start >= MAX_TRIAL_SECONDS:
                for task in pending + tasks[cursor:]:
                    results.append({"task_id": task["task_id"], "ok": False, "error": "trial_budget_exceeded",
                                    "deadline_met": False})
                pending.clear(); cursor = len(tasks)
            while cursor < len(tasks) and tasks[cursor]["arrival_ms"] <= (now - start) * 1000:
                pending.append(tasks[cursor]); cursor += 1
            while pending and len(active) < CONCURRENCY:
                task = choose(policy, pending, model, positions)
                pending.remove(task)
                dispatched = time.perf_counter()
                dispatches.append({"task_id": task["task_id"], "dispatch_ms": (dispatched - start) * 1000,
                                   "estimate_ms": model.estimate(task["service_class"])})
                future = pool.submit(_deliver, server.server_port, run_id, task)
                active[future] = (task, dispatched)
                client_max_active = max(client_max_active, len(active))
            next_arrival = start + tasks[cursor]["arrival_ms"] / 1000 if cursor < len(tasks) else None
            timeout = max(0, min(0.02, next_arrival - time.perf_counter())) if next_arrival is not None else 0.02
            if active:
                done, _ = wait(active, timeout=timeout, return_when=FIRST_COMPLETED)
                completed = sorted(((future, future.result()) for future in done), key=lambda pair: pair[1]["finished"])
                for future, result in completed:
                    task, dispatched = active.pop(future)
                    row = {"task_id": task["task_id"], "ok": result["ok"],
                           "arrival_ms": task["arrival_ms"], "deadline_ms": task["deadline_ms"],
                           "dispatch_ms": (dispatched - start) * 1000,
                           "finished_ms": (result["finished"] - start) * 1000,
                           "queue_ms": max(0, (dispatched - start) * 1000 - task["arrival_ms"])}
                    row["deadline_met"] = result["ok"] and row["finished_ms"] <= task["deadline_ms"]
                    if result["ok"]:
                        model.observe(task["service_class"], result["http_ms"])
                        row.update(receipt_id=result["receipt_id"], http_ms=result["http_ms"],
                                   latency_ms=row["finished_ms"] - task["arrival_ms"])
                    else: row["error"] = result["error"]
                    results.append(row)
            elif next_arrival is not None:
                time.sleep(max(0, min(0.01, next_arrival - time.perf_counter())))
        elapsed = time.perf_counter() - start
        accepted, server_max_active = len(server.receipts), server.max_active
    successful = [row for row in results if row["ok"]]
    receipts = [row["receipt_id"] for row in successful]
    if len(set(receipts)) != len(receipts) or len(results) != len(tasks):
        raise QueueError("receipt_or_result_conservation_failed")
    latencies = [row["latency_ms"] for row in successful]
    return {"run_id": run_id, "scenario": workload["scenario"], "policy": policy,
            "workload_sha256": digest(workload), "public_workload_sha256": digest(public_workload(workload)),
            "messages": len(tasks), "concurrency_limit": CONCURRENCY,
            "ewma_alpha": model.alpha,
            "client_max_concurrency": client_max_active, "server_max_concurrency": server_max_active,
            "duration_ms": elapsed * 1000, "received": len(successful), "unique_receipts": len(set(receipts)),
            "server_accepted": accepted, "errors": len(tasks) - len(successful),
            "deadline_misses": sum(not row["deadline_met"] for row in results),
            "p50_ms": percentile(latencies, 0.50), "p95_ms": percentile(latencies, 0.95),
            "throughput_messages_s": len(successful) / elapsed, "application_bytes_s": len(successful) * 64 / elapsed,
            "latency_denominator": "successful_messages_only", "percentile_method": "linear_interpolation",
            "ewma_final_ms": model.values, "dispatches": dispatches, "results": results}


def policy_sequence(repetition: int, scenario_index: int) -> list[str]:
    # Cyclic shifts and reversal counterbalance warm-up/position across trials.
    offset = (repetition * 2 + scenario_index) % len(POLICIES)
    order = list(POLICIES[offset:] + POLICIES[:offset])
    return order[::-1] if repetition % 2 else order


def load_policy(path: Path | None) -> tuple[float, str | None]:
    if path is None:
        return EWMA_ALPHA, None
    with path.open("rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise QueueError("policy_file_too_large")
    policy = _json(raw.decode("utf-8"))
    if (not isinstance(policy, dict) or set(policy) != {"schema", "ewma_alpha"}
            or policy["schema"] != "civil-queue-policy/v1"):
        raise QueueError("invalid_queue_policy")
    alpha = EWMA(policy["ewma_alpha"]).alpha
    return alpha, digest(policy)


def benchmark(*, count: int = 24, repetitions: int = 3, orders_path: Path | None = None,
              policy_path: Path | None = None) -> dict:
    if type(repetitions) is not int or not 1 <= repetitions <= 3:
        raise QueueError("repetitions_must_be_between_1_and_3")
    workloads = {name: make_workload(name, count) for name in SCENARIOS}
    orders = load_orders(orders_path, workloads)
    alpha, policy_sha256 = load_policy(policy_path)
    trials, execution = [], []
    for repetition in range(repetitions):
        for index, scenario in enumerate(SCENARIOS):
            for policy in policy_sequence(repetition, index):
                execution.append({"repetition": repetition + 1, "scenario": scenario, "policy": policy})
                trial = run_trial(workloads[scenario], policy, orders["scenarios"][scenario]["task_ids"], ewma_alpha=alpha)
                trial["repetition"] = repetition + 1
                trials.append(trial)
    summary = []
    for scenario in SCENARIOS:
        for policy in POLICIES:
            rows = [row for row in trials if row["scenario"] == scenario and row["policy"] == policy]
            summary.append({"scenario": scenario, "policy": policy, "repetitions": repetitions,
                            "p50_ms_median": statistics.median(x["p50_ms"] for x in rows if x["p50_ms"] is not None)
                            if any(x["p50_ms"] is not None for x in rows) else None,
                            "p95_ms_median": statistics.median(x["p95_ms"] for x in rows if x["p95_ms"] is not None)
                            if any(x["p95_ms"] is not None for x in rows) else None,
                            "throughput_messages_s_median": statistics.median(x["throughput_messages_s"] for x in rows),
                            "deadline_misses_total": sum(x["deadline_misses"] for x in rows),
                            "errors_total": sum(x["errors"] for x in rows),
                            "unique_receipts_total": sum(x["unique_receipts"] for x in rows)})
    provenance = {}
    for name, row in orders["scenarios"].items():
        provenance[name] = {"task_order_sha256": digest(row["task_ids"]),
                            "proof": {key: row["proof"][key] for key in
                                      ("analysis_id", "response_sha256", "workload_sha256", "entity_id", "memory_space_id", "ranking_applied")}
                            if row["proof"] is not None else None}
    return {"schema": "civil-application-queue-benchmark/v1", "source": "real_loopback_http",
            "cloud_order_source": orders["source"], "cloud_calls_during_benchmark": 0,
            "orders_sha256": digest(orders), "order_provenance": provenance,
            "parameters": {"messages_each": count, "repetitions": repetitions, "concurrency": CONCURRENCY,
                           "ewma_alpha": alpha, "policy_sha256": policy_sha256, "ewma_prior_ms": EWMA_PRIOR_MS,
                           "odvl_weight_ms": ODVL_WEIGHT_MS, "endpoint": "127.0.0.1:<local-ephemeral-port>/messages"},
            "workloads": workloads, "execution_order": execution, "trials": trials, "summary": summary,
            "limits": ["application_queue_only_not_network_transport", "deterministic_fixtures_not_field_workloads",
                       "real_wall_clock_measurements_subject_to_os_jitter", "static_cached_odvl_order",
                       "source_file_consistency_not_independent_cloud_signature", "no_claim_of_universal_performance_gain"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--orders", type=Path)
    parser.add_argument("--policy", type=Path, help="Bounded shared EWMA alpha; never code or a URL")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink(): raise QueueError("output_already_exists")
        report = benchmark(count=args.count, repetitions=args.repetitions, orders_path=args.orders, policy_path=args.policy)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
        print(canonical({"report_sha256": digest(report), "trials": len(report["trials"]),
                         "errors": sum(x["errors"] for x in report["trials"]),
                         "cloud_order_source": report["cloud_order_source"]}))
        return 0
    except Exception as exc:
        print(canonical({"ok": False, "error": str(exc) if isinstance(exc, QueueError) else "benchmark_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

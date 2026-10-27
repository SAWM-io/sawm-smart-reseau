"""Unit tests and small real HTTP loopback checks; no Cloud credentials/client."""
import copy
from http.client import HTTPConnection
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import queue_engine as engine
from workloads import SCENARIOS, digest, export_workloads, make_workload, public_workload


def cloud_orders(workloads):
    scenarios = {}
    for name, workload in workloads.items():
        order = [t["task_id"] for t in workload["tasks"]][::-1]
        response = {"schema": "basira-odvl-ranking/v1", "memory_space_id": "mem_synthetic_test",
                    "entity_id": "ent_" + "a" * 32, "count": len(order), "reordered": True, "ranking_applied": True,
                    "ranking": [{"candidate_id": task_id, "rank": i, "score": 0.5} for i, task_id in enumerate(order, 1)]}
        proof = {"analysis_id": "synthetic-unit-test", "response_sha256": digest(response),
                 "workload_sha256": digest(public_workload(workload)), "entity_id": response["entity_id"],
                 "memory_space_id": response["memory_space_id"], "ranking_applied": True}
        scenarios[name] = {"task_ids": order, "proof": proof, "response": response}
    return {"schema": "civil-odvl-orders/v1", "source": "basira_cloud", "scenarios": scenarios}


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.workloads = {name: make_workload(name, 16) for name in SCENARIOS}

    def test_workloads_are_deterministic_bounded_and_public_export_has_no_future_service_time(self):
        for name in SCENARIOS:
            self.assertEqual(make_workload(name, 16), self.workloads[name])
            self.assertEqual(len(make_workload(name, 64)["tasks"]), 64)
            tasks = self.workloads[name]["tasks"]
            self.assertEqual(len(set(t["task_id"] for t in tasks)), 16)
            self.assertTrue(all(0 < t["service_ms"] <= 100 and t["payload_bytes"] == 64 for t in tasks))
            self.assertEqual([t["arrival_ms"] for t in tasks], sorted(t["arrival_ms"] for t in tasks))
        for count in (0, 15, 65, True):
            with self.assertRaises(ValueError): make_workload("stable", count)
        self.assertNotIn("service_ms", json.dumps(export_workloads(24)))

    def test_ewma_uses_observed_latency_and_same_bounded_alpha(self):
        model = engine.EWMA(0.5)
        self.assertEqual(model.estimate("slow"), 40)
        model.observe("slow", 100)
        self.assertEqual(model.estimate("slow"), 70)
        model.observe("slow", 10)
        self.assertEqual(model.estimate("slow"), 40)
        self.assertEqual(model.samples["slow"], 2)
        for alpha in (0, 0.99, True, float("nan")):
            with self.assertRaises(engine.QueueError): engine.EWMA(alpha)

    def test_policies_choose_only_eligible_messages_without_service_duration_oracle(self):
        tasks = self.workloads["burst"]["tasks"][:4]
        model = engine.EWMA()
        model.observe("slow", 100)
        model.observe("fast", 10)
        positions = {task["task_id"]: i for i, task in enumerate(reversed(tasks))}
        self.assertEqual(engine.choose("fifo", tasks, model, positions)["task_id"], "msg-0000")
        self.assertEqual(engine.choose("deadline_first", tasks, model, positions)["task_id"], "msg-0002")
        self.assertEqual(engine.choose("ewma", tasks, model, positions)["task_id"], "msg-0002")
        self.assertEqual(engine.choose("odvl", tasks, model, positions)["task_id"], "msg-0003")
        self.assertEqual(engine.choose("ewma_odvl", tasks, model, positions)["task_id"], "msg-0003")
        altered = [{**task, "service_ms": 999999 - i} for i, task in enumerate(tasks)]
        for policy in engine.POLICIES:
            self.assertEqual(engine.choose(policy, tasks, model, positions)["task_id"],
                             engine.choose(policy, altered, model, positions)["task_id"])

    def test_offline_identity_is_explicit_and_cannot_hide_another_order(self):
        orders = engine.identity_orders(self.workloads)
        self.assertEqual(engine.validate_orders(orders, self.workloads)["source"], "offline_identity")
        orders["scenarios"]["burst"]["task_ids"].reverse()
        with self.assertRaisesRegex(engine.QueueError, "offline_order_must_be_identity"):
            engine.validate_orders(orders, self.workloads)

    def test_cloud_source_hash_scope_workload_and_exact_permutation_are_required(self):
        valid = cloud_orders(self.workloads)
        self.assertEqual(engine.validate_orders(valid, self.workloads), valid)
        bad_cases = []
        bad = copy.deepcopy(valid); bad["scenarios"]["stable"]["task_ids"].pop(); bad_cases.append(bad)
        bad = copy.deepcopy(valid); bad["scenarios"]["stable"]["task_ids"][0] = bad["scenarios"]["stable"]["task_ids"][1]; bad_cases.append(bad)
        bad = copy.deepcopy(valid); bad["scenarios"]["stable"]["task_ids"].reverse(); bad_cases.append(bad)
        bad = copy.deepcopy(valid); bad["scenarios"]["stable"]["response"]["ranking"][0]["score"] = 0.9; bad_cases.append(bad)
        bad = copy.deepcopy(valid); bad["scenarios"]["stable"]["proof"]["workload_sha256"] = "0" * 64; bad_cases.append(bad)
        bad = copy.deepcopy(valid); bad["scenarios"]["stable"]["proof"]["entity_id"] = "ent_" + "b" * 32; bad_cases.append(bad)
        for bad in bad_cases:
            with self.subTest(bad=bad), self.assertRaises(engine.QueueError): engine.validate_orders(bad, self.workloads)

    def test_policy_file_contains_only_bounded_numeric_alpha(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "policy.json"
            policy = {"schema": "civil-queue-policy/v1", "ewma_alpha": 0.4}
            path.write_text(json.dumps(policy))
            self.assertEqual(engine.load_policy(path), (0.4, digest(policy)))
            path.write_text(json.dumps({**policy, "url": "http://arbitrary.invalid"}))
            with self.assertRaises(engine.QueueError): engine.load_policy(path)

    def test_actual_http_receipts_are_unique_load_bounded_and_dispatch_not_early(self):
        workload = self.workloads["burst"]
        order = [t["task_id"] for t in workload["tasks"]]
        result = engine.run_trial(workload, "fifo", order, ewma_alpha=0.4)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["received"], 16)
        self.assertEqual(result["unique_receipts"], 16)
        self.assertEqual(result["server_accepted"], 16)
        self.assertLessEqual(result["client_max_concurrency"], 4)
        self.assertLessEqual(result["server_max_concurrency"], 4)
        self.assertEqual(result["ewma_alpha"], 0.4)
        self.assertGreater(result["p95_ms"], 0)
        self.assertGreater(result["throughput_messages_s"], 0)
        self.assertLess(result["duration_ms"], 5000)
        self.assertTrue(all(r["dispatch_ms"] >= r["arrival_ms"] for r in result["results"]))
        self.assertEqual(result["deadline_misses"], sum(r["finished_ms"] > r["deadline_ms"] for r in result["results"]))

    def test_fixture_rejects_duplicate_and_unrelated_path(self):
        workload = self.workloads["stable"]
        with engine.fixture(workload, "unit-test") as server:
            first = engine._deliver(server.server_port, "unit-test", workload["tasks"][0])
            duplicate = engine._deliver(server.server_port, "unit-test", workload["tasks"][0])
            self.assertTrue(first["ok"])
            self.assertFalse(duplicate["ok"])
            connection = HTTPConnection(engine.HOST, server.server_port, timeout=1)
            try:
                connection.request("POST", "/other", body="{}")
                response = connection.getresponse()
                self.assertEqual(response.status, 404)
                response.read()
            finally: connection.close()
            self.assertEqual(len(server.receipts), 1)

    def test_counterbalanced_benchmark_preserves_workload_and_alpha_for_all_policies(self):
        calls = []
        def fake_trial(workload, policy, order, *, ewma_alpha):
            calls.append((workload["scenario"], policy, digest(workload), ewma_alpha))
            return {"scenario": workload["scenario"], "policy": policy, "p50_ms": 1, "p95_ms": 2,
                    "throughput_messages_s": 10, "deadline_misses": 0, "errors": 0, "unique_receipts": 16}
        with patch.object(engine, "run_trial", side_effect=fake_trial):
            result = engine.benchmark(count=16, repetitions=3)
        self.assertEqual(len(calls), 45)
        for name in SCENARIOS:
            rows = [row for row in calls if row[0] == name]
            self.assertEqual({row[2] for row in rows}, {digest(self.workloads[name])})
            self.assertEqual({row[3] for row in rows}, {engine.EWMA_ALPHA})
            for policy in engine.POLICIES: self.assertEqual(sum(row[1] == policy for row in rows), 3)
        self.assertNotEqual(engine.policy_sequence(0, 0), engine.policy_sequence(1, 0))
        self.assertEqual(result["cloud_calls_during_benchmark"], 0)
        self.assertEqual(result["cloud_order_source"], "offline_identity")

    def test_percentiles_are_measured_successes_and_documented_interpolation(self):
        self.assertEqual(engine.percentile([10, 20, 30, 40], .5), 25)
        self.assertAlmostEqual(engine.percentile([10, 20, 30, 40], .95), 38.5)
        self.assertIsNone(engine.percentile([], .95))


if __name__ == "__main__":
    unittest.main()

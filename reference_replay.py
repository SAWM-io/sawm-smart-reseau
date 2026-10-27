#!/usr/bin/env python3
"""Replay private 24-cell load balancing with the original stateful ODVL engine.

External sources are mandatory. No engine code, credentials, TSST server or
Cloud API is bundled or substituted. This is distinct from the HTTP queue lab.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import statistics
import sys
import time
import types

FILES = ("experiments/equilibrage-back/reseau_charge.py", "experiments/equilibrage-back/equilibreurs.py",
         "experiments/equilibrage-back/hybrides.py", "backend/services/basira_odvl.py")


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def sources(root):
    root = Path(root).expanduser().resolve(strict=True)
    public = Path(__file__).resolve().parent
    if root == public or public in root.parents:
        raise ValueError("private_source_root_must_be_external_to_public_repository")
    resolved = {}
    for name in FILES:
        target = (root / name).resolve(strict=True)
        if root not in target.parents or not target.is_file():
            raise ValueError("private_source_outside_declared_root:" + name)
        resolved[name] = target
    return root, resolved


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_odvl_hybrids(path, E, R):
    """Load the two unchanged external classes, avoiding unrelated TSST imports.

    Full hybrides.py imports a TSST bridge that reads local .env files during
    import. The requested comparison does not use TSST. Compile only its original
    ResonanceOdvl/Hybride definitions and literal averaging-window constant.
    No model implementation is copied here or replaced by a stand-in.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name in ("ResonanceOdvl", "Hybride")]
    constants = [node for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "FENETRE_MOYENNE" for t in node.targets)]
    if len(classes) != 2 or len(constants) != 1:
        raise ValueError("private_hybrid_interface_changed")
    window = ast.literal_eval(constants[0].value)
    if type(window) is not int or window != 12:
        raise ValueError("reference_window_changed")
    namespace = {"E": E, "R": R, "random": random, "FENETRE_MOYENNE": window,
                 "__name__": "sawm_reference_hybrids", "__file__": str(path)}
    exec(compile(ast.Module(body=classes, type_ignores=[]), str(path), "exec"), namespace)
    return types.SimpleNamespace(**{name: namespace[name] for name in ("ResonanceOdvl", "Hybride")})


def play(E, R, arm, world, record=False):
    rows = []
    if record:
        rank = arm.classer
        def finish_previous():
            if rows:
                rows[-1].update(absorbed_total=arm.absorbe, lost_total=arm.perdu,
                                redeployments_total=arm.redeplacements)
        def recorded(step, measurements):
            finish_previous()
            ordered = rank(step, measurements)
            rows.append({"step": step, "model_elapsed_minutes": step * R.PAS_MIN,
                         "observed_load": [measurements[i] for i in range(R.CELLULES)],
                         "ranked_cell_ids": list(ordered), "selected_cell_ids": list(ordered[:E.A_DECALER])})
            return ordered
        arm.classer = recorded
    result = arm.jouer(world)
    if record:
        finish_previous()
    return result, rows


def run(private_root, output, trace_only=False):
    root, paths = sources(private_root)
    output = Path(output).expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("output_directory_must_be_new")
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    output.mkdir(parents=True, mode=0o700)
    report = {"schema": "sawm-cell-reference-replay/v1", "source_sha256": hashes,
        "scope": {"simulation": True, "operator_network": False, "live_transport": False,
                  "cloud_calls": 0, "tsst_exercised": False, "sawm_llm_exercised": False},
        "engine": "Private stateful ODVLNetwork; a stateless /odvl/rank call is not equivalent.",
        "loader": "Original external ResonanceOdvl/Hybride class AST; TSST bridge import excluded to avoid reading credentials.",
        "protocol": {"seeds": 8, "steps": 400, "cells": 24, "step_minutes": 5,
                     "horizon_steps": 4, "capacity": 100, "transfer_volume": 34,
                     "chosen_cells_per_step": 3, "average_window": 12, "hybrid_weight": 0.5,
                     "nominal_background": [28, 46], "tight_background": [40, 58]},
        "limitations": ["The original world consumes RNG during future scoring as well as observation; equal seeds do not guarantee identical subsequent noise across arms.",
                        "Transferred load is scored but not reinjected into measured cell loads.",
                        "No broader TSST arm, weight sweep or operator traffic validation is included."],
        "trace_only": trace_only, "trace_files": [], "success": False}
    started = time.perf_counter()
    try:
        folder = root / "experiments/equilibrage-back"
        R = load("reseau_charge", folder / "reseau_charge.py")
        E = load("equilibreurs", folder / "equilibreurs.py")
        H = load_odvl_hybrids(folder / "hybrides.py", E, R)
        if Path(E.odvl.__file__).resolve() != paths["backend/services/basira_odvl.py"]:
            raise ValueError("unexpected_odvl_engine_path")
        results = {}
        for scenario, low, high in (("nominal", 28.0, 46.0), ("serre", 40.0, 58.0)):
            R.BASE_MIN, R.BASE_MAX = low, high
            values = {"base": [], "hybrid": []}
            for seed in range(1 if trace_only else 8):
                memory = H.ResonanceOdvl(random.Random(4000 + seed))
                memory.jouer(R.Monde(random.Random(3000 + seed), 400))
                arms = (("base", E.Moyenne(random.Random(4000 + seed))),
                        ("hybrid", H.Hybride(random.Random(4000 + seed), memory.cache, "moyenne", "ODVL", 0.5)))
                for label, arm in arms:
                    result, rows = play(E, R, arm, R.Monde(random.Random(3000 + seed), 400), record=seed == 0)
                    values[label].append(result)
                    if seed == 0:
                        filename = "trace-%s-%s-seed0.json" % (scenario, label)
                        save(output / filename, {"seed": 0, "scenario": scenario, "arm": label,
                            "cell_count": R.CELLULES, "result": result, "steps": rows,
                            "scope": "Observed synthetic loads and original decisions; no additional world/RNG queries."})
                        report["trace_files"].append(filename)
            if not trace_only:
                values["summary"] = {label: {field: statistics.fmean(row[field] for row in values[label])
                    for field in ("part_absorbee", "redeplacements")} for label in ("base", "hybrid")}
                results[scenario] = values
        if not trace_only:
            report["results"] = results
        report["success"] = all(hashlib.sha256(path.read_bytes()).hexdigest() == hashes[name]
                                for name, path in paths.items())
        if not report["success"]:
            raise ValueError("private_sources_changed_during_replay")
    except Exception as exc:
        report["error"] = type(exc).__name__ + ":" + str(exc)
        raise
    finally:
        report["elapsed_s"] = time.perf_counter() - started
        save(output / "replay.json", report)
        manifest = {file.name: hashlib.sha256(file.read_bytes()).hexdigest()
                    for file in output.glob("*.json") if file.name != "manifest.json"}
        save(output / "manifest.json", manifest)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--trace-only", action="store_true", help="Replay seed 0 for visualizations, without repeating the full campaign")
    args = parser.parse_args()
    try:
        report = run(args.private_source_root, args.output_dir, args.trace_only)
        print(json.dumps({"success": report["success"], "trace_only": report["trace_only"],
                          "output_dir": str(args.output_dir)}, ensure_ascii=False))
        return 0 if report["success"] else 2
    except Exception as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

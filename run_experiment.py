#!/usr/bin/env python3
"""Run one original bounded CPU experiment using hash-pinned public inputs."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True

SEEDS_SHA256 = "9b54552342fd7a9e2334461be5d66b3bd617d3dd0cd25d656511bf5127abb9f1"
METRIC_SHA256 = "1f5c66bddf7074c0108cd712b62411a80221b034e582f26959f977e4fa08e143"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verified_bytes(path, expected, *, compressed=False):
    raw = path.read_bytes()
    if compressed and raw.startswith(b"\x1f\x8b"):
        raw = gzip.decompress(raw)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Input hash differs: " + path.name)
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=Path, required=True)
    parser.add_argument("--metric-file", type=Path, required=True)
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--rounds", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve the existing result and choose a new output filename")
    if args.output.suffix.lower() != ".json" or args.output.name == "kernel-metadata.json":
        parser.error("Output must be a new ordinary JSON result, not a notebook identity file")
    seeds = json.loads(verified_bytes(args.seeds, SEEDS_SHA256, compressed=True))
    selected = [row for row in seeds if row["n"] == args.n]
    if len(selected) != 1:
        parser.error("Choose one of the twelve retained seed sizes")
    verified_bytes(args.metric_file, METRIC_SHA256)
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    metric = load_module("supplied_official_metric", args.metric_file)
    experiment = load_module("contact_experiment", Path(__file__).with_name("contact_experiment.py"))
    result = experiment.rerun_contact_experiment(selected[0], metric, rounds=args.rounds, clearance=4e-8)
    result["input_hashes"] = {"seeds_decompressed": SEEDS_SHA256, "metric": METRIC_SHA256}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"n": args.n, "accepted": result["accepted"], "gain": result["gain"],
                      "official_score": None, "elapsed_seconds": result["elapsed_seconds"]}))


if __name__ == "__main__":
    main()

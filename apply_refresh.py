"""Small notebook integration for pinned numerical data; no remote operations."""
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def _load(path, expected_sha256):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("Pinned numerical input hash differs")
    # The expected hash binds the supplied file bytes. Kaggle may extract gzip
    # uploads into plain JSON, whose public manifest hash is different.
    return json.loads(gzip.decompress(data) if data.startswith(b"\x1f\x8b") else data)


def apply_refresh_bundle(best, labels, stages, *, bundle_path, bundle_sha256,
                         sources_path, sources_sha256, side):
    """Improve incumbents only; return exact decimal overrides and source index.

    Call after existing portfolio construction and immediately before audit /
    export. Do not normalize, repair, or round these already certified rows.
    """
    bundle = _load(bundle_path, bundle_sha256)
    source_data = _load(sources_path, sources_sha256)
    if bundle.get("schema_version") != 1 or source_data.get("schema_version") != 1:
        raise ValueError("Unsupported numerical bundle")
    sources = {int(record["n"]): record for record in source_data["provenance"]}
    seen, overrides = set(), {}
    before = {n: side(poses) for n, poses in best.items()}
    for record in bundle["packings"]:
        n = int(record["n"])
        if n in seen or n not in best or n not in sources:
            raise ValueError("Repeated or unbound packing")
        seen.add(n)
        rows = record["rows"]
        poses = np.array(rows, dtype=float)
        if poses.shape != (n, 3) or not np.isfinite(poses).all():
            raise ValueError("Invalid numerical packing")
        measured = side(poses)
        if abs(measured - float(record["side_decimal"])) > 1e-10:
            raise ValueError("Certificate side differs from numerical packing")
        if measured < before[n] - 1e-12:
            best[n] = poses
            labels[n] = record["method"] + ": " + sources[n]["credit"]
            overrides[n] = {"rows": rows, "poses": poses.copy()}
    if any(side(best[n]) > old + 1e-12 for n, old in before.items()):
        raise AssertionError("Portfolio regression")
    stages.append({"stage": "Pinned 24 October numerical certificates and original contact-axis refinements",
        "score": sum(side(poses) / math.sqrt(n) - 1 for n, poses in best.items()),
        "improved": len(overrides)})
    return overrides, {n: sources[n] for n in overrides}


def export_rows(n, poses, overrides):
    """Use certified decimal bytes where available; stop if later code drifts."""
    if n in overrides:
        if not np.array_equal(np.asarray(poses), overrides[n]["poses"]):
            raise ValueError("Packing changed after adopting its certified decimal rows")
        values = overrides[n]["rows"]
    else:
        values = [[format(float(value), ".17g") for value in row] for row in poses]
    return [{"id": n * (n - 1) // 2 + i, "n": n, "square_id": i,
        "x": x, "y": y, "angle": angle} for i, (x, y, angle) in enumerate(values)]

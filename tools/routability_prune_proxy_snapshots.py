#!/usr/bin/env python3
"""Prune completed RUPlace external-router DEF snapshots safely."""

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


SNAPSHOT_GLOB = "placement/**/ruplace/external/route_*.def"
FINAL_DEF_GLOB = "placement/**/*.gp.def"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def completed_method_dirs(root):
    return sorted({
        summary.parent.parent
        for summary in root.glob("**/evaluation/summary.json")
        if summary.is_file()
    })


def final_placed_defs(method_dir):
    return sorted(
        path for path in method_dir.glob(FINAL_DEF_GLOB)
        if "/ruplace/external/" not in path.as_posix()
    )


def prune_method(method_dir, campaign_root, execute=False):
    summary = method_dir / "evaluation" / "summary.json"
    snapshots = sorted(method_dir.glob(SNAPSHOT_GLOB))
    final_defs = final_placed_defs(method_dir)
    record = {
        "method_dir": str(method_dir.relative_to(campaign_root)),
        "summary": str(summary.relative_to(campaign_root)),
        "summary_sha256": sha256(summary),
        "final_defs": [],
        "snapshot_count": len(snapshots),
        "snapshot_bytes": sum(path.stat().st_size for path in snapshots),
        "snapshots": [
            {
                "path": str(path.relative_to(campaign_root)),
                "size": path.stat().st_size,
            }
            for path in snapshots
        ],
        "executed": bool(execute),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if not final_defs:
        record["status"] = "refused_missing_final_def"
        return record
    record["final_defs"] = [
        {
            "path": str(path.relative_to(campaign_root)),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in final_defs
    ]
    if not snapshots:
        record["status"] = "already_pruned"
        return record
    if execute:
        for path in snapshots:
            path.unlink()
    record["status"] = "pruned" if execute else "dry_run"
    return record


def append_records(path, records):
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True) + "\n")


def manifest_totals(path):
    total = {"methods": 0, "snapshots": 0, "bytes": 0}
    if not path.is_file():
        return total
    with path.open() as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("status") != "pruned":
                continue
            total["methods"] += 1
            total["snapshots"] += int(record.get("snapshot_count", 0))
            total["bytes"] += int(record.get("snapshot_bytes", 0))
    return total


def process_once(campaign_root, manifest, execute=False):
    records = []
    for method_dir in completed_method_dirs(campaign_root):
        record = prune_method(method_dir, campaign_root, execute=execute)
        if record["status"] != "already_pruned":
            records.append(record)
    append_records(manifest, records)
    return records


def process_alive(pid):
    if pid is None:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def write_status(path, campaign_root, manifest, records, phase, total):
    payload = {
        "phase": phase,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "campaign_root": str(campaign_root),
        "manifest": str(manifest),
        "last_pruned_methods": sum(r["status"] == "pruned" for r in records),
        "last_pruned_snapshots": sum(
            r["snapshot_count"] for r in records if r["status"] == "pruned"
        ),
        "last_pruned_bytes": sum(
            r["snapshot_bytes"] for r in records if r["status"] == "pruned"
        ),
        "total_pruned_methods": total["methods"],
        "total_pruned_snapshots": total["snapshots"],
        "total_pruned_bytes": total["bytes"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--status", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--watch-sec", type=float, default=0.0)
    parser.add_argument("--stop-when-pid-exits", type=int)
    args = parser.parse_args(argv)

    campaign_root = args.campaign_root.resolve()
    if not campaign_root.is_dir():
        parser.error("campaign root is not a directory: %s" % campaign_root)
    manifest = args.manifest.resolve()
    status = args.status.resolve() if args.status else None
    if args.watch_sec < 0:
        parser.error("--watch-sec must be nonnegative")
    total = manifest_totals(manifest)

    while True:
        records = process_once(campaign_root, manifest, execute=args.execute)
        pruned = [record for record in records if record["status"] == "pruned"]
        total["methods"] += len(pruned)
        total["snapshots"] += sum(record["snapshot_count"] for record in pruned)
        total["bytes"] += sum(record["snapshot_bytes"] for record in pruned)
        alive = process_alive(args.stop_when_pid_exits)
        phase = "watching" if args.watch_sec and alive else "complete"
        if status:
            write_status(
                status, campaign_root, manifest, records, phase, total
            )
        if not args.watch_sec or not alive:
            break
        time.sleep(args.watch_sec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

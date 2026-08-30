#!/usr/bin/env python3
"""Import quarantined OpenROAD recoveries after strict provenance checks."""

import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.routability_golden_replay import result_meets_resume_contract


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise ValueError("path escapes root: %s" % relative)
    return path


def verify_hashes(root, expected):
    verified = {}
    for relative, digest in sorted(expected.items()):
        path = safe_path(root, relative)
        if not path.is_file():
            raise ValueError("missing provenance input: %s" % relative)
        actual = sha256(path)
        if actual != digest:
            raise ValueError(
                "provenance hash mismatch for %s: %s != %s"
                % (relative, actual, digest)
            )
        verified[relative] = actual
    return verified


def rebase_result(result, artifact_dir):
    artifact_dir = Path(artifact_dir).resolve()
    rebased = copy.deepcopy(result)
    artifacts = rebased.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("OpenROAD result lacks artifacts")
    for name, value in list(artifacts.items()):
        if not isinstance(value, str) or not value:
            raise ValueError("invalid artifact path for %s" % name)
        filename = Path(value).name
        if not filename or filename in (".", ".."):
            raise ValueError("invalid artifact filename for %s" % name)
        path = artifact_dir / filename
        if not path.is_file():
            raise ValueError("missing recovered artifact %s: %s" % (name, path))
        artifacts[name] = str(path)
    return rebased


def validate_result(result):
    candidate = {**result, "authoritative_for_comparison": True}
    if not result_meets_resume_contract(candidate, "openroad"):
        raise ValueError("recovered result fails strict OpenROAD artifact contract")
    return candidate


def load_recovered_result(source):
    path = Path(source) / "openroad.json"
    if not path.is_file():
        raise ValueError("recovery is incomplete: %s" % path)
    try:
        result = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ValueError("invalid recovered OpenROAD JSON: %s" % error)
    return validate_result(rebase_result(result, source))


def load_valid_target(target):
    path = Path(target) / "openroad.json"
    if not path.is_file():
        return None
    try:
        result = json.loads(path.read_text())
        return validate_result(result)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def write_rebased_result(directory, provenance):
    directory = Path(directory).resolve()
    result_path = directory / "openroad.json"
    result = json.loads(result_path.read_text())
    result = rebase_result(result, directory)
    result["recovery_provenance"] = provenance
    validate_result(result)
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (directory / "summary.json").write_text(json.dumps(
        {"results": [result]}, indent=2, sort_keys=True
    ) + "\n")
    return result


def import_route(recovery_root, campaign_root, archive_root, route, dry_run=False):
    name = route.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("route entry lacks a name")
    source = safe_path(recovery_root, route.get("source_dir", ""))
    target = safe_path(campaign_root, route.get("target_dir", ""))
    recovered = load_recovered_result(source)
    existing = load_valid_target(target)
    if existing is not None:
        if existing.get("metrics") != recovered.get("metrics"):
            raise ValueError(
                "%s has a competing valid target with different metrics" % name
            )
        return {"name": name, "status": "already_valid_identical"}

    if dry_run:
        return {"name": name, "status": "validated_pending_import"}

    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(
        prefix=".%s.import-" % target.name, dir=str(target.parent)
    ))
    archive = safe_path(archive_root, "%s/evaluation" % name)
    if archive.exists():
        shutil.rmtree(stage)
        raise ValueError("archive already exists: %s" % archive)
    provenance = {
        "imported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "quarantine_source": str(source),
        "route_name": name,
    }
    archived = False
    installed = False
    try:
        shutil.copytree(source, stage, dirs_exist_ok=True)
        write_rebased_result(stage, provenance)
        archive.parent.mkdir(parents=True, exist_ok=False)
        if target.exists():
            shutil.move(str(target), str(archive))
            archived = True
        os.replace(stage, target)
        installed = True
        imported = write_rebased_result(target, provenance)
        validate_result(imported)
    except Exception:
        if installed and target.exists():
            failed = target.parent / (target.name + ".failed_import")
            if not failed.exists():
                os.replace(target, failed)
        if archived and archive.exists() and not target.exists():
            os.replace(archive, target)
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return {
        "name": name,
        "status": "imported",
        "target": str(target),
        "archived_previous": str(archive) if archived else "",
        "archived_previous_sha256": (
            sha256(archive / "openroad.json") if archived else ""
        ),
    }


def run_import(spec, recovery_root, campaign_root, archive_root, dry_run=False):
    recovery_root = Path(recovery_root).resolve()
    campaign_root = Path(campaign_root).resolve()
    archive_root = Path(archive_root).resolve()
    if campaign_root == archive_root or campaign_root in archive_root.parents:
        raise ValueError("archive root must be outside the golden campaign")
    verified = verify_hashes(recovery_root, spec.get("required_hashes", {}))
    routes = spec.get("routes")
    if not isinstance(routes, list) or not routes:
        raise ValueError("import spec has no routes")
    results = [
        import_route(
            recovery_root, campaign_root, archive_root, route, dry_run=dry_run
        )
        for route in routes
    ]
    return {
        "dry_run": bool(dry_run),
        "recovery_root": str(recovery_root),
        "campaign_root": str(campaign_root),
        "archive_root": str(archive_root),
        "verified_hashes": verified,
        "routes": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--recovery-dir", type=Path, required=True)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    spec = json.loads(args.spec.read_text())
    report = run_import(
        spec, args.recovery_dir, args.campaign_dir, args.archive_dir,
        dry_run=args.dry_run,
    )
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)
        print(args.report)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

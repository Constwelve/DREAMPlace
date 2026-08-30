#!/usr/bin/env python3
"""Prepare local golden-routing storage and attest evaluator activation."""

import argparse
import datetime
import filecmp
import hashlib
import json
import os
from pathlib import Path
import shutil


ARTIFACT_DIRECTORIES = ("source_campaign", "campaign", "summary")
EVALUATOR_MODULES = ("base.py", "innovus.py", "openroad.py")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    try:
        temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def prepare_storage(control_root, artifact_root):
    control_root = Path(control_root).absolute()
    artifact_root = Path(artifact_root).absolute()
    if control_root == artifact_root:
        raise ValueError("control and artifact roots must be different")
    control_root.mkdir(parents=True, exist_ok=True)
    artifact_root.mkdir(parents=True, exist_ok=True)

    for name in ARTIFACT_DIRECTORIES:
        link = control_root / name
        target = artifact_root / name
        if os.path.lexists(link) and (
            not link.is_symlink() or link.resolve() != target.resolve()
        ):
            raise ValueError(
                "refusing to replace retained artifact path: %s" % link
            )

    links = {}
    for name in ARTIFACT_DIRECTORIES:
        target = artifact_root / name
        target.mkdir(parents=True, exist_ok=True)
        link = control_root / name
        if not os.path.lexists(link):
            link.symlink_to(target, target_is_directory=True)
        links[name] = {
            "control_path": str(link),
            "artifact_path": str(target),
            "link_target": os.readlink(link),
        }

    result = {
        "schema_version": 1,
        "status": "passed",
        "prepared_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "control_root": str(control_root),
        "artifact_root": str(artifact_root),
        "retained_paths_replaced": False,
        "links": links,
    }
    atomic_write_json(control_root / "artifact_layout.json", result)
    return result


def prepare_python_install(source_install, target_install, output):
    source_install = Path(source_install).resolve()
    target_install = Path(target_install).absolute()
    output = Path(output).absolute()
    source_package = source_install / "dreamplace"
    target_package = target_install / "dreamplace"
    if not source_package.is_dir():
        raise ValueError("missing source DREAMPlace install: %s" % source_package)
    if os.path.lexists(target_install) and not target_install.is_dir():
        raise ValueError(
            "refusing to replace isolated install path: %s" % target_install
        )
    target_install.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_package, target_package, dirs_exist_ok=True)
    source_files = sum(1 for path in source_package.rglob("*") if path.is_file())
    target_files = sum(1 for path in target_package.rglob("*") if path.is_file())
    if target_files < source_files:
        raise ValueError("isolated DREAMPlace install is incomplete")
    result = {
        "schema_version": 1,
        "status": "passed",
        "prepared_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_install": str(source_install),
        "target_install": str(target_install),
        "source_file_count": source_files,
        "target_file_count": target_files,
        "retained_paths_replaced": False,
    }
    atomic_write_json(output, result)
    return result


def activate_evaluators(source_dir, installed_dir, output):
    source_dir = Path(source_dir).resolve()
    installed_dir = Path(installed_dir).resolve()
    output = Path(output).absolute()
    if source_dir == installed_dir:
        raise ValueError("source and installed evaluator directories must differ")
    installed_dir.mkdir(parents=True, exist_ok=True)

    modules = {}
    for name in EVALUATOR_MODULES:
        source = source_dir / name
        installed = installed_dir / name
        if not source.is_file():
            raise ValueError("missing source evaluator module: %s" % source)
        before_hash = sha256(installed) if installed.is_file() else None
        temporary = installed.with_name(".%s.%d.tmp" % (name, os.getpid()))
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, installed)
        finally:
            if temporary.exists():
                temporary.unlink()
        source_hash = sha256(source)
        installed_hash = sha256(installed)
        byte_identical = filecmp.cmp(source, installed, shallow=False)
        if source_hash != installed_hash or not byte_identical:
            raise ValueError("evaluator activation mismatch: %s" % name)
        modules[name] = {
            "source_sha256": source_hash,
            "installed_before_sha256": before_hash,
            "installed_after_sha256": installed_hash,
            "byte_identical": byte_identical,
            "changed": before_hash != installed_hash,
        }

    result = {
        "schema_version": 1,
        "status": "passed",
        "activated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_dir": str(source_dir),
        "installed_dir": str(installed_dir),
        "modules": modules,
    }
    atomic_write_json(output, result)
    return result


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    storage = subparsers.add_parser("prepare-storage")
    storage.add_argument("--control-root", type=Path, required=True)
    storage.add_argument("--artifact-root", type=Path, required=True)
    activation = subparsers.add_parser("activate-evaluators")
    activation.add_argument("--source-dir", type=Path, required=True)
    activation.add_argument("--installed-dir", type=Path, required=True)
    activation.add_argument("--output", type=Path, required=True)
    isolated = subparsers.add_parser("prepare-python-install")
    isolated.add_argument("--source-install", type=Path, required=True)
    isolated.add_argument("--target-install", type=Path, required=True)
    isolated.add_argument("--output", type=Path, required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "prepare-storage":
        result = prepare_storage(args.control_root, args.artifact_root)
    elif args.command == "activate-evaluators":
        result = activate_evaluators(
            args.source_dir, args.installed_dir, args.output
        )
    else:
        result = prepare_python_install(
            args.source_install, args.target_install, args.output
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

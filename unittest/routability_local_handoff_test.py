#!/usr/bin/env python3

import json
import os
from pathlib import Path
import tempfile
import unittest


from tools.routability_local_handoff import (
    ARTIFACT_DIRECTORIES,
    EVALUATOR_MODULES,
    activate_evaluators,
    prepare_python_install,
    prepare_storage,
)


class RoutabilityLocalHandoffTest(unittest.TestCase):
    def test_prepares_isolated_install_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_install = root / "source_install"
            source_package = source_install / "dreamplace"
            source_evaluators = source_package / "ops/routability_eval"
            source_evaluators.mkdir(parents=True)
            (source_package / "__init__.py").write_text("# source\n")
            (source_evaluators / "base.py").write_text("old base\n")
            target_install = root / "artifact/python_install"
            output = root / "control/python_install.json"

            result = prepare_python_install(
                source_install, target_install, output
            )
            (target_install / "dreamplace/ops/routability_eval/base.py").write_text(
                "corrected base\n"
            )

            self.assertEqual(json.loads(output.read_text()), result)
            self.assertEqual(
                (source_evaluators / "base.py").read_text(), "old base\n"
            )
            self.assertEqual(result["source_file_count"], 2)
            self.assertEqual(result["target_file_count"], 2)

    def test_prepares_alternate_artifact_root_with_control_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "repo/status"
            artifact = root / "alternate/campaign"
            result = prepare_storage(control, artifact)

            self.assertEqual(result["artifact_root"], str(artifact.absolute()))
            self.assertFalse(result["retained_paths_replaced"])
            for name in ARTIFACT_DIRECTORIES:
                link = control / name
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), (artifact / name).resolve())
            manifest = json.loads((control / "artifact_layout.json").read_text())
            self.assertEqual(manifest["links"], result["links"])

    def test_storage_setup_never_replaces_retained_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "repo/status"
            artifact = root / "alternate/campaign"
            retained = control / "campaign"
            retained.mkdir(parents=True)
            marker = retained / "evidence.json"
            marker.write_text('{"retained": true}\n')

            with self.assertRaisesRegex(ValueError, "refusing to replace"):
                prepare_storage(control, artifact)

            self.assertEqual(marker.read_text(), '{"retained": true}\n')
            self.assertFalse(retained.is_symlink())

    def test_isolated_install_refuses_to_replace_non_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source/dreamplace"
            source.mkdir(parents=True)
            (source / "__init__.py").write_text("# source\n")
            target = root / "target"
            target.write_text("retained\n")

            with self.assertRaisesRegex(ValueError, "refusing to replace"):
                prepare_python_install(
                    root / "source", target, root / "manifest.json"
                )
            self.assertEqual(target.read_text(), "retained\n")

    def test_evaluator_activation_is_atomic_and_hash_attested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            installed = root / "installed"
            output = root / "activation.json"
            source.mkdir()
            installed.mkdir()
            for index, name in enumerate(EVALUATOR_MODULES):
                (source / name).write_text("source_%d\n" % index)
                (installed / name).write_text("old_%d\n" % index)

            result = activate_evaluators(source, installed, output)

            self.assertEqual(json.loads(output.read_text()), result)
            self.assertEqual(set(result["modules"]), set(EVALUATOR_MODULES))
            for name in EVALUATOR_MODULES:
                self.assertEqual((source / name).read_bytes(), (installed / name).read_bytes())
                self.assertTrue(result["modules"][name]["byte_identical"])
                self.assertTrue(result["modules"][name]["changed"])
            self.assertFalse(any(path.name.endswith(".tmp") for path in installed.iterdir()))


if __name__ == "__main__":
    unittest.main()

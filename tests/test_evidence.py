"""Byte provenance and bounded excerpt checks; no model/device experiments."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import evidence


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "原始.log"
        self.source.write_bytes("第一行\r\n关键证据\r\n末行\n".encode("utf-8"))
        self.bundle = self.root / "snapshot"

    def capture(self, **kwargs):
        return evidence.capture([self.source], self.bundle, **kwargs)

    def manifest(self):
        return json.loads((self.bundle / "manifest.json").read_text(encoding="utf-8"))

    def test_exact_bytes_and_unicode_line_numbers(self):
        original = self.source.read_bytes()
        self.capture(context={"host": "remote", "command": "caller-declared"})
        data = self.manifest()
        self.assertEqual((self.bundle / data["artifacts"][0]["snapshot"]).read_bytes(), original)
        self.assertEqual(data["declared_context"]["host"], "remote")
        self.assertIn("capture_host", data)
        self.assertEqual(evidence.show(self.bundle, 0, "2:3")["lines"],
                         [{"line": 2, "text": "关键证据"}, {"line": 3, "text": "末行"}])
        self.assertTrue(evidence.verify(self.bundle, True)["artifacts"][0]["source_matches"])

    def test_source_append_does_not_invalidate_frozen_snapshot(self):
        self.capture()
        self.source.write_text("new run\n", encoding="utf-8")
        result = evidence.verify(self.bundle, True)
        self.assertTrue(result["intact"])
        self.assertFalse(result["artifacts"][0]["source_matches"])
        self.assertFalse(result["sources_match"])
        self.assertEqual(evidence.show(self.bundle, 0, "2:2")["lines"][0]["text"], "关键证据")

    def test_modified_snapshot_rejected_even_with_same_size(self):
        self.capture()
        target = self.bundle / self.manifest()["artifacts"][0]["snapshot"]
        raw = target.read_bytes()
        target.write_bytes(b"x" * len(raw))
        self.assertFalse(evidence.verify(self.bundle)["intact"])
        with self.assertRaisesRegex(ValueError, "changed"):
            evidence.show(self.bundle, 0, "1:1")

    def test_existing_bundle_never_overwritten(self):
        self.capture()
        original = (self.bundle / "manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.capture()
        self.assertEqual((self.bundle / "manifest.json").read_bytes(), original)

    def test_size_limit_and_duplicate_input(self):
        with self.assertRaisesRegex(ValueError, "budget"):
            self.capture(max_bytes=1)
        self.assertFalse(self.bundle.exists())
        with self.assertRaisesRegex(ValueError, "duplicate"):
            evidence.capture([self.source, self.source], self.bundle)

    def test_failed_capture_does_not_publish_manifest(self):
        with patch.object(evidence, "file_bytes", side_effect=ValueError("changed during capture")):
            with self.assertRaisesRegex(ValueError, "changed"):
                self.capture()
        self.assertFalse((self.bundle / "manifest.json").exists())

    def test_snapshot_path_cannot_escape_bundle(self):
        self.capture()
        data = self.manifest()
        data["artifacts"][0]["snapshot"] = "../原始.log"
        (self.bundle / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inside"):
            evidence.verify(self.bundle)

    def test_line_limits_are_not_silent_truncation(self):
        self.capture()
        for lines in ("0:1", "2:1", "1:9", "1:201", "1"):
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                evidence.show(self.bundle, 0, lines)
        with self.assertRaises(ValueError):
            evidence.show(self.bundle, -1, "1:1")

    def test_large_single_line_is_bounded(self):
        self.source.write_text("a" * (evidence.MAX_EXCERPT_BYTES + 1), encoding="utf-8")
        self.capture()
        with self.assertRaisesRegex(ValueError, "32 KiB"):
            evidence.show(self.bundle, 0, "1:1")

    def test_unicode_separator_is_not_an_extra_physical_line(self):
        self.source.write_text("a\u2028b\nsecond\n", encoding="utf-8")
        self.capture()
        self.assertEqual(evidence.show(self.bundle, 0, "2:2")["lines"], [{"line": 2, "text": "second"}])

    def test_invalid_context_is_rejected_before_creating_bundle(self):
        with self.assertRaises(ValueError):
            self.capture(context={"value": float("nan")})
        self.assertFalse(self.bundle.exists())

    def test_cli_does_not_execute_declared_command(self):
        marker = self.root / "must-not-exist"
        context = self.root / "context.json"
        context.write_text(json.dumps({"command": f"touch {marker}"}), encoding="utf-8")
        run = subprocess.run([sys.executable, evidence.__file__, "capture", "--out", str(self.bundle),
                              "--file", str(self.source), "--context", str(context)],
                             capture_output=True, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertFalse(marker.exists())
        verify = subprocess.run([sys.executable, evidence.__file__, "verify", "--bundle", str(self.bundle)],
                                capture_output=True, encoding="utf-8")
        self.assertEqual(verify.returncode, 0, verify.stderr)
        self.assertTrue(json.loads(verify.stdout)["intact"])

    def test_source_drift_cli_exits_nonzero_without_losing_snapshot(self):
        self.capture()
        self.source.unlink()
        result = subprocess.run([sys.executable, evidence.__file__, "verify", "--bundle", str(self.bundle),
                                 "--sources"], capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertTrue(data["intact"])
        self.assertFalse(data["sources_match"])


if __name__ == "__main__":
    unittest.main()

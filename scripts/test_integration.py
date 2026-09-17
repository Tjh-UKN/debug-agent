"""Integration checks for UI, reminder hook and isolated installation."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "debug-agent" / "scripts"))
from control import read_config, set_mode
from panel import render, table, width
from recovery import discover, snapshot
from case import execute
from install import install
import install as installer

spec = importlib.util.spec_from_file_location("session_hook", ROOT / "hooks" / "session.py")
session_hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session_hook)


def state():
    return {"case": {"title": "数值偏差", "goal": "定位原因"}, "checkpoint": {}, "hypothesis": {},
            "task": {}, "evidence": {}, "closure": None, "status": "active"}


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.config = self.home / "config.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_off_is_quiet_and_read_only(self):
        self.assertIsNone(session_hook.context_for({"cwd": str(self.home)}, self.config))
        self.assertFalse(self.config.exists())

    def test_on_restores_candidates_without_launching(self):
        folder = self.home / ".debug-agent" / "case-a"
        folder.mkdir(parents=True)
        ledger = folder / "state.json"
        ledger.write_text('{"schema":1,"status":"active","case":{"title":"case-a"}}', encoding="utf-8")
        before = ledger.read_bytes()
        set_mode(True, self.config)
        result = session_hook.context_for({"cwd": str(self.home)}, self.config)
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("case-a", result["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(before, ledger.read_bytes())
        set_mode(False, self.config)
        self.assertIsNone(session_hook.context_for({}, self.config))

    def test_hook_finds_case_from_project_subdirectory(self):
        (self.home / ".git").mkdir()
        nested = self.home / "src" / "model"
        nested.mkdir(parents=True)
        folder = self.home / ".debug-agent" / "active-case"
        folder.mkdir(parents=True)
        (folder / "state.json").write_text('{"schema":1,"status":"active","case":{"title":"active"}}', encoding="utf-8")
        set_mode(True, self.config)
        result = session_hook.context_for({"cwd": str(nested)}, self.config)
        self.assertIn("active-case", result["hookSpecificOutput"]["additionalContext"])

    def test_hook_does_not_hide_active_case_behind_ten_closed_cases(self):
        for name, status in [(f"a{i:02}", "closed") for i in range(10)] + [("z-active", "active")]:
            folder = self.home / ".debug-agent" / name
            folder.mkdir(parents=True)
            (folder / "state.json").write_text(json.dumps({"schema": 1, "status": status, "case": {"title": name}}), encoding="utf-8")
        set_mode(True, self.config)
        result = session_hook.context_for({"cwd": str(self.home)}, self.config)
        self.assertIn("z-active", result["hookSpecificOutput"]["additionalContext"])

    def test_discovery_stops_at_nested_repo_boundary(self):
        folder = self.home / ".debug-agent" / "outer"
        folder.mkdir(parents=True)
        (folder / "state.json").write_text('{"schema":1,"status":"active","case":{}}', encoding="utf-8")
        nested = self.home / "nested"
        (nested / ".git").mkdir(parents=True)
        self.assertEqual(discover(nested)["active"], [])

    def test_corrupt_case_does_not_hide_healthy_case(self):
        for name, contents in (("broken", "not JSON"), ("healthy", '{"schema":1,"status":"active","case":{}}')):
            folder = self.home / ".debug-agent" / name
            folder.mkdir(parents=True)
            (folder / "state.json").write_text(contents, encoding="utf-8")
        result = discover(self.home)
        self.assertEqual(len(result["active"]), 1)
        self.assertEqual(len(result["errors"]), 1)

    def test_recovery_preserves_job_and_unaccepted_result_read_only(self):
        data = state()
        data["rev"] = 4
        data["task"] = {
            "T1": {"id": "T1", "status": "running", "run": {"host": "test-host", "job_id": "job-42", "command": "do-not-execute"}},
            "T2": {"id": "T2", "status": "submitted", "result": {"summary": "already finished", "evidence": ["E1"]}}}
        before = json.dumps(data, sort_keys=True)
        result = snapshot(data)
        self.assertEqual(result["tasks"]["running"][0]["run"]["job_id"], "job-42")
        self.assertEqual(result["tasks"]["submitted"][0]["result"]["evidence"], ["E1"])
        self.assertEqual(result["job_execution"], "none; read-only snapshot")
        self.assertEqual(before, json.dumps(data, sort_keys=True))
        self.assertTrue(any("不重跑" in warning for warning in result["warnings"]))

    def test_recovery_detects_stale_checkpoint_and_invalidated_baseline(self):
        data = state()
        data["rev"] = 8
        data["checkpoint"] = {"current": {"baseline": "S1", "updated_at": "2026-01-01T00:00:00+00:00", "next_action": "old action"}}
        data["scenario"] = {"S1": {"reproduction": "different", "updated_at": "2026-01-02T00:00:00+00:00"}}
        result = snapshot(data)
        self.assertTrue(any("记录变化" in warning for warning in result["warnings"]))
        self.assertTrue(any("基线" in warning for warning in result["warnings"]))

    def test_preferences_preserve_unrelated_settings(self):
        self.config.write_text('{"always_on":false,"theme":"plain"}', encoding="utf-8")
        set_mode(True, self.config)
        self.assertEqual(read_config(self.config), {"always_on": True, "theme": "plain"})

    def test_invalid_preference_not_enabled(self):
        self.config.write_text('{"always_on":"false"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            read_config(self.config)

    def test_empty_case_has_no_fake_progress(self):
        output = render(state())
        self.assertNotIn("█", output)
        self.assertIn("尚无已登记任务", output)

    def test_progress_is_from_tasks_not_hypotheses(self):
        data = state()
        data["task"] = {"T1": {"id": "T1", "question": "缩减", "status": "done"},
                        "T2": {"id": "T2", "question": "对照", "status": "running"}}
        data["hypothesis"] = {"H1": {"id": "H1", "claim": "候选", "status": "open"}}
        output = render(data)
        self.assertIn("1/2", output)
        self.assertIn("待核查", output)
        self.assertIn("非定位完成度", output)

    def test_blocked_closure_never_reported_as_success(self):
        data = state()
        data.update(status="closed", closure={"outcome": "blocked", "conclusion": "缺少环境", "scope": "局部", "limitations": "待续"})
        output = render(data, "done")
        self.assertIn("受阻待续", output)
        self.assertNotIn("根因已确认", output)
        self.assertNotIn("修复已验证", output)

    def test_small_scene_closure_keeps_scope_and_limits(self):
        data = state()
        data["closure"] = {"outcome": "root_cause", "route": "evidence_chain", "scope": "64 卡", "limitations": "4096 卡未验证", "conclusion": "原因已定位", "evidence": ["E1"]}
        output = render(data, "done")
        self.assertIn("根因已确认", output)
        self.assertIn("64 卡", output)
        self.assertIn("4096 卡未验证", output)

    def test_card_preserves_full_critical_limits(self):
        data = state()
        limitations = "已有观察仅覆盖局部场景；" * 12 + "4096 卡未验证，不证明原场景已修复。"
        data["closure"] = {"outcome": "root_cause", "scope": "64 卡", "limitations": limitations, "conclusion": "局部确认"}
        self.assertIn(limitations, render(data, "done"))

    def test_cjk_table_width_and_control_characters(self):
        output = table([("状态", "中文边界 e\u0301"), ("数据", "x\n\x1by")], (6, 16))
        self.assertEqual(len({width(line) for line in output.splitlines()}), 1)
        self.assertNotIn("\x1b", output)

    def test_codex_install_updates_with_backup_only_when_requested(self):
        destination, backup = install("codex", self.home)
        self.assertIsNone(backup)
        skill = destination / "SKILL.md"
        skill.write_text("local customization", encoding="utf-8")
        with self.assertRaises(ValueError):
            install("codex", self.home)
        self.assertEqual(skill.read_text(), "local customization")
        destination, backup = install("codex", self.home, True)
        self.assertEqual((backup / "SKILL.md").read_text(), "local customization")
        self.assertIn("debug-agent", skill.read_text(encoding="utf-8"))

    def test_alias_has_real_path_and_no_hook_side_effect(self):
        destination, _ = install("claude-alias", self.home)
        alias = (destination / "debug-agent.md").read_text(encoding="utf-8")
        self.assertIn((ROOT / "skills/debug-agent/SKILL.md").as_posix(), alias)
        self.assertIn("$ARGUMENTS", alias)
        self.assertFalse((self.home / ".claude/settings.json").exists())

    def test_interrupted_update_restores_previous_files(self):
        destination, _ = install("codex", self.home)
        first = destination / "SKILL.md"
        second = destination / "references" / "tasks.md"
        first.write_bytes(b"old skill")
        second.write_bytes(b"old tasks")
        before = {p.relative_to(destination): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
        original = installer.replace_file
        failed = False

        def fail_once(path, value):
            nonlocal failed
            if path == second and not failed:
                failed = True
                raise OSError("simulated disk failure")
            return original(path, value)

        with patch.object(installer, "replace_file", fail_once):
            with self.assertRaises(OSError):
                install("codex", self.home, True)
        after = {p.relative_to(destination): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)

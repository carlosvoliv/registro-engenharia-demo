import datetime as dt
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from manuel.config import load
from manuel.rules import Validator


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DatasetTests(unittest.TestCase):
    def test_four_items_pass_structural_gate(self):
        policy, workflows, config_errors = load(ROOT / "config")
        self.assertFalse(config_errors)
        validator = Validator(ROOT, policy, workflows, dt.date(2026, 11, 13))
        self.assertEqual(len(validator.all_items("WORKTREE")), 4)
        self.assertEqual([issue for issue in validator.check_all() if not issue.warning], [])

    def test_released_defect_declares_unknown_and_exception(self):
        policy, workflows, _ = load(ROOT / "config")
        items = Validator(ROOT, policy, workflows, dt.date(2026, 11, 13)).all_items("WORKTREE")
        defect = items["DEF-2026-021"][1]
        self.assertEqual(defect["state"], "released")
        self.assertEqual(defect["exceptions"][0]["follow_up"], "TECH-2026-005")
        self.assertIn("unknown", {entry["status"] for entry in defect["evidence"]})

    def test_historical_approvals_follow_item_creation(self):
        policy, workflows, _ = load(ROOT / "config")
        items = Validator(ROOT, policy, workflows, dt.date(2026, 11, 13)).all_items("WORKTREE")
        for line in (ROOT / "registro/aprovacoes.jsonl").read_text().splitlines():
            approval = json.loads(line)
            created = dt.date.fromisoformat(str(items[approval["item"]][1]["lifecycle"]["createdAt"]))
            approved = dt.date.fromisoformat(approval["date"])
            self.assertGreaterEqual(approved, created, approval["item"])


if __name__ == "__main__":
    unittest.main()

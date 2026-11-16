import datetime as dt
import json
import pathlib
import subprocess
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from manuel.config import load
from manuel.rules import Validator, load_item
from manuel.views import collect


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


def shallow(repo: pathlib.Path) -> bool:
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "--is-shallow-repository"], capture_output=True, text=True).stdout.strip()
    return out == "true"


class SimulatedHistoryTests(unittest.TestCase):
    """O histórico dos itens é simulado (datas fictícias); estes testes o mantêm coerente."""

    def setUp(self):
        if shallow(ROOT):
            self.skipTest("clone raso: sem histórico para conferir")

    def test_every_item_walks_only_valid_workflow_transitions(self):
        policy, workflows, _ = load(ROOT / "config")
        validator = Validator(ROOT, policy, workflows, dt.date(2026, 11, 13))
        for path, item in ((p, i) for p, i in validator.all_items("WORKTREE").values()):
            workflow = workflows[item["workflow"]["id"]]
            allowed = {(e["from"], e["to"]) for e in workflow["transitions"]}
            commits = subprocess.run(["git", "-C", str(ROOT), "log", "--reverse", "--format=%H", "--", path], capture_output=True, text=True).stdout.split()
            states: list[str] = []
            for sha in commits:
                state = load_item(ROOT, sha, path)["state"]
                if not states or states[-1] != state:
                    states.append(state)
            self.assertEqual(states[0], "draft", item["id"])
            self.assertEqual(states[-1], item["state"], item["id"])
            for before, after in zip(states, states[1:]):
                blocked_in = after == "blocked" and before in workflow["blockable_from"]
                self.assertTrue((before, after) in allowed or blocked_in, f"{item['id']}: {before} -> {after}")

    def test_state_ages_on_the_presentation_day(self):
        model = collect(ROOT, "HEAD", dt.date(2026, 11, 18))
        ages = {i["id"]: (i["since"], i["age"]) for i in model["items"]}
        self.assertEqual(ages, {
            "FEAT-2026-012": ("2026-11-09", 9), "FEAT-2026-014": ("2026-11-10", 8),
            "DEF-2026-021": ("2026-11-10", 8), "TECH-2026-005": ("2026-11-13", 5),
        })

    def test_history_is_marked_as_simulated(self):
        subjects = subprocess.run(["git", "-C", str(ROOT), "log", "--format=%s", "--", "projetos"], capture_output=True, text=True).stdout.splitlines()
        simulated = [s for s in subjects if s.startswith("chore(dados-simulados)")]
        self.assertGreaterEqual(len(simulated), 10)


if __name__ == "__main__":
    unittest.main()

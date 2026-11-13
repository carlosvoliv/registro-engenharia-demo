from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from helpers import PATH, ROOT, Repo, fixture, review, write_item

CLI = ROOT / "scripts" / "manuel_gate.py"


class CliCheckTests(unittest.TestCase):
    """O subcomando `check` de ponta a ponta, como o workflow o chama (processo real, flags reais)."""

    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)

    def head_state(self, state: str) -> str:
        item = copy.deepcopy(self.repo.item)
        item["state"] = state
        return self.repo.head(item)

    def run_check(self, head: str, reviews: list | None = None, *extra: str, author: str = "ana-demo", sha: str | None = None, base: str | None = None):
        reviews_file = Path(self.scratch.name) / "reviews.json"
        reviews_file.write_text(json.dumps(reviews or []))
        args = [
            sys.executable, str(CLI), "check", "--repo", str(self.repo.path), "--base", base or self.repo.base,
            "--head", head, "--reviews", str(reviews_file), "--pr-author", author, "--today", "2026-11-13",
        ]
        args += ["--head-sha", sha or head]
        return subprocess.run(args + list(extra), capture_output=True, text=True)

    def test_exit_1_with_code_when_the_review_is_missing(self):
        done = self.run_check(self.head_state("planned"))
        self.assertEqual(done.returncode, 1)
        self.assertIn("MG-020", done.stdout)
        self.assertIn("Resumo: 1 erro(s)", done.stdout)
        self.assertEqual(done.stderr, "")

    def test_exit_0_with_review_on_the_exact_sha(self):
        head = self.head_state("planned")
        done = self.run_check(head, [review("eva-demo", head)])
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("Resumo: 0 erro(s), 0 aviso(s)", done.stdout)

    def test_head_sha_flag_decides_which_review_counts(self):
        head = self.head_state("planned")
        stale = self.run_check(head, [review("eva-demo", self.repo.base)])
        self.assertEqual(stale.returncode, 1)
        self.assertIn("MG-021", stale.stdout)
        forced = self.run_check(head, [review("eva-demo", self.repo.base)], sha=self.repo.base)
        self.assertEqual(forced.returncode, 0, forced.stdout)

    def test_head_sha_defaults_to_the_resolved_head(self):
        head = self.head_state("planned")
        done = subprocess.run([
            sys.executable, str(CLI), "check", "--repo", str(self.repo.path), "--base", self.repo.base, "--head", "HEAD",
            "--reviews", str(self._reviews([review("eva-demo", head)])), "--pr-author", "ana-demo", "--today", "2026-11-13",
        ], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout)

    def _reviews(self, reviews: list) -> Path:
        path = Path(self.scratch.name) / "reviews.json"
        path.write_text(json.dumps(reviews))
        return path

    def test_config_dir_makes_the_base_policy_win_over_the_pr(self):
        trusted = Path(self.scratch.name) / "trusted"
        shutil.copytree(self.repo.path / "config", trusted)
        policy_path = self.repo.path / "config/policy.yml"
        policy = yaml.safe_load(policy_path.read_text())
        policy["approvers"]["platform"] = ["malicious-demo"]
        policy_path.write_text(yaml.safe_dump(policy))
        head = self.repo.head()
        forged = self.run_check(head, [review("malicious-demo", head)], "--config-dir", str(trusted))
        self.assertEqual(forged.returncode, 1)
        self.assertIn("MG-090", forged.stdout)
        genuine = self.run_check(head, [review("kadu-demo", head)], "--config-dir", str(trusted))
        self.assertEqual(genuine.returncode, 0, genuine.stdout)

    def test_today_flag_controls_exception_expiry(self):
        item = copy.deepcopy(self.repo.item)
        item["exceptions"] = [{"id": "EXC-2026-001", "waives": ["RF-001"], "reason": "adiado", "requested_by": "ana", "expires": "2026-11-30", "follow_up": item["id"]}]
        self.repo.base = self.repo.head(item)
        item = copy.deepcopy(item)
        item["title"] = "Assinatura digital fictícia (título ajustado)"
        head = self.repo.head(item)
        self.assertEqual(self.run_check(head).returncode, 0)
        late = self.run_check(head, None, "--today", "2026-12-31")
        self.assertEqual(late.returncode, 1)
        self.assertIn("MG-062", late.stdout)

    def test_github_format_annotates_with_the_code(self):
        done = self.run_check(self.head_state("planned"), None, "--format", "github")
        self.assertEqual(done.returncode, 1)
        self.assertIn("::error file=", done.stdout)
        self.assertIn("title=MG-020", done.stdout)

    def test_exit_2_for_unusable_input(self):
        head = self.head_state("planned")
        missing = subprocess.run([
            sys.executable, str(CLI), "check", "--repo", str(self.repo.path), "--base", self.repo.base, "--head", head,
            "--reviews", str(Path(self.scratch.name) / "nao-existe.json"), "--pr-author", "ana-demo",
        ], capture_output=True, text=True)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("Uso incorreto", missing.stderr)
        self.assertNotIn("Traceback", missing.stderr)
        unknown_rev = self.run_check("rev-que-nao-existe")
        self.assertEqual(unknown_rev.returncode, 2)
        self.assertNotIn("Traceback", unknown_rev.stderr)

    def test_data_errors_are_violations_without_traceback(self):
        item = fixture("planned")
        item["ownership"] = []
        head = self.repo.head(item)
        done = self.run_check(head)
        self.assertEqual(done.returncode, 1)
        self.assertIn("MG-002", done.stdout)
        self.assertNotIn("Traceback", done.stderr)
        # data com hora: o YAML lê um datetime
        item = fixture("awaiting-approval")
        item["exceptions"] = [{"id": "EXC-2026-001", "waives": ["RF-001"], "reason": "adiado", "requested_by": "ana", "expires": "2026-12-30T10:00:00", "follow_up": item["id"]}]
        write_item(self.repo.path, item)
        path = self.repo.path / PATH
        path.write_text(path.read_text().replace("'2026-12-30T10:00:00'", "2026-12-30T10:00:00"))
        head = self.repo.commit("data com hora")
        done = self.run_check(head)
        self.assertEqual(done.returncode, 1)
        self.assertIn("MG-060", done.stdout)
        self.assertNotIn("Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()

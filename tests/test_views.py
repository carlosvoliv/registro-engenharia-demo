from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import manuel_view
from manuel.views import collect, render_html, render_markdown, state_since
from helpers import PATH, ROOT, command, fixture, write, write_item

TODAY = dt.date(2026, 11, 18)


class DatedRepo:
    """Repo temporário com histórico de datas controladas, para testar a idade na etapa."""

    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        command(self.path, "init", "-b", "main")
        command(self.path, "config", "user.name", "Pessoa Teste")
        command(self.path, "config", "user.email", "pessoa.teste@example.invalid")
        shutil.copytree(ROOT / "config", self.path / "config")

    def commit(self, message: str, day: str) -> str:
        stamp = f"{day}T12:00:00+00:00"
        env = {**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
        command(self.path, "add", "-A")
        run = subprocess.run(["git", "-C", str(self.path), "commit", "-m", message], capture_output=True, text=True, env=env)
        assert run.returncode == 0, run.stderr
        return command(self.path, "rev-parse", "HEAD")

    def state(self, state: str, day: str, **changes) -> str:
        item = fixture(state)
        item.update(changes)
        write_item(self.path, item)
        return self.commit(f"estado {state}", day)

    def close(self) -> None:
        self.temp.cleanup()


class StateAgeTests(unittest.TestCase):
    def setUp(self):
        self.repo = DatedRepo()
        self.addCleanup(self.repo.close)

    def test_age_counts_from_the_commit_that_entered_the_current_state(self):
        self.repo.state("planned", "2026-11-01")
        self.repo.state("awaiting-approval", "2026-11-09")
        self.repo.state("awaiting-approval", "2026-11-12", title="Título ajustado")
        self.assertEqual(state_since(self.repo.path, "HEAD", PATH, "awaiting-approval"), dt.date(2026, 11, 9))
        item = collect(self.repo.path, "HEAD", TODAY)["items"][0]
        self.assertEqual((item["since"], item["age"]), ("2026-11-09", 9))

    def test_returning_to_a_previous_state_restarts_the_count(self):
        self.repo.state("awaiting-approval", "2026-11-02")
        self.repo.state("planned", "2026-11-05")
        self.repo.state("awaiting-approval", "2026-11-10")
        self.assertEqual(collect(self.repo.path, "HEAD", TODAY)["items"][0]["age"], 8)

    def test_state_in_the_future_never_gives_a_negative_age(self):
        self.repo.state("planned", "2026-12-01")
        self.assertEqual(collect(self.repo.path, "HEAD", TODAY)["items"][0]["age"], 0)

    def test_output_is_deterministic_for_the_same_input(self):
        self.repo.state("awaiting-approval", "2026-11-09")
        model = collect(self.repo.path, "HEAD", TODAY)
        out_dir = self.repo.path / "views"
        self.assertEqual(render_markdown(model), render_markdown(collect(self.repo.path, "HEAD", TODAY)))
        self.assertEqual(render_html(model, out_dir, self.repo.path), render_html(collect(self.repo.path, "HEAD", TODAY), out_dir, self.repo.path))


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.repo = DatedRepo()
        self.addCleanup(self.repo.close)

    def test_text_from_the_registry_is_escaped_in_html(self):
        self.repo.state("planned", "2026-11-09", title="<script>alert(1)</script> & <img src=x onerror=alert(2)>")
        model = collect(self.repo.path, "HEAD", TODAY)
        page = render_html(model, self.repo.path / "views", self.repo.path)
        self.assertNotIn("<script>alert(1)", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;img", page)

    def test_views_do_not_expose_commit_authors_or_forbidden_metrics(self):
        self.repo.state("planned", "2026-11-09")
        model = collect(self.repo.path, "HEAD", TODAY)
        text = render_html(model, self.repo.path / "views", self.repo.path) + render_markdown(model)
        for leaked in ("Pessoa Teste", "pessoa.teste@example.invalid"):
            self.assertNotIn(leaked, text)
        for metric in model["metrics_forbidden"]:
            self.assertNotIn(metric, text)
        self.assertNotIn("commits", text.lower())

    def test_unreadable_item_is_reported_without_breaking_the_view(self):
        self.repo.state("planned", "2026-11-09")
        write(self.repo.path, "projetos/api-contratos/calculo/DEF-2026-099/item.yml", "id: [aberto\n")
        self.repo.commit("quebrado", "2026-11-10")
        model = collect(self.repo.path, "HEAD", TODAY)
        self.assertEqual([i["id"] for i in model["items"]], ["FEAT-2026-012"])
        self.assertEqual([p["path"] for p in model["problems"]], ["projetos/api-contratos/calculo/DEF-2026-099/item.yml"])
        self.assertIn("Problemas", render_markdown(model))

    def test_wrong_types_in_an_item_do_not_crash_the_view(self):
        item = fixture("awaiting-approval")
        item.update(ownership=[], evidence="x", exceptions={"a": 1}, artifacts=[7, {"path": ["a"], "ai_use": "x"}], requirements=[None, {"id": ["x"]}], relations=[{"type": ["a"]}, 3], blocked_by="FEAT-1")
        write_item(self.repo.path, item)
        self.repo.commit("tipos errados", "2026-11-09")
        model = collect(self.repo.path, "HEAD", TODAY)
        render_markdown(model)
        render_html(model, self.repo.path / "views", self.repo.path)

    def test_html_links_resolve_from_the_output_folder(self):
        write_item(self.repo.path, fixture("planned"))
        self.repo.commit("item", "2026-11-09")
        out_dir = self.repo.path / "views"
        out_dir.mkdir()
        page = render_html(collect(self.repo.path, "HEAD", TODAY), out_dir, self.repo.path)
        self.assertIn(f'href="../{PATH}"', page)
        self.assertTrue((out_dir / f"../{PATH}").resolve().is_file())


class DatasetViewTests(unittest.TestCase):
    """O dataset real: o que a visão executiva precisa mostrar para as perguntas ensaiadas."""

    @classmethod
    def setUpClass(cls):
        cls.model = collect(ROOT, "HEAD", TODAY)
        cls.items = {i["id"]: i for i in cls.model["items"]}

    def test_four_items_without_problems(self):
        self.assertEqual(sorted(self.items), ["DEF-2026-021", "FEAT-2026-012", "FEAT-2026-014", "TECH-2026-005"])
        self.assertEqual(self.model["problems"], [])

    def test_feature_waits_for_the_security_design_gate_and_blocks_the_statement(self):
        item = self.items["FEAT-2026-012"]
        self.assertEqual(item["gate"], {"gate": "design", "roles": ["security"], "people": ["Eva"]})
        self.assertIn("FEAT-2026-014", item["blocks"])
        self.assertEqual([b["id"] for b in self.items["FEAT-2026-014"]["blockers"]], ["FEAT-2026-012"])
        self.assertEqual(self.items["FEAT-2026-014"]["blockers"][0]["state"], "awaiting-approval")

    def test_defect_promised_versus_delivered_with_approved_exception(self):
        item = self.items["DEF-2026-021"]
        self.assertEqual({c["id"]: c["status"] for c in item["coverage"]}, {"RF-001": "verificado", "RF-002": "verificado", "RF-003": "verificado", "RNF-001": "exceção"})
        exception = item["exceptions"][0]
        self.assertEqual((exception["id"], exception["follow_up"], exception["days_left"]), ("EXC-2026-001", "TECH-2026-005", 12))
        self.assertEqual([(a["persona"], a["role"]) for a in exception["approvals"]], [("carla", "tech-lead")])
        self.assertIn("3 de 3 funcionais verificados", render_markdown(self.model))

    def test_index_cites_the_files_the_agent_must_open(self):
        text = render_markdown(self.model)
        for item in self.model["items"]:
            self.assertIn(f"`{item['path']}`", text)
        self.assertIn("registro/aprovacoes.jsonl", text)


class CliTests(unittest.TestCase):
    def test_generates_both_files_and_rejects_a_bad_date(self):
        repo = DatedRepo()
        self.addCleanup(repo.close)
        repo.state("planned", "2026-11-09")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(manuel_view.main(["--repo", str(repo.path), "--today", "2026-11-18"]), 0)
            self.assertEqual(manuel_view.main(["--repo", str(repo.path), "--today", "ontem"]), 2)
            self.assertEqual(manuel_view.main(["--repo", str(repo.path / "nao-existe")]), 2)
        self.assertTrue((repo.path / "views/executiva.html").is_file())
        self.assertTrue((repo.path / "views/INDEX.md").is_file())


if __name__ == "__main__":
    unittest.main()

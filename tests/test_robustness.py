from __future__ import annotations

import contextlib
import copy
import datetime as dt
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import manuel_gate
from manuel.config import load
from manuel.rules import Validator, load_item
from helpers import PATH, ROOT, Repo, fixture, review, write, write_item

WRONG = [None, "x", 7, dt.datetime(2026, 12, 30, 10, 0), [[]], {"a": []}]


def rich_item(state: str) -> dict:
    item = fixture(state)
    item["evidence"] = [
        {"claim": "visto", "status": "observed", "source": "artefatos/20-design.md", "requirement": "RF-001"},
        {"claim": "confirmado", "status": "confirmed", "source": "artefatos/20-design.md", "by": "carla", "date": "2026-11-10"},
        {"claim": "ignorado", "status": "unknown", "owner": "ana", "due": "2026-12-01"},
    ]
    item["exceptions"] = [{"id": "EXC-2026-001", "waives": ["RF-001"], "reason": "adiado", "requested_by": "ana", "expires": "2026-11-30", "follow_up": item["id"]}]
    if state == "blocked":
        item["blocked_from"] = "awaiting-approval"
        item["blocked_by"] = [item["id"]]
    return item


def locations(node: object, prefix: tuple = ()):
    """Todo caminho até um nó do documento (exceto a raiz)."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield prefix + (key,)
            yield from locations(value, prefix + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield prefix + (index,)
            yield from locations(value, prefix + (index,))


def replace(item: dict, location: tuple, value: object) -> dict:
    result = copy.deepcopy(item)
    holder = result
    for step in location[:-1]:
        holder = holder[step]
    holder[location[-1]] = value
    return result


class DataErrorTests(unittest.TestCase):
    """Erro de dados vira violação com código MG; nunca exceção nem traceback."""

    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)
        self.policy, self.workflows, _ = load(self.repo.path / "config")

    def check(self, head: str, reviews: list[dict] | None = None, author: str = "ana-demo", *, base: str | None = None) -> list:
        engine = Validator(self.repo.path, self.policy, self.workflows, dt.date(2026, 11, 13))
        engine.check(base or self.repo.base, head, reviews or [], author, head)
        return engine.result()

    def codes(self, head: str, reviews: list[dict] | None = None) -> set[str]:
        return {issue.code for issue in self.check(head, reviews) if not issue.warning}

    def test_MG002_ownership_with_wrong_type_is_a_violation(self):
        for bad in ([], "ana", 7, {"owner": "ana", "approvers": []}, {"owner": "ana", "approvers": {"design": "security"}}, {"owner": "ana", "approvers": {"design": [7]}}):
            item = fixture("planned")
            item["ownership"] = bad
            with self.subTest(ownership=bad):
                head = self.repo.head(item)
                self.assertIn("MG-002", self.codes(head, [review("eva-demo", head)]))

    def test_restriction_with_wrong_type_fails_closed(self):
        item = fixture("planned")
        item["ownership"]["approvers"] = {"design": "security"}
        head = self.repo.head(item)
        self.assertIn("MG-024", self.codes(head, [review("eva-demo", head)]))

    def test_MG060_expires_with_time_is_a_violation(self):
        item = copy.deepcopy(self.repo.item)
        item["exceptions"] = [{"id": "EXC-2026-001", "waives": ["RF-001"], "reason": "adiado", "requested_by": "ana", "expires": "2026-12-30T10:00:00", "follow_up": item["id"]}]
        write_item(self.repo.path, item)
        raw = (self.repo.path / PATH).read_text()
        self.assertIn("'2026-12-30T10:00:00'", raw)
        # Sem aspas, o YAML lê um datetime: era o TypeError da revisão.
        (self.repo.path / PATH).write_text(raw.replace("'2026-12-30T10:00:00'", "2026-12-30T10:00:00"))
        self.assertIsInstance(load_item(self.repo.path, "WORKTREE", PATH)["exceptions"][0]["expires"], dt.datetime)
        head = self.repo.commit("head")
        self.assertIn("MG-060", self.codes(head))

    def test_MG050_and_MG002_dates_with_time_are_rejected(self):
        item = rich_item("awaiting-approval")
        item["evidence"][1]["date"] = dt.datetime(2026, 11, 10, 9, 0)
        item["lifecycle"]["createdAt"] = dt.datetime(2026, 10, 27, 9, 0)
        head = self.repo.head(item)
        self.assertTrue({"MG-050", "MG-002"} <= self.codes(head))

    def test_MG002_yaml_alias_is_rejected(self):
        raw = (self.repo.path / PATH).read_text().replace("title: Assinatura digital fictícia", "title: &t Assinatura digital fictícia\nsubtitle: *t")
        self.assertIn("*t", raw)
        (self.repo.path / PATH).write_text(raw)
        head = self.repo.commit("head")
        issues = self.check(head)
        self.assertTrue(any(i.code == "MG-002" and "alias" in i.message for i in issues))
        self.assertFalse(any(i.code == "MG-003" for i in issues), "item ilegível não é item removido")

    def test_MG002_oversized_and_unreadable_yaml(self):
        (self.repo.path / PATH).write_text("title: " + "x" * (257 * 1024) + "\n")
        self.assertTrue(any(i.code == "MG-002" and "KB" in i.message for i in self.check(self.repo.commit("grande"))))
        (self.repo.path / PATH).write_text("id: [aberto\n")
        self.assertTrue(any(i.code == "MG-002" and "ilegível" in i.message for i in self.check(self.repo.commit("quebrado"))))
        (self.repo.path / PATH).write_text("- só\n- lista\n")
        self.assertTrue(any(i.code == "MG-002" for i in self.check(self.repo.commit("lista"))))

    def test_no_wrong_type_anywhere_in_the_item_crashes_the_validator(self):
        # Cada nó do item (planned) recebe cada valor de tipo errado; o `blocked_*` só vale no estado blocked.
        for state, only in (("planned", None), ("blocked", ("blocked_from", "blocked_by"))):
            item = rich_item(state)
            for location in locations(item):
                if only and location[0] not in only:
                    continue
                for bad in WRONG:
                    write_item(self.repo.path, replace(item, location, bad))
                    with self.subTest(state=state, location=location, value=bad):
                        try:
                            self.check("WORKTREE")
                        except Exception as exc:  # noqa: BLE001
                            self.fail(f"{type(exc).__name__}: {exc}")

    def test_no_wrong_type_in_the_base_item_crashes_the_validator(self):
        item = rich_item("planned")
        top_level = [location for location in locations(item) if len(location) == 1] + [("exceptions", 0, "id"), ("exceptions", 0, "waives", 0)]
        for location in top_level:
            for bad in (None, "x", [[]]):
                write_item(self.repo.path, replace(item, location, bad))
                base = self.repo.commit("base mutada")
                write_item(self.repo.path, rich_item("implementing"))
                with self.subTest(location=location, value=bad):
                    try:
                        self.check("WORKTREE", base=base)
                    except Exception as exc:  # noqa: BLE001
                        self.fail(f"{type(exc).__name__}: {exc}")


class CliExitCodeTests(unittest.TestCase):
    def test_internal_error_exits_2_without_traceback(self):
        err = io.StringIO()
        with mock.patch.object(manuel_gate.Validator, "check_all", side_effect=RuntimeError("falha simulada")):
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = manuel_gate.main(["check-all", "--repo", str(ROOT)])
        self.assertEqual(code, 2)
        self.assertIn("erro interno do validador: RuntimeError: falha simulada", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_github_annotation_escapes_properties_and_message(self):
        issue = manuel_gate.Issue("MG-030", "FEAT-1", "100% ruim\nlinha dois", "projetos/a,b:c/item.yml")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            manuel_gate.report([issue], "github")
        first = out.getvalue().splitlines()[0]
        self.assertEqual(first, "::error file=projetos/a%2Cb%3Ac/item.yml,title=MG-030::100%25 ruim%0Alinha dois")

    def test_violation_exits_1_and_clean_exits_0(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(manuel_gate.main(["check-all", "--repo", str(ROOT)]), 0)


if __name__ == "__main__":
    unittest.main()

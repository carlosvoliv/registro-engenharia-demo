from __future__ import annotations

import copy
import datetime as dt
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from manuel.config import load
from manuel.rules import Validator
from helpers import PATH, PREFIX, ROOT, Repo, fixture, review, write, write_item


class GateTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    def validate(self, head: str, reviews: list[dict] | None = None, author: str = "ana-demo", *, config_dir: Path | None = None, today: str = "2026-11-13") -> set[str]:
        policy, workflows, errors = load(config_dir or self.repo.path / "config")
        engine = Validator(self.repo.path, policy, workflows, dt.date.fromisoformat(today))
        for error in errors:
            engine.add("MG-080", "CONFIG", error)
        engine.check(self.repo.base, head, reviews or [], author, head)
        return {issue.code for issue in engine.result() if not issue.warning}

    def head_state(self, state: str) -> str:
        item = copy.deepcopy(self.repo.item)
        item["state"] = state
        return self.repo.head(item)

    def test_S1_missing_review(self):
        self.assertIn("MG-020", self.validate(self.head_state("planned")))

    def test_S2_skip_state(self):
        self.assertIn("MG-010", self.validate(self.head_state("implementing")))

    def test_S3_approved(self):
        head = self.head_state("planned")
        self.assertEqual(self.validate(head, [review("eva-demo", head)]), set())

    def test_S4_old_commit(self):
        head = self.head_state("planned")
        self.assertIn("MG-021", self.validate(head, [review("eva-demo", self.repo.base)]))

    def test_S5_self_approval(self):
        head = self.head_state("planned")
        self.assertIn("MG-022", self.validate(head, [review("eva-demo", head)], "eva-demo"))

    def test_S6_wrong_role(self):
        head = self.head_state("planned")
        self.assertIn("MG-023", self.validate(head, [review("bruno-demo", head)]))

    def test_S7_placeholder(self):
        policy_path = self.repo.path / "config/policy.yml"
        policy = yaml.safe_load(policy_path.read_text())
        policy["approvers"]["security"] = ["<GITHUB_DO_COLEGA>"]
        policy_path.write_text(yaml.safe_dump(policy))
        head = self.head_state("planned")
        self.assertIn("MG-024", self.validate(head, [review("eva-demo", head)]))

    def test_S8_changes_requested_after_approval(self):
        head = self.head_state("planned")
        reviews = [review("eva-demo", head), review("eva-demo", head, "CHANGES_REQUESTED", 2, "2026-11-13T13:00:00Z")]
        self.assertIn("MG-025", self.validate(head, reviews))

    def test_S9_comment_does_not_drop_approval(self):
        head = self.head_state("planned")
        reviews = [review("eva-demo", head), review("eva-demo", head, "COMMENTED", 2, "2026-11-13T13:00:00Z")]
        self.assertEqual(self.validate(head, reviews), set())

    def test_S10_case_insensitive_login(self):
        head = self.head_state("planned")
        self.assertEqual(self.validate(head, [review("Eva-Demo", head)]), set())

    def test_review_slurp_and_dismissed(self):
        from manuel.reviews import load_reviews
        path = self.repo.path / "reviews.json"
        path.write_text(json.dumps([[review("eva-demo", "old")], [review("eva-demo", "new", "DISMISSED", 2)]]))
        self.assertEqual(len(load_reviews(path)), 2)
        head = self.head_state("planned")
        self.assertIn("MG-025", self.validate(head, load_reviews(path)))

    def test_MG001_path_id_mismatch_and_valid_path(self):
        item = copy.deepcopy(self.repo.item)
        item["id"] = "FEAT-2026-999"
        head = self.repo.head(item)
        self.assertIn("MG-001", self.validate(head))
        self.assertNotIn("MG-001", self.validate(self.repo.base))

    def test_MG001_item_outside_projects(self):
        item = fixture("draft")
        write_item(self.repo.path, item, "outros/FEAT-2026-012/item.yml")
        head = self.repo.head()
        self.assertIn("MG-001", self.validate(head))

    def test_MG002_invalid_owner_and_valid_owner(self):
        item = copy.deepcopy(self.repo.item)
        item["ownership"]["owner"] = "inexistente"
        self.assertIn("MG-002", self.validate(self.repo.head(item)))
        self.assertNotIn("MG-002", self.validate(self.repo.base))

    def test_MG003_item_deleted(self):
        (self.repo.path / PATH).unlink()
        head = self.repo.head()
        self.assertIn("MG-003", self.validate(head))

    def test_MG004_immutable_and_unchanged(self):
        item = copy.deepcopy(self.repo.item)
        item["lifecycle"]["createdAt"] = "2026-11-01"
        self.assertIn("MG-004", self.validate(self.repo.head(item)))
        self.assertNotIn("MG-004", self.validate(self.repo.base))

    def test_MG005_new_item_must_start_draft(self):
        item = fixture("planned")
        item["id"] = "FEAT-2026-099"
        path = PATH.replace("FEAT-2026-012", "FEAT-2026-099")
        write_item(self.repo.path, item, path)
        for name in ("10-requisitos.md", "20-design.md"):
            write(self.repo.path, path.replace("item.yml", f"artefatos/{name}"), "# Exemplo\n\nConteúdo válido.\n")
        head = self.repo.head()
        self.assertIn("MG-005", self.validate(head))
        self.assertNotIn("MG-005", self.validate(self.repo.base))

    def test_MG011_blocked_requires_fields_and_valid_blocked(self):
        item = copy.deepcopy(self.repo.item)
        item["state"] = "blocked"
        item["blocked_from"] = "awaiting-approval"
        item["blocked_by"] = [item["id"]]
        head = self.repo.head(item)
        self.assertNotIn("MG-011", self.validate(head))
        item["blocked_by"] = []
        self.assertIn("MG-011", self.validate(self.repo.head(item)))

    @staticmethod
    def blocked(item: dict, previous: str = "awaiting-approval") -> dict:
        value = copy.deepcopy(item)
        value["state"] = "blocked"
        value["blocked_from"] = previous
        value["blocked_by"] = [value["id"]]
        return value

    def test_MG011_blocked_from_is_immutable_while_blocked(self):
        # PR1: awaiting-approval → blocked, como deve ser.
        blocked = self.blocked(self.repo.item)
        head1 = self.repo.head(blocked)
        self.assertEqual(self.validate(head1), set())
        # PR2: o item continua blocked, mas blocked_from vira implementing.
        self.repo.base = head1
        laundered = copy.deepcopy(blocked)
        laundered["blocked_from"] = "implementing"
        self.assertIn("MG-011", self.validate(self.repo.head(laundered)))
        # A saída legítima, de volta ao estado de origem, continua livre.
        self.assertEqual(self.validate(self.repo.head(fixture("awaiting-approval"))), set())

    def test_MG011_blocked_exit_must_return_to_blocked_from(self):
        self.repo.base = self.repo.head(self.blocked(self.repo.item))
        self.assertIn("MG-011", self.validate(self.repo.head(fixture("implementing"))))
        self.assertEqual(self.validate(self.repo.head(fixture("awaiting-approval"))), set())

    def test_blocked_to_cancelled_is_allowed(self):
        self.repo.base = self.repo.head(self.blocked(self.repo.item))
        head = self.repo.head(fixture("cancelled"))
        self.assertEqual(self.validate(head), set())
        stale = fixture("cancelled")
        stale["blocked_from"] = "awaiting-approval"
        self.assertIn("MG-011", self.validate(self.repo.head(stale)))

    def test_MG012_terminal_change_and_rework_allowed(self):
        item = copy.deepcopy(self.repo.item)
        item["state"] = "closed"
        self.repo.base = self.repo.head(item)
        item["state"] = "planned"
        self.assertIn("MG-012", self.validate(self.repo.head(item)))
        item["state"] = "reviewing"
        self.repo.base = self.repo.head(item)
        item["state"] = "implementing"
        self.assertNotIn("MG-010", self.validate(self.repo.head(item)))

    def test_MG030_missing_empty_placeholder_and_valid(self):
        head = self.head_state("planned")
        self.assertNotIn("MG-030", self.validate(head, [review("eva-demo", head)]))
        item = copy.deepcopy(self.repo.item)
        item["artifacts"] = [item["artifacts"][0]]
        self.assertIn("MG-030", self.validate(self.repo.head(item)))
        item["artifacts"] = fixture()["artifacts"]
        write(self.repo.path, f"{PREFIX}/artefatos/20-design.md", "   \n")
        self.assertIn("MG-030", self.validate(self.repo.head(item)))
        write(self.repo.path, f"{PREFIX}/artefatos/20-design.md", "# Design\n\n[TODO]\n")
        self.assertIn("MG-030", self.validate(self.repo.head(item)))

    def test_MG030_check_revalidates_touched_item_without_transition(self):
        write(self.repo.path, f"{PREFIX}/artefatos/10-requisitos.md", "# Requisitos\n\n[TODO]\n")
        head = self.repo.head()
        self.assertEqual(self.repo.item["state"], "awaiting-approval")
        self.assertIn("MG-030", self.validate(head))
        self.assertNotIn("MG-030", self.validate(self.repo.base))

    def test_MG051_check_revalidates_evidence_of_released_item(self):
        item = copy.deepcopy(self.repo.item)
        item["state"] = "released"
        item["artifacts"] += [
            {"path": "artefatos/30-execucao.md", "kind": "execution", "produced_by": "human"},
            {"path": "artefatos/40-relatorio.md", "kind": "test-report", "produced_by": "human"},
        ]
        item["evidence"] = [{"claim": "teste passou", "status": "observed", "source": "artefatos/40-relatorio.md", "requirement": "RF-001"}]
        for name in ("30-execucao.md", "40-relatorio.md"):
            write(self.repo.path, f"{PREFIX}/artefatos/{name}", "# Registro\n\nFeito e conferido.\n")
        self.repo.base = self.repo.head(item)
        self.assertEqual(self.validate(self.repo.base), set(), "estado de partida deve ser válido")
        stripped = copy.deepcopy(item)
        stripped["evidence"] = []
        self.assertIn("MG-051", self.validate(self.repo.head(stripped)))

    def test_legitimate_pr_adding_evidence_still_passes(self):
        item = copy.deepcopy(self.repo.item)
        item["state"] = "implementing"
        self.repo.base = self.repo.head(item)
        item = copy.deepcopy(item)
        item["evidence"] = [{"claim": "teste passou", "status": "observed", "source": "artefatos/20-design.md", "requirement": "RF-001"}]
        self.assertEqual(self.validate(self.repo.head(item)), set())

    def test_MG031_path_traversal_and_valid(self):
        item = copy.deepcopy(self.repo.item)
        item["artifacts"][0]["path"] = "artefatos/../secret.md"
        self.assertIn("MG-031", self.validate(self.repo.head(item)))
        self.assertNotIn("MG-031", self.validate(self.repo.base))

    def test_MG032_protected_artifact_review(self):
        item = copy.deepcopy(self.repo.item)
        item["state"] = "planned"
        self.repo.base = self.repo.head(item)
        write(self.repo.path, f"{PREFIX}/artefatos/20-design.md", "# Design\n\nVersão revisada.\n")
        head = self.repo.head()
        self.assertIn("MG-032", self.validate(head))
        self.assertNotIn("MG-032", self.validate(head, [review("eva-demo", head)]))

    def planned_base(self) -> dict:
        item = copy.deepcopy(self.repo.item)
        item["state"] = "planned"
        self.repo.base = self.repo.head(item)
        return item

    def test_MG032_swapping_protected_artifact_path(self):
        item = self.planned_base()
        write(self.repo.path, f"{PREFIX}/artefatos/20-design-v2.md", "# Design\n\nOutra versão, sem revisão.\n")
        item["artifacts"][1]["path"] = "artefatos/20-design-v2.md"
        head = self.repo.head(item)
        self.assertIn("MG-032", self.validate(head))
        self.assertNotIn("MG-032", self.validate(head, [review("eva-demo", head)]))

    def test_MG032_changing_the_protected_entries_of_the_artifacts_block(self):
        item = self.planned_base()
        control = copy.deepcopy(item)
        control["evidence"] = [{"claim": "teste passou", "status": "observed", "source": "artefatos/20-design.md", "requirement": "RF-001"}]
        self.assertNotIn("MG-032", self.validate(self.repo.head(control)), "mudança alheia ao bloco protegido não exige review")
        removed = copy.deepcopy(item)
        removed["artifacts"] = removed["artifacts"][:1]
        self.assertIn("MG-032", self.validate(self.repo.head(removed)))
        retyped = copy.deepcopy(item)
        retyped["artifacts"][1]["kind"] = "other"
        self.assertIn("MG-032", self.validate(self.repo.head(retyped)))
        write(self.repo.path, f"{PREFIX}/artefatos/21-design-extra.md", "# Design extra\n\nConteúdo novo.\n")
        added = copy.deepcopy(item)
        added["artifacts"].append({"path": "artefatos/21-design-extra.md", "kind": "design", "produced_by": "human"})
        head = self.repo.head(added)
        self.assertIn("MG-032", self.validate(head))
        self.assertNotIn("MG-032", self.validate(head, [review("eva-demo", head)]))

    def test_MG040_bad_ai_use_variants_and_human_allowed(self):
        for variant in (None, [], [{"schema": "manuel-ai-use/1", "tool": "x", "model": "m", "role": "drafted"}], [{"schema": "manuel-ai-use/1", "tool": "x", "model": "m", "session": "s", "role": "bad"}]):
            item = copy.deepcopy(self.repo.item)
            if variant is None:
                item["artifacts"][0].pop("ai_use")
            else:
                item["artifacts"][0]["ai_use"] = variant
            with self.subTest(variant=variant):
                self.assertIn("MG-040", self.validate(self.repo.head(item)))
        self.assertNotIn("MG-040", self.validate(self.repo.base))

    def test_MG050_evidence_unknown_and_confirmed(self):
        item = copy.deepcopy(self.repo.item)
        item["evidence"] = [{"claim": "teste", "status": "confirmed", "source": "artefatos/20-design.md"}]
        self.assertIn("MG-050", self.validate(self.repo.head(item)))
        item["evidence"] = [{"claim": "incerto", "status": "unknown"}]
        self.assertIn("MG-050", self.validate(self.repo.head(item)))
        item["evidence"] = [{"claim": "teste", "status": "confirmed", "source": "artefatos/20-design.md", "by": "carla", "date": "2026-11-13", "requirement": "RF-001"}]
        self.assertNotIn("MG-050", self.validate(self.repo.head(item)))

    def test_MG051_required_evidence_and_exception_coverage(self):
        item = copy.deepcopy(self.repo.item)
        item["state"] = "reviewing"
        self.repo.base = self.repo.head(item)
        item["state"] = "released"
        item["artifacts"].append({"path": "artefatos/40-relatorio.md", "kind": "test-report", "produced_by": "human"})
        write(self.repo.path, f"{PREFIX}/artefatos/40-relatorio.md", "# Relatório\n\nTeste feito.\n")
        head = self.repo.head(item)
        self.assertIn("MG-051", self.validate(head, [review("carla-demo", head)]))
        item["evidence"] = [{"claim": "teste passou", "status": "observed", "source": "artefatos/40-relatorio.md", "requirement": "RF-001"}]
        head = self.repo.head(item)
        self.assertNotIn("MG-051", self.validate(head, [review("carla-demo", head)]))
        item["evidence"] = [{"claim": "não testado", "status": "observed", "source": "", "requirement": "RF-001"}]
        head = self.repo.head(item)
        self.assertIn("MG-051", self.validate(head, [review("carla-demo", head)]))

    def test_MG051_requirement_covered_by_approved_exception_passes(self):
        item = copy.deepcopy(self.repo.item)
        item["state"] = "reviewing"
        self.repo.base = self.repo.head(item)
        item["state"] = "released"
        item["artifacts"].append({"path": "artefatos/40-relatorio.md", "kind": "test-report", "produced_by": "human"})
        write(self.repo.path, f"{PREFIX}/artefatos/40-relatorio.md", "# Relatório\n\nTeste adiado por exceção.\n")
        without = self.repo.head(item)
        self.assertIn("MG-051", self.validate(without, [review("carla-demo", without)]))
        item["exceptions"] = self.waiver(item["id"])
        covered = self.repo.head(item)
        codes = self.validate(covered, [review("carla-demo", covered)])
        self.assertNotIn("MG-051", codes)
        self.assertNotIn("MG-061", codes)
        # sem a aprovação da exceção, a cobertura não vale: o gate pede o review
        self.assertIn("MG-020", self.validate(covered))

    def test_MG060_061_062_063_exceptions(self):
        item = copy.deepcopy(self.repo.item)
        item["exceptions"] = [{"id": "EXC-2026-001", "waives": ["RF-001"], "reason": "Teste adiado", "requested_by": "ana", "expires": "2026-11-30", "follow_up": item["id"]}]
        head = self.repo.head(item)
        self.assertIn("MG-061", self.validate(head))
        self.assertNotIn("MG-061", self.validate(head, [review("carla-demo", head)]))
        item["exceptions"][0]["waives"] = ["RF-999"]
        self.assertIn("MG-060", self.validate(self.repo.head(item)))
        item["exceptions"][0]["waives"] = ["RF-001"]
        item["exceptions"][0]["follow_up"] = "TECH-999"
        self.assertIn("MG-063", self.validate(self.repo.head(item)))
        item["exceptions"][0]["follow_up"] = item["id"]
        item["exceptions"][0]["expires"] = "2026-11-01"
        self.assertIn("MG-062", self.validate(self.repo.head(item)))
        self.assertNotIn("MG-062", self.validate(self.repo.base))

    @staticmethod
    def waiver(follow_up: str) -> list[dict]:
        return [{"id": "EXC-2026-001", "waives": ["RF-001"], "reason": "Teste adiado", "requested_by": "ana", "expires": "2026-11-30", "follow_up": follow_up}]

    def test_MG061_exception_on_new_item_needs_approval(self):
        item = fixture("draft")
        item["id"] = "FEAT-2026-099"
        item["exceptions"] = self.waiver("FEAT-2026-012")
        path = PATH.replace("FEAT-2026-012", "FEAT-2026-099")
        write_item(self.repo.path, item, path)
        for name in ("10-requisitos.md", "20-design.md"):
            write(self.repo.path, path.replace("item.yml", f"artefatos/{name}"), "# Exemplo\n\nConteúdo válido.\n")
        head = self.repo.head()
        self.assertIn("MG-061", self.validate(head))
        self.assertIn("MG-061", self.validate(head, [review("eva-demo", head)]))
        self.assertEqual(self.validate(head, [review("carla-demo", head)]), set())

    def test_MG061_exception_on_renamed_item_needs_approval(self):
        item = copy.deepcopy(self.repo.item)
        item["id"] = "FEAT-2026-013"
        item["exceptions"] = self.waiver("FEAT-2026-013")
        shutil.move(self.repo.path / PREFIX, self.repo.path / PREFIX.replace("FEAT-2026-012", "FEAT-2026-013"))
        write_item(self.repo.path, item, PATH.replace("FEAT-2026-012", "FEAT-2026-013"))
        head = self.repo.head()
        self.assertIn("MG-061", self.validate(head))
        self.assertNotIn("MG-061", self.validate(head, [review("carla-demo", head)]))

    def test_MG062_warning_in_check_all(self):
        item = copy.deepcopy(self.repo.item)
        item["exceptions"] = [{"id": "EXC-2026-001", "waives": ["RF-001"], "reason": "Teste adiado", "requested_by": "ana", "expires": "2026-11-01", "follow_up": item["id"]}]
        write_item(self.repo.path, item)
        policy, workflows, _ = load(self.repo.path / "config")
        engine = Validator(self.repo.path, policy, workflows, dt.date(2026, 11, 13))
        issues = engine.check_all()
        self.assertTrue(any(i.code == "MG-062" and i.warning for i in issues))

    def test_MG070_bad_parent_and_valid_relation(self):
        item = copy.deepcopy(self.repo.item)
        item["parent"] = "FEAT-999"
        self.assertIn("MG-070", self.validate(self.repo.head(item)))
        item["parent"] = None
        item["relations"] = [{"type": "relates-to", "target": item["id"]}]
        self.assertNotIn("MG-070", self.validate(self.repo.head(item)))

    def test_MG080_invalid_workflow_and_valid_config(self):
        path = self.repo.path / "config/workflows/product-delivery.yml"
        workflow = yaml.safe_load(path.read_text())
        workflow["transitions"].append({"from": "draft", "to": "never"})
        path.write_text(yaml.safe_dump(workflow))
        _, _, errors = load(self.repo.path / "config")
        self.assertTrue(errors)
        self.assertFalse(load(ROOT / "config")[2])

    def test_MG090_platform_review_and_base_config(self):
        trusted = self.repo.path / "trusted-config"
        shutil.copytree(self.repo.path / "config", trusted)
        policy_path = self.repo.path / "config/policy.yml"
        policy = yaml.safe_load(policy_path.read_text())
        policy["approvers"]["platform"] = ["malicious-demo"]
        policy_path.write_text(yaml.safe_dump(policy))
        head = self.repo.head()
        self.assertIn("MG-090", self.validate(head, config_dir=trusted))
        self.assertNotIn("MG-090", self.validate(head, [review("kadu-demo", head)], config_dir=trusted))
        self.assertIn("MG-090", self.validate(head, [review("malicious-demo", head)], config_dir=trusted))

    def test_MG090_covers_the_agent_roles(self):
        write(self.repo.path, "agentes/pergunta.md", "---\npapel: pergunta\npermissoes: [ler]\n---\ncorpo\n")
        head = self.repo.commit("agentes")
        self.assertIn("MG-090", self.validate(head))
        self.assertNotIn("MG-090", self.validate(head, [review("kadu-demo", head)]))

    def test_check_all_and_github_output_and_exit_codes(self):
        cli = ROOT / "scripts/manuel_gate.py"
        args = [sys.executable, str(cli), "check-all", "--repo", str(self.repo.path)]
        okay = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(okay.returncode, 0)
        item = copy.deepcopy(self.repo.item)
        item["state"] = "planned"
        write_item(self.repo.path, item)
        (self.repo.path / f"{PREFIX}/artefatos/20-design.md").unlink()
        bad = subprocess.run(args + ["--format", "github"], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("::error", bad.stdout)
        self.assertIn("MG-030", bad.stdout)
        usage = subprocess.run(args + ["--today", "bad"], capture_output=True, text=True)
        self.assertEqual(usage.returncode, 2)


if __name__ == "__main__":
    unittest.main()

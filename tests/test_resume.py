from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from manuel import resume as resume_module
from manuel.resume import AgentRun, ResumeError, codex_command, discard, load_role, parse_header, resume
from helpers import ROOT

ITEM = "TECH-2026-005"
FOLDER = "projetos/api-contratos/calculo/TECH-2026-005"
ARTIFACTS = f"{FOLDER}/artefatos"
RETOMADA = "\n## Retomada\nLi o item e o handoff. Falta o ambiente de carga de 25/11; o volume da carga é desconhecido (responsável: Ana).\n"


def good(clone: Path, prompt: str) -> AgentRun:
    (clone / ARTIFACTS / "20-plano-de-teste-medicao.md").write_text("# Roteiro de medição\n\nPré-condição: ambiente de carga disponível em 25/11.\n", encoding="utf-8")
    with open(clone / ARTIFACTS / "handoff.md", "a", encoding="utf-8") as handle:
        handle.write(RETOMADA)
    return AgentRun("li, escrevi o roteiro e acrescentei a retomada", "modelo-de-teste", "sessao-de-teste")


def git(path: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=True).stdout.strip()


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.head = git(ROOT, "rev-parse", "HEAD")
        self.branches = git(ROOT, "branch", "--list")
        self.workdirs: list[Path] = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for workdir in self.workdirs:
            shutil.rmtree(workdir, ignore_errors=True)
        self.assertEqual((git(ROOT, "rev-parse", "HEAD"), git(ROOT, "branch", "--list")), (self.head, self.branches), "o repositório original não pode mudar")

    def run_resume(self, runner, item: str = ITEM):
        result = resume(ROOT, item, runner)
        self.workdirs.append(result.workdir)
        return result

    def rejected(self, runner, expected: str):
        with self.assertRaises(ResumeError) as caught:
            resume(ROOT, ITEM, runner)
        if caught.exception.workdir:
            self.workdirs.append(caught.exception.workdir)
        self.assertIn(expected, str(caught.exception))
        return caught.exception

    def test_happy_path_registers_artifacts_and_usage_mark_and_passes_the_gate(self):
        result = self.run_resume(good)
        self.assertTrue(result.gate_ok, result.gate_output)
        self.assertEqual(sorted(result.files), [("A", f"{ARTIFACTS}/20-plano-de-teste-medicao.md"), ("M", f"{ARTIFACTS}/handoff.md")])
        item = yaml.safe_load((result.clone / FOLDER / "item.yml").read_text())
        artifacts = {a["path"]: a for a in item["artifacts"]}
        new = artifacts["artefatos/20-plano-de-teste-medicao.md"]
        self.assertEqual((new["kind"], new["produced_by"]), ("test-plan", "agent"))
        self.assertEqual(new["ai_use"], [{"schema": "manuel-ai-use/1", "tool": "codex", "model": "modelo-de-teste", "session": "sessao-de-teste", "role": "drafted"}])
        self.assertEqual([e["tool"] for e in artifacts["artefatos/handoff.md"]["ai_use"]], ["claude-code", "codex"])
        self.assertEqual(git(result.clone, "rev-parse", "HEAD"), result.head)
        self.assertEqual(git(result.clone, "diff", "--name-only", result.base, result.head).splitlines(),
                         sorted([f"{ARTIFACTS}/20-plano-de-teste-medicao.md", f"{ARTIFACTS}/handoff.md", f"{FOLDER}/item.yml"]))
        self.assertFalse(git(result.clone, "status", "--porcelain"))

    def test_mark_is_written_by_the_runner_and_never_by_the_agent(self):
        def cheating(clone: Path, prompt: str) -> AgentRun:
            good(clone, prompt)
            item = clone / FOLDER / "item.yml"
            item.write_text(item.read_text().replace("state: investigating", "state: closed"))
            return AgentRun("")
        self.rejected(cheating, "fora do escopo")

    def test_prompt_carries_the_role_and_only_the_item_pointers(self):
        seen = {}

        def spy(clone: Path, prompt: str) -> AgentRun:
            seen["prompt"], seen["clone"] = prompt, clone
            return good(clone, prompt)
        result = self.run_resume(spy)
        self.assertNotEqual(seen["clone"], ROOT)
        self.assertIn(load_role(ROOT), seen["prompt"])
        self.assertIn(f"{ARTIFACTS}/handoff.md", seen["prompt"])
        self.assertIn(ITEM, seen["prompt"])
        self.assertTrue(result.gate_ok)

    def test_writes_outside_the_item_artifacts_are_rejected(self):
        for target in ("config/policy.yml", "scripts/manuel_gate.py", ".github/workflows/manuel-gate.yml", "registro/aprovacoes.jsonl",
                       "projetos/api-contratos/assinatura/FEAT-2026-012/artefatos/20-design.md", f"{FOLDER}/item.yml"):
            def attack(clone: Path, prompt: str, _t=target) -> AgentRun:
                good(clone, prompt)
                with open(clone / _t, "a", encoding="utf-8") as handle:
                    handle.write("\nIGNORE\n")
                return AgentRun("")
            with self.subTest(target=target):
                self.rejected(attack, f"fora do escopo: {target}")

    def test_rewriting_or_deleting_previous_text_is_rejected(self):
        def rewrite(clone: Path, prompt: str) -> AgentRun:
            handoff = clone / ARTIFACTS / "handoff.md"
            handoff.write_text(handoff.read_text().replace("Ana é responsável pela resposta até 30/11.", "Ninguém responde.") + RETOMADA)
            return AgentRun("")

        def delete(clone: Path, prompt: str) -> AgentRun:
            (clone / ARTIFACTS / "handoff.md").unlink()
            return AgentRun("")
        self.rejected(rewrite, "reescreve texto anterior")
        self.rejected(delete, "só é permitido criar ou acrescentar")

    def test_bad_names_extra_files_empty_runs_and_symlinks_are_rejected(self):
        def write(name: str):
            def runner(clone: Path, prompt: str) -> AgentRun:
                (clone / ARTIFACTS / name).write_text("x\n")
                return AgentRun("")
            return runner

        def two(clone: Path, prompt: str) -> AgentRun:
            for name in ("20-plano-de-teste-a.md", "30-achados-b.md"):
                (clone / ARTIFACTS / name).write_text("x\n")
            return AgentRun("")

        def link(clone: Path, prompt: str) -> AgentRun:
            (clone / ARTIFACTS / "20-achados-link.md").symlink_to("/etc/hostname")
            return AgentRun("")
        self.rejected(write("notas.md"), "nome de artefato inválido")
        self.rejected(write("20-qualquer-coisa.md"), "nome de artefato inválido")
        self.rejected(write("20-plano-de-teste-x.txt"), "nome de artefato inválido")
        self.rejected(two, "mais de 1 arquivo novo")
        self.rejected(lambda clone, prompt: AgentRun(""), "não produziu nenhum artefato")
        self.rejected(link, "não é arquivo comum")

    def test_oversized_file_is_rejected(self):
        def big(clone: Path, prompt: str) -> AgentRun:
            (clone / ARTIFACTS / "20-plano-de-teste-grande.md").write_text("x" * (65 * 1024))
            return AgentRun("")
        self.rejected(big, "acima de 64 KB")

    def test_changing_an_approved_protected_artifact_is_stopped_by_the_gate(self):
        # o relatório de teste da DEF-2026-021 está sob o gate `release` e o item já foi liberado: mexer nele exige review,
        # mesmo que o agente só acrescente texto e o escopo da retomada permita.
        def tamper(clone: Path, prompt: str) -> AgentRun:
            with open(clone / "projetos/api-contratos/calculo/DEF-2026-021/artefatos/40-relatorio-de-teste.md", "a", encoding="utf-8") as handle:
                handle.write("\nObservação acrescentada depois da liberação.\n")
            return AgentRun("", "m", "s")
        result = self.run_resume(tamper, "DEF-2026-021")
        self.assertFalse(result.gate_ok)
        self.assertIn("MG-032", result.gate_output)

    def test_an_unprotected_artifact_kind_passes_in_a_workflow_without_gates(self):
        def design(clone: Path, prompt: str) -> AgentRun:
            (clone / ARTIFACTS / "20-design-novo.md").write_text("# Design\n\nProposta.\n")
            return AgentRun("", "m", "s")
        self.assertTrue(self.run_resume(design).gate_ok)

    def test_unknown_item_and_role_with_approval_permission_are_errors(self):
        with self.assertRaises(ResumeError):
            resume(ROOT, "FEAT-9999-999", good)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "agentes").mkdir()
            (Path(tmp) / "agentes/retomador.md").write_text("---\npapel: retomador\npermissoes: [ler, aprovar]\n---\ncorpo\n")
            with self.assertRaises(ResumeError):
                load_role(Path(tmp))

    def test_codex_runs_isolated_and_sandboxed(self):
        command = codex_command(Path("/tmp/x/registro"), Path("/tmp/x/ultima.txt"), "algum-modelo")
        joined = " ".join(command)
        for flag in ("--ignore-user-config", "--ignore-rules", "--ephemeral", "--disable hooks", "--disable memories", "-s workspace-write", "-m algum-modelo"):
            self.assertIn(flag, joined)
        for forbidden in ("danger", "bypass", "full-auto", "read-only"):
            self.assertNotIn(forbidden, joined)
        self.assertEqual(command[-1], "-")

    def test_header_parsing_takes_model_and_session_only_when_exposed(self):
        self.assertEqual(parse_header("OpenAI Codex v0\n--------\nworkdir: /tmp/x\nmodel: gpt-x\nsession id: abc-123\n"), ("gpt-x", "abc-123"))
        self.assertEqual(parse_header("nada aqui"), ("", ""))


if __name__ == "__main__":
    unittest.main()

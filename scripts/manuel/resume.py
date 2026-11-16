"""Retomada de um item por um segundo agente, só pelo registro.

O agente recebe um clone limpo (só o que está commitado), escreve documentos em `artefatos/` do item e mais nada. O Manuel
confere o escopo do que mudou, registra os artefatos e a marca de uso no `item.yml` (o agente não preenche a própria marca)
e roda o gate sobre a diferença. O que o agente escreve continua sendo texto de modelo; o código só garante o escopo, o
registro e o resultado do gate.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from .gitread import git
from .views import item_paths

ROLE_FILE = "agentes/retomador.md"
KIND_BY_TYPE = {
    "requisitos": "requirements", "design": "design", "execucao": "execution", "plano-de-teste": "test-plan",
    "relatorio-de-teste": "test-report", "achados": "findings", "outro": "other",
}
NAME = re.compile(r"^(?:handoff|\d\d-(?P<type>requisitos|design|execucao|plano-de-teste|relatorio-de-teste|achados|outro)(?:-[a-z0-9-]+)?)\.md$")
MAX_NEW_FILES = 1
MAX_FILE_BYTES = 64 * 1024
GATE_CLI = Path(__file__).resolve().parents[1] / "manuel_gate.py"


class ResumeError(RuntimeError):
    """A retomada não pode seguir (escopo violado, agente falhou, item inexistente)."""

    def __init__(self, message: str, workdir: Path | None = None):
        super().__init__(message)
        self.workdir = workdir


@dataclass
class AgentRun:
    summary: str
    model: str = ""
    session: str = ""


@dataclass
class Resumed:
    workdir: Path
    clone: Path
    branch: str
    base: str
    head: str
    files: list[tuple[str, str]]
    event: dict
    gate_ok: bool
    gate_output: str
    summary: str
    registered: list[str] = field(default_factory=list)


Runner = Callable[[Path, str], AgentRun]


def load_role(repo: Path) -> str:
    raw = (repo / ROLE_FILE).read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ResumeError(f"{ROLE_FILE} sem cabeçalho YAML")
    head = yaml.safe_load(parts[1])
    if not isinstance(head, dict) or "aprovar" in [str(p) for p in head.get("permissoes", [])]:
        raise ResumeError(f"{ROLE_FILE}: cabeçalho inválido ou com permissão de aprovar")
    return parts[2].strip()


def locate(repo: Path, item_id: str) -> str:
    for path in item_paths(repo, "HEAD"):
        if path.split("/")[3] == item_id:
            return path
    raise ResumeError(f"item {item_id} não existe no registro")


def build_prompt(role: str, item_id: str, item_path: str) -> str:
    folder = item_path.rsplit("/", 1)[0]
    return f"{role}\n\n## Tarefa\nRetome o item {item_id}. A pasta dele é `{folder}/`; comece por `{item_path}` e por `{folder}/artefatos/handoff.md`."


def codex_command(clone: Path, last_message: Path, model: str | None = None) -> list[str]:
    """Codex isolado: sem a configuração, as regras, os hooks, as apps nem a memória de quem roda; escreve só no clone."""
    command = ["codex", "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--disable", "hooks", "--disable", "apps",
               "--disable", "memories", "-s", "workspace-write", "-C", str(clone), "--color", "never", "-o", str(last_message)]
    return command + (["-m", model] if model else []) + ["-"]


def parse_header(stderr: str) -> tuple[str, str]:
    model = re.search(r"^model:\s*(\S+)", stderr, re.M)
    session = re.search(r"^session id:\s*(\S+)", stderr, re.M)
    return (model.group(1) if model else ""), (session.group(1) if session else "")


def make_codex_runner(model: str | None = None, timeout: int = 300) -> Runner:
    def run(clone: Path, prompt: str) -> AgentRun:
        last = clone.parent / "ultima-mensagem.txt"
        try:
            done = subprocess.run(codex_command(clone, last, model), input=prompt, text=True, capture_output=True, timeout=timeout, check=False)
        except FileNotFoundError as exc:
            raise ResumeError("o comando `codex` não foi encontrado") from exc
        except subprocess.TimeoutExpired as exc:
            raise ResumeError(f"o agente não terminou em {timeout} s") from exc
        if done.returncode:
            raise ResumeError(f"o agente falhou (código {done.returncode}): {done.stderr.strip()[-300:]}")
        found_model, session = parse_header(done.stderr)
        summary = last.read_text(encoding="utf-8").strip() if last.is_file() else done.stdout.strip()
        return AgentRun(summary, found_model, session)
    return run


def prepare_clone(repo: Path, item_id: str) -> tuple[Path, Path, str, str]:
    workdir = Path(tempfile.mkdtemp(prefix="manuel-retomada-"))
    clone = workdir / "registro"
    subprocess.run(["git", "clone", "--quiet", "--local", "--no-hardlinks", str(repo), str(clone)], check=True, capture_output=True, text=True)
    for key in ("user.name", "user.email"):
        value = subprocess.run(["git", "-C", str(repo), "config", key], capture_output=True, text=True).stdout.strip()
        git(clone, "config", key, value or "retomada")
    branch = f"retomada/{item_id}"
    git(clone, "checkout", "-q", "-b", branch)
    return workdir, clone, branch, git(clone, "rev-parse", "HEAD").strip()


def changes(clone: Path) -> list[tuple[str, str]]:
    result = []
    for line in git(clone, "status", "--porcelain=v1", "-uall").splitlines():
        flag, path = line[:2].strip(), line[3:].strip().strip('"')
        result.append(({"??": "A", "A": "A", "M": "M", "D": "D"}.get(flag, flag), path))
    return sorted(result, key=lambda c: c[1])


def scope_violations(clone: Path, found: list[tuple[str, str]], folder: str) -> list[str]:
    prefix = f"{folder}/artefatos/"
    problems, new_files = [], 0
    if not found:
        return ["o agente não produziu nenhum artefato"]
    for status, path in found:
        name = path[len(prefix):]
        if not path.startswith(prefix) or "/" in name:
            problems.append(f"fora do escopo: {path}")
        elif status not in {"A", "M"}:
            problems.append(f"só é permitido criar ou acrescentar; recebi {status}: {path}")
        elif not NAME.match(name):
            problems.append(f"nome de artefato inválido: {path}")
        elif (clone / path).is_symlink() or not (clone / path).is_file():
            problems.append(f"não é arquivo comum: {path}")
        elif (clone / path).stat().st_size > MAX_FILE_BYTES:
            problems.append(f"arquivo acima de {MAX_FILE_BYTES // 1024} KB: {path}")
        elif status == "M":
            removed = sum(int(line.split("\t")[1]) for line in git(clone, "diff", "--numstat", "--", path).splitlines() if line.split("\t")[1].isdigit())
            if removed:
                problems.append(f"reescreve texto anterior ({removed} linha(s) removida(s)): {path}")
        else:
            new_files += 1
    if new_files > MAX_NEW_FILES:
        problems.append(f"mais de {MAX_NEW_FILES} arquivo novo")
    return problems


def register(clone: Path, item_path: str, found: list[tuple[str, str]], run: AgentRun, tool: str) -> tuple[dict, list[str]]:
    """Registra no item.yml os artefatos e a marca de uso; o agente não preenche a própria marca."""
    item = yaml.safe_load((clone / item_path).read_text(encoding="utf-8"))
    event = {"schema": "manuel-ai-use/1", "tool": tool, "model": run.model or "nao-informado", "session": run.session or "nao-informado", "role": "drafted"}
    artifacts = item.setdefault("artifacts", [])
    folder, notes = item_path.rsplit("/", 1)[0], []
    for status, path in found:
        relative = path[len(folder) + 1:]
        name = relative.split("/", 1)[1]
        entry = next((a for a in artifacts if isinstance(a, dict) and a.get("path") == relative), None)
        if status == "A":
            if entry is not None:
                raise ResumeError(f"{relative} já está registrado")
            kind = "handoff" if name == "handoff.md" else KIND_BY_TYPE[NAME.match(name).group("type")]
            artifacts.append({"path": relative, "kind": kind, "produced_by": "agent", "ai_use": [dict(event)]})
            notes.append(f"novo {relative} ({kind})")
        else:
            if entry is None or entry.get("produced_by") != "agent":
                raise ResumeError(f"{relative} não é um artefato de agente registrado: o agente não pode alterá-lo")
            entry.setdefault("ai_use", []).append(dict(event))
            notes.append(f"acrescentado {relative}, marca de uso somada")
    (clone / item_path).write_text(yaml.safe_dump(item, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return event, notes


def run_gate(clone: Path, base: str, head: str, author: str = "agente-retomada") -> tuple[bool, str]:
    reviews = clone.parent / "reviews.json"
    reviews.write_text(json.dumps([]), encoding="utf-8")
    done = subprocess.run([sys.executable, str(GATE_CLI), "check", "--repo", str(clone), "--base", base, "--head", head,
                           "--reviews", str(reviews), "--pr-author", author], capture_output=True, text=True)
    return done.returncode == 0, (done.stdout + done.stderr).strip()


def resume(repo: Path, item_id: str, runner: Runner, tool: str = "codex", log: Callable[[str], None] = lambda _: None) -> Resumed:
    item_path = locate(repo, item_id)
    folder = item_path.rsplit("/", 1)[0]
    role = load_role(repo)
    workdir, clone, branch, base = prepare_clone(repo, item_id)
    log(f"clone limpo em {clone} (só o que está commitado, branch {branch})")
    log(f"o agente lê o registro e escreve em {folder}/artefatos/ ...")
    run = runner(clone, build_prompt(role, item_id, item_path))
    found = changes(clone)
    problems = scope_violations(clone, found, folder)
    if problems:
        raise ResumeError("escopo violado, nada foi registrado nem commitado: " + "; ".join(problems) + f" (clone mantido em {clone})", workdir)
    log("escopo conferido: só artefatos do item, sem apagar nem reescrever")
    event, notes = register(clone, item_path, found, run, tool)
    for note in notes:
        log("registrado: " + note)
    git(clone, "add", "--", item_path, *[p for _, p in found])
    git(clone, "commit", "-q", "-m", f"docs({item_id}): artefatos da retomada a partir do handoff")
    head = git(clone, "rev-parse", "HEAD").strip()
    ok, output = run_gate(clone, base, head)
    log("gate: " + ("passa" if ok else "BARRA"))
    return Resumed(workdir, clone, branch, base, head, found, event, ok, output, run.summary, notes)


def apply_branch(repo: Path, result: Resumed) -> None:
    git(repo, "fetch", "--quiet", str(result.clone), f"{result.branch}:{result.branch}")


def discard(result: Resumed) -> None:
    shutil.rmtree(result.workdir, ignore_errors=True)

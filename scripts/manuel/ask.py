"""Agente de pergunta: monta o papel, roda o Claude Code em modo só leitura e confere as fontes que a resposta cita.

O que o código garante é pouco e verificável: o agente nasce só com Read, Grep e Glob, sem as configurações pessoais
de quem roda (`--safe-mode`), e toda fonte citada precisa existir no repositório. O que o agente diz continua sendo
texto de modelo: a verificação mostra que as fontes existem, não que a frase está certa.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from .views import collect, render_html, render_markdown

ROLE_FILE = "agentes/pergunta.md"
NOT_FOUND = "Isso não consta no registro."
REFUSAL = "Esta organização não mede produtividade individual."
OUT_OF_SCOPE = "Só respondo sobre o registro."
READ_ONLY = {"Read", "Grep", "Glob"}
PATH = re.compile(r"(?<![\w/.-])((?:projetos|config|registro|views|agentes|docs)/[\w./-]*\w|CONSTITUTION\.md|README\.md)")


class AskError(RuntimeError):
    """Falha ao consultar o agente (não é falha de verificação)."""


@dataclass
class Role:
    name: str
    version: str
    tools: list[str]
    prompt: str


@dataclass
class Verification:
    kind: str            # respondida | não consta | recusada | sem fonte
    cited: list[str]
    missing: list[str]

    @property
    def ok(self) -> bool:
        return not self.missing and self.kind != "sem fonte"


def load_role(repo: Path) -> Role:
    raw = (repo / ROLE_FILE).read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise AskError(f"{ROLE_FILE} sem cabeçalho YAML")
    head = yaml.safe_load(parts[1])
    if not isinstance(head, dict) or not isinstance(head.get("ferramentas"), list):
        raise AskError(f"{ROLE_FILE}: cabeçalho inválido")
    tools = [str(tool) for tool in head["ferramentas"]]
    if not tools or not set(tools) <= READ_ONLY:
        raise AskError(f"{ROLE_FILE}: o agente de pergunta só pode ter {sorted(READ_ONLY)}; declarou {tools}")
    return Role(str(head.get("papel", "")), str(head.get("versao", "")), tools, parts[2].strip())


def build_command(role: Role, model: str | None = None) -> list[str]:
    """Comando do Claude Code: sem configurações pessoais, só as ferramentas do papel, sem gravar sessão."""
    command = ["claude", "-p", "--safe-mode", "--tools", ",".join(role.tools), "--no-session-persistence", "--system-prompt", role.prompt]
    return command + (["--model", model] if model else [])


def verify(answer: str, repo: Path) -> Verification:
    cited: list[str] = []
    for found in PATH.findall(answer):
        if found not in cited:
            cited.append(found)
    root = repo.resolve()
    missing = []
    for path in cited:
        target = (root / path).resolve()
        if not target.is_relative_to(root) or not target.exists():
            missing.append(path)
    if NOT_FOUND in answer:
        kind = "não consta"
    elif REFUSAL in answer or OUT_OF_SCOPE in answer:
        kind = "recusada"
    else:
        kind = "respondida" if cited else "sem fonte"
    return Verification(kind, cited, missing)


def refresh_views(repo: Path, today: dt.date | None) -> None:
    model = collect(repo, "HEAD", today)
    out = repo / "views"
    out.mkdir(exist_ok=True)
    (out / "INDEX.md").write_text(render_markdown(model), encoding="utf-8")
    (out / "executiva.html").write_text(render_html(model, out, repo), encoding="utf-8")


def ask(repo: Path, question: str, today: dt.date | None = None, model: str | None = None, timeout: int = 180) -> tuple[str, Verification]:
    role = load_role(repo)
    refresh_views(repo, today)
    try:
        run = subprocess.run(build_command(role, model), input=question, text=True, capture_output=True, cwd=repo, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise AskError("o comando `claude` não foi encontrado") from exc
    except subprocess.TimeoutExpired as exc:
        raise AskError(f"o agente não respondeu em {timeout} s") from exc
    if run.returncode or not run.stdout.strip():
        raise AskError(f"o agente falhou (código {run.returncode}): {run.stderr.strip()[:300]}")
    answer = run.stdout.strip()
    return answer, verify(answer, repo)

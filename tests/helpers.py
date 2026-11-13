from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PATH = "projetos/api-contratos/assinatura/FEAT-2026-012/item.yml"
PREFIX = "projetos/api-contratos/assinatura/FEAT-2026-012"


def command(repo: Path, *args: str) -> str:
    run = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if run.returncode:
        raise AssertionError(run.stderr)
    return run.stdout.strip()


def write(repo: Path, path: str, content: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def write_item(repo: Path, item: dict, path: str = PATH) -> None:
    write(repo, path, yaml.safe_dump(item, allow_unicode=True, sort_keys=False))


def fixture(state: str = "awaiting-approval") -> dict:
    return {
        "modelVersion": "3.0", "schemaVersion": "work-item/1.1", "kind": "work-item",
        "id": "FEAT-2026-012", "title": "Assinatura digital fictícia",
        "context": {"organization": "aurora-credito", "system": "originacao", "domain": "assinatura", "repositories": ["api-contratos"]},
        "nature": "feature", "class": "L", "workflow": {"id": "product-delivery", "version": "1.0"},
        "state": state, "ownership": {"owner": "ana", "approvers": {"design": ["security"]}},
        "parent": None, "relations": [], "requirements": [{"id": "RF-001", "text": "Cliente assina na tela."}],
        "evidence": [], "exceptions": [],
        "artifacts": [
            {"path": "artefatos/10-requisitos.md", "kind": "requirements", "produced_by": "agent", "ai_use": [{"schema": "manuel-ai-use/1", "tool": "claude-code", "model": "nao-informado", "session": "demo-1", "role": "drafted"}]},
            {"path": "artefatos/20-design.md", "kind": "design", "produced_by": "human"},
        ],
        "lifecycle": {"createdAt": "2026-10-27"},
    }


def review(login: str, sha: str, state: str = "APPROVED", number: int = 1, when: str = "2026-11-13T12:00:00Z") -> dict:
    return {"id": number, "user": {"login": login}, "state": state, "commit_id": sha, "submitted_at": when}


class Repo:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        command(self.path, "init", "-b", "main")
        command(self.path, "config", "user.name", "Demo")
        command(self.path, "config", "user.email", "demo@example.invalid")
        shutil.copytree(ROOT / "config", self.path / "config")
        policy_path = self.path / "config/policy.yml"
        policy = yaml.safe_load(policy_path.read_text())
        policy["approvers"] = {"security": ["eva-demo"], "tech-lead": ["carla-demo"], "platform": ["kadu-demo"], "product": []}
        policy_path.write_text(yaml.safe_dump(policy, allow_unicode=True, sort_keys=False))
        self.item = fixture()
        write_item(self.path, self.item)
        write(self.path, f"{PREFIX}/artefatos/10-requisitos.md", "# Requisitos\n\nCliente assina na tela.\n")
        write(self.path, f"{PREFIX}/artefatos/20-design.md", "# Design\n\nA assinatura aparece na tela.\n")
        self.base = self.commit("base")

    def commit(self, message: str) -> str:
        command(self.path, "add", "-A")
        command(self.path, "commit", "-m", message)
        return command(self.path, "rev-parse", "HEAD")

    def head(self, item: dict | None = None) -> str:
        if item is not None:
            self.item = item
            write_item(self.path, item)
        return self.commit("head")

    def close(self) -> None:
        self.temp.cleanup()

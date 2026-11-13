from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from .gitread import changed, files, git, read
from .reviews import approval_issue


ITEM_RE = re.compile(r"^projetos/[^/]+/[^/]+/([^/]+)/item\.yml$")
PLACEHOLDER_RE = re.compile(r"\[PREENCHER\]|\[TODO\]|TODO:|PENDENTE DE EXECUÇÃO|\{\{.*?\}\}", re.I | re.S)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NATURES = {"feature", "defect", "incident", "investigation", "technical-work"}
ARTIFACT_KINDS = {"requirements", "design", "execution", "test-plan", "test-report", "findings", "handoff", "other"}
ROLES = {"drafted", "implemented", "reviewed", "analyzed"}
STATUSES = {"observed", "confirmed", "inferred", "unknown"}
RELATIONS = {"blocks", "depends-on", "regularizes", "relates-to"}


@dataclass(frozen=True)
class Issue:
    code: str
    item: str
    message: str
    path: str = ""
    warning: bool = False


def valid_date(value: object) -> bool:
    if isinstance(value, dt.date):
        return True
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return False
    try:
        dt.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def date_value(value: object) -> dt.date:
    return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))


def item_root(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) >= 4 and parts[0] == "projetos":
        return "/".join(parts[:4])
    return None


def load_item(repo: Path, rev: str, path: str) -> dict | None:
    raw = read(repo, rev, path)
    if raw is None:
        return None
    try:
        value = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML ilegível: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"item deve ser objeto YAML: {path}")
    return value


class Validator:
    def __init__(self, repo: Path, policy: dict, workflows: dict[str, dict], today: dt.date):
        self.repo = repo
        self.policy = policy
        self.workflows = workflows
        self.today = today
        self.issues: list[Issue] = []

    def add(self, code: str, item: str, message: str, path: str = "", warning: bool = False) -> None:
        self.issues.append(Issue(code, item, message, path or item, warning))

    def result(self) -> list[Issue]:
        return sorted(set(self.issues), key=lambda i: (i.item, i.code, i.message, i.path))

    def approval(self, gate: str, item: dict | None, reviews: list[dict], author: str, sha: str, identifier: str, path: str) -> bool:
        problem = approval_issue(gate, self.policy, item, reviews, author, sha)
        if problem:
            self.add(problem[0], identifier, problem[1], path)
            return False
        return True

    def all_items(self, rev: str) -> dict[str, tuple[str, dict]]:
        output: dict[str, tuple[str, dict]] = {}
        for path in sorted(files(self.repo, rev)):
            if path.endswith("/item.yml") or path == "item.yml":
                item = load_item(self.repo, rev, path)
                if item is not None:
                    output[str(item.get("id", path))] = (path, item)
        return output

    def structural(self, path: str, item: dict, rev: str, all_items: dict[str, tuple[str, dict]], full: bool) -> None:
        identifier = str(item.get("id") or path)
        match = ITEM_RE.fullmatch(path)
        if not match or identifier != match.group(1):
            self.add("MG-001", identifier, "item.yml fora do caminho canônico ou id diferente da pasta", path)
        required = {
            "modelVersion": str, "schemaVersion": str, "kind": str, "id": str,
            "title": str, "context": dict, "nature": str, "class": str,
            "workflow": dict, "state": str, "ownership": dict, "requirements": list,
            "evidence": list, "exceptions": list, "artifacts": list, "lifecycle": dict,
        }
        for name, kind in required.items():
            if name not in item or not isinstance(item[name], kind):
                self.add("MG-002", identifier, f"campo {name} ausente ou com tipo inválido", path)
        if item.get("modelVersion") != "3.0" or item.get("schemaVersion") != "work-item/1.1" or item.get("kind") != "work-item":
            self.add("MG-002", identifier, "modelVersion, schemaVersion ou kind inválido", path)
        if item.get("nature") not in NATURES or item.get("class") not in {"S", "M", "L", "XL"}:
            self.add("MG-002", identifier, "nature ou class fora do enum", path)
        context = item.get("context") or {}
        if not isinstance(context, dict) or context.get("organization") != self.policy.get("organization") or not isinstance(context.get("repositories"), list) or not context.get("system") or not context.get("domain"):
            self.add("MG-002", identifier, "context inválido", path)
        owner = (item.get("ownership") or {}).get("owner") if isinstance(item.get("ownership"), dict) else None
        if owner not in self.policy.get("people", {}):
            self.add("MG-002", identifier, "ownership.owner ausente da policy.people", path)
        lifecycle = item.get("lifecycle") or {}
        if not isinstance(lifecycle, dict) or not valid_date(lifecycle.get("createdAt")):
            self.add("MG-002", identifier, "lifecycle.createdAt inválido", path)
        wf_ref = item.get("workflow") or {}
        wf = self.workflows.get(wf_ref.get("id")) if isinstance(wf_ref, dict) else None
        if not wf or wf_ref.get("version") != wf.get("version"):
            self.add("MG-002", identifier, "workflow.id ou version inválido", path)
            wf = None
        elif item.get("state") not in wf.get("states", []):
            self.add("MG-002", identifier, "state fora do workflow", path)
        requirements = item.get("requirements") or []
        if not isinstance(requirements, list):
            requirements = []
        req_ids: set[str] = set()
        for req in requirements:
            if not isinstance(req, dict) or not isinstance(req.get("id"), str) or not isinstance(req.get("text"), str) or not req["text"].strip() or req["id"] in req_ids:
                self.add("MG-002", identifier, "requirements inválidos ou duplicados", path)
            else:
                req_ids.add(req["id"])
        if item.get("state") == "blocked":
            blockers = item.get("blocked_by")
            previous = item.get("blocked_from")
            if not isinstance(blockers, list) or not blockers or not wf or previous not in wf.get("blockable_from", []):
                self.add("MG-011", identifier, "blocked exige blocked_by e blocked_from válidos", path)
        elif "blocked_by" in item or "blocked_from" in item:
            self.add("MG-011", identifier, "campos blocked_* fora de blocked", path)
        for field in ("blocked_by",):
            for target in item.get(field, []) if isinstance(item.get(field), list) else []:
                if target not in all_items:
                    self.add("MG-070", identifier, f"{field} aponta para item inexistente {target}", path)
        if item.get("parent") and item["parent"] not in all_items:
            self.add("MG-070", identifier, f"parent aponta para item inexistente {item['parent']}", path)
        for relation in item.get("relations", []) if isinstance(item.get("relations"), list) else []:
            if not isinstance(relation, dict) or relation.get("type") not in RELATIONS or not relation.get("target"):
                self.add("MG-002", identifier, "relation inválida", path)
            elif relation["target"] not in all_items:
                self.add("MG-070", identifier, f"relation aponta para item inexistente {relation['target']}", path, True)
        artifacts = item.get("artifacts") or []
        if not isinstance(artifacts, list):
            artifacts = []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                self.add("MG-002", identifier, "artifacts contém entrada inválida", path)
                continue
            relative = artifact.get("path")
            if not isinstance(relative, str) or not relative.startswith("artefatos/") or PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts or read(self.repo, rev, str(PurePosixPath(path).parent / relative)) is None:
                self.add("MG-031", identifier, f"artifacts[].path inválido ou inexistente: {relative}", path)
            if artifact.get("kind") not in ARTIFACT_KINDS or artifact.get("produced_by") not in {"agent", "human"}:
                self.add("MG-002", identifier, f"kind ou produced_by inválido em {relative}", path)
            if artifact.get("produced_by") == "agent":
                use = artifact.get("ai_use")
                if not isinstance(use, list) or not use or any(
                    not isinstance(event, dict) or event.get("schema") != "manuel-ai-use/1"
                    or not all(isinstance(event.get(field), str) and event[field].strip() for field in ("tool", "model", "session"))
                    or event.get("role") not in ROLES for event in use
                ):
                    self.add("MG-040", identifier, f"ai_use ausente ou inválido em {relative}", path)
        evidence = item.get("evidence") or []
        if not isinstance(evidence, list):
            evidence = []
        for entry in evidence:
            if not isinstance(entry, dict) or not isinstance(entry.get("claim"), str) or not entry["claim"].strip() or entry.get("status") not in STATUSES or (entry.get("requirement") and entry["requirement"] not in req_ids):
                self.add("MG-050", identifier, "evidence malformada", path)
                continue
            status = entry["status"]
            if status in {"observed", "confirmed"} and (not isinstance(entry.get("source"), str) or not entry["source"].strip()):
                self.add("MG-050", identifier, "evidence observada/confirmada sem source", path)
            if status == "confirmed" and (entry.get("by") not in self.policy.get("people", {}) or not valid_date(entry.get("date"))):
                self.add("MG-050", identifier, "evidence confirmada sem by/date", path)
            if status == "unknown" and (entry.get("owner") not in self.policy.get("people", {}) or not valid_date(entry.get("due"))):
                self.add("MG-050", identifier, "evidence desconhecida sem owner/due", path)
        for exception in item.get("exceptions", []) if isinstance(item.get("exceptions"), list) else []:
            if not isinstance(exception, dict) or not re.fullmatch(r"EXC-\d{4}-\d{3}", str(exception.get("id", ""))) or not isinstance(exception.get("waives"), list) or not exception["waives"] or any(req not in req_ids for req in exception["waives"]) or not isinstance(exception.get("reason"), str) or not exception["reason"].strip() or exception.get("requested_by") not in self.policy.get("people", {}) or not valid_date(exception.get("expires")) or not exception.get("follow_up"):
                self.add("MG-060", identifier, "exceção malformada", path)
                continue
            if exception["follow_up"] not in all_items:
                self.add("MG-063", identifier, f"follow_up inexistente: {exception['follow_up']}", path)
            if date_value(exception["expires"]) < self.today:
                self.add("MG-062", identifier, f"exceção vencida: {exception['id']}", path, warning=full)
        if full and wf:
            self.required_artifacts(path, item, rev, wf, None, full=True)
            if self.at_or_after(item, wf, "released"):
                self.required_evidence(path, item)

    def at_or_after(self, item: dict, wf: dict, state: str) -> bool:
        order = wf.get("state_order", [])
        current = item.get("blocked_from") if item.get("state") == "blocked" else item.get("state")
        return state in order and current in order and order.index(current) >= order.index(state)

    def required_artifacts(self, path: str, item: dict, rev: str, wf: dict, edge: dict | None, full: bool = False) -> None:
        identifier = str(item.get("id", path))
        required: set[str] = set()
        if full:
            order = wf.get("state_order", [])
            current = item.get("blocked_from") if item.get("state") == "blocked" else item.get("state")
            if current in order:
                for transition in wf.get("transitions", []):
                    if transition.get("to") in order and order.index(transition["to"]) <= order.index(current) and transition.get("from") in order and order.index(transition["from"]) < order.index(transition["to"]):
                        required.update(transition.get("requires_artifacts", []))
        elif edge:
            required.update(edge.get("requires_artifacts", []))
        artifacts = item.get("artifacts", [])
        if not isinstance(artifacts, list):
            artifacts = []
        for kind in sorted(required):
            candidates = [a for a in artifacts if isinstance(a, dict) and a.get("kind") == kind]
            good = False
            for artifact in candidates:
                relative = artifact.get("path")
                if not isinstance(relative, str) or ".." in PurePosixPath(relative).parts:
                    continue
                content = read(self.repo, rev, str(PurePosixPath(path).parent / relative))
                if content and content.strip() and not PLACEHOLDER_RE.search(content):
                    good = True
            if not good:
                self.add("MG-030", identifier, f"artefato {kind} exigido está ausente, vazio ou contém placeholder", path)

    def required_evidence(self, path: str, item: dict) -> None:
        identifier = str(item.get("id", path))
        entries = item.get("evidence", [])
        exceptions = item.get("exceptions", [])
        requirements = item.get("requirements", [])
        if not isinstance(entries, list):
            entries = []
        if not isinstance(exceptions, list):
            exceptions = []
        if not isinstance(requirements, list):
            requirements = []
        covered = {
            e.get("requirement") for e in entries
            if isinstance(e, dict) and e.get("status") in {"observed", "confirmed"}
            and isinstance(e.get("source"), str) and e["source"].strip()
            and (e["status"] != "confirmed" or (e.get("by") in self.policy.get("people", {}) and valid_date(e.get("date"))))
        }
        covered.update(
            req for exc in exceptions if isinstance(exc, dict)
            and re.fullmatch(r"EXC-\d{4}-\d{3}", str(exc.get("id", "")))
            and isinstance(exc.get("waives"), list)
            and isinstance(exc.get("reason"), str) and exc["reason"].strip()
            and exc.get("requested_by") in self.policy.get("people", {})
            and valid_date(exc.get("expires")) and exc.get("follow_up")
            for req in exc["waives"]
        )
        for req in requirements:
            if isinstance(req, dict) and req.get("id") not in covered:
                self.add("MG-051", identifier, f"requisito {req.get('id')} sem evidência válida ou exceção", path)

    def check_all(self) -> list[Issue]:
        current = self.all_items("WORKTREE")
        for path, item in current.values():
            self.structural(path, item, "WORKTREE", current, full=True)
        return self.result()

    def check(self, base: str, head: str, reviews: list[dict], author: str, sha: str) -> list[Issue]:
        differences = changed(self.repo, base, head)
        current = self.all_items(head)
        previous = self.all_items(base)
        touched_roots = {root for path in differences if (root := item_root(path))}
        touched_paths = {f"{root}/item.yml" for root in touched_roots}
        touched_paths.update(path for path in differences if path.endswith("/item.yml") or path == "item.yml")
        for path in sorted(touched_paths):
            old = load_item(self.repo, base, path)
            new = load_item(self.repo, head, path)
            identifier = str((new or old or {}).get("id") or path)
            if old and not new:
                self.add("MG-003", identifier, "item removido; use cancelled", path)
                continue
            if not new:
                continue
            self.structural(path, new, head, current, full=False)
            wf_ref = new.get("workflow") or {}
            wf = self.workflows.get(wf_ref.get("id")) if isinstance(wf_ref, dict) else None
            if not wf:
                continue
            if not old:
                if new.get("state") != "draft":
                    self.add("MG-005", identifier, "item novo deve nascer em draft", path)
                continue
            for field in ("id", "nature"):
                if old.get(field) != new.get(field):
                    self.add("MG-004", identifier, f"campo imutável alterado: {field}", path)
            for field in ("createdAt",):
                if (old.get("lifecycle") or {}).get(field) != (new.get("lifecycle") or {}).get(field):
                    self.add("MG-004", identifier, f"campo imutável alterado: lifecycle.{field}", path)
            if (old.get("context") or {}).get("organization") != (new.get("context") or {}).get("organization"):
                self.add("MG-004", identifier, "campo imutável alterado: context.organization", path)
            before, after = old.get("state"), new.get("state")
            if before != after:
                if before in wf.get("terminal", []):
                    self.add("MG-012", identifier, "estado terminal não pode mudar", path)
                elif after == "blocked":
                    if before not in wf.get("blockable_from", []) or new.get("blocked_from") != before or not new.get("blocked_by"):
                        self.add("MG-011", identifier, "entrada em blocked inválida", path)
                elif before == "blocked":
                    if after != old.get("blocked_from"):
                        self.add("MG-011", identifier, "saída de blocked deve voltar a blocked_from", path)
                elif after == "cancelled" and before not in wf.get("terminal", []):
                    pass
                else:
                    edge = next((e for e in wf.get("transitions", []) if e.get("from") == before and e.get("to") == after), None)
                    if edge is None:
                        self.add("MG-010", identifier, f"transição inexistente: {before} → {after}", path)
                    else:
                        self.required_artifacts(path, new, head, wf, edge)
                        if edge.get("requires_evidence"):
                            self.required_evidence(path, new)
                        if gate := edge.get("requires_approval"):
                            self.approval(gate, new, reviews, author, sha, identifier, path)
            for gate, spec in wf.get("gates", {}).items():
                if not self.at_or_after(old, wf, spec.get("after_state", "")):
                    continue
                protected = set(spec.get("protects", []))
                artifact_paths = {
                    str(PurePosixPath(path).parent / a.get("path"))
                    for a in old.get("artifacts", [])
                    if isinstance(a, dict) and a.get("kind") in protected and isinstance(a.get("path"), str)
                }
                if artifact_paths.intersection(differences):
                    if approval_issue(gate, self.policy, new, reviews, author, sha):
                        self.add("MG-032", identifier, f"artefato protegido por {gate} mudou sem novo review", path)
            old_excs = {e.get("id"): e for e in old.get("exceptions", []) if isinstance(e, dict)}
            for exc in new.get("exceptions", []) if isinstance(new.get("exceptions"), list) else []:
                if isinstance(exc, dict) and old_excs.get(exc.get("id")) != exc:
                    self.approval("exception", new, reviews, author, sha, identifier, path)
                    if approval_issue("exception", self.policy, new, reviews, author, sha):
                        self.add("MG-061", identifier, "exceção nova ou alterada sem aprovação", path)
        if any(path.startswith(("scripts/", "config/", ".github/")) for path in differences):
            self.add_approval_platform(reviews, author, sha)
        return self.result()

    def add_approval_platform(self, reviews: list[dict], author: str, sha: str) -> None:
        if approval_issue("platform", self.policy, None, reviews, author, sha):
            self.add("MG-090", "PLATFORM", "mudança em scripts/, config/ ou .github/ sem aprovação platform", "config/policy.yml")

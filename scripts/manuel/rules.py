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
    if isinstance(value, dt.datetime):
        return False  # `datetime` herda de `date`, mas o contrato é só YYYY-MM-DD
    if isinstance(value, dt.date):
        return True
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return False
    try:
        dt.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def one_of(value: object, options: object) -> bool:
    """`value in options` sem TypeError quando `value` não é hashável (lista ou objeto no YAML)."""
    try:
        return value in options  # type: ignore[operator]
    except TypeError:
        return False


def section(item: dict, name: str) -> dict:
    value = item.get(name)
    return value if isinstance(value, dict) else {}


def date_value(value: object) -> dt.date:
    return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))


def protected_entries(item: dict, kinds: set[str]) -> set[tuple[str, str]]:
    """Pares (kind, path) das entradas de `artifacts` cujo tipo está sob proteção de um gate."""
    artifacts = item.get("artifacts")
    if not isinstance(artifacts, list):
        return set()
    return {
        (entry["kind"], entry["path"]) for entry in artifacts
        if isinstance(entry, dict) and isinstance(entry.get("kind"), str) and entry["kind"] in kinds
        and isinstance(entry.get("path"), str)
    }


def item_root(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) >= 4 and parts[0] == "projetos":
        return "/".join(parts[:4])
    return None


class ItemError(ValueError):
    """item.yml que não pode ser lido com segurança; vira violação MG-002, não erro de uso."""


MAX_ITEM_BYTES = 256 * 1024


def load_item(repo: Path, rev: str, path: str) -> dict | None:
    raw = read(repo, rev, path)
    if raw is None:
        return None
    if len(raw.encode("utf-8")) > MAX_ITEM_BYTES:
        raise ItemError(f"item.yml acima de {MAX_ITEM_BYTES // 1024} KB: {path}")
    try:
        # Alias YAML pode expandir o documento até estourar tempo e memória do CI.
        if any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(raw, Loader=yaml.SafeLoader)):
            raise ItemError(f"aliases YAML não são permitidos: {path}")
        value = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ItemError(f"YAML ilegível: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ItemError(f"item deve ser objeto YAML: {path}")
    return value


class Validator:
    def __init__(self, repo: Path, policy: dict, workflows: dict[str, dict], today: dt.date):
        self.repo = repo
        self.policy = policy
        self.workflows = workflows
        self.today = today
        self.issues: list[Issue] = []
        self.unreadable: set[tuple[str, str]] = set()

    def load(self, rev: str, path: str) -> dict | None:
        """Lê um item; se estiver ilegível, registra MG-002 e devolve None (já marcado em `unreadable`)."""
        try:
            return load_item(self.repo, rev, path)
        except ItemError as exc:
            self.unreadable.add((rev, path))
            self.add("MG-002", path, str(exc), path)
            return None

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
                item = self.load(rev, path)
                if item is not None:
                    output[str(item.get("id", path))] = (path, item)
        return output

    def structural(self, path: str, item: dict, rev: str, all_items: dict[str, tuple[str, dict]], full: bool, deep: bool | None = None) -> None:
        """`full` é o modo do `check-all` (exceção vencida vira aviso); `deep` revalida artefatos e
        evidências exigidos pelo estado do item e, por padrão, acompanha `full`."""
        deep = full if deep is None else deep
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
        if not one_of(item.get("nature"), NATURES) or not one_of(item.get("class"), {"S", "M", "L", "XL"}):
            self.add("MG-002", identifier, "nature ou class fora do enum", path)
        context = item.get("context") or {}
        if not isinstance(context, dict) or context.get("organization") != self.policy.get("organization") or not isinstance(context.get("repositories"), list) or not context.get("system") or not context.get("domain"):
            self.add("MG-002", identifier, "context inválido", path)
        owner = (item.get("ownership") or {}).get("owner") if isinstance(item.get("ownership"), dict) else None
        if not isinstance(owner, str) or owner not in self.policy.get("people", {}):
            self.add("MG-002", identifier, "ownership.owner ausente da policy.people", path)
        approvers = item["ownership"].get("approvers", {}) if isinstance(item.get("ownership"), dict) else {}
        if not isinstance(approvers, dict) or any(not isinstance(roles, list) or not all(isinstance(r, str) for r in roles) for roles in approvers.values()):
            self.add("MG-002", identifier, "ownership.approvers deve mapear cada gate a uma lista de papéis", path)
        lifecycle = item.get("lifecycle") or {}
        if not isinstance(lifecycle, dict) or not valid_date(lifecycle.get("createdAt")):
            self.add("MG-002", identifier, "lifecycle.createdAt inválido", path)
        wf_ref = item.get("workflow") or {}
        wf = self.workflows.get(wf_ref.get("id")) if isinstance(wf_ref, dict) and isinstance(wf_ref.get("id"), str) else None
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
                if not one_of(target, all_items):
                    self.add("MG-070", identifier, f"{field} aponta para item inexistente {target}", path)
        if item.get("parent") and not one_of(item["parent"], all_items):
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
            if not one_of(artifact.get("kind"), ARTIFACT_KINDS) or not one_of(artifact.get("produced_by"), {"agent", "human"}):
                self.add("MG-002", identifier, f"kind ou produced_by inválido em {relative}", path)
            if artifact.get("produced_by") == "agent":
                use = artifact.get("ai_use")
                if not isinstance(use, list) or not use or any(
                    not isinstance(event, dict) or event.get("schema") != "manuel-ai-use/1"
                    or not all(isinstance(event.get(field), str) and event[field].strip() for field in ("tool", "model", "session"))
                    or not one_of(event.get("role"), ROLES) for event in use
                ):
                    self.add("MG-040", identifier, f"ai_use ausente ou inválido em {relative}", path)
        evidence = item.get("evidence") or []
        if not isinstance(evidence, list):
            evidence = []
        for entry in evidence:
            if not isinstance(entry, dict) or not isinstance(entry.get("claim"), str) or not entry["claim"].strip() or not one_of(entry.get("status"), STATUSES) or (entry.get("requirement") and not one_of(entry["requirement"], req_ids)):
                self.add("MG-050", identifier, "evidence malformada", path)
                continue
            status = entry["status"]
            if status in {"observed", "confirmed"} and (not isinstance(entry.get("source"), str) or not entry["source"].strip()):
                self.add("MG-050", identifier, "evidence observada/confirmada sem source", path)
            if status == "confirmed" and (not one_of(entry.get("by"), self.policy.get("people", {})) or not valid_date(entry.get("date"))):
                self.add("MG-050", identifier, "evidence confirmada sem by/date", path)
            if status == "unknown" and (not one_of(entry.get("owner"), self.policy.get("people", {})) or not valid_date(entry.get("due"))):
                self.add("MG-050", identifier, "evidence desconhecida sem owner/due", path)
        for exception in item.get("exceptions", []) if isinstance(item.get("exceptions"), list) else []:
            if not isinstance(exception, dict) or not re.fullmatch(r"EXC-\d{4}-\d{3}", str(exception.get("id", ""))) or not isinstance(exception.get("waives"), list) or not exception["waives"] or any(not one_of(req, req_ids) for req in exception["waives"]) or not isinstance(exception.get("reason"), str) or not exception["reason"].strip() or not one_of(exception.get("requested_by"), self.policy.get("people", {})) or not valid_date(exception.get("expires")) or not exception.get("follow_up"):
                self.add("MG-060", identifier, "exceção malformada", path)
                continue
            if not one_of(exception["follow_up"], all_items):
                self.add("MG-063", identifier, f"follow_up inexistente: {exception['follow_up']}", path)
            if date_value(exception["expires"]) < self.today:
                self.add("MG-062", identifier, f"exceção vencida: {exception['id']}", path, warning=full)
        if deep and wf:
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
            if isinstance(e, dict) and isinstance(e.get("requirement"), str) and one_of(e.get("status"), {"observed", "confirmed"})
            and isinstance(e.get("source"), str) and e["source"].strip()
            and (e["status"] != "confirmed" or (one_of(e.get("by"), self.policy.get("people", {})) and valid_date(e.get("date"))))
        }
        covered.update(
            req for exc in exceptions if isinstance(exc, dict)
            and re.fullmatch(r"EXC-\d{4}-\d{3}", str(exc.get("id", "")))
            and isinstance(exc.get("waives"), list)
            and isinstance(exc.get("reason"), str) and exc["reason"].strip()
            and one_of(exc.get("requested_by"), self.policy.get("people", {}))
            and valid_date(exc.get("expires")) and exc.get("follow_up")
            for req in exc["waives"] if isinstance(req, str)
        )
        for req in requirements:
            if isinstance(req, dict) and isinstance(req.get("id"), str) and req.get("id") not in covered:
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
            old = self.load(base, path)
            new = self.load(head, path)
            identifier = str((new or old or {}).get("id") or path)
            if (head, path) in self.unreadable:
                continue  # o MG-002 já foi registrado; não é remoção
            if old and not new:
                self.add("MG-003", identifier, "item removido; use cancelled", path)
                continue
            if not new:
                continue
            self.structural(path, new, head, current, full=False, deep=True)
            wf_ref = new.get("workflow") or {}
            wf = self.workflows.get(wf_ref.get("id")) if isinstance(wf_ref, dict) and isinstance(wf_ref.get("id"), str) else None
            if not wf:
                continue
            if not old:
                if new.get("state") != "draft":
                    self.add("MG-005", identifier, "item novo deve nascer em draft", path)
                self.check_exceptions(None, new, reviews, author, sha, identifier, path)
                continue
            for field in ("id", "nature"):
                if old.get(field) != new.get(field):
                    self.add("MG-004", identifier, f"campo imutável alterado: {field}", path)
            for field in ("createdAt",):
                if section(old, "lifecycle").get(field) != section(new, "lifecycle").get(field):
                    self.add("MG-004", identifier, f"campo imutável alterado: lifecycle.{field}", path)
            if section(old, "context").get("organization") != section(new, "context").get("organization"):
                self.add("MG-004", identifier, "campo imutável alterado: context.organization", path)
            before, after = old.get("state"), new.get("state")
            if before != after:
                if before in wf.get("terminal", []):
                    self.add("MG-012", identifier, "estado terminal não pode mudar", path)
                elif after == "cancelled":
                    pass
                elif after == "blocked":
                    if before not in wf.get("blockable_from", []) or new.get("blocked_from") != before or not new.get("blocked_by"):
                        self.add("MG-011", identifier, "entrada em blocked inválida", path)
                elif before == "blocked":
                    if after != old.get("blocked_from"):
                        self.add("MG-011", identifier, "saída de blocked deve voltar a blocked_from", path)
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
            elif before == "blocked" and old.get("blocked_from") != new.get("blocked_from"):
                self.add("MG-011", identifier, "blocked_from é imutável enquanto o item está bloqueado", path)
            for gate, spec in wf.get("gates", {}).items():
                if not self.at_or_after(old, wf, spec.get("after_state", "")):
                    continue
                protected = {kind for kind in spec.get("protects", []) if isinstance(kind, str)}
                before_entries = protected_entries(old, protected)
                after_entries = protected_entries(new, protected)
                folder = PurePosixPath(path).parent
                artifact_paths = {str(folder / relative) for _, relative in before_entries | after_entries}
                # Mudou o conteúdo de um artefato protegido OU o próprio bloco `artifacts` (caminho,
                # tipo, entrada acrescentada ou removida): trocar o caminho não pode fugir do review.
                if before_entries != after_entries or artifact_paths.intersection(differences):
                    if approval_issue(gate, self.policy, new, reviews, author, sha):
                        self.add("MG-032", identifier, f"artefato protegido por {gate} mudou sem novo review", path)
            self.check_exceptions(old, new, reviews, author, sha, identifier, path)
        if any(path.startswith(("scripts/", "config/", ".github/")) for path in differences):
            self.add_approval_platform(reviews, author, sha)
        return self.result()

    def check_exceptions(self, old: dict | None, new: dict, reviews: list[dict], author: str, sha: str, identifier: str, path: str) -> None:
        """Toda exceção nova ou alterada exige o gate `exception`; num item novo, todas são novas."""
        previous = (old or {}).get("exceptions")
        known = {repr(e.get("id")): e for e in previous if isinstance(e, dict)} if isinstance(previous, list) else {}
        current = new.get("exceptions")
        for exc in current if isinstance(current, list) else []:
            if isinstance(exc, dict) and known.get(repr(exc.get("id"))) != exc:
                self.approval("exception", new, reviews, author, sha, identifier, path)
                if approval_issue("exception", self.policy, new, reviews, author, sha):
                    self.add("MG-061", identifier, "exceção nova ou alterada sem aprovação", path)

    def add_approval_platform(self, reviews: list[dict], author: str, sha: str) -> None:
        if approval_issue("platform", self.policy, None, reviews, author, sha):
            self.add("MG-090", "PLATFORM", "mudança em scripts/, config/ ou .github/ sem aprovação platform", "config/policy.yml")

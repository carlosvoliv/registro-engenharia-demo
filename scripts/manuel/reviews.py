from __future__ import annotations

import json
import re
from pathlib import Path


DECISIVE = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}


def load_reviews(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"reviews JSON ilegível: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("reviews deve ser lista JSON")
    if data and all(isinstance(part, list) for part in data):
        data = [review for part in data for review in part]
    if not all(isinstance(review, dict) for review in data):
        raise ValueError("reviews contém entrada inválida")
    return data


def last_decisive(reviews: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    ordered = sorted(reviews, key=lambda r: (str(r.get("submitted_at") or ""), int(r.get("id") or 0)))
    for review in ordered:
        login = str((review.get("user") or {}).get("login") or "").casefold()
        if login and str(review.get("state", "")).upper() in DECISIVE:
            result[login] = review
    return result


def approval_issue(
    gate: str, policy: dict, item: dict | None, reviews: list[dict],
    author: str, head_sha: str,
) -> tuple[str, str] | None:
    gate_policy = policy.get("gates", {}).get(gate, {})
    roles = set(gate_policy.get("approver_roles", []))
    # Tipo errado em ownership/approvers não derruba o validador: a restrição inválida
    # zera os papéis (falha fechada, MG-024) e o `structural` aponta o MG-002 no item.
    ownership = (item or {}).get("ownership")
    restrictions = ownership.get("approvers") if isinstance(ownership, dict) else None
    if isinstance(restrictions, dict) and gate in restrictions:
        allowed = restrictions[gate]
        roles &= {role for role in allowed if isinstance(role, str)} if isinstance(allowed, list) else set()
    configured = {
        str(login).casefold()
        for role in roles
        for login in policy.get("approvers", {}).get(role, [])
        if isinstance(login, str) and not re.fullmatch(r"<.*>", login)
    }
    if not configured:
        return "MG-024", f"aprovador do gate {gate} não configurado"
    decisions = last_decisive(reviews)
    approved = [
        (login, review) for login, review in decisions.items()
        if str(review.get("state", "")).upper() == "APPROVED"
    ]
    for login, review in approved:
        if login in configured and login != author.casefold() and review.get("commit_id") == head_sha:
            return None
    if any(login == author.casefold() and login in configured for login, _ in approved):
        return "MG-022", f"autor do PR não pode aprovar o gate {gate}"
    if any(login in configured and review.get("commit_id") != head_sha for login, review in approved):
        return "MG-021", f"review do gate {gate} pertence a commit antigo"
    if any(str(review.get("state", "")).upper() in {"CHANGES_REQUESTED", "DISMISSED"} for login, review in decisions.items() if login in configured):
        return "MG-025", f"último review decisivo do gate {gate} não é aprovação"
    if approved:
        return "MG-023", f"reviewer não tem papel autorizado para o gate {gate}"
    return "MG-020", f"falta aprovação do gate {gate}"

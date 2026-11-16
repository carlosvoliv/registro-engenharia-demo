"""Visões geradas do registro: os `item.yml` em uma revisão e a idade na etapa derivada do histórico do git.

Nada aqui é gravado no registro nem decide coisa alguma: a fonte da verdade são os itens; a visão é descartável e
regenerável. Um item ilegível não derruba a visão: entra em «problemas».
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
from collections import Counter
from pathlib import Path

from .config import load
from .gitread import files, git, read
from .rules import ItemError, date_value, load_item

STATE_LABEL = {
    "draft": "rascunho", "investigating": "em investigação", "specified": "especificado",
    "awaiting-approval": "aguardando aprovação", "planned": "planejado", "implementing": "em execução",
    "reviewing": "em revisão", "released": "liberado", "closed": "encerrado", "blocked": "bloqueado",
    "cancelled": "cancelado", "superseded": "substituído", "concluded": "concluído",
}
PHASE = {
    "draft": "entrada", "investigating": "entrada", "specified": "entrada", "concluded": "entrada",
    "awaiting-approval": "planejamento", "planned": "planejamento", "implementing": "execução",
    "reviewing": "revisão", "released": "pós-entrega", "closed": "pós-entrega",
}
NATURE_LABEL = {"feature": "entrega de produto", "defect": "correção", "incident": "incidente", "investigation": "investigação", "technical-work": "trabalho técnico"}
EPISTEMIC = {"observed": "observado", "confirmed": "confirmado", "inferred": "inferido", "unknown": "desconhecido"}
LEDGER = "registro/aprovacoes.jsonl"
DELIVERY = {"reviewing", "released", "closed"}  # a partir daqui o prometido é comparado ao entregue


def as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def label(state: str) -> str:
    return STATE_LABEL.get(state, state)


def nature(value: str) -> str:
    return NATURE_LABEL.get(value, value)


def days(n: int) -> str:
    return f"{n} dia" if abs(n) == 1 else f"{n} dias"


def item_paths(repo: Path, rev: str) -> list[str]:
    result = []
    for path in sorted(files(repo, rev)):
        parts = path.split("/")
        if len(parts) == 5 and parts[0] == "projetos" and parts[4] == "item.yml":
            result.append(path)
    return result


def state_since(repo: Path, rev: str, path: str, state: str) -> dt.date | None:
    """Data do primeiro commit da sequência ininterrupta, até `rev`, em que o item está em `state`."""
    since = None
    for line in git(repo, "log", "--format=%H%x09%aI", rev, "--", path).splitlines():
        sha, _, stamp = line.partition("\t")
        try:
            item = load_item(repo, sha, path)
        except ItemError:
            break
        if not item or item.get("state") != state:
            break
        since = dt.datetime.fromisoformat(stamp).date()
    return since


def read_ledger(repo: Path, rev: str) -> list[dict]:
    raw = read(repo, rev, LEDGER) or ""
    result = []
    for line in raw.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("item"), str):
            result.append(entry)
    return result


def next_gate(workflow: dict, item: dict, policy: dict) -> dict | None:
    """Aprovação que o item precisa receber para sair do estado atual, e quem pode dá-la."""
    state = item.get("state")
    order = as_list(workflow.get("state_order"))
    if state not in order:
        return None
    for edge in as_list(workflow.get("transitions")):
        gate = as_dict(edge).get("requires_approval")
        target = as_dict(edge).get("to")
        if as_dict(edge).get("from") == state and gate and target in order and order.index(target) > order.index(state):
            restricted = as_list(as_dict(as_dict(item.get("ownership")).get("approvers")).get(gate))
            roles = [r for r in restricted if isinstance(r, str)] or as_list(as_dict(as_dict(policy.get("gates")).get(gate)).get("approver_roles"))
            people = [name.title() for name, data in as_dict(policy.get("people")).items() if as_dict(data).get("role") in roles]
            return {"gate": gate, "roles": roles, "people": people}
    return None


def build_item(repo: Path, rev: str, path: str, item: dict, today: dt.date, policy: dict, workflows: dict, ledger: list[dict]) -> dict:
    identifier = text(item.get("id"), path.split("/")[3])
    state = text(item.get("state"))
    since = state_since(repo, rev, path, state)
    ownership = as_dict(item.get("ownership"))
    workflow = as_dict(workflows.get(text(as_dict(item.get("workflow")).get("id"))))
    evidence = [e for e in as_list(item.get("evidence")) if isinstance(e, dict)]
    exceptions = []
    for exception in (e for e in as_list(item.get("exceptions")) if isinstance(e, dict)):
        approvals = [a for a in ledger if a.get("exception") == exception.get("id") and a.get("gate") == "exception"]
        expires = exception.get("expires")
        exceptions.append({
            "id": text(exception.get("id")), "waives": [w for w in as_list(exception.get("waives")) if isinstance(w, str)],
            "reason": text(exception.get("reason")), "requested_by": text(exception.get("requested_by")),
            "expires": str(expires) if expires else "", "follow_up": text(exception.get("follow_up")),
            "days_left": (date_value(expires) - today).days if expires else None, "approvals": approvals,
        })
    unknown = [{
        "claim": text(e.get("claim")), "owner": text(e.get("owner")), "due": str(e.get("due") or ""),
        "requirement": text(e.get("requirement")),
        "days_left": (date_value(e["due"]) - today).days if e.get("due") else None,
    } for e in evidence if e.get("status") == "unknown"]
    waived = {w for e in exceptions for w in e["waives"]}
    coverage = []
    for requirement in (r for r in as_list(item.get("requirements")) if isinstance(r, dict)):
        rid = text(requirement.get("id"))
        mine = [e for e in evidence if e.get("requirement") == rid]
        proof = next((e for e in mine if e.get("status") in {"observed", "confirmed"}), None)
        if proof:
            basis = "observado" if proof["status"] == "observed" else f"confirmado por {text(proof.get('by'), '?')} em {proof.get('date', '?')}"
            status = "verificado"
        elif rid in waived:
            status, basis = "exceção", "dispensado por " + ", ".join(e["id"] for e in exceptions if rid in e["waives"])
        elif any(e.get("status") == "unknown" for e in mine):
            status, basis = "desconhecido", "ainda não medido ou confirmado"
        else:
            status, basis = "sem evidência", ""
        coverage.append({"id": rid, "text": text(requirement.get("text")), "status": status, "basis": basis})
    artifacts, tools, agent_total, agent_marked = [], set(), 0, 0
    for artifact in (a for a in as_list(item.get("artifacts")) if isinstance(a, dict)):
        relative = text(artifact.get("path"))
        events = [ev for ev in as_list(artifact.get("ai_use")) if isinstance(ev, dict)]
        if artifact.get("produced_by") == "agent":
            agent_total += 1
            agent_marked += bool(events)
            tools.update(text(ev.get("tool")) for ev in events if ev.get("tool"))
        artifacts.append({"path": f"{path.rsplit('/', 1)[0]}/{relative}", "kind": text(artifact.get("kind")), "produced_by": text(artifact.get("produced_by")), "tools": sorted({text(ev.get("tool")) for ev in events})})
    return {
        "id": identifier, "title": text(item.get("title")), "nature": text(item.get("nature")), "class": text(item.get("class")),
        "state": state, "path": path, "owner": text(ownership.get("owner")),
        "created": str(as_dict(item.get("lifecycle")).get("createdAt") or ""),
        "since": since.isoformat() if since else "", "age": max(0, (today - since).days) if since else None,
        "blocked_from": text(item.get("blocked_from")), "blocked_by": [b for b in as_list(item.get("blocked_by")) if isinstance(b, str)],
        "relations": [{"type": text(r.get("type")), "target": text(r.get("target"))} for r in as_list(item.get("relations")) if isinstance(r, dict)],
        "gate": next_gate(workflow, item, policy), "coverage": coverage, "exceptions": exceptions, "unknown": unknown,
        "evidence": dict(Counter(text(e.get("status")) for e in evidence)),
        "artifacts": artifacts, "ai": {"tools": sorted(tools), "agent_total": agent_total, "agent_marked": agent_marked},
        "approvals": [a for a in ledger if a.get("item") == identifier],
    }


def collect(repo: Path, rev: str = "HEAD", today: dt.date | None = None, config_dir: Path | None = None) -> dict:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    policy, workflows, _ = load(config_dir or repo / "config")
    sha = git(repo, "rev-parse", rev).strip()
    ledger = read_ledger(repo, rev)
    items, problems = [], []
    for path in item_paths(repo, rev):
        try:
            item = load_item(repo, rev, path)
            if item is None:
                continue
            items.append(build_item(repo, rev, path, item, today, policy, workflows, ledger))
        except (ItemError, ValueError, TypeError, KeyError, AttributeError) as exc:
            problems.append({"path": path, "message": str(exc)})
    by_id = {i["id"]: i for i in items}
    for item in items:
        item["blocks"] = sorted({r["target"] for r in item["relations"] if r["type"] == "blocks"} | {o["id"] for o in items if item["id"] in o["blocked_by"]})
        item["blockers"] = [{"id": b, "state": by_id[b]["state"], "age": by_id[b]["age"]} if b in by_id else {"id": b, "state": "", "age": None} for b in item["blocked_by"]]
    return {
        "organization": text(policy.get("organization")), "commit": sha, "today": today.isoformat(),
        "items": items, "problems": problems, "metrics_forbidden": [m for m in as_list(as_dict(policy.get("metrics")).get("forbidden")) if isinstance(m, str)],
    }


def summary(model: dict) -> dict:
    items = model["items"]
    return {
        "total": len(items),
        "waiting": sum(1 for i in items if i["gate"] and i["state"] in {"awaiting-approval", "reviewing"}),
        "blocked": sum(1 for i in items if i["state"] == "blocked"),
        "with_exception": sum(1 for i in items if i["exceptions"] and i["state"] in {"released", "closed"}),
        "open_gaps": sum(len(i["unknown"]) for i in items),
    }


def coverage_line(item: dict) -> str:
    cov = item["coverage"]
    if not cov:
        return "sem requisitos"
    if item["state"] not in DELIVERY:
        return f"{len(cov)} {'prometido' if len(cov) == 1 else 'prometidos'}; a verificação começa na revisão"
    parts = []
    for name, group in (("funcionais", [c for c in cov if not c["id"].startswith("RNF")]), ("não funcionais", [c for c in cov if c["id"].startswith("RNF")])):
        if not group:
            continue
        done = sum(c["status"] == "verificado" for c in group)
        extras = [f"{n} {'por exceção' if st == 'exceção' else st}" for st in ("exceção", "desconhecido", "sem evidência") if (n := sum(c["status"] == st for c in group))]
        parts.append(f"{done} de {len(group)} {name} verificados" + (f" ({', '.join(extras)})" if extras else ""))
    return "; ".join(parts)


def when(n: int | None, prefix: str = "há ") -> str:
    return "—" if n is None else ("hoje" if n == 0 and not prefix.strip() else f"{prefix}{days(n)}")


def deadline(n: int | None) -> str:
    if n is None:
        return "sem prazo"
    return f"vencido há {days(-n)}" if n < 0 else ("vence hoje" if n == 0 else f"faltam {days(n)}")


def attention(model: dict) -> list[tuple[str, str]]:
    """(item, frase) do que precisa de decisão, na ordem: aprovações, bloqueios, exceções, lacunas."""
    result = []
    for i in model["items"]:
        if i["gate"] and i["state"] in {"awaiting-approval", "reviewing"}:
            who = ", ".join(i["gate"]["people"]) or ", ".join(i["gate"]["roles"])
            result.append((i["id"], f"aguarda a aprovação do gate «{i['gate']['gate']}» ({'/'.join(i['gate']['roles'])}: {who}), {when(i['age'], 'na etapa há ')}"))
    for i in model["items"]:
        if i["state"] == "blocked":
            blockers = ", ".join(f"{b['id']} ({label(b['state'])}{', ' + when(b['age']) if b['age'] is not None else ''})" for b in i["blockers"]) or "sem bloqueador informado"
            result.append((i["id"], f"bloqueado por {blockers}"))
    for i in model["items"]:
        for e in i["exceptions"]:
            approved = "; ".join(f"aprovada por {str(a.get('persona', '?')).title()} ({a.get('role', '?')}) em {a.get('date', '?')}" for a in e["approvals"]) or "sem aprovação no ledger"
            result.append((i["id"], f"exceção {e['id']} dispensa {', '.join(e['waives'])} ({e['reason']}); {approved}; {deadline(e['days_left'])}, acompanhamento em {e['follow_up'] or '—'}"))
    for i in model["items"]:
        for u in i["unknown"]:
            result.append((i["id"], f"lacuna: {u['claim']} (responsável {u['owner'].title() or '—'}; {deadline(u['days_left'])})"))
    return result


def render_markdown(model: dict) -> str:
    s = summary(model)
    out = [
        "# Índice do registro (gerado)", "",
        f"Gerado do git: commit `{model['commit'][:12]}`, referência {model['today']}, organização {model['organization']} (dados fictícios). "
        "A fonte da verdade são os `item.yml`; este índice é derivado e descartável. «Na etapa há N dias» vem do histórico do git do `item.yml`.", "",
        f"Itens: {s['total']} · aguardando aprovação: {s['waiting']} · bloqueados: {s['blocked']} · entregues com exceção: {s['with_exception']} · lacunas abertas: {s['open_gaps']}", "",
        "## Itens", "", "| ID | Título | Estado | Responsável | Na etapa desde | Dias | Arquivo |", "|---|---|---|---|---|---|---|",
    ]
    for i in model["items"]:
        out.append(f"| {i['id']} | {i['title']} | {i['state']} | {i['owner'].title()} | {i['since'] or '—'} | {'' if i['age'] is None else i['age']} | `{i['path']}` |")
    out += ["", "## Precisa de atenção", ""]
    out += [f"- **{item}**: {phrase}" for item, phrase in attention(model)] or ["- nada pendente"]
    out += ["", "## Detalhe por item", ""]
    for i in model["items"]:
        out += [f"### {i['id']} — {i['title']}", "",
                f"- Estado: {i['state']} ({label(i['state'])}); na etapa desde {i['since'] or '—'} ({when(i['age'])}); criado em {i['created'] or '—'}; fonte: `{i['path']}` e o histórico do git dele.",
                f"- Natureza e classe: {nature(i['nature'])}, classe {i['class']}. Responsável: {i['owner'].title()}."]
        if i["gate"]:
            out.append(f"- Para avançar: aprovação do gate «{i['gate']['gate']}» (papéis {', '.join(i['gate']['roles'])}; pessoas {', '.join(i['gate']['people']) or '—'}). Enquanto não houver aprovação registrada, o que está nos artefatos é proposta, não decisão.")
        if i["state"] == "blocked":
            out.append(f"- Bloqueado (estava em {i['blocked_from'] or '—'}) por: " + (", ".join(f"{b['id']} [{b['state'] or 'não encontrado'}]" for b in i["blockers"]) or "—"))
        if i["blocks"]:
            out.append(f"- Bloqueia ou é pré-requisito de: {', '.join(i['blocks'])}")
        for r in i["relations"]:
            out.append(f"- Relação `{r['type']}` com {r['target']}")
        for e in i["exceptions"]:
            approved = "; ".join(f"{str(a.get('persona')).title()} ({a.get('role')}) em {a.get('date')}, origem {a.get('source')}" for a in e["approvals"]) or "sem aprovação no ledger"
            out.append(f"- Exceção {e['id']}: dispensa {', '.join(e['waives'])}; motivo: {e['reason']}; pedida por {e['requested_by'].title()}; aprovação: {approved}; expira {e['expires']} ({deadline(e['days_left'])}); acompanhamento: {e['follow_up']}. Fonte: `{i['path']}` e `{LEDGER}`.")
        if i["coverage"] and i["state"] in DELIVERY:
            out.append(f"- Requisitos, prometido × entregue ({coverage_line(i)}): " + "; ".join(f"{c['id']} {c['status']}" + (f" ({c['basis']})" if c["basis"] else "") for c in i["coverage"]) + f". Fonte: `{i['path']}`.")
        elif i["coverage"]:
            out.append(f"- Requisitos prometidos, ainda não entregues (a verificação começa na revisão): {', '.join(c['id'] for c in i['coverage'])}. Fonte: `{i['path']}`.")
        if i["evidence"]:
            out.append("- Evidências por estado: " + ", ".join(f"{EPISTEMIC.get(k, k)} {v}" for k, v in sorted(i["evidence"].items())) + f". Fonte: `{i['path']}`.")
        for u in i["unknown"]:
            out.append(f"- Desconhecido: {u['claim']} Responsável {u['owner'].title() or '—'}, prazo {u['due'] or '—'} ({deadline(u['days_left'])}); requisito {u['requirement'] or '—'}.")
        for a in i["artifacts"]:
            out.append(f"- Artefato `{a['path']}` ({a['kind']}, produzido por {a['produced_by']}" + (f", ferramenta {', '.join(t for t in a['tools'] if t)}" if a["tools"] else "") + ")")
        for a in i["approvals"]:
            if not a.get("exception"):
                out.append(f"- Aprovação registrada: gate {a.get('gate')}, {str(a.get('persona')).title()} ({a.get('role')}) em {a.get('date')}, origem {a.get('source')}. Fonte: `{LEDGER}`.")
        out.append("")
    if model["problems"]:
        out += ["## Problemas", ""] + [f"- `{p['path']}`: {p['message']}" for p in model["problems"]] + [""]
    out.append("Esta visão descreve itens e times; não mede nem ranqueia pessoas.")
    return "\n".join(out) + "\n"


CSS = """
:root{--bg:#f7f7f4;--fg:#1d2327;--muted:#59636a;--card:#fff;--line:#d9dcd6;--accent:#0b5c8a;--warn:#8a4b00;--warnbg:#fff1dc;--ok:#1f6b3a;--okbg:#e4f3e8;--bad:#9b1c1c;--badbg:#fbe7e7}
@media (prefers-color-scheme:dark){:root{--bg:#14181b;--fg:#e8ebed;--muted:#a1abb2;--card:#1d2328;--line:#343c43;--accent:#6bb7e6;--warn:#f1b86c;--warnbg:#3a2c14;--ok:#7fd49b;--okbg:#17301f;--bad:#f19a9a;--badbg:#3d1c1c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}h1{font-size:1.7rem;margin:0}h2{font-size:1.15rem;margin:32px 0 10px}
.meta{color:var(--muted);margin:4px 0 20px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.card b{display:block;font-size:1.9rem;line-height:1.1}.card span{color:var(--muted);font-size:.9rem}
ul.attn{list-style:none;margin:0;padding:0;display:grid;gap:8px}ul.attn li{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:8px;padding:10px 12px}
.tablewrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}table{border-collapse:collapse;width:100%;min-width:720px}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:.85rem;color:var(--muted);font-weight:600}tr:last-child td{border-bottom:0}
a{color:var(--accent)}.chip{display:inline-block;padding:1px 9px;border-radius:999px;font-size:.85rem;border:1px solid var(--line);background:var(--bg);white-space:nowrap}
.chip.warn{color:var(--warn);background:var(--warnbg);border-color:var(--warn)}.chip.ok{color:var(--ok);background:var(--okbg);border-color:var(--ok)}.chip.bad{color:var(--bad);background:var(--badbg);border-color:var(--bad)}
.small{font-size:.9rem;color:var(--muted)}td.nw{white-space:nowrap}footer{margin-top:36px;color:var(--muted);font-size:.9rem;border-top:1px solid var(--line);padding-top:12px}
"""


def chip(state: str, item: dict) -> str:
    kind = "warn" if state in {"awaiting-approval", "blocked"} else ("ok" if state in {"released", "closed"} else "")
    extra = ' <span class="chip warn">com exceção</span>' if item["exceptions"] and state in {"released", "closed"} else ""
    return f'<span class="chip {kind}">{html.escape(label(state))}</span>{extra}'


def render_html(model: dict, out_dir: Path, repo: Path) -> str:
    esc = html.escape

    def link(path: str, shown: str) -> str:
        return f'<a href="{esc(os.path.relpath(repo / path, out_dir).replace(os.sep, "/"))}">{esc(shown)}</a>'

    s = summary(model)
    cards = "".join(f'<div class="card"><b>{n}</b><span>{esc(t)}</span></div>' for n, t in (
        (s["total"], "itens no registro"), (s["waiting"], "aguardando aprovação"), (s["blocked"], "bloqueados"),
        (s["with_exception"], "entregues com exceção"), (s["open_gaps"], "lacunas abertas, com responsável")))
    attn = "".join(f'<li><b>{esc(item)}</b>: {esc(phrase)}</li>' for item, phrase in attention(model)) or "<li>Nada pendente.</li>"
    rows = ""
    for i in model["items"]:
        rows += ("<tr><td class=\"nw\">" + link(i["path"], i["id"]) + f"</td><td>{esc(i['title'])}<br><span class=\"small\">{esc(nature(i['nature']))}, classe {esc(i['class'])}</span></td>"
                 f"<td>{chip(i['state'], i)}<br><span class=\"small\">{esc(PHASE.get(i['state'], ''))}</span></td><td>{esc(i['owner'].title())}</td>"
                 f"<td>{esc(coverage_line(i))}</td>"
                 f"<td class=\"nw\">{esc(i['since'] or '—')}<br><span class=\"small\">{esc(when(i['age']))}</span></td></tr>")
    ai_rows = "".join(
        f"<tr><td>{esc(i['id'])}</td><td>{esc(', '.join(i['ai']['tools']) or '—')}</td><td>{i['ai']['agent_marked']} de {i['ai']['agent_total']}</td></tr>"
        for i in model["items"])
    problems = ("<h2>Problemas na leitura</h2><ul>" + "".join(f"<li>{esc(p['path'])}: {esc(p['message'])}</li>" for p in model["problems"]) + "</ul>") if model["problems"] else ""
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Visão executiva — {esc(model['organization'])}</title><style>{CSS}</style></head>
<body><main>
<h1>Visão executiva</h1>
<p class="meta">{esc(model['organization'])} · gerada do git (commit {esc(model['commit'][:12])}) · referência {esc(model['today'])} · dados fictícios</p>
<div class="cards">{cards}</div>
<h2>Precisa de atenção</h2><ul class="attn">{attn}</ul>
<h2>Itens</h2><div class="tablewrap"><table><thead><tr><th>Item</th><th>Título</th><th>Estado</th><th>Responsável</th><th>Requisitos</th><th>Na etapa desde</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>Uso de IA nos artefatos</h2><div class="tablewrap"><table><thead><tr><th>Item</th><th>Ferramentas registradas</th><th>Artefatos de agente com marca</th></tr></thead><tbody>{ai_rows}</tbody></table></div>
{problems}
<footer>Esta visão descreve itens e times; não mede nem ranqueia pessoas (política em {link('config/policy.yml', 'config/policy.yml')}). A fonte da verdade são os arquivos do registro e o histórico do git; esta página é descartável e regenerável.</footer>
</main></body></html>
"""

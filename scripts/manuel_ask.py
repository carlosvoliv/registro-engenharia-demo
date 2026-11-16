#!/usr/bin/env python3
"""Pergunte ao registro: o agente de pergunta lê só o repositório e a resposta tem as fontes conferidas."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from manuel.ask import AskError, Verification, ask, verify


def block(result: Verification, repo: Path) -> str:
    lines = ["", "--- verificação das fontes ---", f"tipo: {result.kind}"]
    lines.append(f"fontes citadas: {len(result.cited)}; inexistentes: {len(result.missing)}")
    lines += [f"  NÃO EXISTE: {path}" for path in result.missing]
    if result.kind == "sem fonte":
        lines.append("  a resposta não cita arquivo do registro nem diz que não consta")
    lines.append("resultado: " + ("ok" if result.ok else "REPROVADA, não use esta resposta"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pergunta ao registro fictício do Manuel")
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("perguntar", help="faz uma pergunta ao agente (precisa do `claude` instalado e logado)")
    one.add_argument("pergunta")
    one.add_argument("--repo", default=".")
    one.add_argument("--today", help="data de referência AAAA-MM-DD")
    one.add_argument("--model")
    one.add_argument("--timeout", type=int, default=180)
    one.add_argument("--salvar", help="grava pergunta, resposta e verificação neste arquivo Markdown")
    check = sub.add_parser("verificar", help="confere as fontes de uma resposta já escrita (arquivo ou - para a entrada padrão)")
    check.add_argument("arquivo")
    check.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    try:
        if args.command == "verificar":
            answer = sys.stdin.read() if args.arquivo == "-" else Path(args.arquivo).read_text(encoding="utf-8")
            result = verify(answer, repo)
        else:
            today = dt.date.fromisoformat(args.today) if args.today else None
            answer, result = ask(repo, args.pergunta, today, args.model, args.timeout)
            print(answer)
            if args.salvar:
                Path(args.salvar).write_text(f"# Pergunta\n\n{args.pergunta}\n\n# Resposta\n\n{answer}\n\n```text{block(result, repo)}\n```\n", encoding="utf-8")
    except (AskError, ValueError, OSError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    print(block(result, repo))
    return 0 if result.ok else 3


if __name__ == "__main__":
    raise SystemExit(main())

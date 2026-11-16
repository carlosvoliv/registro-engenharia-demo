#!/usr/bin/env python3
"""Ato 2: um segundo agente (Codex) retoma um item só pelo registro; o Manuel confere, registra a marca de uso e roda o gate."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from manuel.gitread import git
from manuel.resume import ResumeError, apply_branch, discard, make_codex_runner, resume


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retomada de um item por um segundo agente")
    parser.add_argument("item", help="ID do item, por exemplo TECH-2026-005")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--modelo")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--aplicar", action="store_true", help="traz a branch da retomada para este repositório (sem trocar de branch)")
    parser.add_argument("--patch", help="grava o diff da retomada neste arquivo")
    parser.add_argument("--descartar", action="store_true", help="apaga o clone temporário ao terminar")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    try:
        result = resume(repo, args.item, make_codex_runner(args.modelo, args.timeout), "codex", log=lambda m: print(f"- {m}", flush=True))
    except (ResumeError, OSError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    print("\n--- o que o agente respondeu ---\n" + result.summary)
    print("\n--- marca de uso registrada pelo Manuel ---")
    print("  " + ", ".join(f"{k}={v}" for k, v in result.event.items()))
    print("\n--- arquivos ---")
    print(git(result.clone, "diff", "--stat", result.base, result.head).rstrip())
    print("\n--- gate sobre a diferença ---\n" + result.gate_output)
    if args.patch:
        Path(args.patch).write_text(git(result.clone, "diff", result.base, result.head), encoding="utf-8")
    if args.aplicar and result.gate_ok:
        apply_branch(repo, result)
        print(f"\nbranch {result.branch} trazida para {repo}")
    print(f"\nclone: {result.clone}" if not args.descartar else "")
    if args.descartar:
        discard(result)
    return 0 if result.gate_ok else 3


if __name__ == "__main__":
    raise SystemExit(main())

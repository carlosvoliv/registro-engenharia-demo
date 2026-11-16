#!/usr/bin/env python3
"""Gera as visões do registro (executiva em HTML e índice em Markdown) a partir do git."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from manuel.views import collect, render_html, render_markdown, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera as visões do registro fictício do Manuel")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--rev", default="HEAD", help="revisão lida (padrão: HEAD)")
    parser.add_argument("--today", help="data de referência AAAA-MM-DD (padrão: hoje, em UTC)")
    parser.add_argument("--out-dir", default="views", help="pasta de saída, relativa ao repo (padrão: views)")
    args = parser.parse_args(argv)
    try:
        repo = Path(args.repo).resolve()
        out_dir = (repo / args.out_dir).resolve()
        today = dt.date.fromisoformat(args.today) if args.today else None
        model = collect(repo, args.rev, today)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "executiva.html").write_text(render_html(model, out_dir, repo), encoding="utf-8")
        (out_dir / "INDEX.md").write_text(render_markdown(model), encoding="utf-8")
    except (ValueError, OSError) as exc:
        print(f"Uso incorreto: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - erro interno sai com 2, sem traceback
        print(f"erro interno do gerador: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    s = summary(model)
    print(f"{s['total']} item(ns) a partir de {model['commit'][:12]}, referência {model['today']}; {len(model['problems'])} problema(s)")
    print(f"  {out_dir / 'executiva.html'}\n  {out_dir / 'INDEX.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

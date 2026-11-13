#!/usr/bin/env python3
"""Gate offline do Manuel; a rede pertence ao workflow que fornece reviews.json."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from manuel.config import load
from manuel.gitread import git
from manuel.reviews import load_reviews
from manuel.rules import Issue, Validator


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Valida o registro fictício do Manuel")
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("check", "check-all"):
        command = sub.add_parser(name)
        command.add_argument("--repo", default=".")
        command.add_argument("--config-dir")
        command.add_argument("--today")
        command.add_argument("--format", choices=("text", "github"), default="text")
        if name == "check":
            command.add_argument("--base", required=True)
            command.add_argument("--head", required=True)
            command.add_argument("--reviews", required=True)
            command.add_argument("--pr-author", required=True)
            command.add_argument("--head-sha")
    return result


def escape(value: str, prop: bool = False) -> str:
    """Escapa o valor de um workflow command do GitHub; nas propriedades (`file=`, `title=`) também `:` e `,`."""
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return value.replace(":", "%3A").replace(",", "%2C") if prop else value


def report(issues: list[Issue], style: str) -> int:
    for issue in issues:
        if style == "github":
            level = "warning" if issue.warning else "error"
            print(f"::{level} file={escape(issue.path, True)},title={escape(issue.code, True)}::{escape(issue.message)}")
        else:
            label = " AVISO" if issue.warning else ""
            print(f"{issue.code}{label} [{issue.item}] {issue.message}")
    errors = sum(not issue.warning for issue in issues)
    warnings = len(issues) - errors
    print(f"Resumo: {errors} erro(s), {warnings} aviso(s)")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    repo = Path(args.repo).resolve()
    config_dir = Path(args.config_dir).resolve() if args.config_dir else repo / "config"
    try:
        today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
        policy, workflows, config_errors = load(config_dir)
        validator = Validator(repo, policy, workflows, today)
        for error in config_errors:
            validator.add("MG-080", "CONFIG", error, str(config_dir / "policy.yml"))
        if args.command == "check-all":
            validator.check_all()
        else:
            reviews = load_reviews(Path(args.reviews))
            sha = args.head_sha or git(repo, "rev-parse", args.head if args.head != "WORKTREE" else "HEAD").strip()
            validator.check(args.base, args.head, reviews, args.pr_author, sha)
        return report(validator.result(), args.format)
    except (ValueError, OSError) as exc:
        print(f"Uso incorreto: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - exit 1 é «há violação»; erro interno sai com 2, sem traceback
        print(f"erro interno do validador: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

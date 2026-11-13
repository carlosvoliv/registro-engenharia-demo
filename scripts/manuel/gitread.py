from __future__ import annotations

import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or f"git {' '.join(args)} falhou")
    return result.stdout


def files(repo: Path, rev: str) -> set[str]:
    if rev == "WORKTREE":
        return {
            str(path.relative_to(repo))
            for path in repo.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(repo).parts
        }
    return set(filter(None, git(repo, "ls-tree", "-r", "--name-only", rev).splitlines()))


def read(repo: Path, rev: str, path: str) -> str | None:
    if rev == "WORKTREE":
        target = repo / path
        return target.read_text(encoding="utf-8") if target.is_file() else None
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{rev}:{path}"],
        text=True, capture_output=True, check=False,
    )
    return result.stdout if result.returncode == 0 else None


def changed(repo: Path, base: str, head: str) -> dict[str, str]:
    if head == "WORKTREE":
        raw = git(repo, "diff", "--name-status", "-M", base)
        raw += "".join(f"A\t{p}\n" for p in git(repo, "ls-files", "--others", "--exclude-standard").splitlines())
    else:
        raw = git(repo, "diff", "--name-status", "-M", base, head)
    result: dict[str, str] = {}
    for line in raw.splitlines():
        columns = line.split("\t")
        if len(columns) < 2:
            continue
        status = columns[0][0]
        if status == "R" and len(columns) == 3:
            result[columns[1]] = "D"
            result[columns[2]] = "A"
        else:
            result[columns[1]] = status
    return result

from __future__ import annotations

from pathlib import Path

import yaml


def load_yaml(path: Path) -> dict:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"YAML ilegível: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"YAML deve ser um objeto: {path}")
    return value


def load(config_dir: Path) -> tuple[dict, dict[str, dict], list[str]]:
    policy = load_yaml(config_dir / "policy.yml")
    workflows: dict[str, dict] = {}
    errors: list[str] = []
    for path in sorted((config_dir / "workflows").glob("*.yml")):
        workflow = load_yaml(path)
        identifier = workflow.get("id")
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"{path.name}: id ausente")
            continue
        workflows[identifier] = workflow
        states = workflow.get("states")
        order = workflow.get("state_order")
        transitions = workflow.get("transitions")
        gates = workflow.get("gates")
        if not isinstance(states, list) or not isinstance(order, list) or not isinstance(transitions, list) or not isinstance(gates, dict):
            errors.append(f"{path.name}: states, state_order, transitions ou gates inválidos")
            continue
        for state in order:
            if state not in states:
                errors.append(f"{path.name}: state_order contém estado desconhecido {state}")
        for edge in transitions:
            if not isinstance(edge, dict) or edge.get("from") not in states or edge.get("to") not in states:
                errors.append(f"{path.name}: transição usa estado desconhecido")
                continue
            gate = edge.get("requires_approval")
            if gate and gate not in policy.get("gates", {}):
                errors.append(f"{path.name}: gate não definido na policy: {gate}")
        for gate in gates:
            if gate not in policy.get("gates", {}):
                errors.append(f"{path.name}: gate não definido na policy: {gate}")
    if not workflows:
        errors.append("nenhum workflow encontrado")
    if policy.get("schema") != "manuel-policy/1":
        errors.append("schema da policy inválido")
    return policy, workflows, errors

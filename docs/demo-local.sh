#!/usr/bin/env bash
set -euo pipefail

source_repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
demo_tmp=$(mktemp -d)
trap 'rm -rf "$demo_tmp"' EXIT
git clone --quiet "$source_repo" "$demo_tmp/repo"
cd "$demo_tmp/repo"
git config user.name 'Demo'
git config user.email 'demo@example.invalid'
cp -a config "$demo_tmp/trusted-config"
python3 - "$demo_tmp/trusted-config/policy.yml" <<'PY'
import pathlib, sys, yaml
path = pathlib.Path(sys.argv[1])
policy = yaml.safe_load(path.read_text())
policy['approvers']['security'] = ['eva-demo']
path.write_text(yaml.safe_dump(policy, allow_unicode=True, sort_keys=False))
PY

item_path='projetos/api-contratos/assinatura/FEAT-2026-012/item.yml'
base_sha=$(git rev-parse HEAD)
git switch --quiet -c demo-s1
python3 - "$item_path" planned <<'PY'
import pathlib, sys, yaml
path = pathlib.Path(sys.argv[1])
item = yaml.safe_load(path.read_text())
item['state'] = sys.argv[2]
path.write_text(yaml.safe_dump(item, allow_unicode=True, sort_keys=False))
PY
git add "$item_path"
git commit --quiet -m 'demo: avançar assinatura'
head_s1=$(git rev-parse HEAD)
printf '[]\n' > "$demo_tmp/reviews.json"

echo 'S1 — sem review, deve barrar com MG-020'
set +e
python3 scripts/manuel_gate.py check --base "$base_sha" --head "$head_s1" --reviews "$demo_tmp/reviews.json" --pr-author ana-demo --config-dir "$demo_tmp/trusted-config"
code=$?
set -e
test "$code" -eq 1

git switch --quiet -c demo-s2 "$base_sha"
python3 - "$item_path" implementing <<'PY'
import pathlib, sys, yaml
path = pathlib.Path(sys.argv[1])
item = yaml.safe_load(path.read_text())
item['state'] = sys.argv[2]
path.write_text(yaml.safe_dump(item, allow_unicode=True, sort_keys=False))
PY
git add "$item_path"
git commit --quiet -m 'demo: pular etapa'
head_s2=$(git rev-parse HEAD)
echo 'S2 — transição que pula estado, deve barrar com MG-010'
set +e
python3 scripts/manuel_gate.py check --base "$base_sha" --head "$head_s2" --reviews "$demo_tmp/reviews.json" --pr-author ana-demo --config-dir "$demo_tmp/trusted-config"
code=$?
set -e
test "$code" -eq 1

git switch --quiet demo-s1
python3 - "$demo_tmp/reviews.json" "$head_s1" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps([{'id': 1, 'user': {'login': 'eva-demo'}, 'state': 'APPROVED', 'commit_id': sys.argv[2], 'submitted_at': '2026-11-13T12:00:00Z'}]))
PY
echo 'S3 — review correto no SHA exato, deve liberar'
python3 scripts/manuel_gate.py check --base "$base_sha" --head "$head_s1" --reviews "$demo_tmp/reviews.json" --pr-author ana-demo --config-dir "$demo_tmp/trusted-config"

# Regras do validador e CLI

O validador compara a **base** do PR com o **PR** e barra a mudança de estado que não tem os artefatos e a aprovação certos. Cada violação tem um **código estável** `MG-nnn` e uma mensagem em português. O contrato dos dados está em [schema.md](schema.md); as pré-condições de publicação, em [publicacao.md](publicacao.md).

`check` avalia **o que o PR muda** (diff base → head) e, para todo item tocado, revalida também os artefatos e as evidências que o estado do item exige. `check-all` aplica as regras **estruturais** (◆) à árvore inteira e não precisa de base nem de review.

A aprovação **nunca é gravada no PR**: ela é derivada, a cada execução, da lista de reviews do GitHub (último review decisivo de cada pessoa, no commit exato do PR). Uma só função serve a MG-020 a MG-025, MG-032, MG-061 e MG-090; só muda o gate consultado.

## Regras

| Código | O que barra | ◆ |
|---|---|---|
| MG-001 | `item.yml` fora de `projetos/<repo>/<módulo>/<ID>/`, ou `id` diferente do nome da pasta | ◆ |
| MG-002 | campo obrigatório ausente, tipo errado ou valor fora do enum; `ownership` ou `ownership.approvers` com tipo errado; `item.yml` ilegível, acima de 256 KB ou com **alias YAML** (a mensagem cita o motivo) | ◆ |
| MG-003 | item removido (itens nunca são apagados; use `cancelled`) | |
| MG-004 | campo imutável alterado: `id`, `nature`, `lifecycle.createdAt`, `context.organization` | |
| MG-005 | item novo que não nasce em `draft` | |
| MG-010 | transição inexistente no workflow (inclui **pular** estado) | |
| MG-011 | bloqueio inconsistente: `blocked` sem `blocked_by` ou `blocked_from` válidos; saída de `blocked` para outro estado que não `blocked_from`; **`blocked_from` alterado enquanto o item continua `blocked`**; campos `blocked_*` fora de `blocked`. Um item `blocked` pode ser cancelado diretamente | ◆ (a parte estática) |
| MG-012 | item em estado terminal mudou de estado | |
| MG-020 | a transição exige aprovação de um gate e **não há** review `APPROVED` válido | |
| MG-021 | há `APPROVED` do aprovador, mas em **commit antigo** | |
| MG-022 | o único `APPROVED` é do **autor do PR** | |
| MG-023 | o aprovador **não tem papel** autorizado para o gate (inclui a restrição `ownership.approvers[gate]`) | |
| MG-024 | aprovador **não configurado** (placeholder ou lista vazia) para o papel exigido | |
| MG-025 | o último review decisivo do aprovador é `CHANGES_REQUESTED` ou `DISMISSED` | |
| MG-030 | artefato exigido ausente, vazio ou com **placeholder** (`[PREENCHER]`, `[TODO]`, `TODO:`, `PENDENTE DE EXECUÇÃO`, `{{...}}`); vale para todas as transições para frente até o estado atual (ou até `blocked_from`) | ◆ |
| MG-031 | `artifacts[].path` absoluto, com `..`, fora de `artefatos/` ou apontando para arquivo inexistente | ◆ |
| MG-032 | o PR altera um artefato **protegido** por um gate já alcançado, **ou** o próprio bloco `artifacts` (caminho trocado, entrada acrescentada, removida ou de outro tipo), sem novo review desse gate | |
| MG-040 | artefato `produced_by: agent` com `ai_use` ausente, vazio ou malformado | ◆ |
| MG-050 | `evidence` malformada (status inválido; `confirmed` sem `by`/`date`/`source`; `observed` sem `source`; `unknown` sem `owner`/`due`; data com hora) | ◆ |
| MG-051 | requisito sem evidência `observed`/`confirmed` e sem exceção que o cubra, na transição que exige evidência e, depois de `released`, em todo item tocado | ◆ |
| MG-060 | exceção malformada (campo faltando, `waives` com requisito inexistente, `expires` inválida ou com hora) | ◆ |
| MG-061 | exceção **nova ou alterada** (inclusive a de um item novo) sem review `APPROVED` válido do gate `exception` | |
| MG-062 | exceção vencida: **erro** no `check`, **aviso** no `check-all` | ◆ (aviso) |
| MG-063 | `follow_up` de exceção aponta para item inexistente | ◆ |
| MG-070 | `blocked_by` ou `parent` inexistente (**erro**); `relations[].target` inexistente (**aviso**) | ◆ |
| MG-080 | workflow ou policy inválidos | ◆ |
| MG-090 | o PR altera `scripts/`, `config/` ou `.github/` sem review do gate `platform`. É defesa em profundidade: **não protege o arquivo do workflow** (ver [publicacao.md](publicacao.md)) | |

Quando há mais de um motivo, o validador reporta **todos**; para o review, prevalece o mais específico (um `APPROVED` do autor é MG-022, e não MG-020; um `APPROVED` em commit antigo é MG-021).

## CLI

```
python3 scripts/manuel_gate.py check \
    --base REV --head REV --reviews reviews.json --pr-author LOGIN \
    [--repo .] [--config-dir CAMINHO] [--head-sha SHA] [--today AAAA-MM-DD] [--format text|github]
python3 scripts/manuel_gate.py check-all \
    [--repo .] [--config-dir CAMINHO] [--today AAAA-MM-DD] [--format text|github]
```

- `--head` aceita um SHA, uma referência ou `WORKTREE` (árvore de trabalho; uso local). `--head-sha` assume, por padrão, o commit de `--head`.
- `--config-dir` aponta para a configuração (`policy.yml` e `workflows/`) **de confiança**. No CI, é a da **base** do PR, nunca a do código do PR. Padrão: `<repo>/config`.
- `--reviews` é um arquivo JSON com os reviews (a lista da API do GitHub, ou a lista de listas de `gh api --slurp`). O validador **não acessa a rede**.
- Saída `text`: uma linha por violação, `MG-nnn [ID] mensagem`, e um resumo. Saída `github`: anotações `::error file=...,title=MG-nnn::mensagem` (e `::warning`), com os valores escapados.

### Códigos de saída

| Saída | Significado |
|---|---|
| `0` | nenhuma violação (avisos são permitidos) |
| `1` | **há violação**; a saída lista os códigos `MG-nnn` |
| `2` | o validador **não conseguiu avaliar**: uso incorreto (argumento, arquivo ou configuração ilegível) ou erro interno (`erro interno do validador: ...`). Falha **fechada**: o job fica vermelho |

Item malformado (tipo errado, data com hora, YAML ilegível) **não** é erro interno: é violação com código, saída `1`.

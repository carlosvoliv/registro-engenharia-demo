# Contratos do registro

Cada item reside em `projetos/<repo>/<modulo>/<ID>/item.yml`; `id` deve coincidir com a pasta. Usa `modelVersion: "3.0"`, `schemaVersion: "work-item/1.1"` e um workflow versionado de `config/workflows/`.

O item declara `context`, `nature`, `class`, `state`, `ownership`, `requirements`, `evidence`, `exceptions`, `artifacts` e `lifecycle`. O workflow enumera estados, arestas, gates e artefatos exigidos. A política define pessoas, papéis e logins aprovadores. O validador interpreta a **configuração da base do PR**.

`artifacts[]` referencia somente arquivos sob `artefatos/`. Cada artefato de agente (`produced_by: agent`) tem `ai_use` como lista de eventos com schema, ferramenta, modelo, sessão e papel. Artefato humano não precisa dessa lista.

`evidence[]` declara `claim` e estado `observed`, `confirmed`, `inferred` ou `unknown`. Observação e confirmação têm fonte; confirmação também tem pessoa e data; desconhecimento tem dono e prazo. Só observação e confirmação cobrem requisitos. Uma exceção pode cobrir temporariamente um requisito, com motivo, solicitante, expiração e item de acompanhamento.

A aprovação é derivada do review no SHA exato do PR. Nenhum resultado é gravado no PR. O ledger histórico é um dado separado; seu escritor pós-merge fica fora desta fatia.

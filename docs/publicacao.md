# Pré-condições antes de publicar a demo

Este arquivo descreve trabalho futuro do mantenedor. A F01 permanece **local**. O workflow no PR pode ser alterado pelo próprio PR; MG-090 é defesa em profundidade e não protege a execução do workflow.

- [ ] **Donos reais:** editar `.github/CODEOWNERS`, retirar os comentários e substituir os placeholders por contas reais com acesso ao repo. Cobrir `/.github/`, `/scripts/`, `/config/` e `/.github/CODEOWNERS`.
- [ ] **Ruleset de `main`:** em *Settings → Rules → Rulesets*, criar uma regra para `main` que exija PR, review de code owner, descarte de reviews obsoletos após novo commit e o check `gate`. Bloquear force push e exclusão da branch.
- [ ] **Bypass:** revisar a lista de bypass em *Settings → Rules → Rulesets*; para a demo, ninguém deve poder ignorar a regra, inclusive o dono do repo.
- [ ] **Teste da proteção:** abrir um PR que altere apenas `.github/workflows/manuel-gate.yml`. Confirmar que o merge fica bloqueado até o review do code owner. Se isso falhar, não apresentar a demo como gate obrigatório.
- [ ] **Teste do check após review:** abrir um PR de transição, observar `gate` vermelho, enviar o review e confirmar que a execução de `pull_request_review` produz um check verde aceito como status obrigatório do mesmo PR.
- [ ] **Versões das actions:** conferir `actions/checkout@v4` e `actions/setup-python@v5` nas páginas oficiais e **fixar cada uma pelo SHA do commit** da versão conferida (a tag pode ser movida). Isto depende do GitHub real; não copie SHAs de memória.
- [ ] **PRs de fork:** não são suportados na demonstração; o gate falha fechado. Não habilite PRs de fork sem revisar o workflow.
- [ ] **Dados:** revisar todos os arquivos **e os metadados dos commits**; confirmar que tudo é fictício e que não há credenciais, e-mail, CPF nem conteúdo da empresa real.
  - Identidades: `git log --all --format='%an <%ae> | %cn <%ce>' | sort -u` deve listar **somente** a identidade pessoal pretendida para o repositório público, e nenhum endereço corporativo.
  - Assinaturas: `git log --all --format=%B` não pode conter trailers de ferramentas (`Co-Authored-By`, `Generated with` e semelhantes).
  - Histórico simulado: os commits `chore(dados-simulados)` têm datas fictícias (27/10 a 13/11) e dizem isso na mensagem; ao publicar, confirme que a descrição do repositório também diz que o histórico dos itens é simulado.
  - Arquivos: busque, em toda a árvore, pelo domínio do e-mail corporativo e por nomes de sistemas ou pessoas reais.

O ledger pós-merge não tem escritor nesta fatia. A possibilidade de o bot escrever numa branch protegida permanece não verificada; as visões da demo deverão ler os reviews pela API até esse mecanismo ser definido.

# Pré-condições de publicação da demo

**Publicado em 16/11/2026** em `carlosvoliv/registro-engenharia-demo` (público, dados e histórico fictícios). Cada item abaixo diz o que foi feito e o que foi **visto no GitHub real**. O workflow no PR pode ser alterado pelo próprio PR; MG-090 é defesa em profundidade e não protege a execução do workflow.

- [x] **Donos reais** (feito: `@carlosvoliv`, dono único; `/agentes/` entrou na lista): editar `.github/CODEOWNERS`, retirar os comentários e substituir os placeholders por contas reais com acesso ao repo. Cobrir `/.github/`, `/scripts/`, `/config/` e `/.github/CODEOWNERS`.
- [x] **Ruleset de `main`** (feito: PR, **1 aprovação com code owner**, descarte de review obsoleto, check `gate`, sem force push nem exclusão; com **0 aprovações o code owner não era exigido**, visto em PR de teste):  em *Settings → Rules → Rulesets*, criar uma regra para `main` que exija PR, review de code owner, descarte de reviews obsoletos após novo commit e o check `gate`. Bloquear force push e exclusão da branch.
- [x] **Bypass** (feito: lista vazia, nem o dono ignora a regra; consequência: com um só humano **nada** que exija review integra, ver «Limite de uma conta só»): revisar a lista de bypass em *Settings → Rules → Rulesets*; para a demo, ninguém deve poder ignorar a regra, inclusive o dono do repo.
- [~] **Teste da proteção** (PR de teste: `gate` vermelho por MG-090 e merge **BLOQUEADO**; o code owner isolado só passou a bloquear com 1 aprovação exigida; PR fechado, resultado registrado aqui): abrir um PR que altere apenas `.github/workflows/manuel-gate.yml`. Confirmar que o merge fica bloqueado até o review do code owner. Se isso falhar, não apresentar a demo como gate obrigatório.
- [ ] **Teste do check após review** (**NÃO feito**: exige uma segunda conta aprovando; o check vermelho e o merge bloqueado foram vistos nos PRs S1 e S2, mas não o verde que vem do review): abrir um PR de transição, observar `gate` vermelho, enviar o review e confirmar que a execução de `pull_request_review` produz um check verde aceito como status obrigatório do mesmo PR.
- [x] **Versões das actions** (feito: `checkout` v4.4.0 e `setup-python` v5.6.0, SHAs resolvidos pela API oficial, e vistos sendo baixados por SHA no log do runner): conferir `actions/checkout@v4` e `actions/setup-python@v5` nas páginas oficiais e **fixar cada uma pelo SHA do commit** da versão conferida (a tag pode ser movida). Isto depende do GitHub real; não copie SHAs de memória.
- [ ] **PRs de fork** (não testado; segue não suportado): não são suportados na demonstração; o gate falha fechado. Não habilite PRs de fork sem revisar o workflow.
- [x] **Dados** (feito antes do push: identidade única, sem trailers, sem padrão de segredo, sem termo da empresa): revisar todos os arquivos **e os metadados dos commits**; confirmar que tudo é fictício e que não há credenciais, e-mail, CPF nem conteúdo da empresa real.
  - Identidades: `git log --all --format='%an <%ae> | %cn <%ce>' | sort -u` deve listar **somente** a identidade pessoal pretendida para o repositório público, e nenhum endereço corporativo.
  - Assinaturas: `git log --all --format=%B` não pode conter trailers de ferramentas (`Co-Authored-By`, `Generated with` e semelhantes).
  - Histórico simulado: os commits `chore(dados-simulados)` têm datas fictícias (27/10 a 13/11) e dizem isso na mensagem; ao publicar, confirme que a descrição do repositório também diz que o histórico dos itens é simulado.
  - Arquivos: busque, em toda a árvore, pelo domínio do e-mail corporativo e por nomes de sistemas ou pessoas reais.

## Visto no GitHub real (16/11)

- O workflow roda no push para `main` (`check-all` verde) e nos PRs, com Python 3.12 e as actions fixadas por SHA.
- **S2** (pular etapa): `gate` vermelho, «transição inexistente: awaiting-approval → implementing», merge bloqueado.
- **S1** (avançar sem review): `gate` vermelho e merge bloqueado, mas pela mensagem «aprovador do gate design não configurado», porque a policy ainda traz o marcador do colega. Com o login real, a mensagem esperada é MG-020 (falta aprovação).
- **Retomada por um segundo agente:** o PR só com artefatos do item passou: `gate` verde.
- `gh api .../reviews --paginate --slurp` rodou no runner (com a lista de reviews **vazia**).

## Ainda não verificado

- O **review de uma segunda conta** reexecutando o check (`pull_request_review`) e esse check verde valendo para o mesmo PR, o S3.
- A **mensagem MG-020** do S1 (depende do login do aprovador).
- O formato do `--slurp` com reviews **reais** e a concorrência (`cancel-in-progress`) entre PR e review.
- O ledger pós-merge (sem escritor), PR de fork e o merge de um PR que exija review.

## Limite de uma conta só

O gate vigia `scripts/`, `config/`, `.github/` e `agentes/` com a aprovação `platform`, e o ruleset exige review de code owner nesses caminhos. Com **um só humano**, o autor do PR é o único aprovador possível e **nenhuma mudança nesses caminhos integra** sem desligar o ruleset. Trocar os aprovadores da policy (por exemplo, pôr o login real do colega) cai no mesmo caso: é preciso a segunda conta como aprovador `platform`, ou o dono desligar o ruleset por um instante, mudar e religar.

O ledger pós-merge não tem escritor nesta fatia. A possibilidade de o bot escrever numa branch protegida permanece não verificada; as visões da demo deverão ler os reviews pela API até esse mecanismo ser definido.

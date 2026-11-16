# Retomada de um item por um segundo agente (ato 2)

Um agente de **outro fornecedor** continua um item só pelo registro. Os dados são fictícios.

```bash
python3 scripts/manuel_resume.py TECH-2026-005 --patch ensaios/retomada.patch
# --aplicar    traz a branch retomada/<ID> para este repositório (sem trocar de branch)
# --descartar  apaga o clone temporário ao terminar
```

## O que acontece

1. **Clone limpo.** O agente recebe um clone do que está **commitado** (nada de `views/`, `ensaios/` nem arquivo local), numa branch `retomada/<ID>`.
2. **O papel e a tarefa.** O prompt é `agentes/retomador.md` mais o ponteiro do item (o `item.yml` e o `handoff.md`). O agente **não tem a conversa anterior**.
3. **Codex isolado.** `codex exec` roda com `--ignore-user-config`, `--ignore-rules`, `--ephemeral`, sem hooks, apps nem memória de quem roda, no sandbox `workspace-write` do clone. Sem isso, os hooks pessoais de quem roda (por exemplo, checagens de outros repositórios) disparariam junto.
4. **Escopo conferido pelo Manuel, não pelo agente.** Só vale: **criar no máximo um** arquivo `NN-<tipo>-<assunto>.md` em `artefatos/` do item e **acrescentar** ao `handoff.md`. Qualquer outra coisa (outro arquivo, `item.yml`, `config/`, `scripts/`, outro item, apagar ou reescrever texto, link simbólico, arquivo acima de 64 KB, nome fora do padrão) **recusa a retomada inteira**, sem registrar nem commitar.
5. **A marca de uso é do Manuel.** O runner registra no `item.yml` o artefato novo e soma o evento `ai_use` (ferramenta, **modelo e sessão lidos do cabeçalho do Codex**, papel `drafted`). O agente não preenche a própria marca; quando a ferramenta não expõe o dado, o campo diz `nao-informado`.
6. **Gate.** `manuel_gate.py check` roda sobre a diferença base → retomada, sem nenhum review. Passa quando o agente só documenta; **barra** quando mexe em artefato protegido já aprovado (MG-032).

## O que o código garante

- O repositório original **não muda** (só com `--aplicar` ele ganha a branch).
- O agente só escreve onde o escopo permite; o que ele escreve é registrado com a marca de quem fez.
- O resultado do gate é do validador, não do agente.

## O que não garante

- **O texto é de modelo e varia.** O que o código confere é o escopo, o registro e o gate; não que o documento esteja certo.
- **O agente pode contornar o que o prompt pede dentro do escopo** (por exemplo, um arquivo com nome válido mas conteúdo ruim). O dev confere e responde pelo que aprova.
- Os dados do registro (fictícios) **saem da máquina** para o fornecedor do agente na chamada ao modelo.
- Funciona com o Codex 0.169.0 logado; outro fornecedor não foi tentado.

## Medido em uma execução (16/11)

Item TECH-2026-005; **56 s** do comando ao gate; o agente escreveu `20-plano-de-teste-preparacao.md` (as perguntas que faltam para Ana, sem inventar medição nem aprovação) e a seção «Retomada» do handoff; gate: 0 erro, 0 aviso. Uma execução não é taxa de acerto, e 56 s está no limite do «até 1 minuto» da demonstração: guarde o `--patch` do ensaio como reserva.

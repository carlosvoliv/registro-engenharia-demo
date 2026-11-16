# Registro de demonstração do Manuel

Este repositório contém **somente dados fictícios** da organização inventada Aurora Crédito. Pessoas, sistemas, demandas, datas e aprovações são simulados para uma demonstração; o histórico dos itens (datas e sequência de estados) também é simulado: os commits `chore(dados-simulados)` têm datas fictícias. Nenhum conteúdo representa a empresa do autor.

## O que foi verificado

O validador local, seus testes e o dataset são verificáveis com `python3 -m unittest discover -s tests -v` e `python3 scripts/manuel_gate.py check-all`.

## O que ainda não foi verificado

A execução do GitHub Actions, o vínculo do check ao PR, as regras de proteção de branch, o review de uma conta externa e a escrita do ledger após merge dependem da publicação e de ensaios reais. Consulte `docs/publicacao.md` antes de publicar.

## Uso local

A visão executiva e o agente de pergunta estão em `docs/visoes-e-pergunta.md` (`scripts/manuel_view.py` e `scripts/manuel_ask.py`).
A retomada de um item por um segundo agente está em `docs/retomada.md` (`scripts/manuel_resume.py`).

O contrato dos dados está em `docs/schema.md`; as regras `MG-nnn` e a CLI, em `docs/regras.md`. O roteiro reproduzível do gate está em `docs/demo-local.md` (`bash docs/demo-local.sh` roda os três cenários).

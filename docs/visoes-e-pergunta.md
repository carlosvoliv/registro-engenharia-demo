# Visão executiva e agente de pergunta

Tudo aqui lê o registro; nada grava nele. Os dados são fictícios.

## Visão executiva

```bash
python3 scripts/manuel_view.py --today 2026-11-18
# gera views/executiva.html (para a sala) e views/INDEX.md (índice que o agente lê)
```

- **Fonte:** os `item.yml` do commit lido (`--rev`, padrão `HEAD`), `registro/aprovacoes.jsonl` e o histórico do git de cada item.
- **Na etapa desde / dias:** vem do **git**: é a data do primeiro commit da sequência ininterrupta em que o `item.yml` está no estado atual. Voltar a um estado anterior reinicia a contagem.
- **Mostra:** o que precisa de atenção (aprovação pendente e de quem, bloqueios, exceções com aprovação e prazo, lacunas com responsável), o prometido contra o entregue por requisito, e a projeção do uso de IA (ferramentas registradas e artefatos de agente com marca).
- **Não mostra:** commits, autores, ranking nem qualquer métrica proibida pela política (`config/policy.yml`). O responsável é **por item**.
- **Segurança:** todo texto vindo do registro é escapado no HTML. Um item ilegível entra em «Problemas» e não derruba a visão.
- `views/` é descartável e **fica fora do git**; regenere quando quiser. A mesma entrada gera a mesma saída (a data de referência é argumento, não relógio).

**Limite dos dados atuais:** as datas vêm dos commits do próprio dataset, então todos os itens entraram no estado atual no mesmo dia. Idades diferentes entre itens exigem um histórico com datas simuladas, que **não foi feito**.

## Agente de pergunta

```bash
python3 scripts/manuel_ask.py perguntar "O que está travando a assinatura digital e quem pode destravar?" --today 2026-11-18
python3 scripts/manuel_ask.py perguntar "..." --salvar ensaios/pergunta-01.md   # guarda a resposta (a pasta fica fora do git)
python3 scripts/manuel_ask.py verificar resposta.txt                              # só confere as fontes de um texto
```

O papel do agente está em `agentes/pergunta.md` (permissões, regras e as três frases exatas: «Isso não consta no registro.», «Esta organização não mede produtividade individual.» e «Só respondo sobre o registro.»). O comando regenera `views/INDEX.md`, roda o Claude Code com `--safe-mode`, `--tools Read,Grep,Glob` e sem gravar sessão, e confere as fontes citadas.

**O que o código garante**
- O agente nasce só com leitura (`Read`, `Grep`, `Glob`); o papel é recusado se declarar outra ferramenta.
- Não carrega `CLAUDE.md`, memória, hooks nem skills de quem roda (`--safe-mode`).
- A pergunta entra pela entrada padrão, nunca como argumento.
- Toda fonte citada precisa existir **dentro** do repositório; resposta sem fonte e sem «não consta» é reprovada (saída 3).

**O que não garante**
- Que a frase esteja certa: a verificação prova que as fontes existem, não que dizem o que o agente afirma. O texto é de modelo e varia a cada execução.
- Que nada da conta de quem roda chegue ao modelo: o Claude Code injeta o contexto da conta mesmo em `--safe-mode`. O papel manda não revelar, mas isso é instrução, não bloqueio.
- Funcionamento em outra versão do Claude Code (testado com a 2.1.325) ou com outro fornecedor.

Cada pergunta leva cerca de 20 s e custa centavos de dólar. Para a demonstração, guarde as respostas ensaiadas como reserva.

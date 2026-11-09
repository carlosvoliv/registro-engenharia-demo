# Design da assinatura digital

## Fluxo proposto
A tela de emissão solicita a assinatura ao cliente.
A API recebe um identificador e o vincula ao contrato.
Uma falha deixa o contrato sem conclusão, com mensagem clara.

## Evidência esperada
O plano de testes deve verificar vínculo, erro e duração.
O tempo de emissão ainda não foi medido.

## Decisão pendente de aprovação da Segurança
A Segurança revisará armazenamento e exposição do identificador.
Nenhuma aprovação deste design está registrada neste item.

## Dependência
O extrato depende de contratos emitidos com assinatura válida.

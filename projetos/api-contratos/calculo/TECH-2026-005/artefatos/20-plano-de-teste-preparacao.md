# Preparação da medição pendente

## Base do próximo passo
TECH-2026-005 está em `investigating`, sob responsabilidade de Ana, e regulariza DEF-2026-021. Seu item.yml não registra requisitos, evidências ou exceções próprios. O RNF-001 da DEF exige resposta em até 200 ms em carga; os resultados funcionais registrados na DEF não demonstram desempenho.

A EXC-2026-001 está no item.yml da DEF: dispensa RNF-001 por indisponibilidade do ambiente até 25/11, aponta esta investigação como acompanhamento e expira em 2026-11-30. O desempenho está registrado como desconhecido, com Ana responsável e prazo de 2026-11-30.

O plano 10-plano-de-teste.md prevê ambiente fictício disponível em 25/11 e confirmação da massa por Ana. Na data desta retomada, 2026-11-16, essa disponibilidade é futura e não foi confirmada pelos artefatos. Não há resultado de carga.

## Próximo passo permitido
Preparar as perguntas abaixo para Ana e obter suas respostas antes de executar e interpretar a medição. Este documento registra pendências; não comprova contato, confirmação, execução ou aprovação.

| Desconhecido | Pergunta a Ana, responsável pelo item |
| --- | --- |
| Disponibilidade efetiva do ambiente | Em 25/11, o ambiente estará disponível? Qual sua identificação, configuração e versão do cálculo a medir? |
| Massa de teste | Qual massa deve ser usada e onde está registrada sua confirmação? |
| Perfil de carga | Quais volume, concorrência, duração e condições devem representar a carga do RNF-001? |
| Critério de medição | Onde começa e termina a duração do cálculo e a qual estatística ou conjunto de observações se aplica o limite de 200 ms? |
| Execução | Quem executará, com qual ferramenta e procedimento reproduzível, após confirmar ambiente e massa? |
| Tratamento da pendência | Se não houver ambiente ou medição até 30/11, qual encaminhamento será submetido às pessoas competentes? |

## Registro posterior esperado
Após as confirmações e a disponibilidade efetiva, registrar data real, executor, ambiente, versão, massa, ferramenta, procedimento, volume e condições de execução, junto das durações observadas e da localização dos dados brutos. Comparar as observações com 200 ms usando o critério esclarecido por Ana. Se faltarem dados para concluir, manter explícita a limitação.

O prazo da exceção não é resultado de teste. Nem este documento nem uma medição futura encerram automaticamente a exceção: o encaminhamento depende das evidências e do processo aplicável, sem aprovação nesta retomada.

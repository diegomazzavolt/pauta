# Validação

## Extrator — 13/09/2026

- `jNQXAC9IVRw`: extração real, seis trechos de legenda manual em inglês.
- `aircAruvnKk`: extração real de faixa automática em inglês, 500 trechos.
- Navegador: consulta, prévia e acionamento de download SRT confirmados.
- Exportadores SRT/VTT/TXT validados por testes. `tests/smoke_live.py` não foi executado: a solicitação foi interrompida pelo usuário; não é contado como validação concluída.

## Jornal — 14/09/2026

- Testes em banco temporário: importação, erros por linha, duplicatas, persistência, prioridade, pausa, recuperação, vídeos novos, legendas automáticas, novas tentativas e tratamento.
- Composição editorial testada com resposta de IA sintética e fontes explícitas. Nenhuma chave real foi configurada nem houve chamada paga à OpenAI. A geração real por IA ainda depende dessa configuração.
- Feed público do 3Blue1Brown obtido; corrigido o `channelId` na raiz Atom, que omite o prefixo UC. Teste de regressão cobre esse formato.
- Resolução por @nome identificou o canal correto. Algumas requisições retornaram timeout ou 404; o monitor mantém próximas tentativas para essas condições.
- Interface e diálogo de importação inspecionados no navegador, incluindo tela de 390 px sem transbordamento horizontal da página.
- Nenhum canal ou matéria fictícia foi inserido no banco do usuário.

Ainda não verificados em produção: hospedagem contínua, matéria real com chave OpenAI, recuperação de lacuna real maior que a janela RSS e longo prazo com grande volume de canais.

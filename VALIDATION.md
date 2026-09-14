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

## Correção do acompanhamento e primeiro vídeo — 14/09/2026

- Reproduzido HTTP 404 no RSS de canais existentes. A listagem pública de uploads por yt-dlp funcionou; adicionada como alternativa para 404/falhas de conexão, preservando restrições 401/403/429.
- Na verificação final, todos os 13 canais cadastrados foram identificados e listados. A disponibilidade do RSS oscilou durante a investigação.
- Último vídeo incluído automaticamente na primeira consulta, inclusive para cadastros anteriores, com prioridade sobre a fila histórica. Lista inicial de IDs evita incluir vídeos antigos quando o YouTube não informa datas.
- 14 legendas já estavam persistidas (295.921 caracteres) antes da atualização; banco copiado para backup antes da migração.
- Limitação global de ritmo e pausa progressiva após bloqueio do YouTube. Nenhuma tentativa de contornar autenticação ou bloqueio.
- 35 testes passaram, cobrindo alternativa RSS/uploads, restrições, seleção inicial sem datas, idempotência, cadastro anterior, prioridade e pausa global das legendas.
- Redação real continua dependente de configuração de chave/modelo pelo usuário.


## Diagnóstico HTTP e configuração da conexão — 14/09/2026

- Amostra real `GI6Ie5neiLQ`: `/watch`, `/youtubei/v1/player` e `/oembed` retornaram HTTP 200; `/api/timedtext` retornou HTTP 429. A listagem encontrou uma faixa automática, mas o texto não pôde ser coletado.
- Teste independente com yt-dlp listou faixas automáticas e também recebeu HTTP 429 no texto. Nenhum áudio/vídeo foi baixado; não houve tentativa de resolver captcha ou contratar serviço/proxy.
- A página pública do DownSub anuncia API autenticada com créditos; isso não revela a implementação do servidor. A tentativa no site público não produziu uma extração confirmada nesta sessão.
- 45 testes locais passaram, incluindo preservação da chave editorial, não exposição de credenciais do proxy, prioridade da variável de ambiente, validação da configuração, retomada apenas quando a conexão muda e distinção entre token ausente e bloqueio global.
- Nenhuma conexão alternativa real foi fornecida/configurada. A fila pendente permanece dependente do acesso do YouTube; esta entrega não é evidência de desbloqueio.

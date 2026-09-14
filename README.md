# Pauta

Um **jornal diário baseado nos canais do YouTube que você acompanha**. Cada TXT importado representa um assunto/editoria. Todos os assuntos compõem a mesma edição, com o mais relevante na capa e referências aos vídeos em cada matéria.

## Usar

1. Abra **Assuntos e canais → Importar assunto**.
2. Dê um nome ao assunto e escolha a prioridade na capa.
3. Selecione um TXT com um link de canal por linha, ou cole o bloco. Aceita `@nome`, `/channel/UC…`, `/c/…` e `/user/…`; TXT em UTF-8 ou UTF-16 com BOM.
4. Salve para acompanhar novos vídeos. Por padrão, entram apenas publicações posteriores ao cadastro. A opção de incluir o feed recente permite começar com material já publicado.
5. Em **Redação**, informe uma chave OpenAI e o ID de um modelo com suporte a Responses e Structured Outputs. A chave permanece no servidor, fora do Git; a API é cobrada na sua conta.
6. Leia **Jornal do dia**, consulte datas anteriores e abra as transcrições em **Acervo de vídeos**.

Sem a configuração da redação, o monitoramento e o acervo funcionam; os textos aguardam análise. A aplicação não publica matérias simuladas.

## Executar

Requer Python 3.12+.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
./start.ps1
```

Abra **http://127.0.0.1:8000**. Linux/macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

O monitor inicia junto com o servidor. Fechar o navegador não interrompe a coleta; parar o servidor ou desligar o computador, sim. GitHub armazena o código; **GitHub Pages não executa este backend nem o monitor**.

## Docker e persistência

```sh
docker compose up -d --build
```

O Compose usa volume persistente e reinício automático. A porta é exposta somente no computador local. Para acesso externo, use hospedagem Python/contêiner com disco persistente, HTTPS e autenticação na entrada; esta versão é um aplicativo pessoal, não um serviço público multiusuário.

Dados: `data/journal.sqlite3`. Configuração de redação: `data/editorial-settings.json`. Faça backup do diretório/volume com o servidor parado ou pela API de backup do SQLite. A configuração contém uma credencial: proteja o volume. Banco, transcrições e chaves são ignorados pelo Git.

## Pipeline

- **Importação:** erros por linha, duplicatas ignoradas, até 500 canais/128 KB por bloco. Blocos adicionais podem usar um assunto existente. Aliases que resolvem para um canal já cadastrado no assunto são desativados como duplicados.
- **Descoberta:** feeds Atom a cada 10 minutos. Vídeos/Shorts do feed são registrados uma única vez pelo ID.
- **Recuperação:** quando o último vídeo conhecido sai do feed, percorre a playlist de uploads até o marcador salvo. Se falhar, mantém o marcador e mostra a pendência, sem declarar cobertura completa.
- **Coleta:** apenas legendas **geradas automaticamente**, sem áudio/vídeo. Prefere português, depois inglês, quando há mais de uma faixa automática. A ferramenta avulsa `/extrator` também mantém suporte a legendas manuais.
- **Espera:** legenda ainda indisponível gera novas tentativas, inicialmente após 5 minutos, aumentando até 24 horas. É possível tentar novamente pelo acervo.
- **Tratamento:** preserva legendas e tempos originais; remove música/aplausos e sobreposições consecutivas do texto de leitura.
- **Análise:** considera todo o texto em partes pela API OpenAI. Resultados intermediários são persistidos para evitar chamadas repetidas. As instruções exigem atribuição de alegações e ignoram comandos contidos nas transcrições.
- **Edição:** consolida vídeos por assunto, reúne as editorias e valida IDs de fontes antes de salvar. Capa: `prioridade × 20 + relevância editorial × 8 + diversidade de canais × 2`, com diversidade limitada a cinco canais.
- **Histórico:** data da coleta do texto, em UTC−3 (São Paulo). A edição é atualizada conforme chegam análises daquele dia. Análises atrasadas podem completar edições anteriores. Uma falha preserva a última edição válida.

## Configuração

| Variável | Uso |
| --- | --- |
| `OPENAI_API_KEY` | Alternativa ao formulário Redação; tem precedência |
| `OPENAI_MODEL` | ID do modelo; tem precedência sobre o formulário |
| `MONITOR_INTERVAL_SECONDS` | Padrão 600, mínimo 60 |
| `JOURNAL_DB` | Caminho SQLite, padrão `data/journal.sqlite3` |
| `MONITOR_ENABLED=0` | Desativa o trabalhador para testes |
| `YOUTUBE_PROXY_URL` | Proxy próprio/autorizado opcional |

Docker Compose lê `.env` baseado em `.env.example`. No PowerShell, use o formulário ou variáveis de ambiente. Use um processo Uvicorn: o monitor tem trava no banco, mas o cache do extrator avulso é local ao processo.

## Limites

YouTube pode atrasar legendas, bloquear conexões, remover vídeos e alterar endpoints. Não há garantia de tempo real nem acesso a vídeos privados/excluídos/sem legendas. Recuperações têm prazo de 180 segundos por tentativa; um marcador removido ou canal volumoso pode exigir intervenção. A fila processa cinco canais, três legendas e duas análises por ciclo; o volume pode ampliar a latência. Textos acima de 30 mil trechos ou dois milhões de caracteres ficam sinalizados.

A redação precisa de chave/modelo válidos e saldo/limites de API. Custos dependem do volume e do modelo; ajuste limites na sua conta. Citações ligam matérias aos vídeos, mas não substituem checagem externa. Fontes e análises podem conter erros.

## Testes

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q
```

Testes usam banco temporário e conteúdo sintético, sem cadastrar exemplos no jornal real. Veja [VALIDATION.md](VALIDATION.md) e [RESEARCH.md](RESEARCH.md).

Fontes técnicas: [YouTube feeds](https://developers.google.com/youtube/v3/guides/push_notifications), [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api), [yt-dlp](https://github.com/yt-dlp/yt-dlp), [OpenAI Responses](https://developers.openai.com/api/reference/cli/resources/responses/methods/create).

# Investigação do DownSub — 13/09/2026

## Observações verificadas

- A página pública https://downsub.com/ oferece campo de URL, consulta de legendas e download em SRT, VTT e TXT. A página https://app.downsub.com/about declara suporte a legendas manuais e geradas automaticamente.
- O HTML inicial contém um contêiner de aplicação e um bundle JavaScript: a página é uma aplicação de navegador, não apenas um link direto para arquivos do YouTube.
- No bundle público `https://downsub.com/js/main.45f8c570fa2c6d88b8e5.js`, o método `downloadSubtitle` constrói o endereço de download em `https://subtitle.downsub.com/`, seguido do formato e parâmetros. Isso comprova que há um serviço intermediário próprio na entrega dos arquivos.
- Ao testar o vídeo público `jNQXAC9IVRw` no DownSub, a interface terminou com “Ocorreu um erro. Tente novamente.” Portanto, não houve download bem-sucedido no serviço de referência durante esta inspeção.

## O que não pode ser afirmado

O código do servidor do DownSub não foi disponibilizado. O frontend não revela com segurança qual extrator, infraestrutura, cookies, tokens ou proxies seu backend utiliza. Não é correto afirmar que ele usa yt-dlp ou youtube-transcript-api. Nossa implementação não reutiliza sua API, código, identidade visual ou infraestrutura.

## Implementação equivalente independente

O YouTube já gera e hospeda faixas de legendas. O método implementado consulta essas faixas, identifica as automáticas e converte texto e marcações de tempo para os arquivos solicitados. Isso não exige executar reconhecimento de fala nem baixar o vídeo.

Fontes primárias:

- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api): listagem por vídeo, distinção `is_generated`, busca por idioma e limitações de IP.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp): suporte a `--skip-download`, legendas manuais e `--write-auto-subs`; usado como extrator alternativo.
- [Sobre o DownSub](https://app.downsub.com/about): capacidades declaradas pelo próprio serviço.

Consulte o histórico de validação em `VALIDATION.md` para os resultados reais desta entrega.

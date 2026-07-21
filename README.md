# 🎤 Sal0 Karaoke 5.0.0

O Sal0 Karaoke cria vídeos de karaokê a partir de músicas e vídeos usando um pipeline local. Ele separa voz e instrumental, transcreve a música, sincroniza as legendas e renderiza o vídeo final com FFmpeg, sem enviar o áudio ou o vídeo para serviços de IA.

> Projeto pessoal, disponibilizado “como está” (*as is*). A disponibilidade de serviços externos de letras e do YouTube pode mudar.

## O que ele faz

- Separa vocais e instrumental com Demucs (`htdemucs`/`htdemucs_ft`).
- Extrai áudio de arquivos MP3, WAV, FLAC, M4A, MP4, MKV e outros formatos compatíveis com FFmpeg.
- Aceita upload local, mídia da biblioteca e download de áudio/vídeo pelo YouTube.
- Transcreve localmente com Faster-Whisper, com modelos Tiny, Small, Medium, Large-v3 e Large-v3 Turbo.
- Usa Silero VAD opcional para reduzir silêncio antes da transcrição.
- Refina timestamps por palavra com alinhamento local e gera legendas ASS próprias para karaokê.
- Oferece três modos de legenda: sílabas/varredura, palavras e linhas.
- Permite informar a letra manualmente ou tentar encontrá-la automaticamente quando houver internet.
- Consulta apenas título e artista em fontes públicas de letras: LRCLIB, Lyrics.ovh e Musixmatch Desktop API.
- Consulta os provedores de letras em paralelo, aceita falha/offline sem interromper o processamento local e mantém a letra editável.
- Dá prioridade à letra manual e permite revisar, salvar, limpar e substituir a letra encontrada.
- Ajusta fonte, cor, posição, quebra de linha, quantidade de palavras, pontuação e visualização da próxima linha.
- Permite fundo original, imagem/vídeo enviado, paisagem aleatória, cor sólida, biblioteca e fundo obtido do YouTube.
- Mantém cache local, biblioteca de mídias, histórico de vídeos e perfis de estilo reutilizáveis.
- Oferece editor web para correções antes da renderização, incluindo pausa de revisão de 75%.
- Possui autenticação local, gerenciamento de usuários e sessões protegidas por senha derivada com PBKDF2.
- Pode enviar notificações e vídeos ao Telegram quando essa integração opcional for configurada.
- Funciona em Docker, Docker Compose, CasaOS e servidores pessoais com armazenamento persistente em `/data`.

## Busca de letras e privacidade

A letra automática é uma ajuda para orientar a transcrição; ela não substitui a sincronização local. O Sal0 Karaoke envia somente a consulta textual de título/artista para os provedores públicos. Nenhum áudio, vídeo, separação Demucs, modelo Whisper, legenda em edição, senha ou configuração do Telegram é enviado para buscar letras.

O Musixmatch é consultado pelo fluxo público do aplicativo desktop: o app solicita um token temporário e o mantém somente em memória durante a consulta. Não há token fixo, cookie pessoal ou chave privada no código. Se as fontes não responderem, o pipeline continua e a letra pode ser colada manualmente.

## Execução com Docker

```yaml
services:
  karaoke-app:
    image: ghcr.io/sal0-apps/sal0-karaoke:latest
    container_name: karaoke-app
    ports:
      - "7885:7860"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

Inicie com:

```bash
docker compose up -d
```

Abra `http://localhost:7885` no navegador.

## Dados persistentes

O volume `/data` preserva todo o estado do aplicativo:

- `/data/library/`: mídias, fundos e histórico;
- `/data/cache/`: arquivos intermediários e cache da última mídia;
- `/data/output/`: vídeos, legendas, modelos baixados, perfis e logs;
- `/data/users.json` e `/data/sessions.json`: autenticação local;
- `/data/output/saved_lyrics.txt`: letra guia salva localmente.

## Modelos e recursos

| Modelo | Uso típico |
| --- | --- |
| Large-v3 Turbo | Melhor equilíbrio entre qualidade e velocidade |
| Medium | Qualidade estável com menor custo |
| Small | Processamento mais rápido |
| Tiny | Prévia e máquinas limitadas |
| Large-v3 | Maior qualidade, com maior consumo |

O tempo depende do modelo, duração da música, CPU/GPU, memória e configuração de separação vocal.

## Licença e fontes externas

O projeto integra FFmpeg, Demucs, Faster-Whisper, Silero VAD e bibliotecas Python com suas próprias licenças. Consulte os respectivos projetos antes de redistribuir imagens Docker ou conteúdo gerado. As fontes de letras são serviços externos gratuitos/públicos, sujeitos a disponibilidade, limites e termos próprios.

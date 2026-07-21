# 🎤 Sal0 Karaoke

Transforme uma música em um vídeo de karaokê sem sair da sua própria máquina. Escolha a faixa, dê um toque no visual e deixe o Sal0 Karaoke cuidar do resto: separar a voz, ouvir a música, montar as legendas e renderizar o vídeo.

É um projeto pessoal, feito para brincar com música e criar karaokês do seu jeito. ✨

## O que tem por aqui

- Upload de áudio/vídeo, biblioteca local e links do YouTube.
- Separação de vocal e instrumental com Demucs.
- Transcrição local com Faster-Whisper e sincronização de legendas em estilo karaokê.
- Modos por sílaba, palavra ou linha.
- Fundo original, cor, imagem, vídeo, paisagem, biblioteca ou YouTube.
- Ajustes de fonte, cor, posição e quebra de texto.
- Perfis para guardar seus estilos favoritos.
- Biblioteca, histórico, cache e editor para revisar as legendas antes de finalizar.
- Letra manual ou busca automática como guia.
- Telegram opcional para avisos e envio do vídeo pronto.

## Sobre a letra

O painel de letra pode ficar fechado enquanto você cria. Ao escolher uma música, o app tenta encontrar uma letra e mostra um aviso dizendo se conseguiu ou não. Quando quiser, abra o painel para ver, editar, colar ou apagar o texto.

A busca consulta só o nome da música e do artista em fontes públicas como LRCLIB, Lyrics.ovh e Musixmatch. O áudio, o vídeo, a separação de voz, a transcrição e a renderização continuam na sua máquina. Se não aparecer nada, sem drama: é só colar a letra manualmente.

## Rodando com Docker

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

Depois:

```bash
docker compose up -d
```

Abra `http://localhost:7885` e solte a primeira música na tela. 🎶

## Onde ficam as coisas

Tudo que o app guarda permanece no volume `/data`: suas mídias, fundos, resultados, perfis, letras, usuários e histórico. Faça backup dessa pasta se quiser preservar suas criações.

## Pequeno aviso

Fontes de letras e YouTube são serviços externos e podem variar de disponibilidade. O Sal0 Karaoke continua funcionando sem a busca de letra; ela é só uma ajuda extra para deixar a legenda ainda melhor.

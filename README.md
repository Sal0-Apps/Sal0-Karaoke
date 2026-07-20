# 🎤 Sal0 Karaokê

O **Sal0 Karaokê** é uma ferramenta pessoal desenvolvida para criar vídeos de karaokê de forma totalmente automática e local. O sistema separa os vocais do instrumental, filtra o silêncio, transcreve a letra e gera legendas sincronizadas palavra por palavra.

> ℹ️ **Nota**: Este é um projeto pessoal criado para uso próprio e disponibilizado "como está" (*as is*). Não há suporte técnico, garantia de atualizações ou acompanhamento de dúvidas/issues.

---

## ✨ Funcionalidades

- **🎛️ Separação de Áudio**: Separa vocais e instrumental usando Demucs (`htdemucs`).
- **🎙️ Filtro de Silêncio (Silero VAD)**: Remove partes sem voz antes da transcrição para economizar tempo e evitar alucinações de legenda.
- **⚡ Transcrição via IA (Faster-Whisper)**: Suporte a múltiplos idiomas e otimizado para rodar em CPU.
- **✨ Sincronização por Palavra (WhisperX Alignment)**: Refinamento de timestamps palavra por palavra para o efeito visual de karaokê.
- **🛠️ Editor de Legendas na Web**: Permite pausar e ajustar o texto ou o tempo das estrofes antes de renderizar o vídeo final.
- **🎬 Renderização de Vídeo**: Gera legendas em formato ASS e renderiza o vídeo final com plano de fundo personalizado.
- **📥 Entradas Flexíveis**: Aceita arquivos locais (vídeo/áudio) ou links do YouTube.
- **🤖 Bot do Telegram (Opcional)**: Envia notificações e o vídeo pronto para o seu Telegram se configurado.
- **🔐 Acesso Local Protegido**: Tela de login simples com senha criptografada para proteger o acesso na sua rede local.

---

## 🎯 Modelos de IA Disponíveis

Você pode escolher entre 5 modelos na interface:

- **Large-v3 Turbo** (*Padrão Recomendado - ~1.5GB*)
- **Medium** (*Alternativa Estável / Fallback - ~1.5GB*)
- **Small** (*Rápido - ~460MB*)
- **Tiny** (*Ultrarrápido - ~75MB*)
- **Large-v3** (*Máxima Qualidade - ~3GB*)

---

## 🐳 Como Executar no Docker

Arquivo `docker-compose.yml`:

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

Para iniciar:
```bash
docker compose up -d
```

Acesse no navegador: `http://localhost:7885`

---

## 📁 Pasta de Dados (`/data`)

Tudo o que o aplicativo precisa salvar fica na pasta `/data`:

- `/data/library/`: Arquivos originais, fundos e vídeos gerados.
- `/data/output/`: Modelos de IA, perfis de estilo e logs.
- `/data/users.json`: Usuários salvos.

---

## 💻 Requisitos

- **Processador**: Qualquer CPU de 64 bits com pelo menos 2 núcleos.
- **Memória RAM**: 4 GB a 8 GB de RAM recomendados.
- **Sistema**: Linux, Windows (Docker Desktop/WSL) ou servidor pessoal (CasaOS, ZimaOS, Unraid).

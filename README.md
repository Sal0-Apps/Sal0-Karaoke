# 🎤 Sal0 Karaokê (v4.0.0)

[![Versão](https://img.shields.io/badge/vers%C3%A3o-v4.0.0-blue.svg)](https://github.com/Sal0-Apps/Sal0-Karaoke)
[![Docker](https://img.shields.io/badge/docker-compat%C3%ADvel-2496ED.svg)](https://ghcr.io/sal0-apps/sal0-karaoke)
[![CPU Only](https://img.shields.io/badge/plataforma-CPU%20Only-green.svg)](#)
[![Licença](https://img.shields.io/badge/licen%C3%A7a-MIT-orange.svg)](#)

> **Gerador Automático e Inteligente de Vídeos de Karaokê Locais via IA**
> Separação de áudio, filtragem de silêncio, transcrição avançada e alinhamento palavra por palavra 100% offline.

---

## 📋 Visão Geral

O **Sal0 Karaokê** é uma solução completa, moderna e totalmente privada para a criação de vídeos de karaokê de nível profissional a partir de qualquer música ou vídeo. 

Utilizando o estado da arte em inteligência artificial para áudio e processamento de linguagem natural, o sistema roda **exclusivamente em CPU** e opera **100% offline**, sem enviar dados ou áudios para servidores externos.

Ideal para servidores domésticos, **Docker**, **CasaOS**, **ZimaOS**, **Unraid** ou qualquer máquina Linux/Windows local.

---

## ✨ Principais Funcionalidades

- **🎛️ Separação de Vocais e Instrumental (Demucs `htdemucs`)**:
  Separa os vocais e o instrumental da faixa original com alta fidelidade de áudio.

- **🎙️ Filtro de Silêncio com Silero VAD**:
  Remove trechos de silêncio antes da transcrição, acelerando o processamento em até 40% e eliminando alucinações de legenda.

- **⚡ Transcrição Inteligente (Faster-Whisper)**:
  Suporte a múltiplos idiomas e otimizado para execução em CPU com modulação dinâmica de RAM (`int8` e `float32`).

- **✨ Sincronização Palavra por Palavra (WhisperX Alignment)**:
  Refinamento cirúrgico de timestamps por palavra, garantindo o efeito de karaokê sincronizado e sem sobreposição.

- **🛠️ Editor e Revisor de Legendas Integrado**:
  Interface web interativa para pausar, revisar e editar o texto e os tempos das estrofes antes da renderização final do vídeo.

- **🎬 Renderização HD em ASS e FFmpeg**:
  Legendas em formato ASS com estilos personalizáveis (cores, fontes, posicionamento, marcação instrumental e prévia da próxima linha).

- **📥 Suporte a Múltiplas Fontes de Entrada**:
  Upload direto de arquivos de áudio/vídeo locais ou download automático via links do **YouTube**.

- **🤖 Notificação e Envio via Bot do Telegram (Opcional)**:
  Notificações de progresso em tempo real e envio automático do vídeo gerado diretamente para o seu Telegram.

- **🔐 Autenticação Local e Multi-Usuário**:
  Sistema de acesso seguro com hashing PBKDF2-HMAC-SHA256, proteção contra brute-force, controle de sessão (TTL) e papéis (Admin/Usuário).

---

## 🔄 Arquitetura do Pipeline de IA (v4.0.0)

```
┌─────────────────┐     ┌────────────────┐     ┌────────────────┐
│ Entrada Áudio/  │ ──> │ Demucs         │ ──> │ Silero VAD     │
│ Vídeo / YouTube │     │ (Separar Voz)  │     │ (Filtro Voz)   │
└─────────────────┘     └────────────────┘     └────────────────┘
                                                        │
                                                        ▼
┌─────────────────┐     ┌────────────────┐     ┌────────────────┐
│ Render FFmpeg   │ <── │ Editor Web     │ <── │ Faster-Whisper │
│ (Vídeo Karaokê) │     │ (Revisão ASS)  │     │ + WhisperX     │
└─────────────────┘     └────────────────┘     └────────────────┘
```

---

## 🎯 Modelos de IA Suportados

A interface permite alternar entre 5 modelos de inteligência artificial otimizados para CPU:

| Modelo | Tamanho Aprox. | Descrição / Uso Recomendado |
| :--- | :--- | :--- |
| **Large-v3 Turbo** | ~1.5 GB | **Padrão Recomendado**: Alta precisão com velocidade otimizada. |
| **Medium** | ~1.5 GB | **Alternativa Estável / Fallback**: Modelo balanceado e ultra-confiável. |
| **Small** | ~460 MB | **Rápido**: Ideal para servidores com menos recursos de memória. |
| **Tiny** | ~75 MB | **Ultrarrápido**: Para testes rápidos ou máquinas de baixo desempenho. |
| **Large-v3** | ~3.0 GB | **Máxima Qualidade**: Precisão máxima de transcrição (modo float32). |

---

## 🐳 Como Executar via Docker Compose

Crie um arquivo `docker-compose.yml` na pasta desejada:

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

Inicie o serviço com:

```bash
docker compose up -d
```

Acesse no navegador: `http://localhost:7885`

---

## 📁 Estrutura de Armazenamento e Volumes (`/data`)

Todos os dados persistentes da aplicação ficam centralizados na pasta `/data`:

- `/data/library/videos/`: Vídeos/áudios originais enviados.
- `/data/library/photos/`: Imagens e vídeos de fundo para os karaokês.
- `/data/library/history/`: Histórico de vídeos de karaokê renderizados.
- `/data/output/models/whisper/`: Modelos de IA pré-baixados.
- `/data/output/profiles.json`: Perfis salvos de estilos de legenda.
- `/data/users.json` & `/data/sessions.json`: Contas de usuários e sessões ativas.

---

## ⚙️ Requisitos de Sistema

- **Processador**: CPU x86_64 ou ARM64 (64-bit) com no mínimo 2 núcleos.
- **Memória RAM**: 
  - Mínimo: 4 GB de RAM (para modelos *Tiny*, *Small* ou *Medium*).
  - Recomendado: 8 GB de RAM (para modelo *Large-v3 Turbo*).
- **Armazenamento**: 5 GB de espaço livre para modelos e arquivos temporários.
- **Sistema Operacional**: Linux (Ubuntu, Debian, CasaOS, ZimaOS, Unraid), Windows (via Docker Desktop/WSL2) ou macOS.

---

## 🛡️ Segurança e Privacidade

- **100% Offline**: Sem telemetria, sem envio de dados ou áudios para a nuvem.
- **Criptografia de Senha**: PBKDF2 com 100.000 iterações e Salt único por usuário.
- **Proteção Brute-Force**: Bloqueio temporário automático após 10 tentativas incorretas.
- **Autenticação**: Suporte a tokens de sessão via `Authorization: Bearer` e `x-session-token`.

---

## 📜 Licença

Distribuído sob a licença **MIT**. Veja o arquivo `LICENSE` para mais detalhes.

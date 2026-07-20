# 🎤 Sal0 Karaokê (v4.0.0)

**Sal0 Karaokê** é uma aplicação completa e local para geração automática de vídeos de Karaokê com inteligência artificial, sincronização palavra por palavra, separação de vocais/instrumental e renderização de alta qualidade.

---

## 🚀 Novidades da Versão v4.0.0 (Major Release)

- **⚡ Faster-Whisper Atualizado**: Desempenho otimizado para CPU com suporte total a `int8` e `float32`.
- **🎯 5 Modelos Organizados**:
  - **Large-v3 Turbo** (*Padrão Recomendado - 1.5GB*)
  - **Medium** (*Alternativa Estável / Fallback - 1.5GB*)
  - **Small** (*Rápido - 460MB*)
  - **Tiny** (*Ultrarrápido - 75MB*)
  - **Large-v3** (*Máxima Qualidade - 3GB*)
- **🧠 Configuração Automática de IA**:
  - **CPU Threads**: Cálculo automático com base nos núcleos disponíveis (`N - 1`).
  - **Compute Type**: `int8` no uso padrão, `float32` no modo *Máxima Qualidade*.
  - **Beam Size**: 5 no modo padrão, 10 no modo *Máxima Qualidade*.
- **🎙️ Silero VAD Integrado**: Remoção de silêncio e trechos sem voz antes do Whisper, acelerando a transcrição e eliminando legendas fantasma.
- **✨ Alinhamento WhisperX Offline**: Refinamento de timestamps por palavra 100% offline para sincronização perfeita de karaokê.
- **🛠️ Editor de Legendas Corrigido**: Painel de revisão e edição de texto/tempos antes da renderização 100% funcional.
- **🔐 Segurança Hardened**: Autenticação local, proteção contra brute-force e gerenciamento de sessões com TTL.

---

## 🐳 Como Executar via Docker

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

Acesse via navegador em `http://localhost:7885` ou no IP do seu servidor local.

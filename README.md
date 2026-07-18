# Sal0 Karaokê 🎙️✨

Uma aplicação web premium, minimalista e de alta performance para a criação local de vídeos de karaokê sincronizados a partir de qualquer música ou vídeo. O sistema utiliza Inteligência Artificial local para separar os vocais e transcrever a voz de forma extremamente precisa.

---

## 🚀 Como Rodar (Docker Compose)

Você pode executar o aplicativo de forma 100% automatizada e sem precisar compilar o código fonte. A imagem pública padrão do repositório já está compilada e pronta para uso.

1. Crie uma pasta para o projeto no seu servidor (ex: `karaokê-app`).
2. Crie um arquivo chamado `docker-compose.yml` dentro dela.
3. Cole o conteúdo abaixo no arquivo:

```yaml
services:
  karaokê-app:
    image: ghcr.io/sal0-apps/sal0-karaoke:latest
    container_name: karaokê-app
    ports:
      - "7885:7860"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

4. Suba o container no terminal da pasta correspondente:
   ```bash
   sudo DOCKER_CONFIG=/tmp/.docker docker compose up -d
   ```
5. Acesse a aplicação no seu navegador: `http://<IP_DO_SERVIDOR>:7885`

---

## 📌 Controle de Versões (Tags da Imagem)

O aplicativo segue um esquema de versionamento estruturado. Você pode escolher a tag da imagem no seu `docker-compose.yml` de acordo com a sua preferência:

* `latest`: Atualizações contínuas contendo as últimas correções e novidades desenvolvidas. (Recomendado para uso do desenvolvedor principal).
* `2.0.0`: Versão estável com biblioteca permanente de mídias, suporte a vídeos de fundo em loop, download direto do YouTube, criptografia forte PBKDF2 e preview sobreposto ao fundo real.
* `1.1.1`: Versão estável inicial contendo o sistema de cache avançado, edição milimétrica de legendas em formato `Minutos:Segundos`, auto-seleção inteligente de fundo, failsafe de tela preta e novo controle de acesso local com contas de usuário.

Para travar em uma versão estável específica, basta alterar a linha `image` do compose, por exemplo:
`image: ghcr.io/sal0-apps/sal0-karaoke:2.0.0`

---

## 🔐 Controle de Acesso e Contas Locais

A partir da versão **2.0.0**, o Sal0 Karaokê conta com armazenamento criptográfico forte das senhas de usuários:

1. **PBKDF2 com Salt de 128 bits:** As senhas não são mais armazenadas em hashes simples (SHA-256). Agora o sistema utiliza derivação de chave forte PBKDF2 com Salt individual aleatório de 16 bytes e 100.000 iterações.
2. **Migração Automática:** Usuários legados criados sob o padrão antigo (v1.1) são detectados e migrados de forma transparente para a nova criptografia forte no primeiro login bem-sucedido.
3. **Login Seguro:** A opção **"Permanecer conectado"** salva a sessão de forma segura no dispositivo para que você não precise digitar as credenciais novamente.

---

## 💎 Recursos em Destaque

* **Biblioteca Permanente de Mídias:** Gerencie e guarde arquivos permanentemente em `/data/library/` nas pastas `videos` (músicas), `photos` (fundos) e `history` (vídeos de karaokês prontos salvos).
* **Download Direto do YouTube:** Insira qualquer URL do YouTube no formulário para que o servidor baixe o vídeo/áudio automaticamente usando `yt-dlp` em segundo plano e inicie o pipeline.
* **Loop & Corte de Vídeo de Fundo:** Use arquivos de vídeo como plano de fundo. Vídeos mais curtos que a música repetem em loop infinito (`-stream_loop -1` no FFmpeg) e vídeos mais longos são cortados exatamente no tempo de duração do instrumental.
* **Preview Dinâmico sobre Fundo Real:** O modal de ajuste de legenda exibe o mockup 16:9 reproduzindo o plano de fundo real selecionado (imagem ou vídeo carregado em loop) em vez de uma tela preta sólida.
* **Persistência da Letra Manual:** A letra oficial digitada/colada é persistida no cache do servidor (`cache_meta.json`) para preenchimento automático em recarregamentos de página.
* **Zero Delay Inicial:** Atualizações de status e porcentagens imediatas ao iniciar o processamento na interface gráfica.
* **Separação Avançada:** Utiliza o modelo de IA **Demucs** na CPU para isolar vocais e instrumentos de forma limpa.
* **Transcrição de Voz Ultra-Precisa:** Integra o **Whisper** com seleção de modelos leves (base) até os maiores (`large-v3`).
* **Editor de Legendas Profissional:** Painel de revisão que exibe e aceita tempos em formato amigável `Minutos:Segundos.Centésimos` (`MM:SS.cc`, ex: `01:30.50`), com inserção e deleção dinâmica de linhas.
* **Ajustes de Design e Estilo:** Configure a posição do texto (superior, central, inferior), tamanho da fonte, cor do destaque e ative visualização prévia da próxima estrofe ou estáticas no início instrumental.
* **Notificação e Entrega via Telegram Bot:** Configuração global do bot do Telegram. O aplicativo envia notificações de progresso e **envia o arquivo final de vídeo MP4 pronto** diretamente no seu grupo ou chat privado.

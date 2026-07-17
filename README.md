# Sal0 karaoke 🎙️✨

Uma aplicação web premium, minimalista e de alta performance para a criação local de vídeos de karaoke sincronizados a partir de qualquer música ou vídeo. O sistema utiliza Inteligência Artificial local para separar os vocais e transcrever a voz de forma extremamente precisa.

---

## 🚀 Como Rodar (Docker Compose)

Você pode executar o aplicativo de forma 100% automatizada e sem precisar compilar o código fonte. A imagem pública padrão do repositório já está compilada e pronta para uso.

1. Crie uma pasta para o projeto no seu servidor (ex: `karaoke-app`).
2. Crie um arquivo chamado `docker-compose.yml` dentro dela.
3. Cole o conteúdo abaixo no arquivo:

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

4. Suba o container no terminal da pasta correspondente:
   ```bash
   sudo DOCKER_CONFIG=/tmp/.docker docker compose up -d
   ```
5. Acesse a aplicação no seu navegador: `http://<IP_DO_SERVIDOR>:7885`

---

## 📌 Controle de Versões (Tags da Imagem)

O aplicativo segue um esquema de versionamento estruturado. Você pode escolher a tag da imagem no seu `docker-compose.yml` de acordo com a sua preferência:

* `latest`: Atualizações contínuas contendo as últimas correções e novidades desenvolvidas. (Recomendado para uso do desenvolvedor principal).
* `1.0`: Versão estável inicial contendo o sistema de cache avançado, edição milimétrica de legendas em formato `Minutos:Segundos`, auto-seleção inteligente de fundo, failsafe de tela preta e novo controle de acesso local com contas de usuário.
* `1.5` (Próxima): Versão planejada com otimizações adicionais de renderização e novos efeitos visuais de legenda.

Para travar em uma versão estável específica, basta alterar a linha `image` do compose, por exemplo:
`image: ghcr.io/sal0-apps/sal0-karaoke:1.0`

---

## 🔐 Controle de Acesso e Contas Locais

A partir da versão **1.0**, o Sal0 Karaoke conta com um sistema de autenticação local integrado para proteção de dados do servidor:

1. **Configuração Inicial:** No primeiro acesso ao site, a tela de configuração inicial será exibida exigindo a criação de um **Usuário Administrador** principal.
2. **Login Seguro:** Em acessos subsequentes, será solicitado o usuário e senha. A opção **"Permanecer conectado"** salva a sessão de forma segura no dispositivo para que você não precise digitar as credenciais novamente.
3. **Gerenciamento de Contas:** Administradores podem acessar a seção **"Gerenciamento de Contas Locais"** dentro das configurações avançadas da interface para cadastrar perfis de acesso para outros usuários ou excluir contas existentes.

---

## 💎 Recursos em Destaque

* **Separação Avançada:** Utiliza o modelo de IA **Demucs** na CPU para isolar vocais e instrumentos de forma limpa.
* **Transcrição de Voz Ultra-Precisa:** Integra o **Whisper** com seleção de modelos leves (base) até os maiores (`large-v3`).
* **Editor de Legendas Profissional:** Painel de revisão que exibe e aceita tempos em formato amigável `Minutos:Segundos.Centésimos` (`MM:SS.cc`, ex: `01:30.50`), com inserção e deleção dinâmica de linhas.
* **Persistência de Cache Inteligente:** Reutilize o áudio e imagem do último processamento em cache para refazer o vídeo de forma instantânea sem precisar fazer upload dos arquivos novamente.
* **Ajustes de Design e Estilo:** Configure a posição do texto (superior, central, inferior), tamanho da fonte, cor do destaque e ative visualização prévia da próxima estrofe ou estáticas no início instrumental.
* **Notificação e Entrega via Telegram Bot:** Configuração global do bot do Telegram. O aplicativo envia notificações de progresso e **envia o arquivo final de vídeo MP4 pronto** diretamente no seu grupo ou chat privado.
* **Failsafe de Tela Preta:** Fallback inteligente no gerador de vídeo. Se o container Docker não tiver imagens de paisagem localmente, o sistema usará a imagem de fundo enviada pelo usuário antes de recorrer ao fundo preto sólido.

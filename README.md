# Sal0 karaoke 🎙️✨

Uma aplicação web minimalista e de alta performance para a criação local de vídeos de karaoke sincronizados a partir de qualquer música ou vídeo. O sistema utiliza Inteligência Artificial local para separar os vocais e transcrever a voz de forma extremamente precisa.

---

## 🚀 Como Rodar em Qualquer Servidor (ZimaOS / Docker Compose)

Para rodar este aplicativo em outro servidor de forma 100% automatizada e sem precisar clonar arquivos de código, você só precisa de **um arquivo** de configuração Docker Compose.

1. Crie uma pasta para o projeto no seu servidor (ex: `karaoke-app`).
2. Crie um arquivo chamado `docker-compose.yml` dentro dela.
3. Cole o conteúdo abaixo no arquivo (certifique-se de substituir `SEU_USUARIO_GITHUB` pelo seu nome de usuário real do GitHub onde este código está hospedado):

```yaml
services:
  karaoke-app:
    image: ghcr.io/SEU_USUARIO_GITHUB/karaoke-app:latest
    container_name: karaoke-app
    ports:
      - "7885:7860"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

4. No terminal da pasta onde criou o arquivo, execute o comando para baixar e subir o container:
   ```bash
   sudo DOCKER_CONFIG=/tmp/.docker docker compose up -d
   ```
5. Acesse a aplicação no seu navegador: `http://<IP_DO_SERVIDOR>:7885`

---

## 💎 Recursos do Sal0 karaoke

* **Separação Avançada:** Utiliza o modelo de IA **Demucs** na CPU para isolar vocais e instrumentos.
* **Transcrição de Voz Ultra-Precisa:** Integra o **Whisper** com seleção de modelos leves até os maiores (`large-v3`).
* **Visual Minimalista e Limpo:** Layout adaptável (Mobile e Desktop) contendo uma aba colapsável de **Configurações Avançadas** para esconder a complexidade técnica.
* **Perfis de Uso Persistentes:** Salve suas configurações preferidas de legendas e modelo de Whisper para carregar com um único clique.
* **Notificação e Entrega via Telegram Bot:** Configuração global do bot do Telegram. O aplicativo envia notificações curtas de progresso e **envia o arquivo final de vídeo MP4 pronto** diretamente no seu grupo do Telegram.
* **Sincronização Ativa Multi-Navegador:** Monitore o progresso do mesmo vídeo em tempo real abrindo o site no PC, celular ou qualquer outro dispositivo concorrentemente.
* **Economia de Recursos (Persistência local):** Os modelos pesados de IA (Whisper e Demucs) ficam salvos localmente na pasta `./data/models` do seu servidor. Eles nunca precisarão ser baixados novamente se você deletar ou recriar o container!

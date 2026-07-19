# 🎤 Sal0 Karaokê v3.0.6

Uma ferramenta local, simples e funcional para criar vídeos de karaokê com remoção de voz via inteligência artificial e legendas sincronizadas.

---

## 📖 Tutorial Rápido para Iniciantes

1. **Escolha a Música:** Envie uma música/vídeo do seu computador, informe a URL do YouTube ou escolha um arquivo salvo na sua Biblioteca.
2. **Escolha o Fundo (Opcional):** Envie uma imagem ou vídeo para usar como fundo do seu karaokê.
3. **Personalize a Legenda:** Nas "Opções Avançadas", altere o tamanho da fonte, a cor do texto, o alinhamento da legenda e as preferências do modelo IA.
4. **Clique em Criar Vídeo Karaokê:** O servidor vai separar o vocal do instrumental (usando Demucs) e sincronizar a letra automaticamente (usando Whisper AI).
5. **Baixe o Vídeo:** Quando terminar, baixe seu vídeo em MP4 direto pelo navegador ou acesse a aba Biblioteca & Histórico.

---

## ⚙️ Principais Funcionalidades

- 🎙️ **Separação de Vocais:** Remove o vocal original e produz o áudio instrumental.
- 📝 **Legendas Sincronizadas:** Animação de varredura por sílabas, palavra por palavra ou linha inteira.
- 📚 **Biblioteca Permanente:** Arquivos enviados ficam armazenados no seu servidor para reutilização rápida.
- ✈️ **Envio Automático para o Telegram:** Envia o vídeo renderizado diretamente para o seu bot ou canal.
- 🎨 **Perfis de Estilo:** Salve suas configurações preferidas para usar em um clique.
- 🔒 **Servidor Local e Seguro:** Processamento 100% no seu próprio hardware.

---

## 🚀 Como Executar com Docker Compose

```yaml
version: '3.8'

services:
  karaoke:
    image: ghcr.io/sal0-apps/sal0-karaoke:3.0.6
    container_name: karaoke-app
    ports:
      - "7860:7860"
    volumes:
      - /seu/caminho/data:/data
    restart: unless-stopped
```

Acesse no navegador em: `http://localhost:7860`

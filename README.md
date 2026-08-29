# Sal0 Karaokê 8.0.0

Aplicação local e auto-hospedada para transformar músicas em vídeos de karaokê. O projeto oferece uma interface web servida por Docker e um aplicativo Android que acessa essa interface no endereço do servidor. O processamento principal ocorre no próprio servidor: o áudio não é enviado para uma plataforma de processamento em nuvem.

Esta é a versão final publicada deste repositório. O objetivo desta documentação é registrar, de forma independente e verificável, a arquitetura, os requisitos, o funcionamento, os limites e as referências técnicas do software. Não há promessa de acompanhamento contínuo, suporte permanente ou compatibilidade futura.

Documentação pública: [Segurança](SECURITY.md) · [Privacidade](PRIVACY.md) · [Status do projeto](PROJECT_STATUS.md) · [Licença](LICENSE)

## Visão geral

O fluxo de criação é composto por cinco fases:

1. seleção de uma música por upload, Biblioteca ou URL do YouTube;
2. extração e preparação do áudio;
3. separação entre voz e instrumental;
4. transcrição local da voz e geração de legendas sincronizadas;
5. composição e renderização do vídeo final com fundo, estilo e histórico.

O sistema inclui contas locais, isolamento de dados entre usuários, permissões administrativas, fila persistente de renderização, Biblioteca de mídias, perfis de renderização, revisão opcional de legendas, notificações por Telegram e uma rota Android para conexão ao servidor.

## Recursos

- modo rápido e modo detalhado para criação de karaokê;
- modo dedicado para legendar vídeos longos, preservar a fala original e entregar MP4 + SRT em português, inglês, espanhol ou no idioma detectado;
- upload múltiplo de áudio e vídeo com processamento sequencial em fila;
- upload de áudio, vídeo e imagens;
- importação opcional de conteúdo do YouTube por `yt-dlp`, com atualização administrativa persistente do mecanismo;
- separação de voz e instrumental usando Demucs;
- transcrição com Faster-Whisper/WhisperX;
- alinhamento e geração de legendas no formato ASS;
- tradução local opcional de legendas com M2M100, sem envio do texto a um serviço de tradução;
- fundos sólidos, imagens, vídeos, vídeo original e itens da Biblioteca;
- busca opcional de letra-guia em provedores externos;
- revisão de texto e tempos antes da renderização;
- resultados permanentes no histórico da Biblioteca;
- contas locais com autenticação por sessão;
- administrador com painel de visualização e download dos resultados de todas as contas;
- bot pessoal do Telegram por usuário e notificações administrativas;
- links de download direto com tokens aleatórios;
- aplicativo Android para roteamento entre endereço local e externo;
- publicação de imagem Docker pelo GitHub Actions.

## Arquitetura e armazenamento

O container utiliza `/data` como volume persistente:

```text
/data/library/videos/    mídias de entrada
/data/library/photos/    imagens e vídeos de fundo
/data/library/history/   vídeos finais e legendas SRT correspondentes
/data/output/models/     modelos Whisper e modelo opcional de tradução
/data/output/            configurações, estado e logs
/data/output/queue_jobs/ entradas isoladas da fila de processamento
/data/cache/             arquivos temporários do pipeline
/data/users.json         usuários locais
/data/sessions.json      sessões locais
```

Contas comuns recebem diretórios isolados sob `/data/user_data`. A conta administradora mantém a Biblioteca principal e pode consultar os diretórios das contas comuns para preview, download, renomeação e exclusão autorizada.

## Execução com Docker

Requisito: Docker Engine com Docker Compose v2.

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

Inicialização:

```bash
mkdir -p data
docker compose pull
docker compose up -d
```

Abra `http://localhost:7885`. No primeiro acesso, crie a conta administradora. Para atualizar uma instalação existente:

```bash
docker compose pull
docker compose up -d --force-recreate
```

O container não deve receber volumes sobre `/app`; apenas `/data` deve ser persistido. A atualização da imagem não altera os dados desse volume.

## Aplicativo Android

O aplicativo Android é um cliente nativo leve para o servidor. Ele armazena os endereços configurados, testa a disponibilidade do endereço local e do endereço externo e abre a interface web do servidor com navegação integrada. A mídia e o processamento permanecem no servidor.

O build de lançamento utiliza `VERSION_NAME=8.0.0` e `VERSION_CODE=80000`. A assinatura deve ser fornecida somente pelo ambiente privado de compilação e nunca deve ser adicionada ao repositório.

## Autenticação e permissões

O backend aceita sessão por `x-session-token`, `Authorization: Bearer <token>` e parâmetro de consulta `token`. O frontend envia os dois cabeçalhos principais. Usuários comuns controlam somente seus próprios arquivos, resultados, perfis e configurações. O administrador pode gerenciar usuários, tarefas, configurações globais e mídias de todas as contas.

## Telegram

Cada conta pode informar o token do próprio bot e o Chat ID correspondente. O sistema envia progresso e o resultado final para o usuário responsável. O administrador recebe também os avisos das contas sob sua gestão, quando seu bot estiver configurado. Tokens e Chat IDs são armazenados somente no volume `/data` e não fazem parte do código-fonte.

## Privacidade, segurança e limitações

- credenciais, tokens, sessões, logs e mídias devem permanecer fora do Git;
- links diretos do Telegram funcionam como credenciais temporárias de acesso e não devem ser compartilhados;
- dados enviados a YouTube, provedores de letras e APIs externas seguem as políticas desses serviços;
- modelos de IA e processamento de vídeo exigem espaço em disco, memória e tempo compatíveis com o hardware;
- a primeira tradução para português ou espanhol pode baixar aproximadamente 2 GB de pesos do modelo M2M100 para o volume persistente;
- esta documentação não constitui garantia de disponibilidade, suporte, segurança ou compatibilidade com serviços externos;
- o administrador é responsável pela exposição da porta, proxy, HTTPS, backups e políticas de retenção do servidor.

## Uso responsável

O Sal0 Karaokê é apenas uma ferramenta. Cada usuário é responsável por respeitar a legislação do seu país, os direitos autorais aplicáveis e os termos dos serviços que decidir utilizar.

O projeto não distribui músicas, não distribui vídeos, não distribui letras protegidas por direitos autorais e não incentiva pirataria. O usuário deve utilizar apenas arquivos, obras, permissões e integrações para os quais tenha autorização adequada.

## Suporte

Issues sobre bugs críticos são bem-vindas quando não contêm dados sensíveis e quando seguem as orientações de segurança. Vulnerabilidades devem ser comunicadas conforme [SECURITY.md](SECURITY.md), e não em uma Issue pública.

O projeto está em manutenção mínima. Não há garantia de novas funcionalidades, respostas rápidas, correções para todos os ambientes ou suporte contínuo.

## Referências técnicas

O projeto utiliza ou se integra às seguintes tecnologias e documentações públicas:

- [FastAPI](https://fastapi.tiangolo.com/), API HTTP e injeção de dependências;
- [Docker Compose](https://docs.docker.com/compose/), execução e persistência do serviço;
- [PyTorch](https://pytorch.org/), infraestrutura de inferência dos modelos;
- [Demucs](https://github.com/facebookresearch/demucs), separação de fontes musicais;
- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper), transcrição eficiente;
- [WhisperX](https://github.com/m-bain/whisperX), alinhamento de palavras e tempos;
- [M2M100 418M](https://huggingface.co/facebook/m2m100_418M), tradução multilíngue local sob licença MIT;
- [Transformers](https://huggingface.co/docs/transformers/), carregamento e execução local do modelo de tradução;
- [yt-dlp](https://github.com/yt-dlp/yt-dlp), obtenção opcional de mídia por URL;
- [FFmpeg](https://ffmpeg.org/documentation.html), conversão, extração e renderização de mídia;
- [LRCLIB](https://lrclib.net/), busca opcional de letras-guia;
- [lyrics.ovh](https://lyrics.ovh/), provedor alternativo de letras;
- [Musixmatch](https://developer.musixmatch.com/), provedor alternativo consultado pelo fluxo de letras;
- [Telegram Bot API](https://core.telegram.org/bots/api), notificações e envio de resultados;
- [Android Developers](https://developer.android.com/), cliente Android;
- [GitHub Actions](https://docs.github.com/actions), validação e publicação da imagem;
- [GitHub Container Registry](https://docs.github.com/packages/working-with-a-github-packages-registry/working-with-the-container-registry), distribuição da imagem Docker.

As integrações externas estão sujeitas às licenças, termos de uso, limites e disponibilidade de seus respectivos projetos e serviços. O código deste repositório é distribuído sob a licença MIT. Componentes de terceiros permanecem regidos por suas próprias licenças.

## Licença

Copyright (c) 2026 Sal0 Apps.

Este projeto é software livre e aberto, distribuído sob os termos da [MIT License](LICENSE). Consulte também as licenças dos componentes de terceiros antes de redistribuir uma imagem ou pacote que os contenha.

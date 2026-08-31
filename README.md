# Sal0 Karaokê 9.0.7

O Sal0 Karaokê é uma aplicação local e auto-hospedada para criar vídeos de karaokê e arquivos de legenda a partir de mídias fornecidas pelo próprio operador. O servidor executa extração de áudio, separação de voz, transcrição, sincronização, tradução opcional e renderização. A interface web é distribuída em uma imagem Docker; o aplicativo Android funciona como cliente do servidor e abre essa mesma interface com roteamento entre endereços local e externo.

Esta é a versão final do projeto. O desenvolvimento ativo foi encerrado e a manutenção é mínima. A publicação do código permite uso, estudo, modificação e criação de forks nos termos da licença MIT, mas não representa promessa de suporte, adequação jurídica para um caso concreto ou compatibilidade futura com serviços externos.

## Documentação

- [Segurança](SECURITY.md)
- [Auditoria de segurança](SECURITY_AUDIT.md)
- [Privacidade](PRIVACY.md)
- [Status do projeto](PROJECT_STATUS.md)
- [Uso jurídico e publicação](LEGAL.md)
- [Componentes e materiais de terceiros](THIRD_PARTY_NOTICES.md)
- [Licença do código](LICENSE)
- [Cliente Android](android/README.md)

## Funcionalidades

- modos Rápido e Detalhado para criação de vídeos de karaokê;
- modo Gerar SRT para transcrição integral de áudio ou vídeo;
- SRT no idioma detectado e tradução local opcional;
- fila persistente para arquivos, links e itens da Biblioteca nos três modos;
- progresso geral e progresso específico das etapas de processamento;
- separação de voz e instrumental com Demucs;
- transcrição local com Faster-Whisper e estabilização de tempos;
- geração de legendas ASS e renderização com FFmpeg;
- fundos sólidos, imagens, vídeos, vídeo original e Biblioteca;
- contas locais com dados separados por usuário;
- acesso administrativo aos resultados de todas as contas;
- integração opcional com Telegram para avisos, arquivos SRT, vídeos e links;
- importação opcional por URL com `yt-dlp`;
- atualização administrativa do mecanismo `yt-dlp` armazenada em `/data`;
- cliente Android com seleção de rota, upload, reprodução e downloads.

## Fluxo de processamento

1. O usuário seleciona arquivo, URL ou item da Biblioteca.
2. O servidor cria um trabalho isolado e o posiciona na fila.
3. A mídia é normalizada e, nos modos de karaokê, voz e instrumental são separados.
4. O Whisper transcreve o áudio e publica o progresso da etapa.
5. O servidor gera SRT ou compõe as legendas do vídeo.
6. O resultado final é salvo na Biblioteca da conta responsável.
7. Se o Telegram estiver configurado, o resultado e os links disponíveis são enviados aos destinatários autorizados.

Trabalhos concluídos ou cancelados não permanecem como histórico da fila. Os resultados permanentes ficam na Biblioteca.

## Requisitos

- Docker Engine;
- Docker Compose v2;
- processador compatível com a imagem publicada;
- espaço suficiente para modelos de IA, arquivos temporários e resultados;
- memória e tempo de processamento proporcionais à duração e à resolução das mídias.

O primeiro uso pode exigir downloads grandes de modelos. A imagem e as dependências também podem mudar de tamanho conforme os repositórios externos utilizados no build.

## Execução com Docker

Exemplo mínimo:

```yaml
services:
  karaoke-app:
    image: ghcr.io/sal0-apps/sal0-karaoke:9.0.7
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

Abra `http://localhost:7885` e crie a conta administradora no primeiro acesso. Para atualizar a instalação sem substituir o volume:

```bash
docker compose pull
docker compose up -d --force-recreate
```

Persista somente `/data`. Montar um volume sobre `/app` pode ocultar arquivos da imagem e produzir uma instalação inconsistente.

## Armazenamento

```text
/data/library/videos/      mídias originais
/data/library/photos/      imagens e vídeos de fundo
/data/library/history/     vídeos finais e arquivos SRT
/data/output/models/       modelos locais
/data/output/queue_jobs/   diretórios isolados dos trabalhos ativos
/data/output/              configurações, estado e logs
/data/cache/               cache reutilizável do administrador
/data/user_data/           dados isolados das contas comuns
/data/users.json           usuários locais
/data/sessions.json        sessões locais
```

O conteúdo de `/data` nunca deve ser adicionado ao Git. O operador é responsável por permissões, backup, retenção e exclusão desses dados.

## Aplicativo Android

O APK é um cliente do servidor, não um processador independente. Ele armazena os endereços configurados no aparelho, escolhe a rota disponível e abre a interface web integrada. O processamento e a Biblioteca permanecem no servidor.

O workflow de uma tag `v*` compila o APK e o anexa à Release correspondente. Quando o ambiente de CI não recebe uma chave privada de lançamento, o Gradle utiliza a assinatura de depuração para manter o artefato instalável; isso não equivale a uma assinatura oficial permanente. Consulte o [guia Android](android/README.md).

## Autenticação e exposição de rede

O backend aceita sessão pelos cabeçalhos `x-session-token` e `Authorization: Bearer`, além do parâmetro de consulta `token` usado por alguns downloads e previews. Parâmetros de consulta podem aparecer em logs de proxy, navegador ou servidor; trate esses registros como confidenciais.

Para acesso fora de uma rede confiável:

- use HTTPS com um proxy reverso mantido e atualizado;
- restrinja a porta do container;
- proteja e faça backup do volume `/data`;
- revise logs antes de compartilhá-los;
- não exponha tokens, links públicos ou arquivos de sessão;
- considere VPN ou rede privada em vez de publicação direta na Internet.

## Serviços externos e dados transmitidos

O processamento de mídia ocorre no servidor, mas a instalação não é estritamente offline por padrão:

- o frontend solicita fontes ao Google Fonts quando a página é carregada;
- o build e a primeira execução podem baixar modelos do Hugging Face e do Demucs;
- a imagem baixa Deno e imagens de fundo públicas durante o build;
- YouTube, LRCLIB, Lyrics.ovh e Musixmatch são consultados somente quando os recursos correspondentes são utilizados;
- Telegram recebe mensagens, arquivos ou links quando configurado pelo usuário.

Leia [PRIVACY.md](PRIVACY.md) antes de expor a aplicação a outras pessoas.

## Uso responsável

O software é apenas uma ferramenta. O usuário e o operador da instalação são responsáveis por cumprir a legislação, os direitos autorais, os direitos de imagem, as licenças das mídias e os termos dos serviços utilizados.

O projeto não inclui nem distribui músicas, vídeos ou letras comerciais no repositório. Ele não concede autorização para baixar, copiar, traduzir, transformar, exibir ou redistribuir conteúdo de terceiros. A presença de suporte técnico a uma URL não significa que o serviço de origem autorize o download. Use apenas material próprio, em domínio público, sob licença compatível ou autorizado pelo titular.

O projeto não incentiva pirataria. Consulte [LEGAL.md](LEGAL.md) para as ressalvas específicas sobre YouTube, letras, codecs, modelos e redistribuição da imagem Docker.

## Segurança e suporte

Issues para bugs críticos são bem-vindas quando não contêm segredos ou dados privados. Vulnerabilidades não devem ser publicadas em Issues; siga [SECURITY.md](SECURITY.md).

O projeto está em manutenção mínima. Não há SLA, garantia de resposta rápida, promessa de novas funcionalidades ou garantia de correção de vulnerabilidades futuras. A [auditoria de 31 de agosto de 2026](SECURITY_AUDIT.md) encontrou dependências com vulnerabilidades conhecidas e limitações de reprodutibilidade; leia o relatório antes de expor ou redistribuir a aplicação. Dependências devem ser auditadas novamente antes de cada distribuição, pois advisories e licenças podem mudar.

## Licença

O código original deste repositório é distribuído sob a [MIT License](LICENSE). A licença MIT não substitui as licenças dos componentes, modelos, fontes, imagens, codecs ou serviços externos. Consulte [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) antes de redistribuir o Docker ou o APK.

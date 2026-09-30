# Sal0 Karaokê

Aplicação auto-hospedada para criar vídeos de karaokê e legendas SRT a partir de áudios e vídeos fornecidos pelo usuário. O servidor realiza a extração de áudio, a separação de voz e instrumental, a transcrição com Whisper, a revisão, a tradução opcional e a renderização. O navegador do PC e o aplicativo Android acessam a mesma instalação e acompanham os mesmos trabalhos.

O processamento principal ocorre no servidor, inclusive em instalações que utilizam apenas CPU. O Android funciona como cliente: conecta-se por endereço local ou externo, envia arquivos, reproduz resultados e salva downloads no aparelho. Modelos, mídias, contas, perfis e fila são mantidos no volume persistente do servidor.

O código original é software livre sob a [licença MIT](LICENSE). Dependências e materiais de terceiros possuem suas próprias licenças. O projeto recebe manutenção pontual, conforme disponibilidade, sem promessa de novas funcionalidades ou suporte contínuo.

## Documentação

- [Manual completo: recursos e tutoriais](MANUAL.md)
- [Instalação, atualização, backup e operação](DEPLOYMENT.md)
- [Cliente Android: conexão, instalação e compilação](android/README.md)
- [Segurança e comunicação privada de vulnerabilidades](SECURITY.md)
- [Revisões de segurança e limitações](SECURITY_AUDIT.md)
- [Privacidade e serviços externos](PRIVACY.md)
- [Estado e manutenção do projeto](PROJECT_STATUS.md)
- [Direitos de uso e distribuição](LEGAL.md)
- [Componentes, modelos, fontes e imagens de terceiros](THIRD_PARTY_NOTICES.md)
- [Licença do código original](LICENSE)

Dentro da aplicação, o botão **Manual** abre tutoriais curtos, organizados em seções expansíveis para leitura no celular.

## Escolha do modo

| Modo | Quando usar | O que configurar | Resultado |
| --- | --- | --- | --- |
| Rápido | Criar karaokê com o perfil preparado pelo administrador | Música e fundo opcional | MP4 com instrumental e legenda, conforme o perfil global |
| Detalhado | Controlar reconhecimento, versos, visual e revisão | Fonte, perfil, modelo Whisper, letra-guia, fundo e ajustes avançados | MP4 de karaokê; a opção de somente remover vocais gera vídeo instrumental sem legenda |
| Gerar SRT | Legendar áudio ou vídeo preservando a fala | Fonte, modelo, leitura da fala, VAD, revisão e idioma da tradução opcional | SRT original, tradução opcional e MP4 legendado automático para entradas somente de áudio |

**Gerar SRT** normaliza o áudio para MP3 e preserva a faixa completa, sem Demucs. Quando a entrada contém somente áudio, também cria um MP4 com fundo simples e as legendas na tela, usando a tradução quando ela for gerada ou o SRT original. A detecção verifica os fluxos da mídia: uma capa incorporada em MP3 não conta como vídeo. Entradas que já contêm vídeo continuam gerando os arquivos SRT. A tradução depende exclusivamente de uma instância LibreTranslate configurada pelo administrador, com padrão de detecção automática → português do Brasil (`pt-BR`). O SRT original é salvo antes da tradução. O Karaokê continua entregando os arquivos gerados pela interface, Biblioteca e Telegram configurado, com os links de download. Se o LibreTranslate falhar, o original continua disponível e sua entrega ao Telegram ainda é tentada. Não há limite fixo de duração imposto pelo modo, mas os recursos do servidor limitam a operação.

### Configurar e manter a tradução

Em **Ajustes → Tradução de SRT · LibreTranslate**, salve a URL base da sua instância, a chave de API se exigida, o tempo limite para enviar o SRT completo. Use **Testar e atualizar idiomas** para consultar os idiomas instalados e verificar uma tradução automática para PT-BR. A configuração fica em `/data/output/libretranslate.json`.

O cliente envia o **arquivo SRT completo** à [API oficial `/translate_file`](https://docs.libretranslate.com/api/operations/translate_file/), baixa o resultado e verifica a quantidade e os tempos das legendas antes de disponibilizá-lo. A instância deve permitir tradução de arquivos e ter `pt-BR` instalado. O tempo limite padrão é de 1.800 segundos por requisição, configurável até 7.200 segundos. A API não informa percentual interno de tradução. Erros temporários têm até três tentativas, sempre preservando o original.

O container `libretranslate/libretranslate:latest` pode ser atualizado separadamente pelo CasaOS/Docker; [modelos de idiomas são atualizados no LibreTranslate](https://docs.libretranslate.com/guides/installation/#update). O botão do Karaokê verifica idiomas e testa o envio e download de um SRT, mas não atualiza outro container. Mudanças incompatíveis futuras na API ainda podem exigir correção do cliente.

## Recursos disponíveis

### Entrada e criação

- Envio de um ou vários arquivos, com seleção no aparelho ou arrastar e soltar.
- Áudio: MP3, WAV, FLAC, M4A, AAC, OGG e Opus.
- Vídeo: MP4, MKV, AVI, MOV, WebM e M4V.
- Importação por link autorizado, busca automática no YouTube com miniaturas nos três modos e na Biblioteca, e reutilização de originais já salvos.
- Identificação do título de links antes do processamento, quando o provedor responde.
- Fundos com vídeo original, cor sólida, imagem, vídeo, arquivo da Biblioteca ou link.
- Fundo surpresa escolhido da coleção preparada pelo administrador.
- Separação local de fontes com Demucs e transcrição com Faster-Whisper.
- Busca opcional de letra-guia, edição manual e aviso quando a busca não encontra resultado.
- Uso automático de letra LRC sincronizada somente quando compatível com título, artista, versão e duração; sem ela, o Whisper continua disponível. Letras já sincronizadas mantêm o destaque progressivo durante o verso, usando os tempos fornecidos pelo LRC.
- Separação inteligente de backing vocals, com volume ajustável, preservando as vozes de apoio no instrumental sem remixar a voz principal.
- Perfis de voz, modelos Whisper e opção de transcrever o original ou os vocais separados.

A extensão reconhecida pelo seletor não garante que todo codec seja reproduzido pelo navegador. O servidor depende de FFmpeg e dos decodificadores instalados.

### Legendas e revisão

- Destaque por sílaba, palavra, linha ou frase estática.
- Cor, tamanho e posição do texto.
- Limites de palavras e caracteres por verso; valor zero solicita organização automática.
- Prévia da próxima frase, primeira legenda no início e indicação de trecho instrumental.
- Filtro de fala Silero VAD, quebra por pontuação e perfis salvos por conta.
- Revisão do texto e dos tempos antes da finalização.
- SRT no idioma original e tradução opcional para português, inglês ou espanhol.
- Resultados originais preservados quando a tradução opcional não pode ser concluída.

Transcrição, tradução e sincronização são estimativas de modelos. A letra-guia ajuda no reconhecimento, mas não garante correspondência perfeita. Revise resultados destinados a publicação, exibição ou acessibilidade.

### Fila, progresso e manutenção

- Uma tarefa de processamento por vez no servidor.
- Até 25 trabalhos ativos por perfil, contando o trabalho em execução.
- Botão **Adicionar novo processo** para abrir os três modos durante o processamento.
- Entradas por arquivo, link ou Biblioteca com opções próprias para cada envio.
- Reordenação de itens aguardando e remoção individual.
- Cancelamento do processo atual.
- Progresso total em destaque, acompanhado pelo avanço da etapa atual, incluindo backing vocals e MP4 do modo SRT.
- Avisos de novas etapas no Telegram; separação das vozes de apoio e renderização do vídeo de áudio informam o avanço em marcos de 25%.
- Pausa administrativa ao fim de uma etapa, com salvamento dos resultados intermediários.
- Retomada após reiniciar, desde que o mesmo volume e os arquivos da tarefa sejam preservados.
- Conclusão da tentativa de entrega ao Telegram antes do início do próximo trabalho.

Qualquer perfil autenticado pode adicionar tarefas, independentemente do dono da tarefa em execução. Só o administrador altera a ordem. Cada perfil vê seus itens e recebe somente suas notificações e resultados; a administração acompanha todos. Itens concluídos ou cancelados saem da fila; os resultados salvos permanecem na Biblioteca. Percentuais de progresso não representam uma previsão exata do tempo restante.

### Biblioteca e contas

- **Resultados** primeiro, com ordenação do mais recente para o mais antigo e identificação do proprietário para a administração.
- Seções **Resultados**, **Adicionar à biblioteca**, **Originais** e **Fundos** recolhíveis, como no manual.
- Miniaturas de vídeo com frame escurecido e título; cartões de título para SRT.
- Grade compacta de resultados no PC e seleção discreta para excluir vários arquivos ou todos os itens de uma categoria, com confirmação e identificação por perfil.
- Uploads e importações opcionais por URL.
- Reutilização, visualização, renomeação e exclusão, conforme o tipo de item.
- Download de MP4 e SRT em Resultados.
- Visualização com controles para avançar ou voltar dez segundos.
- Contas locais com sessão, senhas protegidas por hash e diretórios separados.
- Administrador com acesso às mídias e aos resultados das contas sob sua gestão.
- Configuração administrativa dos modelos, do Modo Rápido, da coleção de fundos e dos usuários.
- Atualização administrativa do mecanismo de importação `yt-dlp`, persistida em `/data`.
- Download administrativo de diagnóstico.

### Telegram e Android

Novos vídeos incluem uma capa em uma abertura silenciosa adicional de três segundos, independente do tempo do conteúdo. O áudio, a imagem e as legendas do karaokê começam juntos após a abertura. O modo SRT preserva os tempos de fala e os silêncios, sem essa abertura. Vídeos antigos não são reeditados automaticamente. A geração usa os [filtros locais do FFmpeg](https://ffmpeg.org/ffmpeg-filters.html), sem serviço externo de imagens.

Refazer um karaokê pelo cache reaproveita apenas insumos compatíveis, não a renderização ou os checkpoints da tarefa anterior. A retomada de uma tarefa pausada continua preservando suas etapas concluídas.

Cada conta pode configurar seu bot e destinatário. As mensagens intermediárias informam as etapas e a situação da letra-guia. A conclusão informa o tempo de processamento e os links local/externo disponíveis, além de tentar anexar o vídeo e/ou os arquivos SRT. No modo SRT com entrada somente de áudio, o MP4 e cada SRT são enviados separadamente.

Quando o vídeo excede o limite adotado pelo envio, o servidor tenta criar uma prévia compactada apenas para o Telegram. O original salvo permanece intacto. Falhas de rede, limites da API e erros de compressão podem impedir o anexo; o envio direto não é garantido para toda mídia.

No Android, **Configurações do app** fica na faixa inferior, inclusive quando o servidor está offline. Ela permite alterar Wi-Fi e endereços de conexão. Os recursos de criação e Telegram são configurados na aba **Ajustes** da página. Os downloads vão para a pasta **Downloads**, com tratamento de nomes UTF-8 e sufixos para evitar sobrescritas.

## Publicação no YouTube

O administrador conecta o canal em **Ajustes → Publicar no YouTube**, verifica a confirmação com o nome do canal e carrega as playlists. A autorização gratuita usa um assistente no computador e o navegador do Google; o servidor pode continuar em HTTP. Não exige serviço pago nem contratação de HTTPS. Consulte o [tutorial de conexão](UPDATES_AUTOMATIC_KARAOKE.md#conectar-o-canal-sem-https-no-servidor).

Em **Playlist de cada usuário**, a administração define uma playlist válida para cada conta. A playlist do administrador fica em **Padrões de publicação do administrador**. Com o canal conectado e uma playlist definida no perfil, **Publicar no YouTube** começa marcado para todos os usuários, inclusive contas novas e configurações antigas, e a publicação automática usa **Não listado**. A playlist do perfil é obrigatória: sem ela, a interface e o servidor bloqueiam a publicação. No modo rápido, o administrador pode escolher outra playlist para aquele vídeo, com a do perfil selecionada por padrão. O envio continua opcional por vídeo: desmarcado, nada é publicado. Título e capa automática ficam definidos antes da publicação. Vídeos prontos também podem ser publicados pelo painel administrativo, com outra privacidade escolhida explicitamente. O [manual](MANUAL.md#youtube-e-publicação-por-usuário) explica configuração e falhas comuns.

## Início rápido com Docker

A versão de distribuição desta documentação é **9.9.7**. O título e o rodapé da página mostram apenas o nome da aplicação. A versão do servidor pode ser consultada no Manual; a versão do APK aparece nas configurações nativas.

Crie um arquivo `compose.yaml`:

```yaml
services:
  karaoke-app:
    image: ghcr.io/sal0-apps/sal0-karaoke:9.9.7
    container_name: karaoke-app
    ports:
      - "7885:7860"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

Execute no diretório do arquivo:

```bash
mkdir -p data
docker compose pull
docker compose up -d
```

Abra `http://localhost:7885` no servidor. Em outro dispositivo, use o endereço do servidor na rede e a porta publicada. Crie o administrador antes de disponibilizar a instalação a outras pessoas.

Para acompanhar automaticamente a tag de distribuição mais recente, use `ghcr.io/sal0-apps/sal0-karaoke:latest`. Alterar a tag exige baixar a imagem e recriar o container; apenas reiniciar não atualiza a imagem. Leia o [procedimento de pausa e atualização](DEPLOYMENT.md#atualizar-com-uma-tarefa-em-andamento).

## Uso responsável

O software é uma ferramenta. O usuário e o operador são responsáveis por cumprir a legislação aplicável, os direitos autorais, os direitos de imagem e os termos dos serviços utilizados.

O repositório não distribui músicas, vídeos ou letras comerciais e não incentiva pirataria. A existência de um importador não autoriza baixar, transformar, traduzir, exibir ou redistribuir conteúdo de terceiros. Use material próprio, em domínio público, sob licença compatível ou com autorização.

Consulte [LEGAL.md](LEGAL.md) para os cuidados relativos a serviços externos, modelos, imagens e distribuição de binários.

## Suporte

Issues sobre bugs críticos são bem-vindas quando não contêm dados privados. Vulnerabilidades devem ser comunicadas pelo procedimento de [SECURITY.md](SECURITY.md), sem publicação de detalhes exploráveis em Issues.

A manutenção é mínima. Não há SLA, garantia de respostas rápidas, revisão de todos os pull requests ou novas funcionalidades. A [auditoria](SECURITY_AUDIT.md) registra achados e limites conhecidos; disponibilizar o código publicamente não equivale a certificar a segurança de uma instalação.

## Licença

O código original permanece sob [MIT](LICENSE), permitindo uso, estudo, modificação e redistribuição com preservação dos avisos exigidos. Bibliotecas, modelos, fontes, imagens e executáveis de terceiros mantêm suas próprias condições. Consulte [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

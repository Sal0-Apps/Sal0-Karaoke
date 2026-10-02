# Sal0 Karaokê

Aplicação auto-hospedada para criar vídeos de karaokê e legendas SRT a partir de áudios e vídeos fornecidos pelo usuário. O servidor realiza a extração de áudio, a separação de voz e instrumental, a transcrição com Whisper, a revisão, a tradução opcional e a renderização. O navegador do PC e o aplicativo Android acessam a mesma instalação e acompanham os mesmos trabalhos.

O processamento principal ocorre no servidor, inclusive em instalações que utilizam apenas CPU. O Android funciona como cliente: conecta-se por endereço local ou externo, envia arquivos, reproduz resultados e salva downloads no aparelho. Modelos, mídias, contas, perfis e fila são mantidos no volume persistente do servidor.

O código original é software livre sob a [licença MIT](LICENSE). Dependências e materiais de terceiros possuem suas próprias licenças. O projeto recebe manutenção pontual, conforme disponibilidade, sem promessa de novas funcionalidades ou suporte contínuo.

O Sal0 Karaokê é destinado a uma instalação pessoal, acessada pela rede local ou por VPN, como ZeroTier. O repositório aberto disponibiliza o código e os pacotes; o projeto não opera um serviço público de processamento nem coleta centralmente as mídias das instalações. Não é necessário expor a porta do app à internet. O processamento principal é local, mas as integrações escolhidas podem se comunicar com serviços externos.

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

**Gerar SRT** usa diretamente o áudio da mídia original e preserva a faixa completa, sem Demucs. Quando a entrada contém somente áudio, também cria um MP4 com fundo simples e as legendas na tela, usando a tradução quando ela for gerada ou o SRT original. A detecção verifica os fluxos da mídia: uma capa incorporada em MP3 não conta como vídeo. Entradas que já contêm vídeo continuam gerando os arquivos SRT. A tradução depende exclusivamente de uma instância LibreTranslate configurada pelo administrador, com padrão de detecção automática → português do Brasil (`pt-BR`). O SRT original é salvo antes da tradução. O Karaokê continua entregando os arquivos gerados pela interface, Biblioteca e Telegram configurado, com os links de download. Se o LibreTranslate falhar, o original continua disponível e sua entrega ao Telegram ainda é tentada. Não há limite fixo de duração imposto pelo modo, mas os recursos do servidor limitam a operação.

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
- Uso automático de letra LRC sincronizada somente quando compatível com título, artista, versão e duração. O texto e os horários de exibição dos versos seguem a letra sincronizada; o Whisper fornece apenas os tempos de animação das palavras reconhecidas dentro de cada verso. Pausas e durações não são redistribuídas. Sem LRC, continua o caminho acústico do Whisper.
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
- Progresso total em destaque, acompanhado pelo avanço da etapa atual, incluindo preparação e análise separadas no backing-vocal e MP4 do modo SRT. Barras de preparação concluídas não antecipam a conclusão da inferência.
- Um aviso no Telegram ao iniciar cada etapa, sem mensagens repetidas de porcentagem; os arquivos finais continuam sendo entregues.
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

A versão de distribuição desta documentação é **10.8**. O título e o rodapé da página mostram apenas o nome da aplicação. A versão do servidor pode ser consultada no Manual; a versão do APK aparece nas configurações nativas.

Crie um arquivo `compose.yaml`:

```yaml
services:
  karaoke-app:
    image: ghcr.io/sal0-apps/sal0-karaoke:10.8
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

A leitura de áudio para o Whisper usa o FFmpeg instalado no servidor, com conversão para mono a 16 kHz. Isso evita incompatibilidades de abertura de arquivos no PyAV. Em caso de falha, repita a tarefa usando o cache disponível para aproveitar as faixas já separadas.

Resultados do modo SRT, incluindo o MP4 criado para áudio, nunca são enviados ao YouTube, nem automaticamente nem manualmente. A publicação aceita somente karaokês com origem confirmada.

## Uso do YouTube em uma instalação local

As funções de pesquisa, importação por link e publicação no canal continuam disponíveis e têm papéis diferentes:

- **Pesquisar** consulta o YouTube para localizar vídeos e exibir título, canal e miniatura. Isso não concede direitos sobre o conteúdo.
- **Importar por link** usa `yt-dlp` para obter a mídia escolhida. Use somente quando os direitos do conteúdo e as condições do serviço permitirem a obtenção e o processamento. A autorização do titular, por si só, não substitui as permissões exigidas pelo YouTube. Os termos restringem downloads e acesso automatizado; as políticas de API também restringem armazenamento e separação de áudio/vídeo. A presença da função no app não comprova autorização da plataforma. Quando a obtenção pela plataforma não for permitida, use um arquivo disponibilizado por uma fonte autorizada.
- **Publicar no canal** usa a YouTube Data API com autorização OAuth do administrador. Essa autorização dá ao app acesso ao canal conectado; não licencia músicas, gravações, letras ou fundos. Contas locais autorizadas publicam nesse canal, não em um canal próprio de cada usuário. Confira o título, a capa, a playlist e a privacidade antes de iniciar.

A publicação começa marcada nos modos Rápido e Detalhado quando há canal e playlist válida no perfil. Desmarcar a opção naquela tarefa impede o envio. A privacidade padrão é **Não listado**: quem tiver o link poderá assistir; isso não equivale a privado nem dispensa direitos autorais. O servidor começa o envio como privado, aplica capa e playlist e então solicita a privacidade escolhida. O Google pode manter restrições em projetos sem auditoria.

Resultados do modo **Gerar SRT**, incluindo seus MP4, nunca são publicados no YouTube: o bloqueio vale para envio automático, manual e retomadas. Permanecem disponíveis para download, Biblioteca, prévia e Telegram configurado. Vídeos antigos sem origem confirmada também ficam bloqueados na publicação.

O uso pessoal, a ausência de divulgação, a gratuidade e o acesso por VPN não criam autorização para baixar, transformar ou publicar conteúdo protegido. Regras do serviço e direitos autorais são condições independentes. As funções foram preservadas; este texto não certifica que toda forma de uso esteja autorizada.

Referências: [Termos do YouTube](https://www.youtube.com/static?template=terms), [políticas da API](https://developers.google.com/youtube/terms/developer-policies), [privacidade do Google](https://policies.google.com/privacy) e [permissões da conta Google](https://myaccount.google.com/permissions).

## Suporte

Issues sobre bugs críticos são bem-vindas quando não contêm dados privados. Vulnerabilidades devem ser comunicadas pelo procedimento de [SECURITY.md](SECURITY.md), sem publicação de detalhes exploráveis em Issues.

A manutenção é mínima. Não há SLA, garantia de respostas rápidas, revisão de todos os pull requests ou novas funcionalidades. A [auditoria](SECURITY_AUDIT.md) registra achados e limites conhecidos; disponibilizar o código publicamente não equivale a certificar a segurança de uma instalação.

## Licença

O código original permanece sob [MIT](LICENSE), permitindo uso, estudo, modificação e redistribuição com preservação dos avisos exigidos. Bibliotecas, modelos, fontes, imagens e executáveis de terceiros mantêm suas próprias condições. Consulte [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Quando um vídeo de fundo decorativo é maior que a música, o início do trecho é escolhido aleatoriamente a cada nova renderização, cabendo a música inteira até o fim do fundo. Vídeos curtos continuam em loop. O vídeo original da música mantém o início e a sincronização. Com letra sincronizada, seu texto fornece os versos; o Whisper serve à análise dos tempos e da animação local.

### Verificação dos tempos da letra sincronizada


Quando existir letra sincronizada correspondente à música, o texto completo, a pontuação, os espaços e os intervalos dos versos são preservados. O texto reconhecido pelo Whisper não participa da animação: somente os tempos locais das palavras são aplicados em ordem. A letra inteira permanece visível no intervalo original do provedor; a varredura clássica de cor acompanha as palavras. O processamento local organiza as quebras visuais e separa a prévia do próximo verso, sem alterar palavras nem timestamps. A fonte se ajusta somente quando o verso completo não cabe na sua região. Sem tempo local suficiente, as palavras restantes ficam visíveis sem animação. Não há limite artificial de doze segundos por verso, redimensionamento de intervalo pela voz ou espaços invisíveis usados para consumir pausas. Com backing vocals ativos, o Whisper recebe a voz principal isolada em áudio completo, sem remoção de silêncios ou VAD no karaokê. A preparação mantém PCM float32, reamostragem adequada ao Whisper e a duração integral; o modelo escolhido usa precisão máxima. A abertura com o título permanece fora do relógio da música. Vídeos existentes precisam ser refeitos para aplicar a correção.

Downloads novos selecionam o melhor vídeo e áudio disponíveis no YouTube, sem teto de 1080p, inclusive para fundos. Isso pode aumentar o espaço e o tempo necessários. Os arquivos já em cache não ganham qualidade retroativamente; para substituir um download antigo, solicite novamente o link. A separação trabalha em PCM float32 a 44,1 kHz, a cópia de análise Whisper usa PCM float32 mono a 16 kHz e o vídeo exporta AAC a 320 kbps. A precisão máxima do Whisper é aplicada ao modelo escolhido, com maior custo em CPU/RAM. Mais precisão numérica e qualidade de origem não garantem transcrição perfeita nem restauram detalhes ausentes na fonte. O cache da análise é preservado entre tarefas compatíveis, incluindo letras sincronizadas e SRT; a revisão e a renderização continuam independentes.

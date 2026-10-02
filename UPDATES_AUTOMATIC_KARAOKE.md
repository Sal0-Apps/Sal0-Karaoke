# Busca no YouTube, letras sincronizadas, backing vocals e publicação

Esta atualização permite pesquisar pelo nome da música nas entradas do YouTube. A busca automática começa depois de uma pausa na digitação e apresenta até seis vídeos com miniatura, título, canal e duração. Está disponível nos modos Rápido, Detalhado e Gerar SRT, além das entradas da Biblioteca. Ao escolher um vídeo, o app preenche o link e mantém o fluxo normal de criação. A pesquisa não baixa os vídeos automaticamente.

## Letra sincronizada somente quando disponível

No modo de letra automática, o app preserva os tempos LRC fornecidos pela LRCLIB. Esses tempos só são utilizados quando artista, título, indicação de versão e duração são compatíveis com a mídia selecionada. A duração precisa diferir em no máximo dois segundos. A correspondência é conservadora, mas não garante que uma gravação com introdução diferente tenha os mesmos tempos.

A letra LRC controla o texto e os horários de exibição de cada verso. O Whisper analisa a gravação somente para animar as palavras reconhecidas dentro desses intervalos. Ele não substitui os tempos dos versos nem troca ou elimina palavras da letra pronta. A animação preserva pausas e durações medidas na voz, sem distribuição uniforme. Palavras sem correspondência segura continuam visíveis em cor discreta, sem animação ou tempos inventados. A etapa informa o progresso e o total de palavras animadas e envia um aviso inicial ao Telegram. O processamento é local e gratuito, sem outra dependência ou serviço pago. Sem letra sincronizada compatível, continua o reconhecimento acústico comum. Os caches acústicos e de revisão são separados; o cache antigo é invalidado ao refazer o resultado, mas vídeos já salvos permanecem intactos.

## Preservar backing vocals

A opção está ativada por padrão nos dois modos de criação e pode ser desativada por música. É possível ajustar o volume das vozes de apoio de 0 a 100%.

O fluxo é local e usa CPU:

1. Demucs separa instrumental e conjunto das vozes.
2. O modelo UVR-BVE-4B_SN-44100-2, executado por audio-separator, separa as vozes de apoio da voz principal a partir da faixa de vozes.
3. FFmpeg soma as vozes de apoio ao instrumental. A mixagem não inclui a faixa original nem a voz principal separada. Um limitador protege os picos.
4. Quando é necessária transcrição, a fonte de vocais passa a ser a voz principal separada. A opção de transcrever a mídia original continua disponível.

O modelo é baixado no primeiro uso e fica em `/data/output/models/backing_vocals`. Depois do download, a separação funciona sem enviar áudio a serviços externos. A busca de músicas e letras precisa de internet. A etapa adicional aumenta o tempo de processamento e pode apresentar vazamento da voz principal ou perdas de harmonias. Qualidade varia com a gravação, especialmente em duetos, uníssonos e vozes sobrepostas.

As faixas intermediárias são reaproveitadas apenas quando completas. Alterações no volume, no modo de sincronização ou na preservação das vozes invalidam os resultados posteriores, evitando reutilizar um vídeo com opções anteriores. Uma falha no modelo interrompe a tarefa com erro; o app não declara que preservou backing vocals usando somente o instrumental.

## SRT e vídeo automático para áudio

O modo Gerar SRT mantém a transcrição do áudio completo e a tradução opcional do LibreTranslate. Quando o arquivo de entrada só contém áudio, gera também um MP4 com fundo escuro, áudio completo e legendas na tela. Usa o SRT traduzido quando disponível, ou o original. A detecção consulta os fluxos reais da mídia, evitando confundir capas incorporadas com vídeo. Entradas com vídeo continuam recebendo os SRTs sem renderização adicional.

O resultado oferece prévia do vídeo e downloads separados de MP4, SRT original e tradução concluída. Esses arquivos são salvos na Biblioteca e têm envios individuais ao Telegram. Não há abertura de capa no MP4 do modo SRT, mantendo os tempos da mídia. Nenhum resultado desse modo pode ser publicado no YouTube, incluindo MP4, envios manuais e retomadas.

## Progresso e avisos das etapas

Backing vocals e renderização do MP4 de áudio exibem porcentagem interna e progresso geral. O backing-vocal distingue preparação do áudio, preparação dos blocos, análise da voz e geração das faixas. A porcentagem corresponde à subetapa identificada, sem confundir as barras rápidas de preparação com a inferência. A análise começa em 0% mesmo após uma preparação em 100% e avança após cada bloco concluído; reconstrução e salvamento ficam sem porcentagem contínua. O Telegram envia apenas um aviso no início de cada etapa, sem mensagens de avanço de porcentagem. A letra sincronizada aplicada e a tradução também recebem avisos; no LibreTranslate, só há informação de início e término, não porcentagem interna contínua. As demais etapas, fila e entrega continuam funcionando como antes.

## Instalação e validação

É necessário reconstruir a imagem Docker: foram adicionadas dependências de separação em CPU e ferramentas para compilar dependências de áudio. Uma instalação usando uma imagem publicada de versão anterior não recebe estas funções apenas atualizando o HTML.

Os testes automatizados cobrem busca com respostas simuladas, seleção conservadora de letras, leitura LRC, geração ASS, reutilização de faixas e falhas do modelo. A mixagem FFmpeg é testada com sinais sintéticos para conferir volume e duração. A sintaxe Python e JavaScript também é verificada.

A imagem é compilada no pipeline da release. A qualidade da inferência do modelo BVE em músicas reais deve ser avaliada com as gravações de uso. Os testes sintéticos da mixagem não comprovam a qualidade da separação neural.

Referências: [LRCLIB](https://lrclib.net/docs), [audio-separator](https://github.com/nomadkaraoke/python-audio-separator), [catálogo de modelos](https://github.com/nomadkaraoke/python-audio-separator/blob/main/audio_separator/models.json).

## Publicar no canal do YouTube (administradores)

Em Configurações, o painel de publicação permite selecionar um vídeo finalizado, revisar o título, preparar uma capa automática ou escolher JPEG/PNG, escolher uma playlist do canal conectado e definir privado, não listado ou público. O envio é feito pelo servidor em segundo plano. A prévia da capa e o título ficam definidos antes de iniciar.

Com o canal conectado e uma playlist definida no perfil, a publicação começa marcada para todas as contas, incluindo novas contas e instalações com preferências antigas. A privacidade automática é **Não listado**. O administrador define uma playlist válida por usuário, além da sua playlist padrão. Sem playlist no perfil, a interface e o servidor bloqueiam a publicação, inclusive tarefas antigas sem destino. O administrador pode escolher outra playlist por vídeo no modo rápido, com a do perfil selecionada por padrão. Cada vídeo ainda envia explicitamente a opção de publicação: o usuário pode desmarcá-la para não enviar nada ao canal.

O modo rápido e o modo completo mostram a playlist atribuída e um título opcional. A conta comum não pode trocar para outra playlist pela API. O modelo `{title} | Karaokê`, a capa automática e a privacidade **Não listado** são aplicados na conclusão. O administrador também pode salvar sua playlist no grupo **Padrões de publicação do administrador**. A conta e a atribuição são verificadas novamente antes do envio; alterações podem bloquear tarefas já agendadas. O administrador pode selecionar qualquer playlist do canal ou nenhuma para seus próprios vídeos e pode publicar resultados existentes no painel.
O app envia primeiro como privado, aplica a capa e a playlist e só então solicita a privacidade escolhida. Erros de capa, playlist ou privacidade aparecem na fila com um botão para retomar a mesma publicação. O identificador do vídeo e a sessão de envio são persistidos. Cópias idênticas de um vídeo no mesmo canal, usuário, playlist e privacidade reutilizam a publicação existente para evitar duplicação. O link fica disponível assim que o YouTube confirma o envio.

### Conectar o canal sem HTTPS no servidor

O servidor pode continuar em HTTP. O administrador autoriza uma vez em um computador com navegador, usando o fluxo OAuth oficial para aplicativos de computador:

1. No Google Cloud, habilite **YouTube Data API v3**, configure o consentimento e crie um cliente OAuth do tipo **Aplicativo para computador**. Baixe seu JSON. Se o projeto estiver em teste, adicione a conta aos usuários de teste.
2. No Karaokê, abra **Ajustes → Publicar no YouTube → Conectar meu canal**. No Windows, baixe **Sal0-YouTube-Conectar.exe** e abra com dois cliques. Não precisa instalar Python. Em Linux/macOS, use a alternativa Python do painel.
3. No navegador do mesmo computador, escolha o JSON do Google, clique em **Preparar conexão** e depois **Abrir Google e autorizar**. Após permitir o acesso, volte à aba do assistente e clique em **Baixar autorização**. O retorno usa apenas `127.0.0.1`, porta temporária, estado único e PKCE.
4. No Karaokê, escolha **youtube-autorizacao.json** e clique em **Conectar meu canal**. O servidor valida a permissão e consulta o canal no Google antes de guardar a conexão.
5. Confira o nome do canal, defina privacidade e playlists por usuário. Não são necessárias variáveis `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` ou `YOUTUBE_REDIRECT_URI` no Compose para este método.

O arquivo de autorização dá acesso ao canal: guarde-o como uma senha e importe somente no seu servidor, pela sua rede de confiança. Os tokens e o cliente de computador ficam em `/data/youtube/token.json`, com permissão 0600. A renovação funciona sem um endereço de retorno HTTPS. A conexão real depende das credenciais do administrador; os testes usam respostas simuladas do Google.

A conexão web com HTTPS continua opcional para quem já tem domínio e cliente do tipo Aplicativo da Web, usando as três variáveis de ambiente e `/api/admin/youtube/callback`. O arquivo `.env.youtube.example` serve apenas para esse método.

### Modo rápido e miniaturas

A escolha da música e o botão Criar são os dois passos principais. Buscar por nome e colar um link têm o mesmo destaque. Arquivos e Biblioteca têm seletores próprios. Fundo, vozes e sincronização ficam em Personalizar, fechado inicialmente. A pesquisa de qualquer entrada do YouTube mostra miniaturas dos vídeos. O layout empilha os campos no celular e usa duas colunas no desktop.

As miniaturas dos Resultados, do player final e da publicação automática são extraídas do próprio vídeo; nos karaokês, a abertura já contém a capa gerada. O vídeo automático do modo SRT usa seu próprio frame, sem abertura extra. Não há uma segunda sobreposição de título. Uma capa personalizada continua opcional para publicações administrativas manuais.

`KARAOKE_CPU_THREADS` permite limitar explicitamente os workers em servidores compartilhados, respeitando também a afinidade disponível. Sem essa variável, o comportamento anterior permanece. O diretório `/data` preserva contas, modelos, músicas, resultados e a conexão do canal.

O YouTube pode restringir uploads de projetos de API sem auditoria a **privado**. A permissão do canal para usar miniaturas personalizadas também é necessária. Em contas OAuth em modo de teste, o acesso concedido pode expirar, exigindo reconexão. Essas restrições pertencem ao Google e não podem ser removidas por uma configuração do Karaokê.

Os testes da publicação usam respostas simuladas: nenhum vídeo foi enviado a um canal real. A conexão OAuth e um envio privado precisam ser conferidos no servidor com as credenciais reais do canal.

Documentação oficial: [Envio de vídeos](https://developers.google.com/youtube/v3/docs/videos/insert), [Envio retomável](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol), [Capas](https://developers.google.com/youtube/v3/docs/thumbnails/set), [Playlists](https://developers.google.com/youtube/v3/docs/playlistItems/insert), [OAuth](https://developers.google.com/identity/protocols/oauth2/web-server).

Quando um vídeo de fundo decorativo é maior que a música, o início do trecho é escolhido aleatoriamente a cada nova renderização, cabendo a música inteira até o fim do fundo. Vídeos curtos continuam em loop. O vídeo original da música mantém o início e a sincronização. Com letra sincronizada, seu texto fornece os versos; o Whisper serve à análise dos tempos e da animação local.

### Verificação dos tempos da letra sincronizada


Quando existir letra sincronizada correspondente à música, o texto completo, a pontuação, os espaços e os intervalos dos versos são preservados. O texto reconhecido pelo Whisper não participa da animação: somente os tempos locais das palavras são aplicados em ordem. A letra inteira permanece visível no intervalo original do provedor; a varredura clássica de cor acompanha as palavras. O processamento local organiza as quebras visuais e separa a prévia do próximo verso, sem alterar palavras nem timestamps. A fonte se ajusta somente quando o verso completo não cabe na sua região. Sem tempo local suficiente, as palavras restantes ficam visíveis sem animação. Não há limite artificial de doze segundos por verso, redimensionamento de intervalo pela voz ou espaços invisíveis usados para consumir pausas. Com backing vocals ativos, o Whisper recebe a voz principal isolada em áudio completo, sem remoção de silêncios ou VAD no karaokê. A preparação mantém PCM float32, reamostragem adequada ao Whisper e a duração integral; o modelo escolhido usa precisão máxima. A abertura com o título permanece fora do relógio da música. Vídeos existentes precisam ser refeitos para aplicar a correção.

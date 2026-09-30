# Busca no YouTube, letras sincronizadas, backing vocals e publicação

Esta atualização permite pesquisar pelo nome da música nas entradas do YouTube. A busca automática começa depois de uma pausa na digitação e apresenta até seis vídeos com título, canal e duração. Ao escolher um vídeo, o app preenche o link e mantém o fluxo normal de criação. A pesquisa não baixa os vídeos automaticamente.

## Letra sincronizada somente quando disponível

No modo de letra automática, o app preserva os tempos LRC fornecidos pela LRCLIB. Esses tempos só são utilizados quando artista, título, indicação de versão e duração são compatíveis com a mídia selecionada. A duração precisa diferir em no máximo dois segundos. A correspondência é conservadora, mas não garante que uma gravação com introdução diferente tenha os mesmos tempos.

LRC informa tempos de versos. O app destaca o verso inteiro e não distribui tempos artificiais entre palavras. Sem uma letra sincronizada compatível, ele segue com a transcrição acústica já existente do Whisper. A opção de sempre usar Whisper permite manter o destaque de palavras. Letras manuais continuam usando o caminho acústico.

## Preservar backing vocals

A opção está ativada por padrão nos dois modos de criação e pode ser desativada por música. É possível ajustar o volume das vozes de apoio de 0 a 100%.

O fluxo é local e usa CPU:

1. Demucs separa instrumental e conjunto das vozes.
2. O modelo UVR-BVE-4B_SN-44100-2, executado por audio-separator, separa as vozes de apoio da voz principal a partir da faixa de vozes.
3. FFmpeg soma as vozes de apoio ao instrumental. A mixagem não inclui a faixa original nem a voz principal separada. Um limitador protege os picos.
4. Quando é necessária transcrição, a fonte de vocais passa a ser a voz principal separada. A opção de transcrever a mídia original continua disponível.

O modelo é baixado no primeiro uso e fica em `/data/output/models/backing_vocals`. Depois do download, a separação funciona sem enviar áudio a serviços externos. A busca de músicas e letras precisa de internet. A etapa adicional aumenta o tempo de processamento e pode apresentar vazamento da voz principal ou perdas de harmonias. Qualidade varia com a gravação, especialmente em duetos, uníssonos e vozes sobrepostas.

As faixas intermediárias são reaproveitadas apenas quando completas. Alterações no volume, no modo de sincronização ou na preservação das vozes invalidam os resultados posteriores, evitando reutilizar um vídeo com opções anteriores. Uma falha no modelo interrompe a tarefa com erro; o app não declara que preservou backing vocals usando somente o instrumental.

## Instalação e validação

É necessário reconstruir a imagem Docker: foram adicionadas dependências de separação em CPU e ferramentas para compilar dependências de áudio. Uma instalação usando uma imagem publicada de versão anterior não recebe estas funções apenas atualizando o HTML.

Os testes automatizados cobrem busca com respostas simuladas, seleção conservadora de letras, leitura LRC, geração ASS, reutilização de faixas e falhas do modelo. A mixagem FFmpeg é testada com sinais sintéticos para conferir volume e duração. A sintaxe Python e JavaScript também é verificada.

A imagem é compilada no pipeline da release. A qualidade da inferência do modelo BVE em músicas reais deve ser avaliada com as gravações de uso. Os testes sintéticos da mixagem não comprovam a qualidade da separação neural.

Referências: [LRCLIB](https://lrclib.net/docs), [audio-separator](https://github.com/nomadkaraoke/python-audio-separator), [catálogo de modelos](https://github.com/nomadkaraoke/python-audio-separator/blob/main/audio_separator/models.json).

## Publicar no canal do YouTube (administradores)

Em Configurações, o painel de publicação permite selecionar um vídeo finalizado, revisar o título, preparar uma capa automática ou escolher JPEG/PNG, escolher uma playlist do canal conectado e definir privado, não listado ou público. O envio é feito pelo servidor em segundo plano. A prévia da capa e o título ficam definidos antes de iniciar.

O administrador pode permitir publicação por usuários e definir uma playlist para cada conta, incluindo a opção de publicar sem playlist. Também pode deixar “Publicar no YouTube” marcado por padrão individualmente. Essa configuração apenas preseleciona a interface: cada vídeo deve enviar explicitamente a opção de publicação, e o usuário pode desmarcá-la. Desmarcado, não existe envio ao canal nem inclusão em playlist.

O modo rápido e o modo completo mostram a playlist atribuída e um título opcional. A conta comum não pode trocar para outra playlist nem contornar a permissão pela API. O modelo `{title} | Karaokê`, a capa automática e a privacidade administrativa são aplicados na conclusão. As permissões e a atribuição são verificadas novamente antes do envio; alterações podem bloquear tarefas já agendadas. O administrador pode selecionar qualquer playlist do canal ou nenhuma para seus próprios vídeos e pode publicar resultados existentes no painel.
O app envia primeiro como privado, aplica a capa e a playlist e só então solicita a privacidade escolhida. Erros de capa, playlist ou privacidade aparecem na fila com um botão para retomar a mesma publicação. O identificador do vídeo e a sessão de envio são persistidos. Cópias idênticas de um vídeo no mesmo canal reutilizam a publicação existente para evitar duplicação. O link fica disponível assim que o YouTube confirma o envio.

### Conectar o canal uma vez

1. No Google Cloud, habilite **YouTube Data API v3** e configure a tela de consentimento OAuth. Se o aplicativo estiver em teste, adicione sua conta aos usuários de teste.
2. Crie um cliente OAuth do tipo **Aplicativo da Web**. Cadastre exatamente a URI de retorno usada pelo app, por exemplo `https://karaoke.seudominio.com/api/admin/youtube/callback`.
3. Defina `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` e `YOUTUBE_REDIRECT_URI` no `.env` do Compose. O arquivo `.env.youtube.example` apresenta o formato sem credenciais reais. Recrie o container após alterar o ambiente.
4. Acesse **Configurações → Publicar no YouTube → Conectar canal** como administrador e escolha a conta/canal desejado na autorização do Google. Confira o nome do canal mostrado no painel.

O retorno exige HTTPS, exceto `localhost`/`127.0.0.1` para desenvolvimento. Um endereço HTTP da rede local no ZimaOS precisa de um endereço HTTPS registrado para esse fluxo. Os tokens ficam no servidor, em arquivos com permissão 0600 em `/data/youtube`, e não são enviados à interface. Conexão OAuth, configuração, publicação de resultados existentes e retomada de tarefas exigem administrador. Usuários autorizados podem solicitar envio dos vídeos que criam; o retorno OAuth valida um estado de uso único, PKCE e o papel atual do administrador.

O YouTube pode restringir uploads de projetos de API sem auditoria a **privado**. A permissão do canal para usar miniaturas personalizadas também é necessária. Em contas OAuth em modo de teste, o acesso concedido pode expirar, exigindo reconexão. Essas restrições pertencem ao Google e não podem ser removidas por uma configuração do Karaokê.

Os testes da publicação usam respostas simuladas: nenhum vídeo foi enviado a um canal real. A conexão OAuth e um envio privado precisam ser conferidos no servidor com as credenciais reais do canal.

Documentação oficial: [Envio de vídeos](https://developers.google.com/youtube/v3/docs/videos/insert), [Envio retomável](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol), [Capas](https://developers.google.com/youtube/v3/docs/thumbnails/set), [Playlists](https://developers.google.com/youtube/v3/docs/playlistItems/insert), [OAuth](https://developers.google.com/identity/protocols/oauth2/web-server).

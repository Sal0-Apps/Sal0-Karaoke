# Manual do Sal0 Karaokê

Este manual descreve os controles disponíveis na distribuição 9.8.0. Para instalar o servidor, consulte [DEPLOYMENT.md](DEPLOYMENT.md). Para configurar o aparelho, consulte o [guia Android](android/README.md).

## 1. Primeiro acesso e navegação

1. Abra o endereço do servidor no navegador ou no aplicativo Android.
2. Se ainda não houver contas, crie o administrador. Faça esse primeiro acesso em uma rede restrita.
3. Nas próximas visitas, entre com o usuário e a senha da instalação.
4. Use **Criar** para preparar ou acompanhar trabalhos, **Ajustes** para configurações e **Biblioteca** para arquivos e resultados.
5. No topo, **Manual** abre os tutoriais curtos, o botão de tema alterna claro/escuro e **Sair** encerra a sessão desta interface.

O título da página apresenta apenas o nome da aplicação. A versão do servidor aparece no Manual; a versão nativa do Android está em **Configurações do app**. As versões podem ser diferentes: mudanças da interface chegam pelo servidor, enquanto alterações nativas exigem instalar um APK atualizado.

As contas são locais a cada instalação. Não existe uma conta central do projeto nem um serviço do projeto para recuperar senhas. Preserve a conta administradora e backups protegidos do volume.

## 2. Selecionar a fonte

Os três modos aceitam arquivo de áudio/vídeo, link autorizado do YouTube ou original salvo na Biblioteca.

| Entrada | Como usar | Observações |
| --- | --- | --- |
| Arquivo | Toque no seletor ou arraste para a área de envio | Áudio: MP3, WAV, FLAC, M4A, AAC, OGG, Opus. Vídeo: MP4, MKV, AVI, MOV, WebM, M4V |
| Vários arquivos | Selecione mais de um no mesmo envio | Cada arquivo vira um trabalho; todos recebem os ajustes desse envio |
| Link | Cole uma URL no campo do modo escolhido | O servidor tenta identificar o título; o download ocorre quando a tarefa é preparada/processada |
| Biblioteca | Escolha um item no seletor | Reutiliza um original já armazenado e evita outro upload |

Para guardar uma mídia sem criar um trabalho, use os formulários da **Biblioteca**. A área de criação prepara trabalhos; a Biblioteca armazena e organiza arquivos.

O seletor lista extensões comuns, mas o codec interno precisa ser decodificável pelo FFmpeg. Uma mídia processável pelo servidor pode não ser reproduzível diretamente no navegador.

## 3. Modo Rápido

Use este modo quando quiser selecionar a música e aproveitar o perfil global preparado pelo administrador.

1. Em **Criar**, escolha **Rápido**.
2. Informe uma única fonte: arquivo(s), URL ou original da Biblioteca.
3. Escolha o fundo, se desejar:
   - **Surpresa:** usa a seleção/coleção configurada pelo administrador;
   - **Vídeo original:** reaproveita a imagem do clipe quando a entrada é vídeo;
   - **Escolher fundo:** envia uma imagem ou vídeo;
   - **Da Biblioteca:** usa um fundo já salvo;
   - **Link de fundo:** solicita outro vídeo como fundo.
4. Confira os indicadores do perfil apresentado.
5. Toque em **Criar meu karaokê** e acompanhe a aba Criar.
6. Se o perfil exigir revisão, corrija as legendas quando o editor aparecer.
7. Ao concluir, visualize ou baixe o resultado.

O perfil global determina modelo, leitura da voz, origem da transcrição, animação, tamanho, cor e posição das legendas, organização de versos, VAD, revisão, salvamento e opção de somente remover vocais. Para controlar essas opções em um envio específico, use **Detalhado**.

Se o administrador desabilitar o modo rápido, a interface usará os outros modos disponíveis. A ausência de uma coleção de fundos utilizável pode exigir outro fundo; não é possível garantir um sorteio sem arquivos válidos.

## 4. Modo Detalhado

### Fonte e perfil da voz

1. Escolha **Detalhado**.
2. Selecione Enviar, YouTube ou Biblioteca na área da mídia.
3. Escolha um perfil salvo ou um ponto de partida.
4. Ajuste a leitura da voz e o modelo Whisper.

Os perfis de leitura incluem **Karaokê equilibrado**, **Canto contínuo**, **Voz difícil** e **Criação rápida**. São combinações de parâmetros para situações diferentes, não classificações de qualidade garantida. Experimente em um trecho representativo da mídia antes de um lote grande.

Modelos maiores tendem a consumir mais RAM e tempo. Large V3 Turbo, Large V3, Medium, Small e Tiny aparecem nos controles conforme a área e disponibilidade. A instalação de novos modelos é administrativa; consulte Ajustes antes de selecionar um modelo ainda indisponível.

### Letra-guia

1. Abra o bloco **Letra**.
2. No modo automático, informe título/artista quando necessário e use **Buscar**.
3. Revise o texto encontrado. Você pode colar uma versão manual, salvar ou limpar o texto.
4. O texto manual tem prioridade sobre a busca automática.
5. Se não houver letra, o processo pode seguir apenas com Whisper; o resumo e o Telegram informam essa condição quando aplicável.

A letra-guia orienta o reconhecimento, mas não garante que a gravação tenha os mesmos versos, repetições ou arranjos. Letras e traduções podem ter direitos próprios; verifique autorização antes de copiar ou publicar.

### Fundo e legenda

Escolha **Vídeo original**, **Imagem / Vídeo** ou **Cor sólida** como modo de fundo. Para imagem/vídeo, envie um arquivo, use a Biblioteca ou um link. O áudio do fundo não é usado como trilha do karaokê.

A legenda pode destacar sílabas, palavras, linhas ou exibir a frase estática. O modo por sílabas é uma animação baseada nos tempos reconhecidos; não é garantia de alinhamento fonético perfeito.

### Mais ajustes

| Controle | Efeito |
| --- | --- |
| Posição do texto | Coloca a legenda na parte inferior, central ou superior |
| Cor principal e tamanho | Altera a aparência das letras |
| Palavras por verso | Limita a quantidade de palavras; zero solicita divisão automática |
| Caracteres por verso | Limita o comprimento; zero solicita divisão automática |
| Fonte da transcrição | Usa o áudio original ou os vocais separados |
| Prévia da próxima frase | Mostra antecipadamente o próximo trecho |
| Legenda no início | Permite apresentar a primeira linha desde o início |
| Silero VAD | Filtra trechos reconhecidos como fala; pode omitir canto suave ou sustentado |
| Quebra por pontuação | Considera pontuação na divisão de versos |
| Texto “Instrumental” | Mostra indicação nos intervalos sem legenda |
| Salvar mídias na Biblioteca | Controla o arquivamento de mídias de entrada; os resultados têm salvamento próprio |
| Somente remover vocais | Faz a separação e renderiza vídeo instrumental, sem transcrição/legenda |
| Revisar antes de finalizar | Abre o editor após a transcrição |

Em **Perfil de Ajustes**, dê um nome à configuração e toque em **Salvar Perfil**. Selecione um perfil para reaplicá-lo. **Excluir** remove o perfil selecionado; não exclui as mídias já produzidas com ele.

## 5. Gerar SRT original e tradução opcional

Este modo cria arquivos de legenda e preserva a fala. Ele não separa vocais, não oferece fundo e não renderiza outro vídeo.

1. Escolha **Gerar SRT**.
2. Envie áudio/vídeo, cole um link autorizado ou selecione um original.
3. Em **Segundo SRT traduzido**, o padrão é **Português (Brasil)**, com detecção automática do idioma de origem pelo LibreTranslate. Também é possível selecionar português, inglês, espanhol ou **Não traduzir**.
4. Configure modelo Whisper, leitura da fala e VAD. Para fala, o filtro pode ajudar a ignorar silêncio; para canto, avalie desligá-lo.
5. Habilite a revisão se quiser corrigir o original antes da tradução.
6. Decida se a mídia de entrada deve ser salva na Biblioteca.
7. Toque em **Gerar arquivos SRT**.
8. Baixe o **SRT original** e o **SRT traduzido**, quando disponível.

O servidor extrai/normaliza o áudio completo para MP3 e transcreve o idioma detectado. O SRT respeita os tempos das falas, priorizando os timestamps por palavra do Whisper. Pausas de pelo menos 600 ms separam blocos: a legenda não é antecipada para preencher silêncio inicial, intervalos ou o fim da mídia. A tradução preserva esses mesmos tempos.

A tradução depende exclusivamente do **LibreTranslate** configurado pelo administrador. O Karaokê envia os textos ao serviço e preserva os tempos das legendas; não carrega mais o modelo M2M100 para traduzir. O original e a tradução concluída continuam disponíveis no aplicativo e na Biblioteca. O Karaokê também tenta anexar ambos ao Telegram configurado, acompanhados dos links de download. Se o LibreTranslate estiver indisponível, o SRT original permanece salvo e sua entrega continua. Se a transcrição falhar antes de gerar qualquer legenda, não há SRT original para entregar.

### Configuração e atualizações do LibreTranslate

1. Abra **Ajustes → Tradução de SRT · LibreTranslate**, como administrador.
2. Informe a URL base do serviço, incluindo a porta. Use um endereço acessível pelo container do Karaokê; `localhost` refere-se ao próprio container.
3. Informe a chave de API somente se sua instância exigir. Deixar o campo vazio mantém a chave salva; marque **Remover chave salva** para apagá-la.
4. Salve e use **Testar e atualizar idiomas**. O teste consulta `/languages`, envia um pequeno SRT por `/translate_file` com origem `auto` e destino `pt-BR` e baixa sua tradução.
5. Se houver lentidão, aumente o tempo limite por requisição. Verifique se a tradução de arquivos está habilitada e se o limite de upload aceita o SRT. O padrão de espera é de 1.800 segundos; a API não informa percentual interno da tradução.
6. Atualize a imagem LibreTranslate no CasaOS/Docker quando necessário. Para atualizar os modelos, use os recursos do próprio LibreTranslate, como `LT_UPDATE_MODELS=true` na inicialização de manutenção. Depois teste novamente pelo Karaokê.

A URL, chave e tempo limite ficam em `/data/output/libretranslate.json`, no volume persistente. Mudanças salvas valem para a próxima tradução; uma tradução em andamento mantém sua configuração inicial. O cliente consulta os idiomas novamente a cada trabalho, envia o SRT completo por `/translate_file` e baixa o arquivo traduzido. Antes de publicar o resultado, verifica se a quantidade e os tempos das legendas foram preservados. Erros temporários têm até três tentativas; erros de chave, idioma ou formato são informados sem apagar o original. O botão de teste envia um pequeno SRT e baixa sua tradução; não instala pacotes nem atualiza a imagem do LibreTranslate.

Não há corte fixo de duração no modo. Ainda é necessário ter espaço para mídia, MP3 intermediário, modelos, cache e resultados; o proxy e a instalação podem impor limites adicionais.

## 6. Revisão de texto e tempos

A revisão é ativada antes do envio da tarefa. Quando o processamento chega ao editor:

1. Selecione um trecho e use **Anterior** / **Próxima** para navegar.
2. Confira o texto e os tempos de início/fim.
3. Reproduza a mídia para comparar o trecho com o áudio.
4. Faça correções e use o botão de salvar/continuar.
5. Se não desejar editar, use **Continuar sem editar**.

No karaokê, a renderização ocorre depois da revisão. No modo SRT, a revisão é do original, antes da tradução opcional. Enquanto aguarda a revisão, esse trabalho mantém a fila ocupada.

A revisão não é a pausa administrativa para reinício. Ao atualizar o servidor durante a edição, salve o trabalho e use o procedimento de manutenção descrito abaixo.

## 7. Fila de processamento

### Criar outro trabalho durante o atual

1. Mantenha a aba **Criar** aberta para acompanhar o progresso principal.
2. Toque em **Adicionar novo processo**.
3. Escolha Rápido, Detalhado ou Gerar SRT.
4. Informe arquivo(s), link ou Biblioteca e configure o novo trabalho.
5. Envie o formulário. Cada envio conserva suas opções.

Os formulários ficam recolhidos durante o acompanhamento e só abrem quando você pede um novo processo. Se selecionar vários arquivos no mesmo formulário, todos usam o modo e os ajustes daquele envio; para misturar configurações, faça envios separados.

### Permissões e limites

- O servidor processa uma tarefa por vez.
- Cada perfil pode ter até 25 trabalhos ativos, incluindo o que estiver em execução.
- Qualquer perfil autenticado pode adicionar tarefas enquanto outro perfil está processando.
- Usuários comuns visualizam e gerenciam os próprios itens; o administrador gerencia todos.
- Somente o administrador pode alterar a ordem, incluindo tarefas de outros perfis.
- Notificações e resultados são enviados apenas ao dono da tarefa e à administração; não são distribuídos aos demais perfis.

### Reordenar, remover e cancelar

Como administrador, use **↑ / ↓** para mover itens aguardando. Um item em processamento não muda de posição. Os demais perfis não veem esses botões.

**Remover** tira um item pendente da fila e limpa seus temporários. **Cancelar Processamento** encerra a tarefa atual. A próxima tarefa elegível começa se a fila estiver ativa e não houver uma pausa/revisão impedindo o avanço.

A fila não é histórico: trabalhos encerrados saem dela. Os arquivos concluídos ficam em **Biblioteca → Resultados**. Cancelar não equivale a apagar todos os arquivos já salvos na Biblioteca.

## 8. Progresso e pausa por etapa

O número maior e a barra são o **progresso total**. O indicador menor representa a **etapa atual**, incluindo transcrição quando há informação disponível. Downloads, carregamento de modelo e certas operações podem não fornecer um percentual contínuo.

O total combina etapas com pesos; não mede diretamente tempo restante. Um avanço de 50% não significa que falta metade do tempo. CPU, duração, modelo, disco, rede e complexidade do áudio alteram a duração.

### Pausar para atualizar

A pausa de manutenção é exclusiva do administrador.

1. Na área junto da fila, toque em **Pausar ao concluir etapa**.
2. Aguarde a etapa atual terminar e a interface confirmar que a pausa foi efetivada.
3. Preserve o volume `/data`, incluindo os diretórios da fila e arquivos intermediários.
4. Atualize ou reinicie o servidor.
5. Abra a interface e toque em **Retomar fila**.

A pausa não interrompe a etapa pela metade. O servidor reutiliza resultados concluídos que ainda estejam disponíveis. Um encerramento forçado antes da confirmação pode exigir repetir a etapa em andamento. Consulte [DEPLOYMENT.md](DEPLOYMENT.md) para os comandos e backup.

## 9. Biblioteca e resultados

| Seção | Conteúdo | Ações na interface |
| --- | --- | --- |
| Originais | Áudios/vídeos guardados por upload, link ou processamento | Usar, Ver quando compatível, Renomear, Excluir |
| Fundos | Imagens e vídeos destinados ao visual | Usar, Ver quando compatível, Renomear, Excluir |
| Resultados | MP4 final e SRT gerado | Ver quando compatível, Baixar, Renomear, Excluir |

**Resultados** aparece primeiro, com os mais recentes no topo. Toque no título de cada seção para mostrar ou esconder seu conteúdo, como no manual. Expanda **Adicionar à biblioteca** para enviar mídia ou guardar um link autorizado. A ação **Usar** preenche a fonte/fundo para a criação; confira o modo e os demais ajustes antes de enviar.

Toque no título de um item para expandir o nome completo. A visualização inclui controles de avanço/retrocesso de dez segundos quando a mídia permite. SRT é entregue como arquivo de texto, não como vídeo.

Os resultados de vídeo têm miniatura independente, com frame escurecido e título; SRTs têm um cartão de título. As miniaturas são geradas localmente sob demanda e armazenadas em `/data/cache/thumbnails`. Novos vídeos incluem uma abertura silenciosa de três segundos com a capa, antes do conteúdo. Áudio, imagem e legenda do conteúdo começam juntos depois dela: a abertura não encobre falas nem muda sua sincronização. Vídeos já salvos recebem miniaturas na Biblioteca, mas não são reeditados automaticamente. O modo Gerar SRT não ganha abertura nem deslocamento de tempos.

O administrador acessa resultados de todos os perfis, identificados pelo proprietário, mesmo quando os nomes são iguais. Download, visualização, renomeação e exclusão dos resultados usam esse proprietário para evitar selecionar o arquivo de outra conta por engano. Contas comuns permanecem limitadas à própria Biblioteca.

Ao refazer um karaokê usando o cache, o aplicativo pode reutilizar o áudio extraído, a separação e a transcrição compatível. Revisão, ASS e vídeo final são produzidos para a nova tarefa; checkpoints do trabalho anterior não são reutilizados. Retomar uma tarefa pausada é diferente: mantém os checkpoints da própria tarefa para não perder etapas concluídas.

Na conclusão da tarefa, os botões da tela dão acesso ao MP4 ou aos SRTs. No Android, os arquivos são salvos pelo sistema em **Downloads**; nomes repetidos recebem sufixos. No PC, o destino depende das preferências do navegador.

## 10. Telegram

### Configurar o destino

1. No Telegram, crie um bot pelo **@BotFather**, seguindo as instruções oficiais.
2. Abra a conversa com o novo bot e envie uma mensagem inicial. Para um grupo, adicione o bot e permita mensagens e arquivos.
3. Obtenha o Chat ID do destino por um meio de confiança. O nome do grupo ou usuário não substitui automaticamente o identificador esperado.
4. Em **Ajustes → Telegram → Editar**, informe token e Chat ID.
5. Toque em **Salvar Telegram**.
6. Processe uma mídia pequena autorizada para conferir as notificações.

Cada conta pode ter uma configuração própria. O bot administrativo também pode receber os avisos de trabalhos dos perfis sob sua gestão, conforme as configurações existentes.

### O que é enviado

- início e etapas intermediárias;
- resultado da busca de letra-guia quando aplicável;
- MP4 ou SRT, por tentativa de anexo;
- tempo total de processamento acumulado pelo trabalho;
- links local e externo disponíveis.

O tempo informado soma o processamento das etapas, incluindo retomadas registradas; não deve ser interpretado como tempo desde a entrada na fila nem como duração do envio final ao Telegram.

Para vídeos grandes, o servidor tenta gerar uma prévia compactada temporária para o Telegram. O original da Biblioteca não é substituído. A fila aguarda o fluxo de envio terminar antes de iniciar a próxima tarefa. Uma tentativa pode terminar em erro, timeout ou mensagem com links; a entrega não é garantida para qualquer tamanho.

### Links local e externo

O link local só funciona em uma rede que alcance o servidor. O externo depende do endereço configurado na administração, roteamento e HTTPS/proxy válidos. Configurar uma URL não abre portas nem cria um túnel.

Os links usam identificadores aleatórios e não exigem a sessão do navegador. Eles não têm expiração automática implementada. Quem receber o link poderá usá-lo enquanto o arquivo e o registro existirem. Proteja mensagens e destinos.

## 11. Administração

### Modelos Whisper

Em **Ajustes → Modelos Whisper**, consulte os modelos disponíveis e os já baixados. O administrador instala modelos; as contas usam os modelos compartilhados. Verifique internet, disco e RAM antes de baixar ou selecionar modelos grandes.

### Perfil global do Modo Rápido

Abra os grupos de transcrição, visual e fluxo. Configure modelo, perfil da voz, origem do áudio, VAD, busca de letra, estilo, fonte, versos, fundo, revisão e salvamento. Marque os fundos da coleção aleatória e salve em **Salvar perfil do Modo Rápido**. **Restaurar padrão** permite voltar aos valores iniciais; confira a tela e salve a configuração desejada.

### Compatibilidade com YouTube

Em **Ajustes → Compatibilidade com YouTube**, consulte as versões exibidas. O administrador pode usar **Atualizar mecanismo** para instalar uma atualização do `yt-dlp` no volume persistente.

Prefira fazer isso sem downloads em execução. Aguarde a conclusão e teste novamente o link autorizado. A atualização não garante acesso a mídias privadas, restritas, removidas ou bloqueadas pelo serviço. Ela também não atualiza automaticamente todos os componentes do servidor.

### Usuários

Na seção administrativa, informe usuário, senha e função e toque em **Adicionar Usuário**. Uma conta administrativa tem acesso ampliado: conceda essa função somente quando necessário.

Excluir um usuário revoga suas sessões, mas não constitui uma operação universal de apagamento de mídias, backups e links. Antes de excluir uma conta, defina com o operador a retenção dos seus dados.

### Diagnóstico

Use **Logs atuais** para baixar o diagnóstico do servidor. O conteúdo pode conter nomes de mídias, endereços ou detalhes de falhas. Revise antes de enviar a terceiros. Vulnerabilidades devem seguir [SECURITY.md](SECURITY.md).

## 12. Configurações do Android

O botão **Configurações do app**, na faixa inferior do APK, abre os campos de Wi-Fi, endereço local e externo. Ele funciona mesmo se o servidor não carregar.

**Salvar e reconectar** aplica os endereços. **Voltar ao karaokê** ou Voltar do Android sai sem salvar. A tela atual da WebView é fechada ao abrir as configurações; formulários não enviados precisam ser refeitos. Processos já aceitos continuam no servidor.

A faixa desaparece junto da interface ao reproduzir um vídeo em tela cheia e volta ao sair desse modo. A permissão de localização serve à leitura do nome do Wi-Fi quando exigida pelo Android; sem ela, o aplicativo tenta as rotas sem confirmar o SSID.

Consulte [android/README.md](android/README.md) para instalação, assinatura e solução de conexão.

## 13. Problemas frequentes

| Sintoma | O que conferir |
| --- | --- |
| Servidor não abre | Container ativo, porta publicada, endereço do servidor e rede; no Android, revise os endereços na faixa inferior |
| APK mostra erro HTTPS | Certificado válido e nome do domínio; o aplicativo não ignora erros de certificado |
| Link do YouTube falha | Disponibilidade e autorização da mídia, internet do servidor e atualização do mecanismo |
| Demucs demora | O processamento em CPU pode ser longo; confira carga, RAM, disco e logs antes de cancelar |
| Whisper parece parado | Carregamento/download do modelo, duração do áudio e etapa atual; o percentual pode não mudar continuamente |
| Tradução falha | Baixe o original; em Ajustes teste o LibreTranslate, confira endereço, chave, idioma PT-BR, limite de upload e tempo de resposta |
| Fila não avança | Pausa administrativa, revisão aguardando ou envio ao Telegram ainda em andamento |
| Sem botão para adicionar | Verifique a sessão e o limite de 25 trabalhos; use Adicionar novo processo para abrir os formulários |
| Telegram sem anexo | Permissões do bot, destino, conectividade, tempo de envio e resultado da compressão; procure os links |
| Download não aparece no Android | Pasta Downloads, notificações do gerenciador, espaço livre e permissões em versões antigas |
| Arquivo não reproduz no navegador | Codec incompatível; baixe e use um reprodutor compatível |
| Sincronia ou texto incorreto | Letra-guia, VAD, modelo e tempos; habilite revisão em um novo processamento |

A instalação prioriza processamento local, mas pode acessar serviços externos para fontes, modelos, letras, importação e Telegram. Consulte [PRIVACY.md](PRIVACY.md) e processe apenas material autorizado.

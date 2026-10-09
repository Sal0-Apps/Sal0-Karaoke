# 11.4.1

- Corrigido o erro `Directory not empty` ao atualizar o mecanismo de downloads pelo app. A limpeza de pacotes antigos deixa de bloquear a instalação ou transformar uma atualização já aplicada em erro. Falhas persistentes de limpeza são registradas e tentadas novamente depois.
- Cada instalação usa uma pasta temporária exclusiva, sem depender de pastas residuais da tentativa anterior. Troca e restauração usam renomeações; uma falha ao carregar o pacote novo restaura a versão anterior mesmo se a remoção de arquivos não funcionar. Uma troca interrompida antes da instalação pode recuperar a cópia anterior ao carregar o mecanismo.
- Consultas de versão não interferem na troca do mecanismo e permanecem disponíveis durante downloads. Uma nova atualização só pode iniciar depois da finalização da tentativa anterior, evitando apagar seu temporário.
- Testes reproduzem o erro da foto, mudanças de diretório durante a limpeza, resíduos ocupados, repetição, restauração, reinício e preservação de cookies/credenciais. O painel no celular acompanha o término e libera novas tentativas. Verificação do yt-dlp real na imagem de distribuição.
- Corrigido o tratamento de respostas inválidas na consulta de canal e playlists: leituras transitórias têm uma única repetição, respostas e páginas são validadas e erros mantêm formato JSON. Falhas internas retornam um código de diagnóstico; o log registra classe/localização sem conteúdo de respostas, tokens ou chaves. Envios e demais operações de escrita não são repetidos automaticamente.
- **Atualizar playlists** fica junto da seleção dos destinos, sem forçar uma reconexão. Consultas de status são agrupadas para evitar sobreposição; atualizações preservam alterações ainda não salvas do mesmo canal. Falhas não apagam seleções nem confundem uma resposta inválida com lista vazia. Canal, sessão e destinos salvos ficam preservados.
- Atualização somente do servidor. Mantidos a reconexão do canal pelo celular, os aplicativos Android/Windows existentes, o áudio original do Whisper, as letras por item, as legendas e o download de fundos durante tarefas.

# 11.4

- Reconexão do canal no próprio app pelo celular, em rede local ou externa: código do Google para autorizar o servidor sem navegador, aprovação em google.com/device e acompanhamento no painel. Credencial de TVs e dispositivos com entrada limitada configurável uma vez por JSON ou ID/chave; futuras reconexões a reutilizam. Não exige retorno HTTPS, PC ou alteração dos clientes Android/Windows.
- Estado da conexão acompanha a renovação real, identifica autorização revogada/expirada e preserva tokens em falhas temporárias de rede. Verificar e renovar consulta o canal; HTTP 401 permite uma renovação automática e uma única repetição, inclusive preservando o corpo do envio de capa.
- Reconectar o mesmo canal preserva playlists, fila, sessão de upload e ID de vídeo confirmado. Envios pausados por autorização retomam após a conexão; troca para outro canal é bloqueada com envios pendentes. Código pendente e aprovação recebida sobrevivem a reinício ou falha de consulta do canal, sem expor tokens e chaves na interface.
- Downloads têm painel próprio para testar link, importar/colar cookies.txt e remover a sessão. Guia para exportar pelo Firefox Android. Cookies privados são validados, limitados aos domínios YouTube/Google e usados em cópias descartáveis; um download antigo não sobrescreve a sessão recém-renovada. Autorização do canal permanece independente.
- Busca, metadados, músicas e fundos compartilham a mesma sessão. Falhas indicam ação de recuperação; tentativa sem cookies limitada para vídeos públicos. Cancelamento continua propagado. Remover cookies não revoga o canal nem altera playlists.
- Correção da seleção do yt-dlp: arquivos antigos no volume não se sobrepõem a uma imagem mais nova. Atualização preparada sem bloquear downloads durante a instalação; a troca final aguarda operações ativas e restaura a versão anterior se falhar.
- Testes de revogação, 401, rede, consentimento Google, intervalo/expiração, acesso administrativo, retomada sem duplicação, privacidade/rotação de cookies, escolha/atualização do mecanismo e navegador móvel pela URL externa. Campos e teclado preservados durante consultas. Mantidos áudio original do Whisper, SRT, letras por item e download de fundos durante tarefas.

# 11.3

- Restaurado o áudio original como padrão de reconhecimento no Modo Rápido, no Modo Detalhado e nos perfis integrados. O arquivo original segue diretamente para a decodificação do Whisper, sem passar pelo WAV intermediário do Demucs nem pela separação de voz principal. Somente a conversão exigida pelo modelo para PCM float32 mono/16 kHz; sem filtros extras, cortes de silêncio ou VAD no karaokê.
- Backing vocals não substituem mais a fonte selecionada. A separação continua montando o instrumental do vídeo; escolher explicitamente Vocais separados ainda envia os vocais do Demucs ou a voz principal isolada ao Whisper. A conferência com letra-guia e sua segunda análise usam a mesma fonte selecionada e o áudio completo.
- Configurações antigas do Modo Rápido migram uma vez para Áudio original, preservando modelo, visual, fundos e demais escolhas. Novas escolhas explícitas de Vocais separados são mantidas. Perfis personalizados já salvos continuam respeitados. A fonte efetiva aparece nos resumos e no aviso de transcrição.
- Cache de reconhecimento anterior é refeito uma vez; o cache novo continua reutilizável. Mudanças de fonte e versão de preparação invalidam revisão, legenda e vídeo, preservando o original e a separação já realizada. Use Refazer para aplicar a correção a resultados concluídos. Atualização somente do servidor, sem mudanças nos clientes Android ou Windows.

# 11.2

- Corrigido o painel de letra que era removido e recolocado a cada atualização de progresso, fechando o teclado, interrompendo a seleção e deslocando a tela. A posição do painel só muda ao trocar de modo; foco, consulta, texto e resultados permanecem durante o acompanhamento.
- Busca automática limitada a uma tentativa por mídia, com repetição explícita pelo usuário. Validação compartilhada de título, artista e versão na interface e no processamento. Uma resposta sem relação, como NOKIA/Drake para YOASOBI, é descartada na origem e na lista de resultados; sem correspondência, a guia fica vazia e o Whisper continua disponível.
- Busca manual aceita título, artista, trechos e pequenas diferenças de escrita. Tocar para buscar ou editar assume o controle imediatamente, cancela a consulta automática e não espera por um rascunho remoto. Resultados, importações e rascunhos atrasados não substituem a escolha atual. Enter também inicia a busca.
- Padrão Manual do Modo Rápido respeitado, rascunhos de links equivalentes vinculados ao mesmo vídeo e guias automáticas antigas verificadas novamente sem apagar escolhas manuais ou cópias já enfileiradas.
- Testes de identidade de músicas/provedores, resultados vazios, Unicode, versões, migração de rascunhos e navegador móvel com foco, seleção, rolagem, andamento, buscas lentas e respostas fora de ordem. Mantidos SRT, Telegram, fila por mídia e download de fundos durante tarefas. Atualização somente do servidor.

# 11.1

- O modo **Legendar vídeo (SRT)** transcreve a fala com Whisper e sempre gera MP4 com legenda embutida. Vídeos mantêm a imagem original; áudios usam o fundo padrão. Mantém áudio completo, tempos das falas e SRTs independentes, sem animação ou separação de vocais.
- Novos padrões administrativos para cor, fundo, opacidade, tamanho e posição da legenda, e imagem/vídeo/cor de fundo para áudio. A tradução é embutida por padrão quando disponível; a administração pode escolher sempre o idioma original. Cada item copia configurações e fundo ao entrar na fila.
- Telegram entrega um único vídeo compactado com os links locais e externos disponíveis para vídeo completo, SRT original e SRT traduzido na mesma mensagem. Sem anexos SRT separados. Falhas de tradução geram vídeo com a legenda original; falhas de envio preservam os links. Compactação acompanha progresso e cancelamento.
- Letras escolhidas ficam vinculadas à mídia nos modos Rápido e Detalhado. Salvar, limpar ou trocar de mídia não altera textos de tarefas anteriores. Cada item guarda sua própria cópia, inclusive letras escolhidas da busca automática. Em lotes, a guia não é copiada para arquivos diferentes. Respostas atrasadas são ignoradas.
- Vídeos de fundo podem ser baixados durante o processamento, em temporários próprios, com acompanhamento separado e publicação atômica na Biblioteca. Recarregar a lista conserva a seleção do formulário.
- Testes de fila, tradução, Telegram, FFmpeg real, compactação, interface e cinco larguras de tela. Atualização somente do servidor; Android e configurador Windows existentes são reutilizados.

# 11.0

- Whisper passa a definir as palavras, o ritmo e toda a sincronia do karaokê. Letras externas, inclusive LRC, servem apenas como guia; horários, offsets e quebras de verso do provedor são ignorados. Esta política substitui a prioridade de versos sincronizados das versões 10.x.
- A guia orienta o contexto e o vocabulário do modelo. Todas as palavras reconhecidas são comparadas; correspondências confiáveis corrigem grafia e pontuação mantendo os tempos locais. Versos ausentes não são copiados sem reconhecimento da voz.
- Diferenças podem disparar uma segunda análise local do áudio completo. Ela é limitada a uma tentativa e só substitui a primeira quando melhora a correspondência, sem perda relevante de confiança acústica. Contagens de conferência aparecem no andamento; o relatório e o resultado conferido ficam em cache.
- Mantidos áudio completo sem VAD no karaokê, voz principal isolada com backing vocals, precisão máxima do modelo escolhido, frases legíveis, posições estáveis e destaque suave. Salvar uma revisão sem editar seus horários preserva os tempos das palavras.
- Migração invalida legendas, vídeo e revisões antigas baseadas em LRC. Áudio e análises Whisper compatíveis continuam reutilizáveis; a conferência em cache é vinculada à guia, ao áudio e ao modelo. Use **Refazer** para aplicar a mudança a vídeos concluídos.
- Interface e documentação refletem o novo fluxo. Publicação somente do servidor, com testes de fluxo, cache, transcrição, renderização real e navegador; Android e configurador Windows existentes são reutilizados.

# 10.9

- Corrigida a divisão de frases no karaokê gerado apenas pelo Whisper. Os controles de palavras e caracteres passam a organizar linhas visuais, sem cortar versos pela contagem nem deixar “deu” separado de “me”. Pausas, pontuação, início de frase e marcadores de letra-guia orientam as trocas de verso.
- Verso e prévia mantêm posições estáveis em toda a música, inclusive no último verso. A prévia fica mais legível e aparece durante os três segundos da contagem regressiva.
- Corrigida a direção do destaque: texto aguardando o canto em branco, cor escolhida aplicada conforme as palavras são cantadas. Palavras recebem uma transição breve e gradual; sílabas mantêm a varredura pelos tempos locais, respeitando pausas e sem deslocar o texto.
- Letra sincronizada preserva integralmente texto, espaços, pontuação e intervalos do provedor. Apenas os tempos locais animam as palavras. A escolha entre sílabas, palavras e modos estáticos é respeitada também no fluxo do servidor.
- Mudanças visuais invalidam somente legenda e vídeo no checkpoint, preservando áudio, análise Whisper e revisão já salva. Use **Refazer** para aplicar a correção a vídeos concluídos.
- Verificação com FFmpeg/libass real de posições, palavras completas, transição de cor, pausas e letra sincronizada, além dos testes de criação, fila e publicação. Atualização somente do servidor.

# 10.8

- Removida a mensagem fixa de arquivos adicionados acima do andamento. A contagem da fila continua refletindo os itens realmente aguardando.
- **Adicionar à fila** aparece ao lado de **Cancelar**, no progresso e na revisão. A inclusão abre uma tela limpa com os três modos e um aviso compacto sobre o processamento atual. **Voltar ao andamento** retorna sem cancelar a tarefa.
- Carregamento separado enquanto a mídia é preparada e enviada. O andamento só reaparece depois que o servidor confirma todos os itens do envio, incluindo lotes. Se a tarefa anterior já terminou, o próximo item aparece aguardando início, sem exibir o resultado anterior. Respostas sem confirmação válida preservam a seleção e mostram o erro no formulário.
- Atualizações de progresso, término da tarefa, fila e carregamento atrasado do editor de revisão não substituem o formulário nem o estado de envio. Falha parcial conserva somente os arquivos pendentes para a próxima tentativa.
- Corrigido o resumo da música escolhida ao selecionar um arquivo no Modo Rápido. Nova inclusão limpa a seleção anterior e mantém os ajustes do usuário.
- Verificação de navegador para os três modos, respostas atrasadas, falhas parciais, revisão, permissões, fila pausada e cinco larguras de tela. Publicação somente do servidor.

# 10.7

- Auditoria do fluxo de criação, revisão, fila, cache, renderização e interface. Relatório: [AUDIT_FLOW_V10_7.md](AUDIT_FLOW_V10_7.md).
- Letra sincronizada continua sendo a fonte do texto completo e dos intervalos dos versos. Salvar uma revisão sem alterações preserva também os espaços originais. O Whisper fornece apenas os tempos locais da animação; karaokê mantém o áudio completo e a voz principal isolada quando há backing vocals.
- Layout com regiões separadas para verso e prévia também aplicado às legendas comuns. Corrigida a duplicação do primeiro verso na introdução. Sílabas usam varredura; palavras destacam a palavra inteira; linhas/frases ficam estáticas, respeitando a cor escolhida.
- Revisão com campos maiores, áudio original autenticado e navegação que busca o início do verso. Linhas vazias, tempos inválidos e ordem invertida mostram o erro no editor e não liberam uma renderização inválida. A prévia de fundo usa a sessão atual e o vídeo original quando selecionado.
- Envios em lote preservam somente os arquivos pendentes em caso de falha; arquivos já aceitos não são enviados novamente pela repetição do lote. Erros e confirmações ficam na página. A fila é salva com substituição atômica; falha ao salvar uma tarefa não deixa um trabalho oculto em memória.
- Promoção de cache prepara a cópia antes de substituir a anterior, com recuperação após interrupção. Corrigido o fundo de cor sólida para usar preto. Finalização do FFmpeg fecha o pipe e encerra processos em falhas de acompanhamento.
- Cabeçalho menor no celular, Biblioteca sem quebra de palavra, navegação por teclado e controles que refletem a política de letra sincronizada e áudio sem cortes. Configurações antigas são normalizadas.
- Verificação com 244 testes Python, FFmpeg/libass real e testes de navegador para os três modos, revisão, tentativas de novo, YouTube e tamanhos de tela. O workflow de publicação verifica também os modelos reais de backing vocals e Whisper em CPU.
- Publicação somente do servidor. Android e configurador Windows existentes são reutilizados.

# 10.6

- Reverte a mudança visual da 10.5 e restaura a varredura clássica de cor do karaokê. Corrigida a sobreposição entre verso atual e prévia da próxima linha mostrada na foto.
- Letra sincronizada continua fornecendo todas as palavras e os intervalos dos versos. Processamento local aplica quebras visuais, ajuste de fonte quando necessário e regiões separadas para verso/prévia nas posições superior, central e inferior.
- Animação usa somente os tempos locais, ignorando o texto reconhecido. Pausas usam início absoluto de karaokê no libass, sem caracteres invisíveis que desloquem ou cortem a letra.
- Cache invalida a renderização da 10.5, preservando análises de voz compatíveis. Áudio completo, voz principal isolada com backing vocals ativos e ausência de VAD no karaokê permanecem.
- Publicação somente do servidor: Android e configurador Windows existentes são reutilizados.

# 10.5

- Letra sincronizada mantém texto completo e tempos dos versos intactos. Retirados o ajuste dos versos pela voz e o limite artificial de 12 segundos.
- Animação usa somente os intervalos locais de palavras, em ordem, ignorando totalmente o texto reconhecido. A letra inteira fica visível; somente a cor muda, sem espaços invisíveis, cortes ou desaparecimento de palavras.
- Palavras sem tempo local suficiente continuam visíveis. Um cache de animação incompatível não pode substituir o texto original.
- Karaokê envia o áudio completo ao Whisper, sem VAD nem remoção de silêncios: voz principal isolada com backing vocals ativos, PCM float32 e precisão máxima no modelo escolhido. A abertura do título permanece fora da música.
- Resultados antigos são refeitos; análises acústicas compatíveis permanecem reutilizáveis. Servidor Docker, interface e documentação atualizados para 10.5. Android e configurador Windows existentes são reutilizados; só são recompilados quando houver alterações relevantes em seu código.

# 10.4

- Letra sincronizada fornece sempre o texto completo do karaokê quando corresponde ao artista e à música. Divergências de duração ou tempo e a opção de tempos pelo áudio não substituem esse texto pela transcrição do Whisper.
- Animação local preserva todas as palavras do provedor. Quando há incompatibilidade, versos reconhecidos usam tempos medidos na gravação; versos sem reconhecimento suficiente conservam os tempos fornecidos.
- Com backing vocals ativados, o Whisper recebe somente a voz principal isolada, independentemente da opção de áudio original e do volume das vozes de apoio. A mixagem final continua preservando os backing vocals no volume escolhido.
- Cache invalida legendas antigas e análises feitas na fonte vocal incorreta, preservando áudio separado e análises compatíveis. A abertura com título continua fora do relógio da música.

# 10.3

- Corrigida a perda do cache acústico de letras sincronizadas ao refazer um vídeo. Análise bruta e metadados são reaproveitados sem reutilizar checkpoints de outra tarefa; revisão manual não sobrescreve o resultado original do Whisper.
- Preservado o cache após falhas posteriores e incluídos os resultados de análise SRT. O cache só é apagado após uma promoção bem-sucedida; pedidos compatíveis do mesmo vídeo YouTube podem reutilizar o download.
- Identificação da mídia por SHA-256, com migração do cache legado sem repetir a separação desnecessariamente. Mesma letra com mudanças apenas de espaços/quebras de linha não invalida a análise.
- Letra-guia corrige também palavras mal reconhecidas entre duas frases confirmadas, sem inserir versos ausentes ou alterar tempos da voz. Letras sincronizadas aceitas continuam mantendo texto e relógios do provedor.
- Downloads novos buscam os melhores fluxos disponíveis, sem teto de 1080p. Preparação e mixagem em PCM float32; Whisper recebe seu formato exigido de mono/16 kHz com reamostragem de maior precisão e usa precisão máxima no modelo escolhido.
- SRT usa a mídia original diretamente, sem recompressão intermediária MP3. Exportação de áudio dos vídeos em AAC a 320 kbps. Estas escolhas aumentam uso de CPU, memória, disco e tempo, sem garantia de reconhecimento perfeito ou recuperação de detalhes ausentes na fonte.
- Primeira análise após atualizar a versão de preparação/precisão é refeita uma vez. Repetições compatíveis posteriores reutilizam o Whisper. Mantidos abertura fora do relógio da música, animação, backing vocals, revisão, busca, fila, Biblioteca, Telegram, interface responsiva e bloqueio absoluto de publicação dos resultados SRT no YouTube.

# 10.2

- Corrigida a aceitação de letras sincronizadas com introdução ou cortes diferentes da gravação, mesmo quando artista, título e duração total coincidem.
- Após o Whisper, os tempos de vários versos são conferidos contra frases reconhecidas na gravação. Um desvio consistente faz o app usar letra-guia e tempos da voz; os tempos de uma LRC compatível permanecem intactos, com Whisper apenas na animação.
- Preservado o cache de áudio, backing-vocal e transcrição. A primeira repetição após atualizar refaz as legendas e o vídeo para não reutilizar o resultado incorreto.
- Incluídos o diagnóstico no resumo e nos registros, percentual da verificação e um único aviso de início dessa etapa no Telegram.
- Testada a abertura silenciosa de três segundos com FFmpeg real: áudio e legenda continuam usando o relógio do conteúdo e são deslocados juntos no MP4 final.
- Mantidos os recursos dos modos Rápido, Detalhado e SRT, busca, publicação no YouTube, playlists, privacidade Não listado, fundos aleatórios, Biblioteca, fila e Android. Resultados SRT continuam bloqueados no YouTube.

## Atualizações anteriores: 10.1

- Mantido o uso pessoal em rede local ou VPN, com esclarecimento desse cenário no README, Manual, instalação, privacidade e textos jurídicos.
- Atualizados Requests 2.34.2, python-multipart 0.0.32, Jinja2 3.1.6, FastAPI 0.142.2, Starlette 1.7.0, Uvicorn 0.54.0 e Transformers 5.18.0.
- Adaptada a abertura da interface à API atual de templates do Starlette, preservando o layout e as funções.
- Esclarecidas pesquisa, importação e publicação no YouTube, as permissões independentes do conteúdo e da plataforma, OAuth, privacidade Não listado e revogação do acesso ao canal.
- Mantidos todos os recursos de karaokê, SRT, tradução, backing-vocal, letra sincronizada, animação Whisper, fundos aleatórios, fila, Biblioteca, Telegram e Android. Resultados SRT continuam bloqueados no YouTube.
- Avisos de terceiros atualizados sem declarar resolvidas as pendências de licenças de modelos, imagens e redistribuição.

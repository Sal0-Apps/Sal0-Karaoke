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

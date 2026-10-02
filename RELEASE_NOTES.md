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

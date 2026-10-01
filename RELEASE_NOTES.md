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

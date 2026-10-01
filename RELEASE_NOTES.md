# 9.9.11

- Corrigida a falha `metadata_errors` ao iniciar a transcrição: o áudio é convertido pelo FFmpeg para o formato do Whisper, sem depender da abertura de arquivos pelo PyAV.
- A mesma conversão atende transcrição, tradução e animação das letras sincronizadas; a tentativa sem VAD reaproveita o áudio convertido.
- Áudio inválido e cancelamento são tratados antes do carregamento do modelo. As faixas de backing-vocal existentes continuam aproveitáveis pelo cache.
- A publicação valida leitura de áudio e inferência real do Whisper em CPU dentro da imagem, além dos testes do backing-vocal, interface e Android.
- Mantidos os tempos dos versos da letra sincronizada, animação pelo Whisper, busca no YouTube, MP4 para áudio no modo SRT, playlists por perfil, privacidade Não listado, fila, Biblioteca e Android.

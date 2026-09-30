# 9.9.10

- Corrigido o progresso do backing-vocal: o app distingue preparação do áudio, preparação dos blocos, análise da voz e geração das faixas.
- A análise tem seu próprio percentual de 0 a 100%, atualizado após cada bloco concluído. As barras rápidas de preparação não são tratadas como conclusão da separação.
- Reconstrução e salvamento mostram a subetapa sem inventar uma porcentagem. Os registros identificam as barras, e o Telegram mantém somente o aviso inicial.
- Testes cobrem a sequência de barras do problema, falhas durante a análise e inferência real em CPU com identificação das subetapas.
- Mantidos os tempos dos versos da letra sincronizada, animação pelo Whisper, busca no YouTube, MP4 para áudio no modo SRT, playlists por perfil, privacidade Não listado, fila, Biblioteca e Android.
- Documentação completa e instruções de diagnóstico atualizadas.

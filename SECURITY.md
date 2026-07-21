# Segurança e privacidade

## Processamento local

O áudio, a separação vocal, os modelos Demucs/Faster-Whisper, a sincronização e a renderização FFmpeg são executados no ambiente local do aplicativo. O volume `/data` deve ser tratado como privado: ele pode conter mídias, legendas, vídeos, perfis, logs, usuários e sessões.

## Busca automática de letras

Quando o modo automático está ativo e existe internet, o aplicativo envia somente uma consulta textual de título/artista para fontes públicas de letras. A busca usa LRCLIB, Lyrics.ovh e o fluxo público do aplicativo desktop do Musixmatch. O áudio, o vídeo e os arquivos de processamento nunca são enviados para esses provedores.

O token temporário do Musixmatch, quando fornecido pelo endpoint público, permanece apenas em memória. O repositório não contém token fixo, cookie pessoal, API key ou credencial de usuário. A busca é opcional: indisponibilidade, timeout ou ausência de internet não interrompem a criação local, e a letra manual continua disponível.

## Segredos e configuração

- Nunca publique `.env`, `.env_deploy`, tokens do GitHub, tokens do Telegram, chaves privadas, cookies ou arquivos do volume `/data`.
- Use `.env.example` somente como modelo sem valores reais.
- Configure credenciais apenas no ambiente de execução ou em um segredo do CI.
- Troque imediatamente qualquer credencial que tenha sido publicada por engano; apagar o arquivo em um commit posterior não remove o valor do histórico.
- Restrinja a porta publicada e use uma rede confiável, VPN ou proxy autenticado quando o serviço sair da máquina local.

## Relato

Para relatar uma vulnerabilidade, não inclua tokens, senhas, mídias ou logs completos em uma issue pública. Remova dados pessoais e envie apenas o cenário mínimo necessário por um canal privado do mantenedor.

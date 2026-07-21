# 🛡️ Segurança

Este é um projeto pessoal disponibilizado abertamente sem garantias ou compromissos de manutenção contínua.

## Privacidade e Dados

- Áudio, vídeo, modelos de IA, transcrição e renderização rodam localmente na sua máquina ou servidor.
- A busca de letra é automática por padrão e pode ser substituída pela entrada manual: o título/artista da música selecionada é enviado à LRCLIB quando houver conexão e a letra retornada pode ser salva localmente para revisão. Nenhum arquivo de áudio ou vídeo é enviado nessa busca.
- Senhas locais são salvas usando PBKDF2 com Salt.
- Arquivos de configuração e credenciais locais são ignorados no Git pelo `.gitignore`.

## Avisos ou Modificações

Como este projeto é mantido apenas como hobby/ferramenta pessoal, **não há equipe de suporte dedicada nem acompanhamento constante de mensagens ou problemas**. 

Se você encontrar algum ponto de melhoria ou quiser ajustar a segurança para a sua necessidade, fique à vontade para modificar o código diretamente na sua instalação local ou no seu próprio repositório.

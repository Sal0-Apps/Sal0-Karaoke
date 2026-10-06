# Estado do projeto

O Sal0 Karaokê é um projeto pessoal para instalação local e acesso por VPN. A distribuição atual é a **11.3**: o Whisper recebe o arquivo original por padrão, sem passar pela separação de vocais, mesmo com backing vocals ativos. A opção de fonte é respeitada e aparece no resumo; configurações antigas do Modo Rápido migram para original preservando visual e fundos. O cache anterior de reconhecimento é refeito uma vez. A separação continua preparando o instrumental do vídeo. Mantém a busca de letra da 11.2: teclado, foco, seleção e rolagem permanecem durante as atualizações; uma tentativa automática por mídia valida título, artista e versão, descartando respostas sem relação; o controle manual ignora respostas antigas. Mantém os recursos da 11.1: legendagem SRT sempre gera vídeo com legendas embutidas e opções próprias no administrador; Telegram entrega vídeo compactado com links dos SRTs; letras ficam vinculadas a cada mídia e item da fila; fundos podem ser baixados durante o processamento. No karaokê, Whisper define as palavras e toda a sincronia; letras externas, inclusive sincronizadas, servem como guia de reconhecimento e conferência. Diferenças podem gerar uma segunda análise local do áudio completo. Mantém a organização de frases, posições estáveis, destaque suave, inclusão de novos trabalhos em tela limpa, revisão com áudio, recuperação de fila/cache e recursos existentes. Atualização somente do servidor; Android e configurador Windows existentes continuam utilizáveis. Veja [AUDIT_FLOW_V10_7.md](AUDIT_FLOW_V10_7.md) para a auditoria anterior.

Não há um roteiro público de desenvolvimento ativo. Publicações pontuais não representam compromisso de novas versões, funcionalidades, migrações ou acompanhamento contínuo. Pull requests e solicitações de funcionalidades provavelmente não serão revisados.

## Suporte e segurança

Bugs críticos podem ser registrados em Issues sem dados privados. Vulnerabilidades devem seguir [SECURITY.md](SECURITY.md) e poderão ser avaliadas conforme disponibilidade, gravidade e viabilidade. Não há prazo garantido de resposta ou correção.

## Continuidade por forks

Pessoas interessadas em continuar o desenvolvimento são incentivadas a criar um fork sob os termos da [licença MIT](LICENSE), definir sua própria manutenção e documentar alterações, dependências e migrações. Preserve os avisos de autoria e as licenças de terceiros.

## Documentação

- [Apresentação](README.md)
- [Manual completo](MANUAL.md)
- [Instalação e atualização](DEPLOYMENT.md)
- [Segurança](SECURITY.md)
- [Auditoria](SECURITY_AUDIT.md)
- [Privacidade](PRIVACY.md)
- [Direitos de uso](LEGAL.md)
- [Terceiros](THIRD_PARTY_NOTICES.md)

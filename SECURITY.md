# Segurança

## Comunicação de vulnerabilidades

Não abra vulnerabilidades de segurança em Issues públicas, pull requests ou discussões abertas. Relatos públicos podem expor usuários, instalações e dados antes que o problema seja compreendido.

Envie um relato privado pelo mecanismo de contato ou de segurança disponibilizado pelo repositório no GitHub. Inclua, quando possível:

- descrição objetiva do problema;
- passos para reproduzir a falha;
- impacto observado ou potencial;
- versão, ambiente e configuração afetados;
- evidências que não contenham senhas, tokens, dados pessoais ou mídias privadas;
- uma forma segura de contato, caso seja necessário esclarecer o relatório.

Não envie credenciais reais, tokens de bots, arquivos de sessão, conteúdo de `/data` ou dados pessoais no relato.

## Tratamento

Os relatos serão analisados conforme a disponibilidade dos responsáveis pelo projeto. A análise pode não resultar em correção, publicação de aviso ou prazo de resposta.

Este projeto está em manutenção mínima e não oferece acompanhamento contínuo, SLA, suporte permanente ou garantia de novas versões. Correções de segurança poderão ser avaliadas eventualmente quando forem viáveis e necessárias.

Até que uma correção esteja disponível, mantenha o serviço em rede confiável, restrinja a exposição externa, use HTTPS ou uma VPN quando aplicável, atualize o Docker e proteja o volume persistente `/data`.

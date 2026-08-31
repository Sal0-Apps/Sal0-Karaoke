# Política de segurança

## Como relatar uma vulnerabilidade

Não publique vulnerabilidades, provas de conceito, credenciais ou dados de instalações em Issues, pull requests ou discussões abertas.

Use o recurso privado **Report a vulnerability** disponível na aba **Security** do repositório, quando habilitado. Inclua somente as informações necessárias:

- versão e ambiente afetados;
- descrição do impacto;
- passos mínimos para reprodução;
- condição necessária para exploração;
- sugestão de mitigação, se conhecida;
- uma forma segura de contato.

Nunca envie senhas, tokens de sessão, tokens do Telegram, links privados de download, conteúdo de `/data`, mídias de usuários ou logs sem revisão. Substitua valores reais por exemplos inofensivos.

Se o canal privado não estiver disponível, não divulgue detalhes exploráveis em público. Uma Issue pode apenas solicitar a abertura de um canal privado, sem revelar a vulnerabilidade.

## Política de atendimento

O projeto está em manutenção mínima. Relatos serão avaliados conforme disponibilidade, sem SLA ou garantia de confirmação, correção, aviso público ou nova versão. Pull requests e solicitações de funcionalidade provavelmente não serão revisados.

## Operação segura

- mantenha o serviço em rede confiável ou atrás de VPN e HTTPS;
- não exponha diretamente a porta do container à Internet sem controles adicionais;
- proteja `/data/users.json`, `/data/sessions.json`, configurações do Telegram e logs;
- trate URLs com parâmetro `token` como credenciais;
- restrinja o acesso ao host Docker e ao socket do Docker;
- atualize imagem, sistema operacional e dependências após avaliação;
- faça backup antes de qualquer atualização;
- revise logs e arquivos de diagnóstico antes de compartilhá-los;
- revogue imediatamente qualquer segredo que possa ter sido exposto.

## Dependências e modelos

O projeto utiliza bibliotecas, modelos e executáveis de terceiros. Advisories podem surgir depois da última versão. Antes de publicar ou expor uma instalação, execute uma auditoria atualizada das dependências Python, da imagem base, dos pacotes Debian e do aplicativo Android.

O resultado datado da revisão mais recente está em [SECURITY_AUDIT.md](SECURITY_AUDIT.md). Esse relatório registra vulnerabilidades conhecidas e limitações que ainda exigem tratamento; ele não deve ser interpretado como certificação de segurança.

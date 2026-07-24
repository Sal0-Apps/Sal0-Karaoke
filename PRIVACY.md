# Privacidade

## Processamento local

O Sal0 Karaokê prioriza o processamento local ou auto-hospedado. Músicas, vídeos, resultados, sessões, configurações e arquivos temporários permanecem na instalação e no volume persistente configurado pelo administrador.

O projeto não coleta dados pessoais em servidores próprios. Não há, no código do projeto, um serviço central destinado a registrar contas, mídias ou histórico de uso de todas as instalações.

## Integrações opcionais

Serviços configurados voluntariamente pelo usuário, como Telegram, YouTube e provedores de letras, são de responsabilidade do próprio usuário. Ao ativar uma integração, o usuário decide quais dados serão enviados ao serviço correspondente e fica sujeito à política de privacidade, aos termos de uso e à disponibilidade desse serviço.

O Telegram pode receber mensagens de progresso, links diretos ou vídeos conforme a configuração da conta. O YouTube e os provedores de letras podem receber URLs, títulos, artistas ou outros dados necessários ao recurso solicitado. O projeto não controla a retenção ou o tratamento realizado por esses serviços externos.

## Responsabilidade da instalação

Os dados permanecem na instalação local, salvo quando o próprio usuário configura integrações externas ou expõe o serviço por rede, proxy, VPN ou endereço público. O administrador da instalação é responsável por:

- proteger o volume `/data` e os arquivos de sessão;
- restringir portas, usuários e acesso administrativo;
- configurar HTTPS, VPN ou proxy quando houver acesso externo;
- proteger tokens de Telegram e outras credenciais;
- definir backups, retenção e exclusão de mídias;
- revisar logs antes de compartilhá-los.

Este documento descreve o comportamento pretendido do projeto e não constitui garantia de segurança, anonimização ou conformidade legal em uma instalação específica.

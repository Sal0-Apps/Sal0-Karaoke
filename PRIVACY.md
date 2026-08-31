# Privacidade

## Escopo

O Sal0 Karaokê é auto-hospedado e não possui um serviço central operado pelo projeto para coletar contas, mídias ou histórico das instalações. O responsável pelo servidor atua como operador dos dados armazenados na própria instalação.

## Dados locais

O volume `/data` pode conter:

- usuários e hashes de senha;
- sessões ativas;
- tokens e identificadores de chat do Telegram;
- mídias originais e fundos;
- vídeos e arquivos SRT gerados;
- modelos de IA, cache, estado e logs;
- endereços local e externo configurados.

Esses dados permanecem no servidor até que o operador ou o aplicativo os remova. O projeto não define uma política universal de retenção, backup ou exclusão.

## Comunicações externas

Embora o processamento principal seja local, a instalação não é totalmente offline por padrão:

- o navegador solicita as fontes Inter e Outfit ao Google Fonts quando carrega a interface;
- modelos podem ser baixados do Hugging Face e dos repositórios utilizados por Demucs e Transformers;
- a construção da imagem baixa Deno e imagens públicas do Wikimedia Commons;
- URLs e metadados de mídia podem ser enviados ao YouTube por meio de `yt-dlp` quando o usuário solicita esse recurso;
- consultas de letras podem transmitir título e artista a LRCLIB, Lyrics.ovh ou Musixmatch;
- Telegram recebe mensagens, documentos, vídeos compactados e links quando configurado;
- GitHub e GHCR recebem dados normais de acesso quando código, imagem, APK ou Release são consultados.

Esses serviços aplicam suas próprias políticas, termos, registros e períodos de retenção. O projeto não controla o tratamento realizado por terceiros.

## Tokens em URLs e logs

Alguns downloads e previews aceitam sessão ou link público no endereço. URLs podem ser registradas pelo navegador, proxy reverso, servidor HTTP, roteador ou ferramenta de diagnóstico. Logs devem ser protegidos e revisados antes de compartilhamento.

Os links públicos enviados pelo Telegram possuem tokens aleatórios, mas a versão 9.0.7 não aplica expiração automática a esses registros. Quem receber ou copiar um link poderá usá-lo enquanto o registro e o arquivo permanecerem no servidor. O operador deve remover resultados e registros que não devam mais ser acessíveis e evitar publicar esses endereços em canais abertos.

## Responsabilidades do operador

O operador deve:

- informar os usuários sobre os serviços externos ativados;
- definir base jurídica, retenção e exclusão quando a legislação exigir;
- proteger o volume `/data` e os backups;
- limitar contas administrativas;
- configurar HTTPS ou VPN para acesso remoto;
- revogar tokens e sessões expostos;
- atender solicitações aplicáveis de acesso ou exclusão;
- verificar requisitos locais de proteção de dados.

Este documento descreve o comportamento técnico observado e não constitui garantia de anonimização, conformidade com LGPD/GDPR ou adequação a uma jurisdição específica.

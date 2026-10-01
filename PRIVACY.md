# Privacidade

## Escopo

O Sal0 Karaokê é auto-hospedado e não possui um serviço central operado pelo projeto para coletar contas, mídias ou histórico das instalações. O responsável pela instalação controla os dados locais e deve avaliar suas responsabilidades conforme a legislação aplicável ao uso realizado.

O Sal0 Karaokê é destinado a uma instalação pessoal, acessada pela rede local ou por VPN, como ZeroTier. O repositório aberto disponibiliza o código e os pacotes; o projeto não opera um serviço público de processamento nem coleta centralmente as mídias das instalações. Não é necessário expor a porta do app à internet. O processamento principal é local, mas as integrações escolhidas podem se comunicar com serviços externos.

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
- a tradução de SRT envia o arquivo de legenda completo à instância LibreTranslate configurada pelo administrador; o padrão detecta a origem automaticamente e traduz para português do Brasil. O operador dessa instância controla seus registros, arquivos e retenção. A URL e a chave opcional ficam em `/data/output/libretranslate.json`;
- a publicação via YouTube Data API envia o MP4 escolhido, capa, título, privacidade e playlist ao Google; o modo Gerar SRT nunca é enviado a essa API;
- GitHub e GHCR recebem dados normais de acesso quando código, imagem, APK ou Release são consultados.

Esses serviços aplicam suas próprias políticas, termos, registros e períodos de retenção. O projeto não controla o tratamento realizado por terceiros.

## Tokens em URLs e logs

Alguns downloads e previews aceitam sessão ou link público no endereço. URLs podem ser registradas pelo navegador, proxy reverso, servidor HTTP, roteador ou ferramenta de diagnóstico. Logs devem ser protegidos e revisados antes de compartilhamento.

Os links públicos enviados pelo Telegram possuem tokens aleatórios, mas o aplicativo não aplica expiração automática a esses registros. Quem receber ou copiar um link poderá usá-lo enquanto o registro e o arquivo permanecerem no servidor. O operador deve remover resultados e registros que não devam mais ser acessíveis e evitar publicar esses endereços em canais abertos.

## Dados no Android

O aparelho armazena SSID e endereços de conexão nas preferências do aplicativo, além da sessão e preferências da interface na WebView. Arquivos baixados são salvos em Downloads. Abrir as configurações de conexão fecha a página atual, mas não interrompe trabalhos já aceitos pelo servidor. A limpeza dos dados do APK não apaga automaticamente mídias e contas do servidor.

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

## Autorização do canal YouTube

A autorização é importada do assistente local ou concluída pelo OAuth web configurado pelo administrador. O servidor guarda tokens de acesso e renovação e os dados da credencial em `/data/youtube/token.json`, com permissão de arquivo 0600. Não são enviados ao mantenedor do repositório. A renovação faz requisições ao Google; esses dados permitem acesso ao canal e não são criptografados em repouso pelo aplicativo. Proteja o volume e seus backups.

Para encerrar o acesso, revogue a permissão em [Conexões da conta Google](https://myaccount.google.com/permissions) e remova o arquivo de autorização armazenado no seu servidor. Faça isso sem tarefas de publicação em andamento. Revogar não apaga vídeos já enviados; remover dados do servidor também não remove o conteúdo do YouTube. O administrador da instalação é o contato para solicitações sobre seus dados locais. Consulte a [privacidade do Google](https://policies.google.com/privacy) e os [termos do YouTube](https://www.youtube.com/static?template=terms).

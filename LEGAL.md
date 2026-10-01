# Uso pessoal, licenças e integrações

> Este documento é uma análise técnica e informativa, não aconselhamento jurídico. Leis, contratos e licenças variam conforme jurisdição e forma de distribuição. Para uma decisão comercial ou institucional, consulte um profissional qualificado.

O Sal0 Karaokê é destinado a uma instalação pessoal, acessada pela rede local ou por VPN, como ZeroTier. O repositório aberto disponibiliza o código e os pacotes; o projeto não opera um serviço público de processamento nem coleta centralmente as mídias das instalações. Não é necessário expor a porta do app à internet. O processamento principal é local, mas as integrações escolhidas podem se comunicar com serviços externos.

## O que a licença MIT cobre

A [licença MIT](LICENSE) autoriza uso, cópia, modificação e redistribuição do código original do Sal0 Karaokê, desde que o aviso de copyright e a licença sejam preservados. Ela não concede direitos sobre:

- músicas, vídeos, letras, imagens ou vozes processadas pelo usuário;
- marcas, nomes e identidades de terceiros;
- bibliotecas, executáveis, modelos, fontes ou imagens de terceiros;
- conteúdo obtido de serviços externos;
- patentes relacionadas a codecs ou formatos multimídia.

A publicação sob MIT pressupõe que o titular indicado no arquivo `LICENSE` possui ou recebeu autorização para licenciar todas as contribuições originais e os recursos visuais próprios do projeto. O histórico Git não comprova sozinho a origem jurídica de cada contribuição.

## Revisões e limites

Em 1º de outubro de 2026, a revisão do código v10.0 e dos 85 commits alcançáveis procurou padrões de tokens GitHub/Telegram, chaves AWS, chaves privadas e segredos OAuth Google, sem encontrar correspondências. Isso não inclui uma inspeção integral dos binários e artefatos antigos. A atualização v10.1 atualiza dependências e textos, mantendo as funções; não encerra automaticamente todas as pendências de licenças.

## Conclusão histórica da auditoria de publicação

A revisão de textos de 12 de setembro de 2026, para a versão 9.5.0, conferiu novamente os 22 commits alcançáveis anteriores à publicação e não encontrou segredos de alta confiança. Ela não encerra as pendências de licenças e dependências registradas abaixo. O título público mantém apenas o nome da aplicação; versões e limitações estão nos documentos de operação e auditoria.

Na auditoria local de 31 de agosto de 2026:

- nenhum segredo de alta confiança foi encontrado nos 21 commits alcançáveis;
- não foram encontrados e-mails pessoais: o histórico usa endereço `users.noreply.github.com`;
- não há `.env`, keystore, chave privada ou arquivo de credencial rastreado;
- o antigo `.env.example` continha somente um marcador e foi removido da árvore de trabalho;
- o código-fonte pode permanecer público sob MIT, desde que o mantenedor confirme a autoria do código, do nome e dos ícones;
- a redistribuição da imagem Docker e do APK exige uma análise adicional dos componentes efetivamente incorporados;
- dependências fixadas apresentaram advisories conhecidos e devem ser atualizadas e testadas antes de uma nova distribuição.

Não foi necessário reescrever o histórico por segredo, porque nenhum valor confidencial foi localizado. Reescrever commits apenas para remover um arquivo de exemplo inofensivo acrescentaria risco e não aumentaria a proteção de credenciais.

O método, os achados de dependências e as limitações da revisão estão documentados em [SECURITY_AUDIT.md](SECURITY_AUDIT.md).

## Mídias e direitos autorais

Criar um instrumental, legenda, tradução ou vídeo sincronizado pode envolver reprodução, adaptação, transformação, exibição pública e distribuição. Essas atividades podem depender de autorização do titular, licença aplicável, domínio público ou exceção legal específica.

O usuário deve processar somente conteúdo:

- de sua autoria;
- em domínio público;
- sob licença que permita o uso pretendido; ou
- autorizado pelos titulares relevantes.

O projeto não inclui um catálogo próprio de gravações comerciais. As integrações podem buscar mídias e letras externas, mas isso não transforma conteúdo protegido em conteúdo livre.

## Uso do YouTube em uma instalação local

As funções de pesquisa, importação por link e publicação no canal continuam disponíveis e têm papéis diferentes:

- **Pesquisar** consulta o YouTube para localizar vídeos e exibir título, canal e miniatura. Isso não concede direitos sobre o conteúdo.
- **Importar por link** usa `yt-dlp` para obter a mídia escolhida. Use somente quando os direitos do conteúdo e as condições do serviço permitirem a obtenção e o processamento. A autorização do titular, por si só, não substitui as permissões exigidas pelo YouTube. Os termos restringem downloads e acesso automatizado; as políticas de API também restringem armazenamento e separação de áudio/vídeo. A presença da função no app não comprova autorização da plataforma. Quando a obtenção pela plataforma não for permitida, use um arquivo disponibilizado por uma fonte autorizada.
- **Publicar no canal** usa a YouTube Data API com autorização OAuth do administrador. Essa autorização dá ao app acesso ao canal conectado; não licencia músicas, gravações, letras ou fundos. Contas locais autorizadas publicam nesse canal, não em um canal próprio de cada usuário. Confira o título, a capa, a playlist e a privacidade antes de iniciar.

A publicação começa marcada nos modos Rápido e Detalhado quando há canal e playlist válida no perfil. Desmarcar a opção naquela tarefa impede o envio. A privacidade padrão é **Não listado**: quem tiver o link poderá assistir; isso não equivale a privado nem dispensa direitos autorais. O servidor começa o envio como privado, aplica capa e playlist e então solicita a privacidade escolhida. O Google pode manter restrições em projetos sem auditoria.

Resultados do modo **Gerar SRT**, incluindo seus MP4, nunca são publicados no YouTube: o bloqueio vale para envio automático, manual e retomadas. Permanecem disponíveis para download, Biblioteca, prévia e Telegram configurado. Vídeos antigos sem origem confirmada também ficam bloqueados na publicação.

O uso pessoal, a ausência de divulgação, a gratuidade e o acesso por VPN não criam autorização para baixar, transformar ou publicar conteúdo protegido. Regras do serviço e direitos autorais são condições independentes. As funções foram preservadas; este texto não certifica que toda forma de uso esteja autorizada.

Referências: [Termos do YouTube](https://www.youtube.com/static?template=terms), [políticas da API](https://developers.google.com/youtube/terms/developer-policies), [privacidade do Google](https://policies.google.com/privacy) e [permissões da conta Google](https://myaccount.google.com/permissions).

O mesmo cuidado vale para Telegram, LRCLIB, Lyrics.ovh, Musixmatch e demais serviços externos. O provedor Musixmatch usa um endpoint de aplicativo desktop e não demonstra, sozinho, licença contratual para obter ou redistribuir letras. Confirme as condições do provedor antes de utilizar seus resultados.

## Letras e traduções

Letras musicais e traduções podem ser obras protegidas. A disponibilidade de uma letra em uma API não prova que ela pode ser copiada, adaptada ou redistribuída. O operador deve verificar a licença e os termos de cada provedor e evitar publicar resultados sem autorização.

## FFmpeg, codecs e imagem Docker

O container instala FFmpeg pelo repositório Debian e solicita H.264 por meio de `libx264`. O [projeto FFmpeg](https://ffmpeg.org/legal.html) informa que a base é LGPL-2.1-or-later, mas que habilitar componentes GPL, especialmente `libx264`, altera as obrigações aplicáveis ao binário. A licença exata depende da configuração do pacote Debian realmente incorporado e deve ser confirmada com a saída de `ffmpeg -version` da imagem publicada.

Distribuir uma imagem que contém esse binário pode exigir, entre outras obrigações, avisos, textos de licença e acesso ao código-fonte correspondente da versão exata distribuída. A licença MIT do Sal0 Karaokê não elimina essas obrigações. O mantenedor da imagem deve conservar o manifesto de pacotes, a configuração do FFmpeg e um mecanismo compatível de oferta do código-fonte.

Codecs como H.264, AAC e MPEG podem também envolver patentes em algumas jurisdições. O próprio projeto FFmpeg recomenda avaliação específica para uso comercial.

## Modelos de IA

Pesos de modelos são artefatos independentes do código que os carrega. Cada model card deve ser conferido na revisão exata utilizada. Não redistribua pesos em uma imagem pública se a licença do repositório, da revisão ou do arquivo não puder ser confirmada.

Na data da auditoria, os model cards públicos de [`Systran/faster-whisper-medium`](https://huggingface.co/Systran/faster-whisper-medium) e [`facebook/m2m100_418M`](https://huggingface.co/facebook/m2m100_418M) indicavam MIT. O identificador exato `deepdml/faster-whisper-large-v3-turbo` usado pelo código não forneceu metadados públicos de licença. Existem repositórios públicos de nome semelhante, mas eles não comprovam a licença do identificador efetivamente solicitado. Uma cópia em cache não deve ser redistribuída sem comprovação da origem, revisão e licença exatas.

## Imagens, fontes e identidade visual

O build tenta baixar cinco imagens por URLs fixas do Wikimedia Commons. Apenas `Moraine Lake 17092005.jpg` teve página e domínio público confirmados nesta revisão. As outras quatro URLs não apresentaram página correspondente confirmável; não devem ser descritas como livres nem redistribuídas até a identificação correta. A relação exata está em [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). As fontes Inter e Outfit são carregadas do Google Fonts e permanecem sob suas próprias licenças.

Os ícones e o nome Sal0 Karaokê devem ser publicados apenas se o mantenedor possuir os direitos necessários e se não houver conflito de marca. A licença MIT do código não constitui registro de marca.

## Privacidade e proteção de dados

Uma instalação pública pode tratar contas, sessões, endereços de rede, mídias, letras, identificadores do Telegram e logs. O operador deve definir controles, retenção, base jurídica e avisos adequados à jurisdição. Consulte [PRIVACY.md](PRIVACY.md).

## Checklist antes de redistribuir

- confirmar autoria e autorização do código e dos ícones;
- executar varredura de segredos na árvore e em todos os commits;
- executar auditoria atual de vulnerabilidades;
- registrar versões e licenças de dependências diretas e transitivas;
- guardar os textos de licença exigidos no Docker e no APK;
- confirmar a licença de cada modelo e imagem incorporados;
- cumprir obrigações de código-fonte de componentes LGPL/GPL;
- revisar termos de YouTube, letras, Telegram e demais integrações;
- documentar privacidade, retenção, segurança e contato;
- evitar afirmações de que o projeto torna legal o uso de conteúdo de terceiros.

## Parecer resumido

O código-fonte pode ser mantido publicamente sob MIT se o titular confirmar que possui os direitos sobre as contribuições originais, o nome e a identidade visual. Não foi encontrado impedimento jurídico evidente à simples publicação do código.

Isso não equivale a afirmar que toda imagem Docker ou APK possa ser redistribuída sem providências adicionais. Há pendências documentadas de licenças de fundos, modelo de transcrição, configuração do FFmpeg, oferta de fontes correspondentes e vulnerabilidades conhecidas. O uso de importação por URL continua condicionado aos direitos sobre a mídia e aos termos do serviço de origem.

# Uso jurídico e publicação pública

> Este documento é uma análise técnica e informativa, não aconselhamento jurídico. Leis, contratos e licenças variam conforme jurisdição e forma de distribuição. Para uma decisão comercial ou institucional, consulte um profissional qualificado.

## O que a licença MIT cobre

A [licença MIT](LICENSE) autoriza uso, cópia, modificação e redistribuição do código original do Sal0 Karaokê, desde que o aviso de copyright e a licença sejam preservados. Ela não concede direitos sobre:

- músicas, vídeos, letras, imagens ou vozes processadas pelo usuário;
- marcas, nomes e identidades de terceiros;
- bibliotecas, executáveis, modelos, fontes ou imagens de terceiros;
- conteúdo obtido de serviços externos;
- patentes relacionadas a codecs ou formatos multimídia.

A publicação sob MIT pressupõe que o titular indicado no arquivo `LICENSE` possui ou recebeu autorização para licenciar todas as contribuições originais e os recursos visuais próprios do projeto. O histórico Git não comprova sozinho a origem jurídica de cada contribuição.

## Conclusão da auditoria de publicação

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

O software não fornece músicas, vídeos ou letras comerciais e não transforma conteúdo protegido em conteúdo livre.

## YouTube e outras plataformas

O suporte técnico a URLs não representa autorização da plataforma. Os [Termos de Serviço do YouTube](https://www.youtube.com/static?template=terms) restringem download, reprodução, alteração e uso automatizado, salvo quando o próprio serviço autoriza ou quando existe permissão prévia aplicável. O operador deve revisar os termos vigentes e os direitos do conteúdo antes de usar `yt-dlp`.

O mesmo princípio vale para Telegram, LRCLIB, Lyrics.ovh, Musixmatch, Hugging Face, Google Fonts, Wikimedia Commons, GitHub e outros serviços. APIs não documentadas, limites técnicos e condições de uso podem mudar sem aviso.

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

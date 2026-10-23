# Downloads e conferência da letra — 12.7.3

## Download durante o processamento

Em **Biblioteca → Adicionar à biblioteca → Música ou vídeo**, o download do YouTube pode começar enquanto outra música está em processamento. Cada importação usa uma pasta temporária e um identificador próprios. O arquivo só aparece na Biblioteca depois de salvo completamente; importações com o mesmo título recebem nomes diferentes. Falhas ao salvar são exibidas como erro.

O andamento usa os bytes informados pelo download quando disponíveis e mostra a etapa quando o tamanho não é conhecido. A consulta acompanha o identificador da transferência, inclusive com outras abas abertas. Áudio, letras, revisões e cache da fila em execução ficam preservados. Downloads continuam usando a coordenação existente do yt-dlp, podendo aguardar outra transferência ou manutenção do mecanismo, sem aguardar o processamento da música terminar.

## Refrões, contexto e silêncio

Três regressões foram reproduzidas e corrigidas:

- Uma divisão de janela acústica podia separar a palavra dos vizinhos necessários para propor a correção da guia. Agora as propostas conservam o contexto reconhecido ao redor da divisão; cada alteração continua dependendo da confirmação acústica na sua janela.
- Uma correção aceita fazia a rotina ignorar a comparação de repetições. A comparação agora usa o texto corrigido e exige que a hipótese reduzida explique melhor o áudio completo. Refrões realmente cantados são preservados.
- Uma correção aceita também podia ignorar a verificação de palavras sem apoio vocal. A mesma combinação conservadora de confiança acústica e detector de voz passa a valer após a correção. Ausência do detector não é interpretada como silêncio.

A apresentação contínua dos versos da 12.7.2 é mantida. Modelo Whisper, áudio, relógio da gravação, estilos e revisões manuais não são alterados. O cache automático de alinhamento muda de versão; ao refazer uma tarefa sem revisão manual, a legenda e o vídeo derivados são recalculados. Vídeos já concluídos não mudam sozinhos.

## Validação

A suíte local completa passou com 639 testes Python. Inclui os três testes que falhavam antes da correção, isolamento das importações, erro de gravação, escopo por usuário, cache/revisões, geração real de ASS/FFmpeg e tradução de SRT. Os fluxos de navegador de download durante o processamento, criação/revisão, fila/cache, SRT e interface passaram em Chromium, incluindo celular e desktop. Downloads externos, YouTube e Telegram são simulados nesses testes; não houve envio real.

O ensaio de canto real do projeto, em CPU com três threads, corrigiu uma palavra adulterada, removeu três palavras inseridas no silêncio final e distinguiu texto duplicado de uma repetição realmente cantada. No trecho controlado de 17 palavras, o erro mediano de início passou dos 400 ms introduzidos para cerca de 134 ms. Esse ensaio mede alinhamento nesse trecho; não é uma medida geral de reconhecimento nem valida as músicas específicas do usuário.

## Aplicação

Após a publicação da imagem, atualize somente o servidor para `ghcr.io/sal0-apps/sal0-karaoke:12.7.3`, preservando o volume `/data`, as portas e os recursos atuais. Os aplicativos Android e Windows existentes continuam compatíveis. Use **Refazer** para aplicar a nova conferência aos resultados anteriores. A imagem `12.7.2` permanece disponível para retorno.

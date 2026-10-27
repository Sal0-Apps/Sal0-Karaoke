# 12.7.8 — precisão por verso no karaokê

O exemplo fornecido de **How Not To Drown**, de CHVRCHES com Robert Smith, mostrou duas falhas combinadas: uma falha isolada descartava a guia inteira, e a limpeza posterior podia apagar palavras já confirmadas quando a separação de voz enfraquecia finais cantados.

## Correção

Cada verso confirmado preserva seu texto e seus tempos medidos, mesmo quando outro verso continua incerto. O reconhecimento permanece disponível nos trechos não confirmados ou não cobertos pela guia. O resumo distingue essa cobertura; uma análise acústica concluída não significa que toda a guia foi confirmada.

Finais omitidos e versos depois de pausas recebem novas janelas de análise, limitadas a 29 segundos. A estimativa de posição serve para escolher o áudio analisado; ela nunca vira um tempo de palavra no vídeo. Uma última tentativa reconhece o trecho independentemente, sem fornecer a guia como prompt, e só aceita uma frase completa que realmente coincida com o reconhecimento e tenha tempos válidos.

Quando o reconhecimento independente também falha, um verso só é recuperado se as hipóteses do Whisper e o alinhador MMS concordarem dentro do contexto dos versos vizinhos. O MMS fornece tempos positivos e medidos para todas as palavras; silêncio digital, falta de apoio fonético, inversão da sequência e encaixe em outro trecho impedem a recuperação. Novas análises locais usam contexto adicional e continuam limitadas a 29 segundos por tentativa. Uma posição sugerida pelo alinhamento da música inteira não basta para confirmar uma frase curta no instrumental.

A sequência de palavras e versos deve avançar na gravação. Uma repetição não pode voltar ao refrão anterior, e o refinamento dos tempos não pode mover a última palavra para antes da precedente. A limpeza do stem vocal não apaga palavras confirmadas na fonte escolhida para transcrição. Essas palavras também ficam fora de uma segunda correção lexical ou redução de repetições.

O refinamento confere os tempos nos dois sentidos: quando uma palavra seguinte avança, a anterior também pode receber seu tempo correto sem violar a ordem. Isso corrige a primeira palavra de um refrão que ficava destacada durante a pausa, apesar de o alinhador ter medido o início correto. Silêncio digital medido na fonte escolhida também limita o início das palavras; essa regra não usa o volume do stem separado.

## SRT

**SRT e Legendar vídeo não executam essa conferência acústica adicional.** O fluxo usa a transcrição do áudio completo, a revisão manual quando solicitada, a geração do SRT e a tradução opcional. Isso vale para transcrição nova, reaproveitada, revisada e retomada de checkpoint. A geração do vídeo legendado e os downloads continuam disponíveis.

## Validação

O defeito foi reproduzido com o original fornecido e uma referência completa da [descrição oficial](https://www.youtube.com/watch?v=7U_LhzgwJ4U): o código anterior confirmava 53 dos 55 versos, mas rejeitava toda a guia por causa de dois versos. O áudio original e o vídeo enviado têm a mesma duração musical; o resultado inclui os três segundos habituais da abertura.

No teste corrigido desse original, as **344 palavras dos 55 versos** foram preservadas, com texto na mesma ordem da referência e tempos positivos para todas as palavras. As nove palavras dos dois versos inicialmente incertos foram recuperadas pela análise conjunta. As três palavras falsas do silêncio final foram descartadas, e a última palavra ficou em aproximadamente **281,29 s** da origem, antes da abertura ser acrescentada. Isso valida o texto e os tempos nesse arquivo; não é uma medição de acerto universal.

A análise local usou o modelo **medium em int8**, com quatro threads e alinhador MMS em CPU. O teste float32 excedeu a memória disponível no ambiente local; a configuração de precisão e o modelo escolhidos no aplicativo não foram alterados. A medição acima usou o áudio original completo. A preservação de finais enfraquecidos no stem foi verificada separadamente por regressão automatizada. Os arquivos privados e a letra de referência não foram incluídos no repositório.

Os testes de regressão cobrem finais ausentes, verso inteiro omitido, refrões distintos, pausa longa, guia incompleta, stem atenuado, ordem das palavras, preservação de revisões e cancelamento. Há também testes do fluxo SRT que falham se a conferência acústica for chamada em transcrição nova, salva ou revisada.

No teste de canto real com anotações independentes de início, foram recuperadas 43 palavras, incluindo um verso inteiro e as quatro palavras omitidas do refrão final. A pausa de sete segundos foi preservada, com erro mediano de início de 0,1141 s nesse teste. A gravação de validação é **Feel (Stripped)**, de Cortez, distribuída sob CC BY pelo conjunto JamendoLyrics usado no teste existente.

A suíte local concluiu 699 testes; apenas o teste de fonte CJK foi ignorado porque a fonte não estava instalada no ambiente local. O fluxo SRT também foi verificado em navegador, incluindo configurações responsivas e revisão por origem. A publicação da imagem exige novamente a suíte da aplicação e os testes reais de CPU e canto no contêiner.

## Atualização e limites

Atualize apenas a imagem do servidor para `ghcr.io/sal0-apps/sal0-karaoke:12.7.8`, preservando `/data`, recursos e configurações, e reabra o aplicativo. Use **Refazer** para aplicar a correção a um resultado existente. Arquivos exportados não mudam automaticamente. Os modelos escolhidos, os arquivos de origem, o reconhecimento bruto, as revisões manuais, os downloads e os estilos da 12.7.7 são preservados. A revisão manual continua tendo prioridade sobre a análise automática.

Uma guia precisa conter as repetições cantadas e corresponder à versão da gravação. Voz sobreposta, canto fraco e trechos diferentes da referência ainda podem exigir revisão; a alteração não garante acerto integral em qualquer música. O resumo mantém visíveis as partes que ainda dependem do reconhecimento.

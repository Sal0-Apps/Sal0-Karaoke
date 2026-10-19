# Correção das legendas — 12.7.2

A 12.7.1 introduziu uma regressão: a interseção de intervalos de cada palavra com o detector de voz fragmentou a exibição em flashes, e a política de guia estrita descartou trechos legítimos quando a correspondência era incerta. A 12.7.2 usa novamente a apresentação da 12.7 como base.

## Versos contínuos

O verso permanece legível entre palavras e respirações curtas. As animações respeitam o início medido de cada palavra, com os mesmos estilos, cores, brilho, prévia e controles de instrumental existentes. A detecção auxiliar de voz não funciona como uma máscara que liga e desliga a letra a cada palavra. Intervalos instrumentais continuam seguindo os controles existentes.

## Guia para conferência

A guia ajuda a propor correções no contexto. Propostas lexicais mantêm a quantidade de palavras da frase e precisam explicar melhor o áudio completo da janela de alinhamento, comparadas com o reconhecimento original. Uma proposta incerta, uma falha de modelo ou um empate não apagam a frase: ela permanece disponível para revisão. Repetições só são removidas quando a hipótese reduzida explica melhor o canto; a quantidade de refrões impressos não decide quantas vezes a gravação canta.

A transcrição bruta, os tempos do áudio e as revisões manuais são preservados. Não há preenchimento de versos somente a partir da guia. A revisão confirmada pelo usuário não é submetida a outra filtragem nem carrega novamente os modelos ao renderizar. O Whisper selecionado e os componentes locais existentes são mantidos.

Essa conferência não garante reconhecimento perfeito em toda gravação. A revisão permite conferir diferenças que permanecerem. Os testes de continuidade, texto e canto real não substituem a avaliação das músicas afetadas pelo problema relatado.

## Aplicar a correção

Use `ghcr.io/sal0-apps/sal0-karaoke:12.7.2` ou atualize `latest`, preservando o volume `/data`, portas e recursos atuais. Os clientes Android e Windows existentes continuam compatíveis. Ao refazer uma tarefa, a versão de qualidade do cache invalida o alinhamento automático da 12.7.1 e a versão de apresentação invalida ASS/vídeo. Entradas e revisões manuais não são apagadas.

Vídeos já renderizados não mudam sozinhos: use **Refazer** após atualizar e recriar o container. A imagem `12.7` continua disponível para retorno. Nenhum serviço pago ou integração de faturamento foi acrescentado.

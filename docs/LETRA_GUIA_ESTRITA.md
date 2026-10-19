# Letra-guia estrita — 12.7.1

Quando há uma letra-guia válida, a saída automática utiliza somente palavras dela confirmadas na gravação. A guia pode ser colada, editada ou encontrada pela busca existente. Texto manual continua tendo prioridade na escolha da guia da mídia.

## Conferência pela voz

O reconhecimento procura as palavras no áudio. Palavras e frases parecidas são comparadas com o contexto da guia: uma correspondência confirmada pode receber o texto correto dela, conservando os tempos medidos. Uma frase ausente, uma repetição sem apoio na voz ou uma guia de outra gravação não devem completar a legenda por adivinhação. Quando a confirmação é insuficiente, o trecho fica sem texto.

Os horários e offsets de um arquivo LRC não reposicionam o canto. As quebras da guia organizam os versos confirmados, sem mover uma palavra para o verso anterior. A gravação mantém sua duração, introdução e encerramento; não há deslocamento global dos tempos para tentar encaixar o texto.

Sem letra-guia, o reconhecimento normal continua disponível. O modelo Whisper selecionado e os componentes locais de alinhamento existentes são mantidos. Esta atualização não acrescenta modelo, serviço pago ou integração de cobrança.

## Silêncios, prévia e instrumental

Com guia, as letras aparecem apenas nas janelas confirmadas do canto. Elas deixam de permanecer na introdução, no encerramento, entre versos e em pausas dentro de um mesmo verso. A proteção continua funcionando com **Instrumental** desligado.

A prévia da próxima linha pode aparecer durante o canto atual, conforme a opção existente, mas desaparece junto com as letras nas pausas. **Manter a primeira linha visível** não antecipa o texto durante uma introdução sem voz. O aviso instrumental, sua barra e a contagem continuam disponíveis quando ativados.

Pequenas interrupções de até 80 ms podem ser unidas para evitar que respiros e variações breves de energia façam o texto piscar. As janelas não são ampliadas para antes ou depois das palavras medidas. Evidências isoladas menores que 40 ms não exibem um verso inteiro.

## Revisar e refazer

1. Confira se a guia corresponde à versão cantada, incluindo refrões e repetições.
2. Ative a revisão se quiser conferir o resultado antes de renderizar. Um trecho omitido pode indicar voz difícil de distinguir ou falta de correspondência na guia.
3. Use os controles existentes para revisar texto e tempos. A interface, o visual e o fluxo permanecem os mesmos.
4. Para aplicar a atualização a um resultado antigo, refaça o item. O vídeo já renderizado não muda sozinho; arquivos permanentes e revisões salvas não são apagados pela atualização.

A política restringe o texto automático; ela não certifica reconhecimento infalível. Coros sobrepostos, separação com vazamentos e gravações difíceis podem causar omissões ou exigir revisão. Os testes de regressão e de renderização verificam o comportamento controlado, sem representar uma medição de erro para todo repertório.

Consulte também as [notas da atualização](ATUALIZACAO_12_7_1.md) e o [guia de instalação e atualização](../DEPLOYMENT.md).

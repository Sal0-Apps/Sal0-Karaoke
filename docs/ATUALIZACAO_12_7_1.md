# Atualização 12.7.1

Use `ghcr.io/sal0-apps/sal0-karaoke:12.7.1`, preservando o volume `/data`, as portas e os recursos atribuídos ao container. Os clientes Android e Windows existentes continuam compatíveis. A imagem `12.7` permanece disponível para retorno; o histórico da [atualização 12.7](ATUALIZACAO_12_7.md) foi preservado.

## Letra confirmada na gravação

Com guia válida, o texto automático fica limitado às palavras dela confirmadas na voz. A conferência contextual pode substituir uma palavra ou frase parecida pela forma correspondente da guia sem deslocar os tempos. Palavras ausentes, repetições sem confirmação e trechos incertos ficam sem texto. Horários de LRC não determinam os tempos da gravação.

Sem guia, o reconhecimento normal continua disponível. O Whisper escolhido e os componentes locais de alinhamento existentes são mantidos, assim como o editor, a divisão dos versos e as opções de apresentação. A correção não acrescenta modelo, serviço pago nem mecanismo de cobrança.

## Letras fora das pausas

As janelas de exibição respeitam palavras medidas e atividade vocal. Letras e prévias não permanecem na introdução, em pausas dentro do verso, entre versos ou no encerramento sem canto. Isso independe da opção de aviso instrumental. A prévia continua disponível durante o canto; o aviso, a barra e a contagem mantêm seus estilos da 12.7.

Não há extensão do verso até o próximo início, nem deslocamento ou corte do áudio. Pequenas interrupções de energia são tratadas para evitar piscadas, sem antecipar a entrada medida das palavras. Os detalhes e limites estão em [letra-guia estrita](LETRA_GUIA_ESTRITA.md).

## Atualização e validação

Pause a fila e aguarde o checkpoint antes de trocar a imagem quando houver tarefa em andamento. Faça backup do volume e siga o [procedimento de atualização](../DEPLOYMENT.md#atualizar-com-uma-tarefa-em-andamento). Resultados existentes não são reescritos; refazer um item aplica a política atual às etapas automáticas correspondentes.

A validação inclui guia estrita, evidência vocal, texto de saída e renderização real em FFmpeg/libass, com aviso instrumental e prévia ligados ou desligados. Os casos verificam introdução, instante anterior à voz, pausa interna, intervalo entre versos, encerramento e preservação dos dados de origem. Essas verificações não prometem reconhecer perfeitamente toda gravação.

As proteções de serviços e faturamento continuam descritas em [Google e YouTube](GOOGLE_E_YOUTUBE.md).

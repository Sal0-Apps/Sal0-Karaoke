# 12.7.7 — apresentação sobre a base 12.7.5

O relato de música incompleta foi esclarecido como consequência de uma queda de energia. Esta revisão volta à base de processamento da **12.7.5**, aprovada pelo usuário, e concentra as alterações na apresentação do karaokê. O reconhecimento, a letra-guia, os modelos, as fontes de áudio, os downloads e a fila permanecem como na 12.7.5.

## Troca de versos

O vídeo fornecido de Bonnie & Clyde, da YUQI, mostra a frase quase apagada em alguns frames de transição, por exemplo perto de 00:21,5. O fade de opacidade era aplicado novamente ao verso inteiro quando a prévia se tornava a linha ativa. Ele foi removido; a transição de cor das palavras continua obedecendo aos tempos existentes.

Os caracteres chineses do título de abertura apareciam como quadrados. O contêiner agora inclui Noto CJK, e a capa seleciona essa fonte para títulos com esses caracteres. Os demais títulos mantêm a fonte anterior.

## Opções do administrador

Em **Ajustes → Animação e instrumental**, estão disponíveis:

- **Animação das palavras:** varredura clássica, suave com acabamento luminoso, pulso luminoso, contorno colorido e preenchimento instantâneo. Os modos de linha/frase estática continuam estáticos.
- **Instrumental:** texto clássico, barra de progresso, três pontos de progresso ou contagem em destaque.
- **Texto do aviso:** até 40 caracteres, como Instrumental, Solo ou Prepare-se.
- **Tamanho do aviso:** de 60% a 150% do tamanho da letra, sem aumentar a prévia do próximo verso.
- **Contagem:** de 0 a 5 segundos. Use 0 para desativar os números e manter o aviso e a prévia.
- **Cor, brilho e pausa mínima:** controles existentes preservados.

Os indicadores acompanham a duração da pausa já identificada; não fazem nova análise musical e não alteram tempos, texto ou áudio. A configuração continua restrita ao administrador e é compartilhada entre contas. Arquivos antigos de configuração recebem os campos adicionais sem perder suas escolhas. Valores inválidos não substituem uma configuração salva.

## Validação

- Comparação dos dois vídeos fornecidos, incluindo frames das transições.
- Regressão renderizada com FFmpeg para a frase usada no exemplo, verificando sua legibilidade desde o primeiro frame.
- Renderização dos cinco efeitos, verificando diferenças visuais e ausência de destaque antes do canto.
- Quatro estilos de instrumental nas três posições, com fonte ampliada e verificação da separação entre aviso e prévia.
- Persistência dos novos campos, leitura de configuração antiga, contagem desligada e validação de entradas.
- Renderização da abertura com caracteres CJK e teste do editor em navegador, em tela de celular e desktop.
- Suíte completa de regras da aplicação, além das verificações de CPU e canto real exigidas antes da publicação da imagem.

## Atualização

Atualize apenas a imagem do servidor, preservando `/data`, portas e limites atuais, e reabra o aplicativo. As novas escolhas valem para as próximas renderizações. Use **Refazer** no resultado existente para aplicar o visual; não apague o cache nem as revisões manuais. Os clientes Android e Windows atuais continuam compatíveis.

O vídeo já exportado não é alterado automaticamente. Esta correção visual não constitui uma nova transcrição nem uma promessa de acerto para todas as letras.

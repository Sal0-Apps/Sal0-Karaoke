# Sal0 Karaoke 12.7.6 — duração completa do resultado

Foi reproduzido um caso em que o arquivo original tinha quatro segundos de áudio
e apenas um segundo de imagem. Com a capa de três segundos, a versão anterior
produzia sete segundos de áudio, mas só quatro de vídeo, e informava sucesso.
Agora o último quadro original é mantido até o fim do som. A extensão acontece
antes de desenhar a legenda, que continua avançando sobre esse fundo.

O renderizador cria um arquivo temporário e confere a duração das duas faixas
antes de substituir o resultado. O tempo esperado inclui os três segundos da
capa. A existência do arquivo ou o retorno zero do FFmpeg não bastam para
considerá-lo pronto. Uma falha mantém o resultado anterior e remove o temporário.
Checkpoints de renderização também são conferidos antes da reutilização.

O áudio convertido e as faixas de voz, instrumental e backing vocals são
comparados à duração da faixa de áudio original, com tolerância para arredondamento
de codecs. Arquivos parciais são refeitos; os arquivos automáticos que dependiam
deles são descartados. A origem, a letra guia e as revisões manuais permanecem.
Pares novos de stems são conferidos antes de serem movidos para o cache.

Em vídeos SRT, o fim da imagem original continua presente quando o áudio termina
antes. A saída de áudio recebe silêncio somente para cobrir esse trecho final;
o comando tem duração limitada e a saída também é conferida antes da substituição.

O downloader do YouTube aborta em fragmentos indisponíveis. A duração anunciada,
quando disponível, é comparada ao arquivo completo, tolerando metadados arredondados.
Uma transferência parcial é removida antes de tentar outro formato ou encerrar
com erro; a guia e o fundo da tarefa não são apagados.

## Testes

- FFmpeg real: vídeo original de um segundo com áudio de quatro, capa e legenda
  entre 2,5 e 3,8 segundos. A saída tem sete segundos nas duas faixas e a legenda
  aparece perto do fim, depois de a imagem original ter acabado.
- Um FFmpeg simulado que encerra com sucesso, mas entrega um MP4 realmente curto,
  não substitui o resultado anterior nem deixa um temporário aproveitável.
- O estágio real de preparação do pipeline reconstrói WAVs de um segundo para
  uma origem de quatro segundos e depois reaproveita os arquivos completos.
  A guia e a revisão manual permanecem; transcrição automática parcial é descartada.
- Stems de backing vocals com versão correta e duração errada são recalculados.
  Um par novo incompleto não recebe marcador de conclusão.
- Download parcial é rejeitado e repetido; quando todas as tentativas falham,
  a entrada parcial é removida e a guia permanece.
- Vídeo SRT com quatro segundos de imagem e um de som mantém as duas faixas
  até quatro segundos, sem cortar o fim da imagem.

Esta checagem verifica a duração das mídias; ela não comprova que todos os versos
foram reconhecidos. Uma origem já cortada, sem duração externa de referência,
não permite recuperar o trecho ausente. Para examinar outro tipo de incompletude,
é necessário comparar o resultado afetado com sua origem.

Atualize o servidor e use **Refazer** na música afetada para aplicar as verificações.
Os clientes Android e Windows atuais continuam compatíveis.

# 12.7.4 — alinhamento da letra completa

Uma guia correta ainda podia produzir frases incompletas: o prompt do Whisper
era limitado, e a correção posterior só substituía palavras já reconhecidas.
Além disso, MMS e Silero, preparados para fala, podiam classificar fonemas
cantados nos refrões como palavras sem apoio e removê-los.

Agora o modelo Whisper escolhido recebe a letra completa como alvo de
alinhamento, em janelas com contexto. As palavras reconhecidas localizam as
janelas; os tempos finais vêm do alinhamento com o áudio, sem interpolação de
palavras omitidas e sem usar horários externos de LRC. O pareamento por mínimo
de edições mantém refrões parcialmente reconhecidos em sua ordem correta.

O CTC pode refinar os tempos e fornecer marcações de caracteres dentro do verso
confirmado. Um fonema fraco ou uma região ausente do detector de fala conserva
o texto e o tempo medido pelo Whisper. A ausência de uma palavra na transcrição
inicial deixa de impedir sua recuperação.

Guias incompatíveis, versos sem confirmação ou repetições reconhecidas fora de
uma guia incompleta mantêm o caminho de reconhecimento. Com menos da metade da guia reconhecida como
âncoras, a recuperação direta pelo Whisper fica limitada a gravações de até 29 segundos.
Confirmação humana continua acima das análises automáticas.

Os caches automáticos são independentes da transcrição bruta. A política de
qualidade muda da versão 6 para 7, invalidando legendas e vídeos derivados ao
refazer uma música, preservando áudio e revisões manuais. O alinhamento completo
acrescenta trabalho em CPU; sua análise fica disponível para reutilização.

O endereço do large-v3-turbo da DeepDML foi corrigido para o checkpoint
`deepdml/faster-whisper-large-v3-turbo-ct2`, confirmado no catálogo do publicador.
O cache local existente continua prioritário.

O caso de CHVRCHES — Over foi examinado usando o original e o resultado fornecidos
pelo usuário, com a letra da descrição do canal oficial. Os arquivos e a letra
da música não são incorporados ao repositório nem à imagem. A reprodução local
verifica cobertura do texto, os refrões e a pausa anterior à ponte; ela não é
uma medida de precisão para outras músicas.

O ensaio público de canto em CPU continua usando Cortez — Feel (Stripped), CC BY,
do JamendoLyrics. Além do trecho anterior, agora remove um verso inteiro e
palavras de outras frases, repete canto real após sete segundos de silêncio e
verifica a recuperação do texto e seus tempos contra anotações independentes.

Atualize o servidor para `ghcr.io/sal0-apps/sal0-karaoke:12.7.4`, preservando o
volume `/data`, portas e recursos. Use **Refazer** para recalcular resultados
antigos. Os clientes Android e Windows atuais continuam compatíveis. A imagem
`12.7.3` permanece disponível para retorno.

Validação desta versão: 656 testes Python locais; o ensaio ampliado recuperou
43 palavras, incluindo um verso inteiro omitido e uma repetição após sete
segundos de silêncio, com erro mediano de início de 0,1141 s frente às anotações.
No original de Over, foram preservadas as 290 palavras e os 56 versos da guia.
Esses resultados descrevem os dois ensaios, sem promessa geral de precisão.

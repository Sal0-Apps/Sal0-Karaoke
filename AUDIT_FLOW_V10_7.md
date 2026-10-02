# Auditoria de funcionamento e interface — 10.7

Revisão do servidor e da interface em 2 de outubro de 2026, partindo da 10.6. A prioridade foi manter a letra sincronizada intacta e tornar os controles coerentes com o processamento. Android e configurador Windows não precisaram de alterações.

## Fluxo verificado

| Etapa | Verificação e resultado |
| --- | --- |
| Autenticação e contas | Sessão, isolamento de Biblioteca/cache/resultados e permissões de revisão. A mídia da revisão agora usa a mesma sessão do login; o encerramento da sessão limpa também a chave legada. |
| Seleção de origem | Arquivos, YouTube e Biblioteca nos modos Rápido, Detalhado e SRT. Opções inválidas são recusadas antes de criar arquivos de uma nova tarefa. |
| Envio em lote | Falha no segundo arquivo, acompanhamento dos aceitos e tentativa de novo apenas dos pendentes. O arquivo aceito anteriormente não se repete. Sucesso limpa a seleção de arquivos. |
| Fila | Limites, permissões, pausa, retomada, cancelamento e isolamento de tarefas. Gravação atômica de fila e pausa; erro de gravação remove a nova tarefa da memória. |
| Preparação de áudio | Conversão e separação com relógio completo. Karaokê permanece sem VAD; com vozes de apoio ativadas, Whisper recebe a voz principal isolada. O modo SRT mantém seu tratamento de fala. |
| Texto sincronizado | Texto, pontuação, espaços e intervalos do provedor continuam sendo a fonte principal. Palavras reconhecidas erradas não substituem nem recortam a letra. Salvar revisão sem alterações preserva o texto exato. |
| Animação e visual do vídeo | FFmpeg/libass real: varredura, palavra inteira e modos estáticos; pausas; fontes grandes; três posições; verso e prévia em regiões separadas; introdução sem duplicação. A proteção de layout agora cobre também legendas comuns. |
| Revisão | Texto em campos maiores, erros inline, validação de linhas vazias/tempos/ordem e áudio original com busca do início da linha selecionada. A prévia é explicitamente de texto/fundo; a animação final vem da renderização. |
| Plano de fundo | Vídeo original da tarefa tem prioridade sobre um fundo enviado que não será usado. A opção de cor sólida agora renderiza preto e sua prévia corresponde a esse resultado. |
| Cache e recuperação | Reaproveitamento de análise compatível, invalidação de renderizações antigas e revisão separada do Whisper bruto. A promoção copia antes de substituir, restaura a versão anterior se a troca falhar e recupera uma troca interrompida ao acessar os caminhos do usuário. |
| Resultados e serviços | Exportação de MP4/SRT, tradução, Biblioteca, capa, Telegram e regras de publicação YouTube cobertos pelos testes existentes. SRT continua inelegível para publicação automática de karaokê. |
| Interface | Navegador em 320, 360, 390, 768 e 1440 px, sem expansão horizontal. Cabeçalho menor no celular, Biblioteca sem quebra, teclado nas abas e revisão nos temas claro/escuro. Legenda sobre o fundo mantém contraste no tema claro. |

## Falhas corrigidas

- Uma linha vazia podia causar divisão por zero na revisão; tempos não finitos ou invertidos também não eram validados.
- Salvar uma letra sincronizada sem mudanças removia espaços das extremidades.
- Uma falha de lote mantinha arquivos já aceitos selecionados para reenviar.
- Legendas comuns ainda usavam espaços invisíveis para pausas e podiam sobrepor o verso à prévia central.
- Modos de palavra e frase não produziam o comportamento anunciado quando havia animação sincronizada.
- Primeiro verso persistente, contagem regressiva e prévia podiam desenhar o mesmo verso duas vezes.
- Fundo de cor sólida caía no caminho de paisagem aleatória.
- A revisão podia usar um fundo que não seria renderizado, uma chave de autenticação antiga ou texto escuro sobre vídeo preto no tema claro.
- Persistência de fila não era atômica; promoção de cache apagava a versão anterior antes de completar a cópia.
- Falha de acompanhamento do FFmpeg podia deixar o processo ou seu pipe aberto.
- Perfis antigos podiam exibir VAD ligado no karaokê; números inválidos no Modo Rápido podiam impedir a normalização.

## Validação

- **244 testes Python** no conjunto completo. Incluem testes reais de áudio/FFmpeg, renderização libass, pausas e cores, exportação, cache, recuperação e permissões.
- **Dois testes de navegador**: criação/revisão e administração YouTube. Exercitam os três formulários, falha parcial, repetição de envio, texto canônico, áudio autenticado com byte ranges, busca do verso, teclado e cinco larguras de tela. Capturas do editor nos dois temas fazem parte dos artefatos do workflow.
- A publicação Docker repete os testes na imagem e executa os smokes de **backing vocals e Whisper reais em CPU** antes de enviar a imagem e atualizar `latest`.

Os testes do navegador simulam respostas dos serviços e os testes dos provedores usam dados controlados. Esta auditoria não equivale a executar uma música completa do usuário, publicar um vídeo na sua conta nem medir desempenho no seu servidor.

## Melhorias futuras identificadas

- Levar o download inicial do YouTube para uma etapa da fila: atualmente ele ainda ocorre durante a preparação do envio. Isso permitiria cancelamento e acompanhamento mais uniformes em downloads longos.
- Medir tempo, memória e qualidade com um pequeno conjunto de músicas reais: voz suave, rap, duetos, backing vocals e gravações com introduções distintas.
- Exibir o resultado do alinhamento por palavra na revisão a partir do ASS já renderizado, mantendo o player atual para conferir o áudio. A prévia de texto atual não simula toda a animação final.

Precisão de reconhecimento e separação depende da gravação e dos modelos. A fonte sincronizada continua protegida contra essas diferenças, mas os tempos locais da animação podem precisar de ajuste em casos difíceis.

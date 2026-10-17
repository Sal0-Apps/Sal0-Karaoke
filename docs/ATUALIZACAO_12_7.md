# Atualização 12.7

Use `ghcr.io/sal0-apps/sal0-karaoke:12.7` preservando o volume `/data`, a porta e o orçamento de CPU. A imagem anterior `12.6.2` permanece disponível para retorno. Clientes Android e autorizador Windows existentes continuam compatíveis.

## Animação e instrumental

Em **Ajustes → Animação e instrumental**, o administrador define o estilo para todas as contas:

| Opção | Padrão | Alternativas |
| --- | --- | --- |
| Animação | Suave | Varredura clássica |
| Brilho no estilo suave | Ativado | Desativado |
| Instrumental | Texto e barra vetorial | Texto clássico |
| Cor do instrumental | Azul `#38BDF8` | Cor RGB |
| Pausa mínima | 2 segundos | 1,5 a 10 segundos |
| Contagem | Até 3 segundos | 1 a 5 segundos |

A contagem se adapta à duração disponível; no encerramento há apenas o aviso, sem contagem para um canto inexistente. Pausas são medidas entre palavras, inclusive dentro de um verso da guia. As divisões e o texto da guia permanecem no editor. O modo de palavra/sílaba e a cor da letra continuam nas escolhas existentes. Os novos ajustes não acrescentam atraso ou antecipação ao canto.

O arquivo persistente é `/data/output/karaoke_animation.json`. Ler e alterar a configuração exige administrador no backend. Ao refazer, os estilos novos invalidam as etapas de legenda/vídeo correspondentes; a transcrição original e as revisões humanas são preservadas. Vídeos já renderizados precisam ser refeitos para incorporar as correções.

O alinhamento confere o início contra a atividade vocal para evitar que vazamentos baixos da separação sustentem uma antecipação longa. Tempos de caracteres ficam limitados aos da palavra. Não há deslocamento global arbitrário nem corte da gravação. Resultados específicos ainda dependem da voz, da separação e da qualidade dos tempos reconhecidos; não foi medida taxa de erro no repertório real do servidor AMD.

## Publicação automática

Rápido e Avançado enviam a escolha explicitamente. Se o painel ainda não carregou, o servidor usa o padrão da conta quando há canal conectado e playlist atribuída. Desmarcar continua impedindo a publicação, inclusive depois de atualizar o painel. Contas sem playlist não recebem a playlist de outro usuário.

O envio fica persistido antes da geração da capa e da reconferência remota das playlists adicionais. O worker verifica novamente o canal e os destinos antes de publicar. Falhas de capa ficam no painel como a mesma tarefa retomável. Vídeos com identificador confirmado continuam protegidos contra reenvio duplicado. A correção não publica retroativamente todos os vídeos antigos sem uma solicitação.

As proteções de serviços e de faturamento Google continuam as mesmas: veja [Google e YouTube](GOOGLE_E_YOUTUBE.md). Não foi alterada a conta externa nem foram enviados vídeos ou mensagens reais nos testes.

## Verificação

Testes cobrem antecipação de vários segundos com vazamento instrumental, início das letras dentro da palavra, renderização real em FFmpeg, pausas internas/introdução/encerramento, permissões e persistência administrativas, escolha automática nos dois modos, preparação de capa, retomada e conclusão pelo worker. A interface foi conferida em desktop e celular. A publicação da imagem depende também da suíte completa no Docker e dos ensaios de inferência real de CPU do GitHub Actions.

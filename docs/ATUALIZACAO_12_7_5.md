# Sal0 Karaoke 12.7.5 — confirmação da primeira música

O caso relatado ocorre ao criar a primeira música após excluir a fila anterior.
Nos registros fornecidos, busca e metadados retornam HTTP 200, mas as consultas
de confirmação retornam 404. Esse trecho não mostra uma resposta ao envio de
criação nem um erro do yt-dlp. A ausência de uma linha de acesso não prova que o
pedido não chegou: ela normalmente aparece quando o servidor responde.

Pedidos sem arquivos agora usam `application/x-www-form-urlencoded`, aceito
pela mesma rota existente. Só uploads reais usam multipart. Arquivos vazios de
campos não selecionados não transformam links em uploads. Guia, opções, sessão e
identificador de confirmação continuam enviados; uma nova tentativa mantém o
identificador enquanto a página estiver aberta.

Uma nova origem também deixa de recuperar ou copiar o cache legado antes da
entrada na fila. Essa cópia podia esperar por uma promoção longa de arquivos,
inclusive remanescente de uma execução anterior. A tarefa recebe cache próprio,
é persistida e só então o worker inicia o download. **Refazer** continua usando
os arquivos da execução escolhida. Selecionar novamente um link como nova
origem faz um novo download, em vez de reaproveitar automaticamente o cache legado.

O aviso apresenta erros HTTP e respostas sem confirmação separadamente de
tempo esgotado e falhas de transporte. Em uma falha, as escolhas e o botão de
criação continuam disponíveis. O cabeçalho `x-submission-id` permite relacionar
a chegada do pedido, antes de interpretar o corpo, à preparação e à confirmação
da tarefa. Os registros não incluem token de sessão, letra nem URL da música.

## Validação

- Um teste de regressão reproduziu a espera pelo bloqueio do cache antes da
  alteração e passou após a correção, mantendo a confirmação disponível.
- Chromium envia os formulários reais a um servidor Uvicorn/FastAPI, sem
  interceptar a criação, em três cenários: fila vazia, fila recém-excluída e
  cache anterior bloqueado. Todos confirmam uma única tarefa, preservam a guia
  com refrão repetido e devolvem o mesmo trabalho ao repetir o pedido.
- Os testes da interface cobrem os três modos, uploads, falhas HTTP 502 com
  corpo HTML, perda de resposta, tentativas automáticas e manuais e preservação
  das escolhas.
- Um upload multipart malformado confirma que a chegada e o HTTP 400 ficam
  visíveis nos registros antes de o endpoint executar, sem registrar credenciais.

Esses testes verificam o envio e a aceitação do pedido; não comprovam um
download autenticado no servidor da instalação afetada. A fila vazia por si só
não explica a falha relatada. Se ela persistir, os novos registros distinguem
pedido ausente, leitura do formulário e preparação da tarefa, sem atribuir
automaticamente o problema a cookies ou ao YouTube.

## Atualização

Atualize a imagem do servidor para `ghcr.io/sal0-apps/sal0-karaoke:12.7.5`,
preservando o volume `/data`, as portas e os recursos da instalação. Reabra o
aplicativo para carregar a interface atualizada. Os clientes Android e Windows
atuais continuam compatíveis; a imagem `12.7.4` permanece disponível para retorno.

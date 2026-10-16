# YouTube, renovação e limites de cobrança

Proteções da versão 12.6.2, verificadas em 16/10/2026 sobre a base 12.6.1.

## Renovação e retomada

A autorização OAuth e a sessão de transferência do vídeo têm expirações independentes. Renovar a autorização não recupera uma URI de envio vencida. Quando o YouTube responde 404 ou 410 nessa sessão, o Sal0 reinicia a transferência uma vez, na mesma tarefa. Um `video_id` já confirmado é preservado: a publicação continua com capa, playlists e privacidade, sem enviar o arquivo novamente.

Depois de confirmar novamente o mesmo canal, tarefas bloqueadas por autorização e erros identificados de sessão expirada voltam à fila. Outros erros permanecem disponíveis para revisão. Uma resposta atrasada da autorização anterior não pode bloquear novamente a autorização recém-confirmada.

Quando o Google exige reconectar/renovar, o bot configurado dos administradores recebe uma orientação para abrir **Ajustes → YouTube → Publicação**. O aviso não inclui tokens e não é enviado aos bots de usuários comuns. A confirmação de entrega é persistida para não repetir o mesmo aviso a cada consulta ou reinicialização. Falhas de entrega podem ser tentadas novamente na próxima detecção. Uma nova expiração após renovação permite um novo aviso. É necessário ter Telegram administrativo configurado e funcionando; o aviso é disparado ao detectar o problema numa consulta ou tentativa de envio.

## O que foi verificado e bloqueado no aplicativo

- As chamadas Google encontradas são OAuth, YouTube Data API, downloads do YouTube e Google Fonts. Não foi encontrado uso de Google Cloud Speech, Translate, Gemini, faturamento ou compra de créditos.
- O cliente autenticado de publicação aceita somente caminhos da YouTube Data API no domínio exato `www.googleapis.com`. Caminhos de outros serviços, desvios por `..`, codificações de caminho e redirecionamentos são bloqueados antes de enviar a credencial.
- Uma instância LibreTranslate não pode ser configurada com endereço `googleapis.com` ou seus subdomínios, inclusive variações codificadas ou com ponto final DNS. O endereço é revalidado antes de cada chamada e redirecionamentos não são seguidos. A tradução existente continua usando LibreTranslate; reconhecimento e alinhamento continuam locais.
- Ao receber `quotaExceeded` ou `dailyLimitExceeded`, o envio para e informa que é necessário aguardar. O aplicativo não habilita faturamento, compra cota, cria recursos Google Cloud nem usa serviços pagos como alternativa.

As unidades de custo da documentação de cota são unidades de requisições. Este código não possui acesso às configurações de faturamento da conta e não consegue comprovar que outros projetos, serviços, assinaturas ou recursos da sua conta não geram cobranças.

## Limite que depende da conta Google

Não é possível garantir por alteração de código que **nunca haverá nenhuma cobrança em toda a conta Google**. Para impedir consumo faturável futuro do projeto do aplicativo, confira no Google Cloud Console se ele está sem uma conta de faturamento vinculada. Use um projeto exclusivo para o Sal0; não ative faturamento ou APIs pagas nele. Desvincular faturamento pode interromper recursos Google Cloud desse projeto e não apaga valores já incorridos. Essa alteração não foi realizada nem validada na conta nesta sessão.

Fontes oficiais:

- [Sessões de upload retomáveis e expiração](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol)
- [Cotas da YouTube Data API](https://developers.google.com/youtube/data/determine_quota_cost)
- [Consultar e desativar faturamento de um projeto](https://docs.cloud.google.com/billing/docs/how-to/modify-project)

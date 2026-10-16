# Validação da revisão local

Base: 12.6.1, commit `1e387fffa2d1ed6e61e422a061c652c846edeb02`. Verificação em 16/10/2026, Windows, Python 3.12 e Chrome headless; execução de produção prevista no Docker Linux.

## Resultados

| Área | Resultado |
| --- | --- |
| Navegador real | 10/10 suítes aprovadas: interface, criação/revisão, letras, fila, cache, ajustes, Telegram, publicação e recuperação do YouTube |
| Python | 49 suítes executadas, 562 testes; 42 suítes integralmente aprovadas, com 458 testes |
| CPU/runner | Testes verificam quatro threads, cotas/afinidade, passagem de configuração ao subprocesso e cancelamento |
| Whisper | Testes simulam orçamento combinado de guia/vocabulário, VAD vazio/falhas, preservação do modelo, reutilização e tempos curtos |
| Cache/revisões | Inferência antiga é atualizada uma vez; revisão humana é preservada; mudanças explícitas de execução invalidam apenas resultados correspondentes |
| Alinhamento | 32 testes do alinhamento existente aprovados; equivalência numérica da atividade de áudio validada |
| Vídeo | Renderização real H.264 1280×720, capa silenciosa, áudio e legendas; 80 testes nos seis módulos de legendas/renderização aprovados |
| YouTube novo | 14 testes aprovados de sessão expirada, autorização renovada, concorrência, notificações, cota e bloqueio de outras APIs |
| Integração YouTube/tradução | 22 testes de recuperação, cinco de rotas e 13 do cliente LibreTranslate aprovados após as mudanças |
| Código | Compilação Python e `git diff --check` aprovados |

O teste novo do navegador verifica ausência de emojis nas telas, referências válidas aos SVGs, opções nativas sem marcação SVG, biblioteca de fundos vazia, preservação de seleção, zero mutações de DOM para status idêntico, uma requisição por poll e editor com 80 linhas em celular. Os testes antigos foram adaptados para o texto acompanhado de SVG; uma contagem de busca automática foi isolada por mídia para evitar dependência da velocidade do navegador.

## Limitações identificadas

As seguintes suítes não passaram integralmente neste Windows:

- `test_v8_queue_and_admin_results.py`: Bash indisponível para testar expressão de versão do script de release.
- `test_telegram_delivery.py`, `test_youtube_device_auth.py`, `test_youtube_publisher.py`: comparação de permissões POSIX 0600 com modo Windows 0666.
- `test_youtube_desktop_oauth.py`: permissões POSIX e restrições de sockets de retorno OAuth no ambiente Windows.
- `test_youtube_download_access.py`: permissões POSIX e execução do mecanismo de download no ambiente restrito.
- `test_youtube_engine_recovery.py`: troca/remoção de diretórios ativos no Windows, também reproduzida na base HEAD.

Foram executadas comparações com os fontes originais em uma pasta de baseline; logs registram as falhas de plataforma. Não foram enfraquecidas verificações de permissões de produção para fazer os testes passarem. Os caminhos ASS/SRT dos testes e renderizadores passaram a usar o escape existente para permitir renderização real no Windows.

Não foram medidos tempo por música, consumo de RAM completo ou taxa de erro com os modelos reais no A10. Não houve acesso ao servidor de produção, OAuth real, canal YouTube, bot Telegram ou faturamento Google. As recuperações de publicação e notificações foram testadas com respostas simuladas; não houve publicação nem mensagem real.

Logs detalhados e screenshots locais ficam em `review-artifacts/`, excluídos do Git e do pacote de fontes. Esse diretório também contém `python-final-summary.json`, `browser-final-summary.json` e relatórios de baseline.

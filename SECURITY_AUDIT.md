# Auditoria de segurança

> Revisão técnica realizada em 31 de agosto de 2026 sobre a versão 9.0.7. Este documento é um retrato datado, não uma certificação, garantia de ausência de vulnerabilidades ou substituto para testes de intrusão.

## Escopo e método

A revisão abrangeu a árvore de trabalho, os 21 commits alcançáveis do repositório, dependências Python declaradas, código Python do servidor, arquivos de build, cliente Android, workflows, documentação e mecanismos locais de publicação.

Foram executadas:

- busca por padrões de tokens do GitHub, tokens de bots do Telegram, chaves AWS, chaves privadas, arquivos `.env`, keystores e nomes usuais de credenciais na árvore atual e no histórico Git;
- inspeção manual dos pontos de autenticação, downloads externos, persistência, Docker e publicação;
- análise estática do diretório `app` com Bandit;
- resolução e consulta de vulnerabilidades conhecidas das dependências de `app/requirements.txt` com `pip-audit`;
- conferência manual das URLs, licenças e serviços externos citados na distribuição.

Ferramentas automáticas produzem falsos positivos e falsos negativos. Arquivos removidos de referências não alcançáveis, artefatos externos, segredos ofuscados e dados existentes apenas em instalações de usuários não podem ser excluídos por esta revisão.

## Resultado sobre segredos

Não foi encontrado segredo de alta confiança nos 21 commits alcançáveis nem na árvore atual. O histórico usa apenas o endereço público `sal0-apps@users.noreply.github.com`. Também não foram encontrados `.env` real, chave privada, keystore, token do Telegram ou PAT do GitHub rastreados.

O arquivo `.env.example` presente no histórico continha somente o marcador `YOUR_GITHUB_TOKEN_HERE`, sem credencial funcional. Ele foi removido da versão atual porque orientava um fluxo de publicação baseado em token salvo em arquivo. Não há justificativa técnica para reescrever o histórico apenas por esse marcador inofensivo.

Como medida preventiva, os arquivos `.gitignore` e `.dockerignore` passaram a excluir formatos adicionais de credenciais, chaves e keystores. O auxiliar `deploy.sh` deixou de ler tokens de arquivos, inserir credenciais em URLs, adicionar todos os arquivos automaticamente ou reescrever branch e tags com `--force`.

Qualquer token que tenha sido enviado em conversa, terminal, log ou outro sistema fora do Git deve ser considerado separadamente e revogado no provedor; a ausência dele no repositório não prova que permaneceu confidencial.

## Vulnerabilidades conhecidas nas dependências

O `pip-audit` reportou 26 vulnerabilidades conhecidas distribuídas entre cinco pacotes na resolução possível em 31 de agosto de 2026:

| Pacote resolvido | Situação observada | Tratamento recomendado |
| --- | --- | --- |
| `python-multipart 0.0.9` | múltiplos problemas de negação de serviço e análise de multipart; uma condição adicional depende de opções não padrão de upload | atualizar e testar uploads, fila e autenticação |
| `Jinja2 3.1.4` | advisories corrigidos em versões posteriores, sobretudo quando um atacante controla templates | atualizar; o uso atual de templates estáticos reduz, mas não elimina, a necessidade |
| `requests 2.32.3` | problemas corrigidos em versões posteriores, incluindo exposição de credenciais de `.netrc` em determinadas condições | atualizar e testar integrações HTTP |
| `transformers 4.57.6` | advisories ligados a carregamento de modelos e checkpoints; algumas correções exigem versões incompatíveis com o limite atual `<5` | revisar a política de modelos e planejar migração testada |
| `starlette 0.37.2` | dependência transitiva do FastAPI com advisories de multipart, host e caminho em cenários específicos | atualizar FastAPI/Starlette em conjunto e executar regressão completa |

`torch 2.6.0+cpu` e `torchaudio 2.6.0+cpu` vieram do índice próprio do PyTorch e não puderam ser avaliados pelo banco PyPI usado nessa execução. Imagem base Debian, pacotes APT, Deno, FFmpeg, modelos, APK e dependências Gradle também exigem scanners próprios; portanto, o número acima não representa o total possível da distribuição.

As dependências não foram alteradas nesta revisão para evitar mudança funcional sem uma rodada dedicada de compatibilidade. A versão 9.0.7 não deve ser descrita como livre de vulnerabilidades conhecidas.

## Análise estática

O Bandit registrou 44 achados de severidade baixa, nenhum de severidade alta e um de severidade média. O achado médio está em `app/download_models.py`: o build usa `urllib.request.urlretrieve` para baixar imagens por URLs HTTPS fixas sem verificação de hash. Embora a entrada não seja controlada pelo usuário, a integridade do artefato externo não é comprovada.

Também foram observados downloads sem revisão imutável ou checksum para Deno, `yt-dlp` e modelos. Essa configuração reduz a reprodutibilidade e amplia o risco de cadeia de suprimentos. Uma futura distribuição deve fixar versões, revisões e hashes, gerar SBOM e verificar a imagem final.

## Superfície de exposição

- O parâmetro de consulta `?token=` é aceito para compatibilidade com downloads e previews. Esse token pode aparecer em histórico, logs e cabeçalhos de referência; prefira cabeçalhos de autenticação e proteja os logs.
- As sessões são tokens persistidos em texto claro em `/data/sessions.json`, têm validade de até 30 dias e também são armazenadas no `localStorage` do navegador. Uma cópia do volume, um script injetado na origem ou um log com a URL pode permitir reutilização da sessão.
- Links públicos enviados pelo Telegram usam tokens aleatórios de 256 bits, mas os registros atuais não expiram automaticamente. O acesso termina apenas quando o registro ou o arquivo é removido; trate cada link como credencial compartilhável.
- A criação do primeiro administrador é intencionalmente aberta enquanto `users.json` não contém contas. A instalação deve ser inicializada em rede restrita para impedir que outra pessoa conclua o primeiro cadastro.
- Senhas novas usam PBKDF2-HMAC-SHA-256 com salt aleatório e 100.000 iterações; hashes SHA-256 legados são migrados após login válido. O custo e o algoritmo devem ser revistos periodicamente, e `/data/users.json` continua sendo material sensível.
- O servidor manipula uploads grandes e executa ferramentas multimídia. Limites de requisição, armazenamento, CPU, RAM e tempo devem ser impostos no proxy e no host.
- O Docker não deve expor diretamente a aplicação à Internet sem HTTPS, autenticação adicional, atualização e isolamento de rede.
- O volume `/data` contém contas, sessões, tokens do Telegram, mídias e logs. Ele requer permissões restritas, backup protegido e política de retenção.
- Modelos, imagens e executáveis baixados durante build ou execução devem ser tratados como código e artefatos de terceiros.
- O workflow usa Actions identificadas por tags de versão, não por hashes imutáveis. Embora sejam projetos amplamente utilizados, a publicação possui risco adicional de cadeia de suprimentos até que cada Action seja fixada por SHA e revisada.

## Prioridades antes de nova distribuição

1. Atualizar e testar `python-multipart`, FastAPI/Starlette, Jinja2 e Requests.
2. Definir uma migração segura para Transformers sem carregar checkpoints não confiáveis.
3. Adicionar expiração e revogação aos links públicos e reduzir o uso de tokens de sessão em URLs.
4. Auditar a imagem final com scanner de sistema operacional e gerar SBOM.
5. Fixar versões, revisões e hashes de Actions, Deno, `yt-dlp`, modelos e imagens.
6. Remover ou substituir os quatro fundos cujas páginas e licenças não puderam ser confirmadas.
7. Confirmar a licença do identificador exato `deepdml/faster-whisper-large-v3-turbo` ou substituí-lo por um modelo público com licença registrada.
8. Capturar `ffmpeg -version`, manifesto Debian e fontes correspondentes da imagem efetivamente distribuída.
9. Habilitar o canal privado de reporte descrito em [SECURITY.md](SECURITY.md).

## Conclusão

O repositório-fonte pode permanecer público após a remoção das orientações inseguras de publicação e a inclusão destes avisos, pois não foi localizado material confidencial de alta confiança no histórico alcançável. Isso não torna a aplicação adequada para exposição pública sem controles nem resolve as vulnerabilidades de dependências e as pendências de licenciamento da distribuição binária.

Consulte também [LEGAL.md](LEGAL.md), [PRIVACY.md](PRIVACY.md) e [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

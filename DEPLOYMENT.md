# Instalação e operação

Este guia descreve a instalação Docker e os cuidados de operação do Sal0 Karaokê. O [manual completo](MANUAL.md) explica a utilização da interface.

O Sal0 Karaokê é destinado a uma instalação pessoal, acessada pela rede local ou por VPN, como ZeroTier. O repositório aberto disponibiliza o código e os pacotes; o projeto não opera um serviço público de processamento nem coleta centralmente as mídias das instalações. Não é necessário expor a porta do app à internet. O processamento principal é local, mas as integrações escolhidas podem se comunicar com serviços externos.

Para acesso remoto, conecte primeiro a VPN e abra o endereço privado do servidor. Não encaminhe a porta 7885 no roteador para a internet. HTTP pode ser usado dentro dessa rede restrita; a VPN protege o trecho do túnel, não qualquer rede local insegura nem um aparelho comprometido. HTTPS continua opcional dentro da instalação e recomendado quando viável.

## Requisitos e capacidade

- Docker Engine e Docker Compose v2.
- CPU compatível com a arquitetura da imagem publicada.
- Acesso à internet para baixar imagem, dependências e modelos quando necessário.
- Disco suficiente para originais, fundos, modelos, resultados, backups e temporários.
- RAM adequada ao modelo de transcrição e à separação Demucs.

A distribuição utiliza PyTorch para CPU e não exige GPU. Não existe uma duração universal de processamento nem um requisito único de RAM: modelos e mídias maiores aumentam o consumo. Reserve espaço adicional para arquivos temporários, inclusive durante compactação para o Telegram.

O Dockerfile contém seleção de Deno para amd64/arm64, mas o workflow padrão não publica um manifesto multi-arquitetura. Verifique a arquitetura da imagem efetivamente disponível antes de usar em ARM.

## Instalação inicial

Crie uma pasta própria para a instalação e salve nela o arquivo `compose.yaml`:

```yaml
services:
  karaoke-app:
    image: ghcr.io/sal0-apps/sal0-karaoke:12.7.2
    container_name: karaoke-app
    ports:
      - "7885:7860"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

No mesmo diretório:

```bash
mkdir -p data
docker compose pull
docker compose up -d
docker compose ps
```

Abra `http://localhost:7885` no host. Em outro dispositivo, use o IP/nome desse host e a porta 7885. A porta interna é 7860; o exemplo publica 7885. Se mudar o mapeamento, atualize os endereços usados pelos clientes.

Crie o administrador em rede restrita antes de permitir acesso de outras pessoas. A primeira configuração é aberta enquanto não há contas.

Somente `/data` deve receber o volume persistente. Não monte um diretório vazio sobre `/app`, pois isso oculta o código e a interface da imagem.

## Diretórios persistentes

| Caminho no container | Uso |
| --- | --- |
| `/data/library/videos/` | Originais da Biblioteca principal |
| `/data/library/photos/` | Imagens e vídeos de fundo |
| `/data/library/history/` | Resultados finais |
| `/data/output/models/whisper/` | Modelos de reconhecimento baixados |
| `/data/output/profiles.json` | Perfis da instalação principal |
| `/data/output/telegram.json` | Configuração principal do Telegram |
| `/data/output/external_url.json` | Endereço externo usado pelos links |
| `/data/output/state.json` | Estado do processamento |
| `/data/output/app_diagnostic.log` | Diagnóstico |
| `/data/output/queue_jobs/` | Entradas isoladas e checkpoints das tarefas |
| `/data/output/processing_queue.json` | Fila persistida |
| `/data/output/` | Demais configurações, controles e links públicos |
| `/data/cache/` | Cache legado do perfil, migrado conforme a próxima fila |
| `/data/user_data/` | Bibliotecas e configurações isoladas das contas comuns |
| `/data/users.json` e `/data/sessions.json` | Contas e sessões |

O backup deve incluir o volume inteiro. Copiar apenas resultados não preserva contas, fila, configurações ou checkpoints. Não adicione `data`, backups, logs, chaves Android ou credenciais ao Git.

## Estabilidade das legendas na 12.7.2

Atualize o servidor para `ghcr.io/sal0-apps/sal0-karaoke:12.7.2`, preservando o volume `/data`, portas e recursos atribuídos ao container. Os clientes Android e Windows existentes continuam compatíveis. A imagem `12.7` permanece como opção de retorno com o mesmo volume.

Esta versão restaura a apresentação da 12.7 e retira o filtro estrito da 12.7.1. Versos ficam contínuos através de pausas curtas entre palavras; a guia confere o reconhecimento com substituições apoiadas no áudio. Diferenças incertas ficam para revisão. Ao refazer um item, o cache automático da 12.7.1 é recalculado e a legenda/vídeo são reconstruídos, preservando áudio bruto e revisões manuais. Consulte [notas da 12.7.2](docs/ATUALIZACAO_12_7_2.md).

## Mensagens do Telegram na 12.2

Atualize apenas a imagem do servidor, mantendo os volumes e o APK existente. O token e o Chat ID salvos continuam disponíveis. Em **Ajustes → Meu bot do Telegram**, use **Verificar conexão** e **Enviar mensagem de teste** para confirmar o destino sem processar um vídeo. Falhas mostram a ação necessária no próprio painel; se houver erro de rede, confira o acesso do contêiner a `api.telegram.org`, internet e DNS do servidor. Nenhuma porta de entrada ou webhook adicional é necessário para enviar as mensagens.

Publicações confirmadas no YouTube acrescentam **Assistir no YouTube** à mensagem do resultado no Telegram. O vínculo entre vídeo e mensagem fica em `/data/output/telegram-results/`, no volume persistente. Todos os painéis de Ajustes começam recolhidos; abra o painel desejado antes de usar os controles.

## Reconexões do YouTube na 12.2

Não há mudança nos aplicativos Android ou Windows. O volume `/data` conserva credenciais, playlists e fila. Após atualizar o servidor, abra **Ajustes → Canal e publicação no YouTube** no celular, pela conexão local ou externa do app. Cadastre uma vez uma credencial Google do tipo **TVs e dispositivos com entrada limitada** no painel; nas próximas expirações use **Reconectar canal pelo celular** e aprove o código no Google. Não exige variáveis OAuth nem portas adicionais. O [manual](MANUAL.md#conectar-ou-reconectar-o-canal-pelo-celular) inclui os passos e a limitação de sete dias de projetos Google em Teste.

Em **Downloads do YouTube**, teste links, atualize o mecanismo e renove a sessão por cookies.txt, inclusive pelo Firefox Android. A renovação do canal não autentica downloads; remover a sessão de downloads não desconecta o canal.

A 12.2 mantém a correção do erro `Directory not empty` durante a atualização do mecanismo. Atualize a imagem do servidor para esta versão; depois use **Atualizar mecanismo** e **Testar link** no painel. Pastas residuais de pacotes não exigem exclusão manual. A conexão já aprovada com o canal e a sessão de downloads são preservadas.

## Atualizar com uma tarefa em andamento

1. Entre como administrador e abra **Criar**.
2. Use **Pausar ao concluir etapa** junto da fila.
3. Aguarde a confirmação de que o checkpoint foi salvo e o trabalho está pausado. A etapa em execução continua até terminar.
4. Faça um backup consistente do volume.
5. Altere a tag da imagem para a versão desejada no Compose, ou mantenha `latest` se quiser acompanhar as publicações.
6. Execute no diretório da instalação:

```bash
docker compose pull
docker compose up -d --force-recreate
docker compose ps
```

7. Confirme que o servidor abre e que o volume correto está montado.
8. Volte à interface e toque em **Retomar fila**.

Se não houver trabalho, basta fazer backup e atualizar. O comando `restart` sozinho não baixa uma nova imagem.

A pausa salva o avanço entre etapas; não salva cada instante dentro de Demucs ou Whisper. Encerrar o container antes da confirmação pode exigir repetir a etapa em andamento. Preserve a configuração e os arquivos da tarefa para reutilizar checkpoints.

## Backup e restauração

Para obter uma cópia consistente:

1. Pause a fila e aguarde a confirmação.
2. Pare o serviço com `docker compose stop`.
3. Copie a pasta do host montada em `/data` para um destino protegido, usando sua ferramenta de backup.
4. Guarde também o Compose e a identificação da imagem usada.
5. Inicie novamente com `docker compose up -d` e retome pela interface.

Para restaurar, pare a instalação de destino, recupere o volume completo, confira permissões e o mapeamento do Compose e inicie com uma imagem compatível. Preserve o backup original até validar contas, Biblioteca e fila.

Backups contêm sessões e tokens. Controle acesso e retenção. Restaurar uma cópia antiga pode recuperar credenciais e links que já tinham sido revogados na instalação mais nova.

Evite limpar `queue_jobs`, cache ou estado durante tarefas ativas ou pausadas. Excluir volumes, recriar a instalação sem o mesmo volume ou usar comandos de remoção de volumes pode causar perda de dados.

## Rede e Android

O aplicativo Android pede nome do Wi-Fi, endereço local e endereço externo. Exemplo de porta com este Compose: `http://192.168.1.50:7885`. O endereço é ilustrativo; use o host real da sua rede.

Para uma instalação apenas local, informe o mesmo endereço nos dois campos do APK. Ele não funcionará fora dessa rede sem VPN ou outra rota que alcance o servidor.

Para acesso remoto:

- configure HTTPS com certificado válido em um proxy reverso;
- prefira acesso restrito por VPN/rede confiável;
- limite a exposição da porta e o acesso ao host;
- ajuste limites de upload e timeout do proxy conforme o uso;
- proteja logs, backups e o volume;
- configure a URL externa do servidor para que os links enviados ao Telegram usem o endereço correto.

Informar uma URL no APK ou nos Ajustes não configura roteador, firewall, DNS, certificado ou túnel. O endereço externo de uma integração e os endereços nativos do APK são configurações distintas.

## Modelos e mecanismos externos

O build tenta preparar modelos e fundos. Falhas externas podem deixar modelos indisponíveis até a instalação posterior. Consulte **Ajustes → Modelos de reconhecimento** como administrador.

A atualização de `yt-dlp` pela interface é armazenada em `/data/output/yt_dlp_runtime`. Ela pode sobreviver à troca da imagem e não equivale à atualização de todas as dependências. Teste os recursos utilizados após alterações.

Dependências, licenças e URLs externas devem ser verificadas antes de redistribuir uma imagem própria. Consulte [SECURITY_AUDIT.md](SECURITY_AUDIT.md), [LEGAL.md](LEGAL.md) e [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Diagnóstico

Comandos úteis, executados no diretório do Compose:

```bash
docker compose ps
docker compose logs --tail=200
docker stats karaoke-app --no-stream
docker compose images
```

A interface também oferece **Ajustes → Logs atuais** ao administrador. Logs podem incluir detalhes de mídias e requisições; revise antes de compartilhar.

## Publicação pelo mantenedor

O workflow configurado em `.github/workflows/docker-publish.yml` é acionado por tags `v*` ou execução manual. Ele testa o servidor, publica a imagem no GHCR e, em uma tag, compila o APK e cria a Release com o arquivo.

Antes de publicar:

1. Revise as alterações e o inventário de arquivos.
2. Execute os testes aplicáveis.
3. Atualize de forma consistente a versão do Docker, Compose, APK, diagnóstico e documentação.
4. Verifique segredos na árvore, no histórico e nos artefatos.
5. Faça o commit explícito dos arquivos revisados.
6. Use a autenticação do Git por gerenciador de credenciais ou SSH.
7. Crie uma tag nova e acompanhe o workflow até a conclusão.

O auxiliar `deploy.sh` exige alterações rastreadas já commitadas, envia `main` e cria uma tag nova. Ele não faz o commit por você e não substitui uma revisão dos arquivos não rastreados. Não use tokens em URLs nem salve credenciais no repositório.

Para conservar a identidade de atualização do Android, proteja uma chave de assinatura própria fora do Git e use-a em todas as versões. Sem configuração de assinatura de lançamento, o projeto usa uma chave de depuração; builds independentes podem ter assinaturas diferentes e não atualizar um APK instalado. Consulte o [guia Android](android/README.md).

## Cache da fila na 12.2

Cada execução mantém seus arquivos em `/data/output/queue_jobs/<id>/cache/`, com índice persistente da fila. Não remova essas pastas enquanto quiser revisar os itens. Resultados concluídos, falhos, cancelados e removidos continuam disponíveis até a aceitação de uma nova origem após esgotar a fila do perfil. Reexecuções permanecem na mesma fila; resultados da Biblioteca e modelos continuam preservados. A mudança aplica-se às tarefas ainda disponíveis na atualização e às novas; arquivos que a versão anterior já descartou não são recuperáveis.

Atualize apenas a imagem do servidor para `ghcr.io/sal0-apps/sal0-karaoke:12.7.2` ou `latest`. Os aplicativos Android e Windows existentes continuam compatíveis. Publicações substituídas no YouTube recebem outro link; o anterior só é removido após confirmar o novo vídeo, capa, playlists e privacidade. Playlists adicionais começam desmarcadas em novas criações, com a playlist do perfil mantida.

### Ícone no ZimaOS / CasaOS

Use o mesmo endereço em `services.karaoke-app.labels.icon` e em `x-casaos.icon`:

```
https://raw.githubusercontent.com/Sal0-Apps/Sal0-Karaoke/main/app/templates/app-icon-v8.png?v=12.5.1
```

O endereço renovado evita o reaproveitamento da imagem antiga. Atualize os dois campos no Compose instalado e salve a configuração do aplicativo no ZimaOS; baixar apenas a nova imagem Docker não reescreve os metadados do painel. O ícone web também vem do arquivo `app-icon-v8.png`. O endpoint legado `/favicon.png` serve esse mesmo arquivo para compatibilidade, sem manter uma segunda imagem.

### Inclusão por link do YouTube

A confirmação de `/api/process` grava a tarefa na fila sem aguardar a transferência do YouTube. O download só começa quando o worker alcança o item; ele mostra andamento e aceita cancelamento. Cada inclusão da interface leva um identificador: depois de uma falha de conexão, o cliente consulta a confirmação e pode repetir a requisição com o mesmo identificador sem duplicar a tarefa da fila atual. Erros da transferência ficam no item, com a origem e as escolhas preservadas para refazer. O salvamento opcional da origem na Biblioteca continua funcionando depois do download.

### Sincronização e retorno à versão anterior (12.6)

A etapa de alinhamento usa MMS CTC na CPU e consulta os vocais separados, sem mudar a fonte de reconhecimento escolhida para o Whisper nem remover trechos da linha do tempo. O modelo adicional tem aproximadamente 1,2 GB, é baixado uma vez em `/data/output/models/lyric_alignment` e liberado da RAM ao terminar. O primeiro uso exige acesso a `dl.fbaipublicfiles.com`. Progresso em MB e o estado do alinhador aparecem na tela. Falhas conservam os tempos anteriores e a limpeza de silêncio, com indicação de indisponibilidade; uma tentativa posterior pode repetir a etapa.

Transcrições brutas continuam nos arquivos originais. O resultado de qualidade fica em `aligned_lyrics.json` e o texto exibido em `display_segments.json`; rascunhos e revisões manuais têm prioridade. Idiomas/escritas sem normalização compatível mantêm os tempos do Whisper e a verificação de silêncio. O sistema usa limiares conservadores e não promete resolver todos os estilos de canto.

A branch `backup/pre-lyric-quality-12.5.1-2026-10-16` preserva o código anterior no commit `4cd19a4c19b3b9b03611a6d39ad0962b7ed8f300`. Para voltar ao servidor anterior, use `ghcr.io/sal0-apps/sal0-karaoke:12.5.1`, mantendo o mesmo volume, portas e limites. O volume de dados não deve ser removido. Para desativar somente a etapa de CTC na nova versão, existe `KARAOKE_ALIGNMENT=off`; a verificação de silêncio continua ativa. O uso dos pesos segue a licença própria descrita em `app/THIRD_PARTY_MODELS.md`.


### Divisão dos versos e repetição (12.6.1)

As quebras da guia só são aplicadas quando o trecho reconhecido confirma as bordas do verso; relógios de LRC não são usados para posicionar palavras. Trechos sem correspondência continuam com a divisão natural por frases. As marcações ficam no resultado automático exibido e no cache de alinhamento. O cache de qualidade anterior é recalculado sem repetir desnecessariamente o reconhecimento bruto; revisões manuais confirmadas continuam tendo prioridade.

Uma repetição textual adjacente é apenas uma hipótese de erro. Antes de suprimi-la, o alinhador compara a probabilidade CTC das duas sequências com todos os quadros do áudio do trecho. Repetições explicitamente presentes na guia e refrões realmente cantados são preservados. Essa proteção não substitui a revisão de gravações difíceis.

A versão anterior desta correção permanece em `ghcr.io/sal0-apps/sal0-karaoke:12.6` e no tag `v12.6` (commit `fd7e8bba17999ff76b10c8b916c285517b8bf3c6`). A 12.5.1 também continua disponível. Para retornar, use a imagem versionada mantendo o mesmo volume de dados.

### CPU, interface e retomada do YouTube (12.6.2)

A 12.6.2 mantém os modelos, o fluxo e os dados existentes. O orçamento de CPU respeita os recursos atribuídos ao container; no A10 de quatro núcleos, o Demucs deixa de ficar limitado a uma thread. Não mantenha uma cota de CPU inferior ao que deseja disponibilizar ao aplicativo. Consulte [configuração e limites de hardware](docs/HARDWARE.md).

Sessões de envio expiradas são reiniciadas uma vez na mesma tarefa; IDs de vídeos já confirmados não são reenviados. A autorização renovada do mesmo canal recupera os bloqueios correspondentes e o Telegram administrativo informa quando é preciso renovar. Veja [YouTube, renovação e limites de cobrança](docs/GOOGLE_E_YOUTUBE.md). O aplicativo não compra cota nem ativa faturamento; configurações de faturamento da conta Google e serviços externos não são controlados por ele.

Use `ghcr.io/sal0-apps/sal0-karaoke:12.6.2` após a publicação da imagem validada. Preserve o volume `/data`, portas e configurações. Android e autorizador Windows atuais continuam compatíveis. Para retornar ao código anterior, use a imagem `12.6.1` com o mesmo volume.

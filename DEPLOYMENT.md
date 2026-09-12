# Instalação e operação

Este guia descreve a instalação Docker e os cuidados de operação do Sal0 Karaokê. O [manual completo](MANUAL.md) explica a utilização da interface.

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
    image: ghcr.io/sal0-apps/sal0-karaoke:9.5.0
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
| `/data/output/models/whisper/` | Modelos Whisper baixados |
| `/data/output/profiles.json` | Perfis da instalação principal |
| `/data/output/telegram.json` | Configuração principal do Telegram |
| `/data/output/external_url.json` | Endereço externo usado pelos links |
| `/data/output/state.json` | Estado do processamento |
| `/data/output/app_diagnostic.log` | Diagnóstico |
| `/data/output/queue_jobs/` | Entradas isoladas e checkpoints das tarefas |
| `/data/output/processing_queue.json` | Fila persistida |
| `/data/output/` | Demais configurações, controles e links públicos |
| `/data/cache/` | Cache reutilizável |
| `/data/user_data/` | Bibliotecas e configurações isoladas das contas comuns |
| `/data/users.json` e `/data/sessions.json` | Contas e sessões |

O backup deve incluir o volume inteiro. Copiar apenas resultados não preserva contas, fila, configurações ou checkpoints. Não adicione `data`, backups, logs, chaves Android ou credenciais ao Git.

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

O build tenta preparar modelos e fundos. Falhas externas podem deixar modelos indisponíveis até a instalação posterior. Consulte **Ajustes → Modelos Whisper** como administrador.

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

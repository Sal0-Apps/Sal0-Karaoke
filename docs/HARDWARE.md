# Execução no servidor AMD A10

Configuração informada: AMD PRO A10-9700E, quatro núcleos/quatro threads,
16 GB DDR4-2133 e Radeon integrada. Nesta instalação Demucs, Whisper e
alinhamento usam CPU. A Radeon integrada não oferece CUDA para o
Faster-Whisper e esta revisão não instala outro motor nem troca os modelos.

O orçamento automático usa todos os processadores atribuídos ao processo,
respeitando afinidade e cotas de CPU do Docker. Sem limitação do container,
o A10 utiliza quatro threads nas operações de IA. `--jobs 0` do Demucs e
um worker do Whisper evitam multiplicar memória e pools de trabalho.
O modelo Demucs continua `htdemucs_ft`, com quatro análises e stems float32.

Foi corrigida uma divergência entre processos: o servidor configurava OMP,
mas o runner Demucs lia outra variável e terminava usando uma thread.
Agora o pai e o runner recebem o mesmo valor em `DEMUCS_CPU_THREADS`.
OMP/MKL/OpenBLAS compartilham esse orçamento; workers OMP aguardam em modo
passivo por padrão. Não é necessário manter a CPU em 100% quando não há
operações paralelizáveis.

O modelo Whisper retido entre tentativas da mesma música é liberado antes
da próxima separação Demucs. Isso evita somar os pesos das duas etapas nos
16 GB. A precisão padrão dos modos atuais é mantida: `standard` usa int8
na CPU e `max_quality` usa float32. O mesmo modelo selecionado é preservado.

FFmpeg mantém libx264, resolução, preset e bitrate existentes. Seus filtros
e encoder recebem o orçamento de threads; logs repetidos de frames deixam
de disputar gravações com progresso e interface. Erros guardam as últimas
linhas do diagnóstico, e subprocessos são encerrados também se callbacks
falharem.

## Testar o código desta revisão

O Compose principal continua apontando para a imagem publicada. Para usar
os fontes deste checkout, execute a partir da pasta desta revisão:

```sh
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f karaoke-app
```

O override usa `sal0-karaoke:local-review`, a porta 7885 e `./data:/data` do
Compose principal. Se os dados existentes ficam em outra pasta, ajuste o
volume no Compose antes de iniciar, para apontar para essa mesma pasta.
Os diretórios de biblioteca, cache, modelos, usuários e sessões continuam
sob `/data`.

`KARAOKE_CPU_THREADS=3` limita todas as etapas quando for preciso reservar
mais tempo ao host. `DEMUCS_CPU_THREADS=3` limita apenas a separação Demucs.
Valores maiores que os recursos realmente atribuídos são reduzidos.
Cotas de Docker de uma CPU continuam representando apenas uma CPU de tempo;
para utilizar os quatro núcleos, remova essa cota na configuração do host.

`WHISPER_COMPUTE_TYPE=int8_float32` é uma opção explícita para quem quiser
comparar consumo/resultado no próprio repertório; só é aceito se o backend
o suporta. Não é ativado automaticamente no modo de máxima qualidade.

Não foi possível medir tempo por música neste ambiente: Docker e os modelos
completos não estão instalados. FFmpeg/ffprobe portáteis foram usados apenas
na verificação local, sem alterar dependências da aplicação. Os testes cobrem
o orçamento de threads, a passagem ao runner, progresso, encerramento de
subprocessos e renderização real. Não há percentual de aceleração ou de
precisão medido.

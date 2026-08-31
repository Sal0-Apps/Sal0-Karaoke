# Componentes e materiais de terceiros

Este arquivo identifica dependências diretas e materiais conhecidos do Sal0 Karaokê. Ele não substitui os textos integrais das licenças, não cobre automaticamente todas as dependências transitivas e deve ser regenerado antes de cada nova distribuição binária.

## Dependências Python diretas

| Componente | Uso | Licença indicada pelo projeto |
| --- | --- | --- |
| [PyTorch](https://github.com/pytorch/pytorch) e Torchaudio | inferência e áudio | conjunto de licenças BSD, Apache-2.0, MIT e outras identificadas na distribuição |
| [Demucs](https://github.com/facebookresearch/demucs) | separação de fontes | MIT |
| [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) | transcrição | MIT |
| [FastAPI](https://github.com/fastapi/fastapi) | API HTTP | MIT |
| [Uvicorn](https://github.com/Kludex/uvicorn) | servidor ASGI | BSD-3-Clause |
| [python-multipart](https://github.com/Kludex/python-multipart) | formulários e uploads | Apache-2.0 |
| [Jinja](https://github.com/pallets/jinja) | templates | BSD-3-Clause |
| [Pydub](https://github.com/jiaaro/pydub) | utilitários de áudio | MIT |
| [Requests](https://github.com/psf/requests) | cliente HTTP | Apache-2.0 |
| [SoundFile](https://github.com/bastibe/python-soundfile) | leitura e escrita de áudio | BSD-3-Clause |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | importação opcional por URL | Unlicense |
| [Transformers](https://github.com/huggingface/transformers) | modelo de tradução | Apache-2.0 |
| [SentencePiece](https://github.com/google/sentencepiece) | tokenização | Apache-2.0 |
| [Safetensors](https://github.com/huggingface/safetensors) | pesos de modelos | Apache-2.0 |

Os pacotes podem trazer NumPy, CTranslate2, Hugging Face Hub, PyAV, Silero VAD e outras dependências transitivas. Consulte os metadados instalados em `*.dist-info` e produza um inventário SBOM da imagem final.

## Executáveis e bibliotecas do sistema

| Componente | Observação |
| --- | --- |
| [FFmpeg](https://ffmpeg.org/legal.html) | LGPL-2.1-or-later na base; componentes GPL como `libx264` alteram as obrigações. Confirmar a configuração do binário Debian efetivamente distribuído. |
| [libsndfile](https://libsndfile.github.io/libsndfile/) | biblioteca distribuída separadamente e sujeita à licença do pacote Debian. |
| [Deno](https://github.com/denoland/deno) | runtime JavaScript sob MIT; baixado durante o build. |
| Debian e Python | a imagem base e os pacotes mantêm seus próprios avisos e licenças em `/usr/share/doc` e na distribuição Python. |

## Modelos

| Modelo | Finalidade | Situação observada |
| --- | --- | --- |
| [Systran/faster-whisper-medium](https://huggingface.co/Systran/faster-whisper-medium) | transcrição alternativa | model card MIT |
| `deepdml/faster-whisper-large-v3-turbo` | transcrição padrão solicitada pelo código | metadados públicos de licença não recuperados na auditoria de 2026-08-31; não confundir com repositórios de nome semelhante |
| [facebook/m2m100_418M](https://huggingface.co/facebook/m2m100_418M) | tradução local opcional | model card MIT |
| `htdemucs_ft` | separação de voz | distribuído pelo projeto Demucs; confirmar a revisão e os arquivos efetivamente incorporados |

Model cards e licenças podem mudar. Registre o hash da revisão de cada peso utilizado em uma imagem publicada.

## Android

| Componente | Uso | Licença indicada pelo projeto |
| --- | --- | --- |
| [AndroidX Activity](https://developer.android.com/jetpack/androidx/releases/activity) | atividade principal | Apache-2.0 |
| [JUnit 4](https://github.com/junit-team/junit4) | testes; não compõe o runtime | EPL-1.0 |
| Android Gradle Plugin | build | Apache-2.0 |

## Fontes web

A interface solicita [Inter](https://github.com/rsms/inter) e [Outfit](https://github.com/Outfitio/Outfit-Fonts) pelo Google Fonts. Ambas são disponibilizadas sob SIL Open Font License 1.1. O carregamento remoto também cria uma comunicação de rede com o Google, descrita em [PRIVACY.md](PRIVACY.md).

## Imagens padrão do Wikimedia Commons

O script `app/download_models.py` tenta baixar cinco arquivos durante o build. Eles não estão no repositório-fonte, mas um download bem-sucedido pode incorporá-los à imagem Docker.

| Arquivo solicitado pelo código | Situação verificada em 31 de agosto de 2026 |
| --- | --- |
| [Moraine Lake 17092005.jpg](https://commons.wikimedia.org/wiki/File:Moraine_Lake_17092005.jpg) | página existente; autor indicado: Gorgo; domínio público |
| [`Neckarhalde_Tübingen_Ganzaufnahme.jpg`](https://upload.wikimedia.org/wikipedia/commons/thumb/3/35/Neckarhalde_T%C3%BCbingen_Ganzaufnahme.jpg/1280px-Neckarhalde_T%C3%BCbingen_Ganzaufnahme.jpg) | a URL não apresentou página de descrição correspondente; autoria e licença não confirmadas |
| [`Fuji_from_Motoshu_2004-11-16.jpg`](https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Fuji_from_Motoshu_2004-11-16.jpg/1280px-Fuji_from_Motoshu_2004-11-16.jpg) | a URL não apresentou página de descrição correspondente; autoria e licença não confirmadas |
| [`Loch_Lomond_from_Duncryne.jpg`](https://upload.wikimedia.org/wikipedia/commons/thumb/c/ca/Loch_Lomond_from_Duncryne.jpg/1280px-Loch_Lomond_from_Duncryne.jpg) | a página exata não pôde ser confirmada; não atribuir a arquivos apenas semelhantes pelo título |
| [`Val_di_Funes_panorama_April_2017.jpg`](https://upload.wikimedia.org/wikipedia/commons/thumb/a/a2/Val_di_Funes_panorama_April_2017.jpg/1280px-Val_di_Funes_panorama_April_2017.jpg) | a página exata não pôde ser confirmada; autoria e licença não confirmadas |

Somente a primeira imagem possui atribuição e licença confirmadas nesta revisão. As demais não devem ser redistribuídas nem descritas como domínio público ou Creative Commons até que suas páginas canônicas sejam identificadas. O build atual ignora falhas de download, mas isso não resolve a ausência de comprovação jurídica quando um arquivo já estiver em cache ou vier a ser servido pela URL.

## Serviços externos

YouTube, Telegram, LRCLIB, Lyrics.ovh, Musixmatch, Hugging Face, Google Fonts, Wikimedia Commons, GitHub e GHCR são serviços independentes. Uma integração técnica não concede licença sobre conteúdo nem substitui os termos do serviço.

## Código do Sal0 Karaokê

O código original do repositório permanece sob [MIT](LICENSE). Componentes e materiais acima permanecem sob suas respectivas licenças.

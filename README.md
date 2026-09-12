# 🎤 Sal0 Karaokê

Transforme uma música em um vídeo de karaokê sem mandar seu áudio para uma nuvem de processamento. Escolha a faixa, ajuste o visual e deixe o Sal0 Karaokê separar a voz, transcrever, sincronizar e renderizar tudo no seu próprio computador ou servidor.

É um projeto pessoal, feito com carinho para brincar com música — mas organizado o bastante para virar o cantinho de karaokê de uma casa, família ou grupo de amigos. ✨

## O que ele faz

| Parte | Possibilidades |
|---|---|
| Música | Upload, Biblioteca ou link do YouTube identificado e preparado ao criar |
| Modo Rápido | Link, arquivo ou Biblioteca, fundo opcional e um botão; o restante segue o padrão do administrador |
| Voz | Separação de vocal e instrumental com Demucs |
| Legenda | Transcrição local com Faster-Whisper e modos por sílaba, palavra ou linha |
| Perfis | Opções prontas para karaokê equilibrado, canto contínuo, voz difícil/mix e criação rápida, além dos perfis pessoais |
| Letra-guia | Texto manual ou busca opcional em LRCLIB, Lyrics.ovh e Musixmatch |
| Visual | Vídeo original, cor, imagem, vídeo, Biblioteca ou fundo do YouTube |
| Revisão | Editor de texto e tempos antes da renderização |
| Resultado | Preview, download como `Música - Karaokê.mp4` e histórico permanente |
| Telegram | Bot pessoal por usuário, avisos e vídeo ou link direto |
| Contas | Espaços separados para Biblioteca, cache, letras, perfis, bot e resultados |

Todo o processamento de mídia continua local. Quando a busca automática de letra é usada, apenas o nome da música e do artista é consultado na internet; a letra encontrada serve como guia para a transcrição.

Nas telas de criação, basta colar o link: o nome do vídeo aparece na interface e o download necessário acontece ao clicar em criar. Os botões para baixar e guardar uma música ou um fundo antes do processo ficam na **Biblioteca**.

## Contas sem misturar os discos

- Cada usuário comum vê e controla apenas as próprias criações.
- Um usuário comum não cria contas nem cancela a tarefa de outra pessoa.
- Cada conta pode configurar seu próprio bot do Telegram.
- O administrador gerencia o servidor, pode cancelar qualquer tarefa e recebe também os avisos de todas as contas.
- A Biblioteca antiga permanece com a conta administradora; novos usuários recebem espaços separados automaticamente.

## Rodando com Docker

```yaml
services:
  karaoke-app:
    image: ghcr.io/sal0-apps/sal0-karaoke:latest
    container_name: karaoke-app
    ports:
      - "7885:7860"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

Depois, execute:

```bash
docker compose up -d
```

Abra `http://localhost:7885`. No primeiro acesso, o aplicativo pede a criação da conta administradora.

## Um primeiro karaokê

### Modo Rápido

O **Modo Rápido** é a primeira aba de criação para todas as contas. Link do YouTube, arquivo local e Biblioteca ficam disponíveis ao mesmo tempo: basta interagir com a opção desejada e clicar em criar. Música, vídeo, imagem e fundo também podem ser arrastados diretamente para seus campos.

O seletor entre **Rápido** e **Detalhado** acompanha a rolagem da tela. Durante uma produção ele fica temporariamente bloqueado e os dois formulários são ocultados, evitando iniciar outra configuração por engano.

Quando nenhum fundo é informado, o app sorteia uma imagem ou vídeo da coleção marcada pelo administrador. Se a coleção estiver vazia, usa o vídeo original. Os arquivos da coleção continuam privados na Biblioteca administrativa: o usuário recebe somente o fundo sorteado durante o processamento.

O administrador define o perfil global em **Ajustes → Modo Rápido**. Todas as opções técnicas ficam disponíveis ali — modelo, perfil da voz, fonte da transcrição, VAD, letra, aparência da legenda, coleção de fundos, revisão e salvamento — sem carregar a tela rápida.

Os valores iniciais são **Large V3 Turbo**, perfil **Voz difícil**, fonte **50**, vocais separados pelo Demucs, letra automática, texto centralizado, prévia da próxima frase e renderização direta sem revisão.

### Modo Detalhado

1. Em **Criar**, envie uma música, cole um link do YouTube ou escolha um item da Biblioteca.
2. Escolha um **Perfil da música**. **Karaokê equilibrado** é o ponto de partida recomendado.
3. Deixe **Letra automática** ativa ou abra o bloco para colar uma letra manualmente.
4. Escolha o fundo e, se quiser, abra **Mais ajustes** para personalizar legenda e revisão.
5. Clique em **Criar Karaokê** e acompanhe as etapas com o resumo da música, letra, modelo e fundo em uso.
6. Quando terminar, assista no próprio app, baixe o MP4 ou abra **Biblioteca → Resultados**.

A página consulta o estado do servidor continuamente, sem reaproveitar respostas antigas do navegador. Ao voltar para a aba ou recuperar a conexão, ela confere o processamento imediatamente.

Para canto, o filtro Silero VAD fica desligado por padrão: ele foi criado para detectar fala e pode cortar notas suaves ou sustentadas. Os perfis de voz difícil também evitam esse filtro; a opção continua disponível em **Mais ajustes** para gravações faladas ou muito ruidosas.

Em **Mais ajustes**, deixar palavras ou caracteres por verso em zero ativa a divisão inteligente. Quando existe letra-guia, as linhas originais orientam o fim de cada verso; sem ela, o app considera pontuação, pausas e duração. Os cortes internos do Whisper não dividem mais uma frase por conta própria, e a linha atual permanece visível até a próxima começar.

O botão de tema claro/escuro fica sempre no topo da tela.

## Telegram e links diretos

Cada conta configura seu bot em **Ajustes → Meu bot do Telegram**. O administrador pode informar uma URL externa do servidor. Ao concluir um vídeo, o app cria um endereço aleatório de download direto para aquele arquivo; assim, o link funciona sem levar uma sessão do navegador para o Telegram.

Quem receber esse endereço consegue baixar o vídeo enquanto ele existir na Biblioteca. Trate a mensagem como um link privado e não a encaminhe para pessoas que não devam acessar o arquivo.

## Dados, privacidade e cuidados

Tudo que o app guarda fica no volume `/data`: usuários, sessões, modelos, mídias, fundos, letras, perfis, caches e resultados.

- Use uma senha que não esteja sendo usada em outro serviço.
- Publique o app somente em uma rede confiável, VPN ou proxy configurado por você.
- Faça backup da pasta `/data` para preservar contas e criações.
- Nunca publique `.env_deploy`, tokens do GitHub, tokens do Telegram ou arquivos de sessão.
- Os logs podem conter nomes de arquivos e endereços. Revise o texto antes de compartilhá-lo.
- Fontes de letras e YouTube são serviços externos e podem ficar indisponíveis. O restante do fluxo continua local.

## Onde pedir ajuda

Ao relatar um problema, conte o que estava fazendo, qual etapa apareceu e qual foi a mensagem de erro. O administrador pode gerar um relatório atualizado em **Ajustes → Diagnóstico**. Remova nomes pessoais, endereços e outros dados que não precisem aparecer no relato.

Divirta-se — e deixe o microfone longe da caixa de som. 🎶

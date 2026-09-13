# Cliente Android do Sal0 Karaokê

O APK acessa o servidor Sal0 Karaokê. Demucs, Whisper, tradução e renderização são executados no servidor; o aparelho funciona como cliente de conexão, envio, reprodução e download.

## Instalar

1. Baixe o APK na [Release da versão](https://github.com/Sal0-Apps/Sal0-Karaoke/releases/tag/v9.6.0).
2. No Android, permita a instalação pela origem que abriu o arquivo, se o sistema solicitar.
3. Instale e abra o Sal0 Karaokê.
4. Configure a conexão e entre com a conta da instalação.

O mínimo configurado pelo projeto é Android 8.0 (API 26). O suporte real à reprodução depende da WebView e dos codecs do aparelho.

Atualizações sobre um APK já instalado exigem a mesma assinatura. Se o Android recusar por assinatura incompatível, confira a origem do APK e preserve as configurações antes de considerar uma reinstalação. Não desinstale supondo que as preferências e a sessão serão preservadas.

## Primeira conexão

Preencha:

| Campo | O que informar |
| --- | --- |
| Nome da rede Wi-Fi | SSID da rede em que o endereço local deve ser priorizado |
| Endereço local | URL alcançável pelo aparelho dentro dessa rede, incluindo a porta publicada |
| Endereço externo | URL acessível fora da rede, normalmente HTTPS por proxy ou acesso via VPN |

Com o Compose de exemplo, o endereço local tem a porta 7885, por exemplo `http://192.168.1.50:7885`. Esse IP é ilustrativo. Não use `localhost` no celular para apontar para um servidor em outro computador.

Os dois endereços são obrigatórios na configuração atual. Para uso somente local, pode repetir o mesmo endereço nos dois campos; isso não cria acesso fora da rede.

Toque em **Conectar ao meu servidor**. O aplicativo testa as rotas antes de abrir a página e acompanha alterações de conectividade. A leitura do SSID pode exigir acesso à localização no Android. Sem permissão, o aplicativo tenta as rotas sem confirmar o nome do Wi-Fi.

## Alterar as configurações do app

Na faixa inferior do APK, toque em **Configurações do app**. O botão é nativo e permanece acessível mesmo quando a página do servidor está offline.

1. Revise Wi-Fi, endereço local e externo.
2. Toque em **Salvar e reconectar** para aplicar.
3. Use **Voltar ao karaokê** ou Voltar do Android para sair sem salvar.

Abrir essas configurações fecha a WebView atual. Os campos de criação ainda não enviados precisam ser preenchidos novamente; tarefas já aceitas continuam no servidor. O número da versão do APK aparece nessa tela.

A faixa inferior não repete o título ou os controles da página. Durante vídeo em tela cheia, ela fica oculta e reaparece ao sair desse modo.

**Configurações do app** altera a conexão deste aparelho. **Ajustes**, dentro da página, controla Telegram, modelos, perfis, administração e demais recursos do servidor. Um endereço salvo no APK não altera automaticamente os links externos enviados pelo Telegram.

## Usar a aplicação

A interface contém os modos Rápido, Detalhado e Gerar SRT, fila, progresso, revisão, Biblioteca e Ajustes. O botão **Manual** apresenta tutoriais resumidos; o [manual completo](../MANUAL.md) detalha todos os controles.

Mudanças de HTML, CSS e JavaScript chegam quando o servidor é atualizado. Alterações na conexão nativa, permissões, downloads ou interface Android exigem um novo APK.

## Arquivos, downloads e reprodução

- O seletor do Android permite fornecer arquivos aos formulários, inclusive vários quando o campo aceita.
- Os downloads usam o gerenciador do sistema e ficam em **Downloads**.
- O nome informado pelo servidor é priorizado, com suporte a UTF-8.
- Nomes já existentes recebem sufixos para evitar sobrescrita.
- Aparelhos antigos podem solicitar permissão de armazenamento.
- O vídeo pode ser aberto em tela cheia; Voltar sai da reprodução em tela cheia.
- Links externos à instalação são encaminhados a aplicativos apropriados, quando disponíveis.

Se um download não aparecer, confira o gerenciador de downloads, espaço livre, conectividade e permissões. SRT é um arquivo de legenda, não um vídeo. Nem todo codec aceito pelo servidor é reproduzível pela WebView.

## Segurança e privacidade

O aparelho guarda os endereços, o SSID, dados de sessão da WebView e os arquivos baixados. O servidor recebe uploads e requisições. A aplicação não fornece um serviço central de armazenamento do projeto.

A configuração aceita HTTP para rede local, e o APK não ignora certificados HTTPS inválidos. Use uma rede confiável e HTTPS/VPN quando necessário. Endereços locais e externos são tratados como origens distintas; uma troca de endereço pode exigir novo login.

Consulte [PRIVACY.md](../PRIVACY.md) e [SECURITY.md](../SECURITY.md).

## Compilar

A configuração atual utiliza JDK 17, Android SDK Platform 36, Android Gradle Plugin 9.2.1, AndroidX Activity 1.13.0 e Gradle compatível (o script local orienta Gradle 9.4.1).

No diretório `android`, com SDK e ferramentas configurados:

```bash
gradle --no-daemon :app:testDebugUnitTest :app:lintRelease :app:assembleRelease -PVERSION_NAME=9.6.0 -PVERSION_CODE=90600
```

O APK de saída fica em `app/build/outputs/apk/release/app-release.apk`.

### Assinatura própria

O Gradle lê as variáveis locais:

- `ANDROID_KEYSTORE_PATH`;
- `ANDROID_KEYSTORE_PASSWORD`;
- `ANDROID_KEY_ALIAS`;
- `ANDROID_KEY_PASSWORD`.

Carregue os valores por um cofre de segredos ou ambiente protegido. Não inclua senhas, arquivos de chave ou tokens no Git, em logs ou em exemplos públicos.

Com essas variáveis definidas, o auxiliar PowerShell pode ser usado:

```powershell
.\build-release.ps1 -VersionName 9.6.0 -VersionCode 90600
```

Ele executa testes, lint e build e copia o resultado para `android/Sal0-Karaoke-Android.apk`, ignorado pelo Git.

Sem todas as variáveis de assinatura de lançamento, o Gradle utiliza a assinatura de depuração. Builds independentes podem usar chaves distintas; isso não fornece uma identidade estável de atualização. Uma distribuição mantida deve conservar uma chave própria fora do repositório.

## Publicação

O workflow de tags `v*` publica a imagem no GHCR, compila o APK e o anexa à Release. Para publicar a partir de um fork, configure suas próprias permissões, destinos e assinatura e preserve as licenças aplicáveis.

A compilação não certifica que todas as redes e versões de Android funcionarão. Teste conexão local/externa, configurações offline, upload múltiplo, download de MP4/SRT e reprodução no aparelho que será utilizado.

# Cliente Android do Sal0 Karaokê

O aplicativo Android é um cliente do servidor Sal0 Karaokê. Ele não executa Demucs, Whisper ou renderização no aparelho; a interface principal e o processamento permanecem no servidor.

## Recursos nativos

- configuração dos endereços local e externo;
- acompanhamento de conectividade com `ConnectivityManager`;
- leitura do SSID após autorização do usuário;
- teste das rotas e fallback automático;
- indicador da rota ativa;
- seletor de arquivos do Android;
- downloads na pasta `Downloads` com nomes UTF-8 e prevenção de sobrescrita;
- reprodução em tela cheia;
- bloqueio de navegação interna para origens não configuradas.

Alterações apenas em HTML, CSS ou JavaScript chegam pelo servidor atualizado. Mudanças no código Java, manifesto ou recursos Android exigem um novo APK.

## APK publicado

O workflow associado a tags `v*` executa o build e anexa `Sal0-Karaoke-v<versão>.apk` à Release do GitHub. Se as variáveis de assinatura privada não estiverem presentes no ambiente, o Gradle usa a assinatura de depuração. Esse fallback produz um APK instalável, mas não fornece uma identidade de assinatura permanente para distribuição oficial.

Um mantenedor que pretenda oferecer atualizações Android consistentes deve proteger uma chave própria, assinar todas as versões com a mesma chave e nunca adicioná-la ao Git.

## Compilação

Requisitos:

- JDK 17;
- Gradle 9.4.1;
- Android SDK Platform 36;
- Android Build Tools compatíveis com `compileSdk 36`.

Build de desenvolvimento:

```bash
gradle :app:assembleDebug
```

Build de lançamento assinado no PowerShell:

```powershell
$env:ANDROID_KEYSTORE_PATH = 'C:\caminho\sal0-karaoke-release.p12'
$env:ANDROID_KEYSTORE_PASSWORD = 'senha-local-do-keystore'
$env:ANDROID_KEY_ALIAS = 'sal0-karaoke'
$env:ANDROID_KEY_PASSWORD = 'senha-local-da-chave'
.\build-release.ps1 -VersionName 9.0.7 -VersionCode 90007
```

Use valores reais somente no ambiente local ou em um cofre de segredos. Não grave senhas no histórico do terminal compartilhado, em `.env`, no código ou no repositório.

O script local executa testes, lint e montagem; depois copia o APK para `android/Sal0-Karaoke-Android.apk`, que permanece ignorado pelo Git.

## Privacidade e rede

O cliente solicita permissões de rede, Wi-Fi e localização necessárias para identificar o SSID em versões do Android que exigem essa autorização. O servidor configurado recebe as requisições da WebView. Consulte [PRIVACY.md](../PRIVACY.md) e [SECURITY.md](../SECURITY.md).

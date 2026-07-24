# Sal0 Karaokê para Android

Cliente Android do servidor Sal0 Karaokê.

## O que é nativo

- configuração inicial com Wi-Fi, endereço local e endereço externo;
- acompanhamento das mudanças de rede com `ConnectivityManager`;
- leitura do SSID autorizado pelo usuário;
- teste dos dois servidores e fallback automático;
- indicador claro da rota ativa;
- seletor de arquivos do Android para músicas, imagens e vídeos;
- downloads salvos na pasta `Downloads`;
- reprodução em tela cheia;
- bloqueio de navegação interna para origens não configuradas.

A tela principal continua sendo servida pelo contêiner. Por isso, alterações em HTML, CSS e JavaScript chegam assim que o Docker é atualizado, sem exigir outra instalação do APK.

O APK não é publicado nas Releases do GitHub e não faz atualização nativa pela internet. Quando o código Android mudar, ele é recompilado localmente e instalado manualmente, preservando a mesma assinatura de lançamento.

## Compilar

Requisitos:

- JDK 17;
- Gradle 9.4.1;
- Android SDK Platform 36;
- Android Build Tools 36.0.0.

Build de desenvolvimento:

```bash
gradle :app:assembleDebug
```

Build de lançamento no PowerShell:

```powershell
$env:ANDROID_KEYSTORE_PATH = 'C:\caminho\sal0-karaoke-release.p12'
$env:ANDROID_KEYSTORE_PASSWORD = 'senha-do-keystore'
$env:ANDROID_KEY_ALIAS = 'sal0-karaoke'
$env:ANDROID_KEY_PASSWORD = 'senha-da-chave'
.\build-release.ps1 -VersionName 5.6.0 -VersionCode 50600
```

O script executa os testes, o lint, gera o APK assinado e atualiza `android/Sal0-Karaoke-Android.apk` apenas na cópia local. As chaves e senhas nunca devem ser commitadas.

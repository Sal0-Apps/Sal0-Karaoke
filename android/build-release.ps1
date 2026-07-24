[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+([-.][0-9A-Za-z.-]+)?$')]
    [string]$VersionName,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 2147483647)]
    [int]$VersionCode
)

$ErrorActionPreference = 'Stop'

$androidRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$keystorePath = $env:ANDROID_KEYSTORE_PATH
$requiredSecretNames = @(
    'ANDROID_KEYSTORE_PATH',
    'ANDROID_KEYSTORE_PASSWORD',
    'ANDROID_KEY_ALIAS',
    'ANDROID_KEY_PASSWORD'
)

foreach ($secretName in $requiredSecretNames) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($secretName))) {
        throw "Defina a variável local $secretName antes de gerar o APK."
    }
}

if (-not (Test-Path -LiteralPath $keystorePath -PathType Leaf)) {
    throw "Keystore não encontrado em: $keystorePath"
}

$gradle = Get-Command gradle -ErrorAction SilentlyContinue
if ($null -eq $gradle) {
    throw 'Gradle não encontrado no PATH. Instale o Gradle 9.4.1 ou adicione-o ao PATH.'
}

Push-Location $androidRoot
try {
    & $gradle.Source --no-daemon `
        :app:testDebugUnitTest `
        :app:lintRelease `
        :app:assembleRelease `
        "-PVERSION_NAME=$VersionName" `
        "-PVERSION_CODE=$VersionCode"

    if ($LASTEXITCODE -ne 0) {
        throw "O Gradle terminou com código $LASTEXITCODE."
    }

    $artifact = Join-Path $androidRoot 'app\build\outputs\apk\release\app-release.apk'
    $localApk = Join-Path $androidRoot 'Sal0-Karaoke-Android.apk'
    if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
        throw 'O Gradle terminou sem gerar o APK de lançamento.'
    }

    Copy-Item -LiteralPath $artifact -Destination $localApk -Force
    Write-Host "APK local atualizado: $localApk"
}
finally {
    Pop-Location
}

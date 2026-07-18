#!/bin/bash
# ==============================================================================
# 🚀 Sal0 Karaokê - Script de Release Automatizado (Git & GitHub v2.1.0)
# Uso: bash deploy.sh <versao> [mensagem]
# ==============================================================================

# ⚙️ DADOS DO AUTOR
GIT_AUTHOR_NAME="VictorS4l0"
GIT_AUTHOR_EMAIL="victormordecai@gmail.com"
GITHUB_USER="VictorS4l0"

# Tenta ler o Token de um arquivo local seguro (.env_deploy ou ~/.github_token) se existir
GITHUB_TOKEN=""
if [ -f ".env_deploy" ]; then
    GITHUB_TOKEN=$(grep -v '^#' .env_deploy 2>/dev/null | tr -d '\r\n ' | head -n 1)
elif [ -f "$HOME/.github_token" ]; then
    GITHUB_TOKEN=$(grep -v '^#' "$HOME/.github_token" 2>/dev/null | tr -d '\r\n ' | head -n 1)
fi

# Define o comando Git injetando a exceção de diretório seguro e identidade do autor
GIT="git -c safe.directory=* -c user.name=$GIT_AUTHOR_NAME -c user.email=$GIT_AUTHOR_EMAIL"

# Limpar travas órfãs do Git se existirem
rm -f .git/index.lock 2>/dev/null
rm -f .git/refs/remotes/origin/*.lock 2>/dev/null

VERSION=$1
MESSAGE=${2:-"Atualizacao e melhorias"}

if [ -z "$VERSION" ]; then
    echo "❌ Erro: Informe o número da versão."
    echo "📌 Exemplo de uso: bash deploy.sh 2.1.0 \"Descricao das alteracoes\""
    exit 1
fi

TAG="v$VERSION"

# Determina o destino de Push (com Token se encontrado, ou 'origin' padrão)
if [ -n "$GITHUB_TOKEN" ] && [ "$GITHUB_TOKEN" != "COLE_SEU_TOKEN_DO_GITHUB_AQUI" ]; then
    echo "🔑 Token de acesso validado! Usando autenticação direta do GitHub..."
    PUSH_TARGET="https://$GITHUB_TOKEN@github.com/Sal0-Apps/Sal0-Karaoke.git"
else
    PUSH_TARGET="origin"
fi

echo "========================================================"
echo "🚀 Criando e enviando Release no GitHub: Sal0 Karaokê $TAG"
echo "========================================================"

# Se o último commit contiver segredo rejeitado pelo GitHub, desfaz o commit local automaticamente
if $GIT log -1 --pretty=%B 2>/dev/null | grep -q "Release v"; then
    echo "🔄 Desfazendo commit local com segredo antigo..."
    $GIT reset HEAD~1 2>/dev/null
fi

# 1. Adicionar e commitar alterações no Git
echo "📦 1/3 Adicionando arquivos e criando commit seguro..."
$GIT add .
$GIT commit -m "Release $TAG: $MESSAGE"

# 2. Push para a branch main
echo "⬆️ 2/3 Enviando código para o GitHub (main)..."
$GIT push "$PUSH_TARGET" main
PUSH_STATUS=$?

if [ $PUSH_STATUS -ne 0 ]; then
    echo "❌ Erro no envio da branch main. Verifique se o Token no .env_deploy é válido."
    exit 1
fi

# 3. Remover tag antiga local/remota se existir e enviar nova tag
echo "🏷️ 3/3 Criando e enviando a Tag $TAG para o GitHub..."
$GIT tag -d "$TAG" 2>/dev/null
$GIT push "$PUSH_TARGET" --delete "$TAG" 2>/dev/null
$GIT tag -a "$TAG" -m "Release $TAG: $MESSAGE"
$GIT push "$PUSH_TARGET" "$TAG"
TAG_STATUS=$?

if [ $TAG_STATUS -eq 0 ]; then
    echo "========================================================"
    echo "✅ RELEASE $TAG ENVIADA PARA O GITHUB COM SUCESSO!"
    echo "========================================================"
else
    echo "❌ Erro ao enviar a Tag $TAG."
fi

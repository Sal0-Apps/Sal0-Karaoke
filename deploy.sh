#!/bin/bash
set -euo pipefail

# Sal0 Karaokê — auxiliar de publicação.
# A autenticação deve ser fornecida pelo gerenciador de credenciais do Git,
# GitHub CLI ou chave SSH. O script nunca lê nem injeta tokens em URLs.

VERSION=${1:-}
MESSAGE=${2:-"Atualização e melhorias"}

if [ -z "$VERSION" ]; then
    echo "❌ Erro: Informe o número da versão."
    echo "📌 Exemplo de uso: bash deploy.sh 2.1.1 \"Descrição das alterações\""
    exit 1
fi

TAG="v$VERSION"

echo "========================================================"
echo "🚀 Criando e enviando Release no GitHub: Sal0 Karaokê $TAG"
echo "========================================================"

# O script não cria commits nem inclui arquivos automaticamente.
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "❌ A árvore de trabalho contém alterações. Revise e faça o commit manualmente."
    exit 1
fi

# 1. Enviar a branch sem reescrever o histórico.
echo "⬆️ 1/2 Enviando código para o GitHub (main)..."
git push origin main

# 2. Criar uma tag nova; tags existentes não são substituídas.
if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "❌ A tag $TAG já existe. Escolha outra versão."
    exit 1
fi
echo "🏷️ 2/2 Criando e enviando a tag $TAG..."
git tag -a "$TAG" -m "Release $TAG: $MESSAGE"
git push origin "$TAG"

echo "✅ $TAG enviada. O GitHub Actions cuidará dos artefatos configurados."

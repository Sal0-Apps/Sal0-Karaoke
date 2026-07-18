#!/bin/bash
# ==============================================================================
# 🚀 Sal0 Karaokê - Script de Deploy Automatizado em Comando Único
# Uso: ./deploy.sh <versao> [mensagem]
# Exemplo: ./deploy.sh 2.0.1 "Ajustes de layout e correcao de bugs"
# ==============================================================================

VERSION=$1
MESSAGE=${2:-"Atualizacao e melhorias"}

if [ -z "$VERSION" ]; then
    echo "❌ Erro: Informe o número da versão."
    echo "📌 Exemplo de uso: ./deploy.sh 2.0.1 \"Descricao das alteracoes\""
    exit 1
fi

TAG="v$VERSION"

echo "========================================================"
echo "🚀 Iniciando Deploy Automatizado: Sal0 Karaokê $TAG"
echo "========================================================"

# 1. Adicionar e commitar alterações no Git
echo "📦 1/4 Adicionando arquivos e criando commit..."
sudo HOME=/tmp git add .
sudo HOME=/tmp git commit -m "Release $TAG: $MESSAGE"

# 2. Push para a branch main
echo "⬆️ 2/4 Enviando codigo para o GitHub (main)..."
sudo HOME=/tmp git push origin main

# 3. Remover tag antiga se existir e enviar nova tag
echo "🏷️ 3/4 Criando e enviando a Tag $TAG..."
sudo HOME=/tmp git tag -d "$TAG" 2>/dev/null
sudo HOME=/tmp git push origin --delete "$TAG" 2>/dev/null
sudo HOME=/tmp git tag -a "$TAG" -m "Release $TAG: $MESSAGE"
sudo HOME=/tmp git push origin "$TAG"

# 4. Atualizar o container Docker no servidor
echo "🐳 4/4 Atualizando o container Docker no servidor..."
sudo DOCKER_CONFIG=/tmp/.docker docker compose down
sudo DOCKER_CONFIG=/tmp/.docker docker compose pull
sudo DOCKER_CONFIG=/tmp/.docker docker compose up -d

echo "========================================================"
echo "✅ DEPLOY DA VERSÃO $TAG CONCLUÍDO COM SUCESSO!"
echo "========================================================"

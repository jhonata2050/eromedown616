#!/bin/bash
# ==============================================================================
# SCRIPT DE DEPLOY E MIGRAÇÃO AUTOMÁTICA PARA DOCKER - EROMEDOWN
# ==============================================================================
set -e

echo "🚀 Iniciando preparação e deploy do EromeDown em Docker..."

# 1. Verificar instalação do Docker
if ! command -v docker &> /dev/null; then
    echo "⚠️ Docker não encontrado. Instalando Docker oficial..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER || true
    rm get-docker.sh
    echo "✅ Docker instalado com sucesso!"
fi

# 2. Desativar serviço antigo do systemd se existir (para liberar a porta 5000)
if systemctl is-active --quiet eromedown 2>/dev/null; then
    echo "🛑 Parando serviço antigo systemd eromedown para liberar portas..."
    sudo systemctl stop eromedown || true
    sudo systemctl disable eromedown || true
    echo "✅ Serviço antigo desativado."
fi

# 3. Preparar diretório de dados persistentes
mkdir -p data
chmod 777 data

# 4. Migrar banco de dados existente se houver
if [ -f "analytics.db" ] && [ ! -f "data/analytics.db" ]; then
    echo "📦 Migrando seu analytics.db existente para a pasta persistente ./data/..."
    cp analytics.db data/analytics.db
    chmod 666 data/analytics.db
    echo "✅ Banco de dados e configurações preservados em ./data/analytics.db!"
fi

# 5. Criar arquivo .env se não existir
if [ ! -f ".env" ]; then
    echo "⚙️ Criando arquivo de ambiente .env com valores recomendados..."
    cp .env.example .env
fi

# 6. Construir e iniciar o container em segundo plano
echo "🐳 Construindo imagem e subindo containers com Docker Compose..."
docker compose down || true
docker compose up -d --build

echo ""
echo "===================================================================="
echo "🎉 EROMEDOWN EM DOCKER INICIADO COM SUCESSO!"
echo "===================================================================="
echo "Status do container:"
docker compose ps
echo ""
echo "Acompanhe os logs em tempo real executando:"
echo "   docker compose logs -f"
echo "===================================================================="

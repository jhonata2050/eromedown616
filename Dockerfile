# ==============================================================================
# DOCKERFILE - EROMEDOWN PRODUCTION
# ==============================================================================
FROM python:3.11-slim

# Metadados
LABEL maintainer="eromedown.org"
LABEL description="EromeDown - High Performance Video Downloader"

# Configurações de ambiente do Python e Container
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    DATA_DIR=/app/data \
    GUNICORN_BIND=0.0.0.0:5000 \
    GUNICORN_WORKERS=4 \
    GUNICORN_THREADS=16

WORKDIR /app

# Instalar dependências essenciais do sistema:
# - curl: para healthchecks e diagnósticos de conectividade
# - ffmpeg: para processamento/conversão de formatos no yt-dlp
# - ca-certificates: para validação de certificados SSL em downloads
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependências Python aproveitando o cache de camadas do Docker
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar os arquivos da aplicação
COPY . /app/

# Criar pasta persistente de dados para o SQLite e conceder permissões
RUN mkdir -p /app/data && chmod -R 777 /app/data

# Expor porta do serviço
EXPOSE 5000

# Verificação de saúde em tempo real do container
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/version || exit 1

# Comando de inicialização em alta concorrência
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]

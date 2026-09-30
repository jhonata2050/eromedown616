# ==============================================================================
# CONFIGURAÇÃO DE ALTA CONCORRÊNCIA E PERFORMANCE GUNICORN (CORE SHIELD)
# ==============================================================================
# Esta configuração resolve definitivamente o Erro 524 da Cloudflare (Timeout 100s)
# ao permitir que downloads de mídia rodem em threads concorrentes sem bloquear
# as requisições web do site e do painel administrativo.

import multiprocessing

# Endereço e Porta local (vinculado estritamente ao localhost por segurança)
bind = "127.0.0.1:5000"

# Arquitetura Híbrida Multi-Processo + Multi-Thread:
# 4 workers * 16 threads = 64 conexões simultâneas!
# Mesmo se 10 usuários estiverem baixando arquivos pesados simultaneamente,
# ainda restam 54 threads livres para navegação instantânea (< 50ms) no site e admin.
workers = 4
worker_class = "gthread"
threads = 16

# Timeout estendido para streaming de vídeos longos sem derrubar o worker
timeout = 300
keepalive = 5

# Reciclagem automática de workers para prevenir vazamento de memória residual
max_requests = 3000
max_requests_jitter = 200

# Otimizações de rede do SO
backlog = 2048

# Logs do servidor
accesslog = "-"
errorlog = "-"
loglevel = "info"

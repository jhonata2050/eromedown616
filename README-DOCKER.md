# 🐳 Guia de Deploy em Docker — EromeDown

Este guia ensina como rodar o **EromeDown** em qualquer VPS econômica (Hetzner, OVH, DigitalOcean, Linode, Oracle Cloud Free Tier, AWS Lightsail, etc.) utilizando Docker e Docker Compose, reduzindo seus custos de infraestrutura a quase zero sem perder desempenho.

---

## ⚡ 1. Deploy Rápido em 1 Comando (Linux VPS)

Na sua VPS (Ubuntu/Debian), entre na pasta do projeto e execute:

```bash
chmod +x deploy-docker.sh
./deploy-docker.sh
```

O script cuidará de tudo:
1. Instala o Docker (se ainda não tiver instalado).
2. Para o serviço antigo do `systemd` (evitando conflito de portas).
3. Migra seu banco `analytics.db` para `./data/analytics.db` (preserva todos os dados, visitas e anúncios!).
4. Constrói a imagem e sobe o container em segundo plano.

---

## 🛠️ 2. Deploy Manual com Docker Compose

Se preferir rodar manualmente passo a passo:

```bash
# 1. Crie a pasta de dados persistente
mkdir -p data

# 2. Se já possuir um analytics.db anterior, copie para dentro de data/
cp analytics.db data/analytics.db 2>/dev/null || true

# 3. Configure as variáveis (opcional)
cp .env.example .env

# 4. Construa a imagem e inicie o container
docker compose up -d --build
```

---

## 📋 Comandos Úteis do Dia a Dia

### Ver o status do container
```bash
docker compose ps
```

### Acompanhar logs em tempo real
```bash
docker compose logs -f
```

### Reiniciar o container
```bash
docker compose restart
```

### Atualizar para a versão mais recente do código
```bash
git pull origin main
docker compose up -d --build
```

### Parar a aplicação
```bash
docker compose down
```

---

## 💾 Persistência de Dados e Backups

Todos os seus dados (visitas, métricas, configurações de anúncios e senhas) ficam salvos na pasta local `./data/analytics.db` na sua VPS.

- **Fazer backup**: Basta copiar o arquivo `data/analytics.db`.
- **Restaurar**: Basta colocar o arquivo `analytics.db` dentro da pasta `data/`.
- Mesmo se você destruir o container ou fizer rebuild da imagem Docker, **nenhum dado é perdido**!

---

## 🌐 Configuração de Domínio / Cloudflare / Nginx

### Opção A: Usando Nginx na VPS como Proxy Reverso (Recomendado)
Se você já possui o Nginx rodando na VPS com SSL da Cloudflare, mantenha o bloco:

```nginx
location / {
    proxy_pass http://127.0.0.1:5000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;
    proxy_set_header CF-IPCountry $http_cf_ipcountry;
    
    # Suporte a downloads pesados sem timeout
    proxy_read_timeout 300s;
    proxy_connect_timeout 75s;
    proxy_buffering off;
}
```

### Opção B: Exposição Direta na Porta 80
Se você não usa Nginx na VPS e quer que o Docker responda direto na porta 80:
1. Abra o arquivo `.env`:
   ```bash
   nano .env
   ```
2. Altere `PORT=5000` para:
   ```env
   PORT=80
   ```
3. Reinicie com:
   ```bash
   docker compose up -d
   ```

---

## 💡 Dicas de Economia de Custo (VPS Baratas Recomendadas)
Como o sistema agora está otimizado com índices B-Tree e workers eficientes, você não precisa de uma VPS dedicada cara. Recomendações:
- **Hetzner Cloud**: Servidor CX22 (2 vCPU, 4GB RAM) por apenas **~€3.79/mês**.
- **DigitalOcean**: Droplet básico de $4 a $6/mês.
- **Oracle Cloud Free Tier**: Instâncias ARM gratuitas (até 4 OCPUs e 24GB de RAM gratuitos para sempre).
- **OVH / Contabo**: Planos VPS a partir de $4 a $5/mês.

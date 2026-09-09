import gzip
from flask import Flask, request, jsonify, render_template, session as flask_session, redirect, url_for, Response, stream_with_context, abort
import socket
import urllib.parse
import re
import time
import requests
import urllib3
import urllib3.util.connection as urllib3_cn
from db import init_db, get_settings, update_setting, set_admin_password, verify_admin_password, verify_admin_credentials, set_admin_credentials, log_visit, log_download, get_stats
from social_downloader import process_social_url

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Forçar resolução IPv4: elimina o delay crítico de 20s de timeout IPv6 nos servidores do Erome
urllib3_cn.allowed_gai_family = lambda: socket.AF_INET

app = Flask(__name__)
app.secret_key = 'erome-secure-session-key-9021-x8k3'

# Inicializar banco de dados de analytics e configurações
init_db()

# Sessão persistente com pool de conexões
session = requests.Session()
session.verify = False
adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=50, max_retries=2)
session.mount('https://', adapter)
session.mount('http://', adapter)

# Proteção contra Brute Force (em memória por IP)
failed_attempts = {}

def is_ip_blocked(ip):
    now = time.time()
    info = failed_attempts.get(ip)
    if info and info['blocked_until'] > now:
        return True, int((info['blocked_until'] - now) / 60) + 1
    return False, 0

def record_failed_attempt(ip):
    now = time.time()
    info = failed_attempts.setdefault(ip, {'count': 0, 'blocked_until': 0})
    info['count'] += 1
    if info['count'] >= 5:
        info['blocked_until'] = now + 900 # 15 minutos de bloqueio

def reset_failed_attempts(ip):
    failed_attempts.pop(ip, None)

def get_client_country():
    cf_country = request.headers.get('CF-IPCountry')
    if cf_country:
        return cf_country
        
    ip = request.headers.get('CF-Connecting-IP', request.remote_addr)
    if ip in ('127.0.0.1', '::1', 'localhost'):
        return 'Brasil (Local)'
    return 'Brasil'

@app.before_request
def track_visitor():
    # Registrar visita nas páginas principais
    if request.path in ('/', '/social') and request.method == 'GET':
        ip = request.headers.get('CF-Connecting-IP', request.remote_addr)
        country = get_client_country()
        log_visit(ip, country, request.path)

@app.route('/')
def index():
    settings = get_settings()
    return render_template('index.html', settings=settings)

@app.route('/social')
def social_page():
    settings = get_settings()
    return render_template('social.html', settings=settings)

@app.route('/get_social_video', methods=['POST'])
def get_social_video():
    url = request.form.get('url')
    if not url:
        return jsonify({'error': 'Por favor, insira o link do vídeo.'})
        
    result = process_social_url(url)
    if result.get('success'):
        country = get_client_country()
        log_download(result.get('title', 'Vídeo Social'), country, url=url)
        
    return jsonify(result)

@app.route('/get_video', methods=['POST'])
@app.route('/get_videos', methods=['POST'])
def get_video():
    url = request.form.get('url')
    if not url or 'erome.com' not in url:
        return jsonify({'error': 'Por favor, insira um link válido do erome.com'})

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        resp = session.get(url, headers=headers, timeout=10, verify=False)
        resp.raise_for_status()
        html = resp.text
        
        titles = re.findall(r'<title>(.*?)</title>', html)
        page_title = titles[0].replace(' - EroMe', '').replace(' - Porn Videos & Photos', '').strip() if titles else 'Video Erome'
        page_title = re.sub(r'[\/*?:"<>|]', "", page_title)
        
        mp4_links = re.findall(r'<source src="([^"]+\.mp4)"', html)
        if not mp4_links:
            mp4_links = re.findall(r'src="([^"]+\.mp4)"', html)
            
        unique_links = []
        for link in mp4_links:
            if link not in unique_links:
                unique_links.append(link)
                
        videos = []
        for i, link in enumerate(unique_links):
            vid_title = f'{page_title} - Parte {i+1}'
            safe_title = urllib.parse.quote(vid_title)
            safe_url = urllib.parse.quote(link)
            filename = f'{vid_title}.mp4'
            videos.append({
                'title': vid_title,
                'filename': filename,
                'raw_url': link,
                'url': f'/proxy_download?url={safe_url}&title={safe_title}&filename={urllib.parse.quote(filename)}'
            })
        
        return jsonify({'success': True, 'title': page_title, 'videos': videos})
    except Exception as e:
        print(f"ERRO: {e}")
        return jsonify({'error': f'Erro ao processar o link. Verifique se a URL está correta ou se o conteúdo é público. Detalhe: {e}'})

@app.route('/proxy_download')
def proxy_download():
    video_url = request.args.get('url')
    title = request.args.get('title', 'video')
    filename = request.args.get('filename')
    ext = request.args.get('ext', 'mp4').lower()
    platform = request.args.get('platform', '').lower()
    skip_count = request.args.get('skipCount', '0') in ('1', 'true', 'True')
    
    if not video_url:
        return "URL não fornecida", 400
        
    if ext not in ('mp4', 'mp3', 'webm', 'm4a', 'wav'):
        ext = 'mp4'
        
    # Headers dinâmicos de acordo com a plataforma de origem
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    }
    
    if 'erome.com' in video_url or platform == 'erome':
        headers['Referer'] = 'https://www.erome.com/'
    elif 'tiktok' in video_url or platform == 'tiktok':
        headers['Referer'] = 'https://www.tiktok.com/'
    elif 'twimg.com' in video_url or platform in ('twitter', 'x'):
        headers['Referer'] = 'https://twitter.com/'
    elif 'instagram' in video_url or platform == 'instagram':
        headers['Referer'] = 'https://www.instagram.com/'
    elif 'reddit' in video_url or 'redd.it' in video_url or platform == 'reddit':
        headers['Referer'] = 'https://www.reddit.com/'
        
    # Encaminhar cabeçalho Range para suporte a aceleração e resumo de download
    if 'Range' in request.headers:
        headers['Range'] = request.headers['Range']
    
    try:
        if not skip_count:
            try:
                country = get_client_country()
                log_download(title, country, url=video_url)
            except Exception as le:
                print("Erro log:", le)

        # Timeout estendido e streaming de alto throughput
        req = session.get(video_url, headers=headers, stream=True, verify=False, timeout=(10, 300))
        
        if req.status_code >= 400:
            return f"Erro no servidor de mídia: status {req.status_code}", req.status_code
        
        if filename:
            clean_name = re.sub(r'[\/*?:"<>|]', "", filename).strip()
        else:
            ascii_title = re.sub(r'[^a-zA-Z0-9_\- ]', '', title).strip() or 'video'
            clean_name = f"{ascii_title}.{ext}"
            
        if not clean_name.lower().endswith(f'.{ext}'):
            download_filename = f"{clean_name}.{ext}"
        else:
            download_filename = clean_name
            
        encoded_filename = urllib.parse.quote(download_filename)
        content_type = 'audio/mpeg' if ext == 'mp3' else req.headers.get('content-type', 'video/mp4')
        
        resp_headers = {
            'Content-Disposition': f'attachment; filename="{download_filename}"; filename*=UTF-8\'\'{encoded_filename}',
            'Content-Type': content_type,
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'no-cache',
            'Access-Control-Allow-Origin': '*'
        }
        
        if 'content-length' in req.headers:
            resp_headers['Content-Length'] = req.headers['content-length']
        if 'content-range' in req.headers:
            resp_headers['Content-Range'] = req.headers['content-range']
            
        def stream_data():
            try:
                # 512KB chunks: optimal for high throughput and rapid streaming
                for chunk in req.iter_content(chunk_size=512 * 1024):
                    if chunk:
                        yield chunk
            finally:
                req.close()
        
        return Response(
            stream_with_context(stream_data()),
            status=req.status_code,
            headers=resp_headers
        )
    except Exception as e:
        print(f"ERRO PROXY: {e}")
        return f"Erro ao conectar ao servidor de mídia: {str(e)}", 504

# ================= SEGURANÇA E ROTA PRIVADA OCULTA ================= #

# MODO FANTASMA / DESATIVAR PAINEL ADMIN:
# - Mude para False se quiser desligar 100% o painel admin na web.
# - Quando estiver False, qualquer tentativa de acessar o link secreto retornará Erro 404 (Não Encontrado).
# - O site de download e todos os anúncios salvos no banco continuam rodando 100% no automático!
# - Para reabrir o painel e alterar anúncios no futuro, basta voltar esta opção para True.
ENABLE_ADMIN_PANEL = True

# Qualquer tentativa de acesso a rotas comuns de admin retorna 404 estrito
@app.route('/admin')
@app.route('/admin/')
@app.route('/administrator')
@app.route('/wp-admin')
@app.route('/cpanel')
def decoy_404():
    abort(404)

@app.route('/<secret_slug>', methods=['GET'])
def secret_admin_panel(secret_slug):
    if not ENABLE_ADMIN_PANEL:
        abort(404)
        
    settings = get_settings()
    current_slug = settings.get('admin_slug', 'painel-gestao-9021')
    
    # Se o slug digitado não for exatamente o configurado, finge que a página não existe
    if secret_slug != current_slug:
        abort(404)
        
    if not flask_session.get('admin_logged'):
        return render_template('admin_login.html', current_slug=current_slug)
        
    if request.args.get('logout'):
        flask_session.pop('admin_logged', None)
        return redirect(f'/{current_slug}')
        
    stats = get_stats()
    message = request.args.get('msg')
    return render_template('admin.html', stats=stats, settings=settings, current_slug=current_slug, message=message)

@app.route('/sys-auth-verify/<secret_slug>', methods=['POST'])
def secret_admin_auth(secret_slug):
    if not ENABLE_ADMIN_PANEL:
        abort(404)
        
    settings = get_settings()
    current_slug = settings.get('admin_slug', 'painel-gestao-9021')
    
    if secret_slug != current_slug:
        abort(404)
        
    client_ip = request.headers.get('CF-Connecting-IP', request.remote_addr)
    blocked, minutes = is_ip_blocked(client_ip)
    if blocked:
        return render_template('admin_login.html', current_slug=current_slug, error=f'Acesso bloqueado por excesso de tentativas. Aguarde {minutes} minuto(s).')
        
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    
    if verify_admin_credentials(username, password):
        reset_failed_attempts(client_ip)
        flask_session['admin_logged'] = True
        return redirect(f'/{current_slug}')
    else:
        record_failed_attempt(client_ip)
        attempts = failed_attempts.get(client_ip, {}).get('count', 1)
        remaining = max(0, 5 - attempts)
        return render_template('admin_login.html', current_slug=current_slug, error=f'Credenciais incorretas! Você possui mais {remaining} tentativa(s) antes do bloqueio temporário por IP.')

@app.route('/sys-action-save/<secret_slug>', methods=['POST'])
def secret_admin_save(secret_slug):
    if not ENABLE_ADMIN_PANEL:
        abort(404)
    settings = get_settings()
    current_slug = settings.get('admin_slug', 'painel-gestao-9021')
    
    if secret_slug != current_slug or not flask_session.get('admin_logged'):
        abort(404)
        
    section = request.form.get('section', 'ads')
    
    if section == 'ads':
        fields = ['ad_top', 'ad_bottom', 'ad_left', 'ad_right', 'ad_popunder']
        for f in fields:
            update_setting(f, request.form.get(f, ''))
            
        ads_enabled = '1' if request.form.get('ads_enabled') else '0'
        update_setting('ads_enabled', ads_enabled)
        return redirect(f'/{current_slug}?msg=Anúncios atualizados com sucesso!')
        
    elif section == 'security':
        new_username = request.form.get('admin_username', '').strip()
        new_slug = request.form.get('admin_slug', '').strip()
        new_password = request.form.get('new_password', '').strip()
        
        if new_username:
            update_setting('admin_username', new_username)
            
        new_slug = re.sub(r'[^a-zA-Z0-9\-_]', '', new_slug)
        if new_slug:
            update_setting('admin_slug', new_slug)
            current_slug = new_slug
            
        if new_password:
            set_admin_password(new_password)
            
        return redirect(f'/{current_slug}?msg=Credenciais de segurança e rota privada atualizadas com sucesso!')
        
    return redirect(f'/{current_slug}')


# ================= AGGRESSIVE SEO, PAGESPEED & CACHING ================= #

@app.after_request
def pagespeed_optimize(response):
    # Cache de 1 ano para arquivos estáticos (CSS, JS, Imagens, Fontes) - PageSpeed 100
    if request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    
    # Cabeçalhos de Segurança e Boas Práticas de SEO do Google
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    
    # Compressão Gzip nativa em HTML, CSS, JS e JSON (reduz tamanho em até 80% e zera o tempo de FCP)
    accept_encoding = request.headers.get('Accept-Encoding', '')
    if (
        'gzip' in accept_encoding
        and response.status_code == 200
        and not response.direct_passthrough
        and response.content_type
        and any(t in response.content_type for t in ('text/', 'application/json', 'application/javascript', 'application/xml'))
        and len(response.get_data()) > 300
    ):
        try:
            gzip_buffer = gzip.compress(response.get_data(), compresslevel=6)
            response.set_data(gzip_buffer)
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = len(gzip_buffer)
            response.headers['Vary'] = 'Accept-Encoding'
        except Exception:
            pass
            
    return response

@app.route('/robots.txt')
def robots_txt():
    content = """# https://eromedown.org robots.txt
User-agent: *
Allow: /
Allow: /social
Allow: /static/
Disallow: /admin
Disallow: /sys-*
Disallow: /proxy_download
Disallow: /get_video
Disallow: /get_social_video

# Crawlers específicos
User-agent: Googlebot
Allow: /
Allow: /social

User-agent: Bingbot
Allow: /
Allow: /social

Sitemap: https://eromedown.org/sitemap.xml
"""
    return Response(content, mimetype='text/plain')

@app.route('/sitemap.xml')
def sitemap_xml():
    today = time.strftime('%Y-%m-%d')
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
    <url>
        <loc>https://eromedown.org/</loc>
        <lastmod>{today}</lastmod>
        <changefreq>daily</changefreq>
        <priority>1.0</priority>
        <xhtml:link rel="alternate" hreflang="x-default" href="https://eromedown.org/" />
        <xhtml:link rel="alternate" hreflang="pt" href="https://eromedown.org/?lang=pt" />
        <xhtml:link rel="alternate" hreflang="en" href="https://eromedown.org/?lang=en" />
        <xhtml:link rel="alternate" hreflang="es" href="https://eromedown.org/?lang=es" />
        <xhtml:link rel="alternate" hreflang="fr" href="https://eromedown.org/?lang=fr" />
        <xhtml:link rel="alternate" hreflang="ru" href="https://eromedown.org/?lang=ru" />
    </url>
    <url>
        <loc>https://eromedown.org/social</loc>
        <lastmod>{today}</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.8</priority>
        <xhtml:link rel="alternate" hreflang="x-default" href="https://eromedown.org/social" />
        <xhtml:link rel="alternate" hreflang="pt" href="https://eromedown.org/social?lang=pt" />
        <xhtml:link rel="alternate" hreflang="en" href="https://eromedown.org/social?lang=en" />
        <xhtml:link rel="alternate" hreflang="es" href="https://eromedown.org/social?lang=es" />
        <xhtml:link rel="alternate" hreflang="fr" href="https://eromedown.org/social?lang=fr" />
        <xhtml:link rel="alternate" hreflang="ru" href="https://eromedown.org/social?lang=ru" />
    </url>
</urlset>"""
    return Response(content, mimetype='application/xml')

@app.route('/manifest.json')
def manifest_json():
    manifest = {
        "name": "EromeDown - Erome Video Downloader",
        "short_name": "EromeDown",
        "description": "Download Erome videos, albums and photos in HD quality with one click.",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0a0c",
        "theme_color": "#ee5f96",
        "icons": [
            {
                "src": "/static/ads/cam_model.jpg",
                "sizes": "192x192",
                "type": "image/jpeg"
            }
        ]
    }
    return jsonify(manifest)

if __name__ == '__main__':
    app.run(debug=True, port=5000, threaded=True)

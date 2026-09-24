import gzip
import threading
from flask import Flask, request, jsonify, render_template, session as flask_session, redirect, url_for, Response, stream_with_context, abort
import socket
import urllib.parse
import re
import time
import requests
import urllib3
import urllib3.util.connection as urllib3_cn
from db import init_db, get_settings, update_setting, set_admin_password, verify_admin_password, verify_admin_credentials, set_admin_credentials, log_visit, log_download, get_stats, parse_device_info, resolve_country
from social_downloader import process_social_url
from multi_downloader import extract as multi_extract, detect_site, resolve_luxuretv_media

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Forçar resolução IPv4: elimina o delay crítico de 20s de timeout IPv6 nos servidores do Erome
urllib3_cn.allowed_gai_family = lambda: socket.AF_INET

app = Flask(__name__)
app.secret_key = 'erome-secure-session-key-9021-x8k3'

# Inicializar banco de dados de analytics e configurações
init_db()

# --- CACHE DE SETTINGS EM MEMÓRIA (evita SQLite em cada request) ---
_settings_cache = {'data': None, 'ts': 0}
_SETTINGS_TTL = 60  # segundos

def get_cached_settings():
    now = time.time()
    if _settings_cache['data'] is None or (now - _settings_cache['ts']) > _SETTINGS_TTL:
        _settings_cache['data'] = get_settings()
        _settings_cache['ts'] = now
    return _settings_cache['data']

def invalidate_settings_cache():
    _settings_cache['data'] = None

# --- LOG ASSÍNCRONO (não bloqueia render da página) ---
def log_visit_async(ip, country, path, **kwargs):
    def _log():
        try:
            log_visit(ip, country, path, **kwargs)
        except Exception:
            pass
    threading.Thread(target=_log, daemon=True).start()

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
    if cf_country and len(cf_country) == 2:
        return cf_country.upper()
        
    ip = request.headers.get('CF-Connecting-IP', request.remote_addr)
    if ip in ('127.0.0.1', '::1', 'localhost'):
        return 'BR'
    return 'BR'

# Assinaturas de User-Agent de bots/crawlers/scanners conhecidos
BOT_UA_SIGNATURES = [
    # Crawlers e bots de busca
    'googlebot', 'bingbot', 'slurp', 'duckduckbot', 'baiduspider', 'yandexbot',
    'sogou', 'exabot', 'facebot', 'ia_archiver', 'ahrefsbot', 'semrushbot',
    'dotbot', 'mj12bot', 'rogerbot', 'linkdexbot', 'blexbot', 'proximic',
    'sistrix', 'searchatlas', 'seobilitybot', 'rankactivelinkbot',
    # Scanners de segurança e pentest
    'nmap', 'nikto', 'sqlmap', 'masscan', 'zap/', 'burpsuite', 'nessus',
    'openvas', 'acunetix', 'w3af', 'nuclei', 'zgrab', 'go-http-client',
    'python-requests', 'python-urllib', 'libwww-perl', 'curl/', 'wget/',
    'httpx', 'httpclient', 'okhttp', 'java/', 'axios/',
    # Ferramentas de scraping/automação
    'scrapy', 'mechanize', 'phantomjs', 'selenium', 'puppeteer', 'playwright',
    'headlesschrome', 'headless', 'prerender', 'crawl', 'spider', 'bot/',
    'robot', 'fetcher', 'archiver', 'downloader', 'extractor', 'parser',
    # Monitoramento e uptime
    'uptimerobot', 'pingdom', 'statuscake', 'site24x7', 'freshping',
    'hetrixtools', 'monitor', 'checker',
    # Outros
    'dataforseo', 'bytespider', 'claude-web', 'gpt-', 'openai', 'anthropic',
]

def is_bot(ua_string):
    """Detecta bots/crawlers pelo User-Agent. Retorna True se for bot."""
    if not ua_string or len(ua_string) < 10:
        return True  # UA vazio ou muito curto = bot/script
    ua_lower = ua_string.lower()
    return any(sig in ua_lower for sig in BOT_UA_SIGNATURES)

@app.before_request
def track_visitor():
    # Registrar visita nas páginas principais (ignora bots, não bloqueia render)
    if request.path in ('/', '/social') and request.method == 'GET':
        ua = request.headers.get('User-Agent', '')
        if is_bot(ua):
            return
        ip = request.headers.get('CF-Connecting-IP', request.remote_addr)
        country = get_client_country()
        device, os_name, browser = parse_device_info(ua)
        city = request.headers.get('CF-IPCity', '')
        log_visit_async(ip, country, request.path, device=device, os_name=os_name, browser=browser, city=city)

@app.route('/')
def index():
    settings = get_cached_settings()  # Cache 60s — sem SQLite em cada request
    initial_url = request.args.get('url', '').strip()
    return render_template('index.html', settings=settings, initial_url=initial_url)

@app.route('/social')
def social_page():
    return redirect('/', code=301)

@app.route('/get_social_video', methods=['POST'])
def get_social_video():
    return jsonify({'error': 'Downloader de redes sociais desativado. Use o EromeDown para baixar vídeos do Erome.'})

@app.route('/favicon.ico')
@app.route('/favicon.png')
def favicon():
    from flask import send_from_directory
    return send_from_directory(
        app.static_folder, 'favicon.png',
        mimetype='image/png',
        max_age=86400
    )

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "EromeDown",
        "short_name": "EromeDown",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0a0c",
        "theme_color": "#0a0a0c"
    })

@app.route('/ad_slot/<slot>')
def ad_slot(slot):
    settings = get_settings()
    if settings.get('ads_enabled', '1') != '1':
        return ('', 204)
        
    ad_content = ''
    if slot == 'bottom':
        ad_content = settings.get('ad_bottom', '')
    elif slot == 'left':
        ad_content = settings.get('ad_left', '')
    elif slot == 'right':
        ad_content = settings.get('ad_right', '')
    elif slot == 'top':
        ad_content = settings.get('ad_top', '')
        
    if not ad_content or not ad_content.strip():
        return ('', 204)
        
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body, html {{ margin:0; padding:0; overflow:hidden; background:transparent; display:flex; align-items:center; justify-content:center; width:100%; height:100%; }}
</style>
</head>
<body>
{ad_content}
</body>
</html>"""
    return Response(html, mimetype='text/html')

@app.route('/sitemap.xml')
def sitemap():
    from datetime import date
    today = date.today().isoformat()
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
  <url>
    <loc>https://eromedown.org/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
    <xhtml:link rel="alternate" hreflang="pt" href="https://eromedown.org/?lang=pt"/>
    <xhtml:link rel="alternate" hreflang="en" href="https://eromedown.org/?lang=en"/>
    <xhtml:link rel="alternate" hreflang="es" href="https://eromedown.org/?lang=es"/>
    <xhtml:link rel="alternate" hreflang="fr" href="https://eromedown.org/?lang=fr"/>
    <xhtml:link rel="alternate" hreflang="ru" href="https://eromedown.org/?lang=ru"/>
    <xhtml:link rel="alternate" hreflang="x-default" href="https://eromedown.org/"/>
  </url>
</urlset>"""
    return Response(xml, mimetype='application/xml',
                    headers={'Cache-Control': 'public, max-age=86400'})

@app.route('/robots.txt')
def robots():
    txt = """User-agent: *
Allow: /
Disallow: /get_video
Disallow: /get_videos
Disallow: /proxy_download
Disallow: /get_social_video
Disallow: /ad_slot/

Sitemap: https://eromedown.org/sitemap.xml
"""
    return Response(txt, mimetype='text/plain',
                    headers={'Cache-Control': 'public, max-age=86400'})

@app.route('/api/version')
def api_version():
    return jsonify({
        'version': 'v3.4-direct-media-stream-mobile-fix',
        'status': 'online',
        'time': '2026-09-23T21:07:00-03:00',
        'supported_sites': ['erome', 'xvideos', 'pornhub', 'luxuretv']
    })

@app.route('/api/debug_luxuretv')
def debug_luxuretv():
    import shutil, subprocess, socket
    test_id = request.args.get('id', '462523')
    target_embed = f'https://en.luxuretv.com/embed/{test_id}'
    
    out = {
        'curl_path': shutil.which('curl'),
        'dns_resolution': None,
        'dns_error': None,
        'curl_embed_rc': None,
        'curl_embed_len': None,
        'curl_embed_err': None,
        'curl_embed_preview': None,
        'curl_has_stream': False,
        'requests_status': None,
        'requests_err': None,
        'requests_has_stream': False
    }
    
    # 1. Test DNS
    try:
        addr = socket.getaddrinfo('en.luxuretv.com', 443, socket.AF_INET)
        out['dns_resolution'] = [a[4][0] for a in addr]
    except Exception as e:
        out['dns_error'] = str(e)
        
    # 2. Test curl
    if out['curl_path']:
        try:
            cmd = [
                out['curl_path'], '-s', '-k', '-L',
                '-A', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                '-H', 'Referer: https://luxuretv.com/',
                '--max-time', '10',
                target_embed
            ]
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore', timeout=12)
            out['curl_embed_rc'] = p.returncode
            out['curl_embed_err'] = p.stderr[:200]
            out['curl_embed_len'] = len(p.stdout)
            out['curl_embed_preview'] = p.stdout[:300]
            out['curl_has_stream'] = 'cf-stream' in p.stdout
        except Exception as e:
            out['curl_embed_err'] = str(e)
            
    # 3. Test requests
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Referer': 'https://luxuretv.com/'
        }
        r = session.get(target_embed, headers=headers, timeout=10, verify=False)
        out['requests_status'] = r.status_code
        out['requests_has_stream'] = 'cf-stream' in r.text
        out['requests_preview'] = r.text[:300]
    except Exception as e:
        out['requests_err'] = str(e)
        
    return jsonify(out)

@app.after_request
def add_cache_headers(response):
    content_type = response.headers.get('Content-Type', '')
    if 'text/html' in content_type:
        # Permite Cloudflare cachear por 5 min (CDN), browser revalida a cada visita
        # Isso elimina o custo de Flask+SQLite em cada requisição repetida
        response.headers['Cache-Control'] = 'public, s-maxage=300, max-age=0, must-revalidate'
        response.headers['Vary'] = 'Accept-Encoding'
    return response

@app.route('/get_video', methods=['POST'])
@app.route('/get_videos', methods=['POST'])
def get_video():
    url = request.form.get('url', '').strip()
    if not url:
        return jsonify({'error': 'Por favor, insira um link válido.'})

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    # ── Detectar site e redirecionar ──────────────────────────────
    site = detect_site(url)
    if site in ('xvideos', 'pornhub', 'luxuretv'):
        try:
            result = multi_extract(url)
            # Formatar vídeos no mesmo padrão do Erome
            videos_out = []
            for v in result.get('videos', []):
                safe_url   = urllib.parse.quote(v['url'])
                safe_title = urllib.parse.quote(v['title'])
                safe_fname = urllib.parse.quote(v['filename'])
                videos_out.append({
                    'title':     v['title'],
                    'filename':  v['filename'],
                    'raw_url':   v['url'],
                    'type':      v.get('type', 'video'),
                    'quality':   v.get('quality', ''),
                    'thumbnail': v.get('thumbnail', ''),
                    'url': f'/proxy_download?url={safe_url}&title={safe_title}&filename={safe_fname}&page_url={urllib.parse.quote(url)}',
                })
            return jsonify({'success': True, 'title': result['title'], 'videos': videos_out})
        except Exception as e:
            return jsonify({'error': str(e)})

    if 'erome.com' not in url:
        return jsonify({'error': 'Site não suportado. Cole um link do Erome, XVideos, PornHub ou LuxureTV.'})

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,pt-BR;q=0.8',
            'Referer': 'https://www.erome.com/'
        }
        resp = session.get(url, headers=headers, timeout=15, verify=False)
        resp.raise_for_status()
        html = resp.text
        
        titles = re.findall(r'<title>(.*?)</title>', html, re.IGNORECASE)
        page_title = titles[0].replace(' - EroMe', '').replace(' - Porn Videos & Photos', '').strip() if titles else 'Video Erome'
        page_title = re.sub(r'[\/*?:"<>|]', "", page_title).strip() or 'Video Erome'
        
        # Procura por todos os padrões de vídeo MP4 no HTML do Erome
        mp4_candidates = []
        mp4_candidates.extend(re.findall(r'<source[^>]+(?:src|data-src)=[\"\']([^\"\']+\.mp4[^\"\']*)[\"\']', html, re.IGNORECASE))
        mp4_candidates.extend(re.findall(r'<video[^>]+(?:src|data-src)=[\"\']([^\"\']+\.mp4[^\"\']*)[\"\']', html, re.IGNORECASE))
        mp4_candidates.extend(re.findall(r'[\"\'](https?://[^\"]+?\.mp4[^\"]*?)[\"\']', html, re.IGNORECASE))
        mp4_candidates.extend(re.findall(r'[\"\'](//[^\"]+?\.mp4[^\"]*?)[\"\']', html, re.IGNORECASE))
        
        unique_links = []
        for raw_link in mp4_candidates:
            clean_link = raw_link.strip().replace('&amp;', '&')
            if clean_link.startswith('//'):
                clean_link = 'https:' + clean_link
            elif clean_link.startswith('/'):
                clean_link = 'https://www.erome.com' + clean_link
            elif not clean_link.startswith('http'):
                clean_link = 'https://' + clean_link
                
            if clean_link not in unique_links:
                unique_links.append(clean_link)
                
        videos = []
        for i, link in enumerate(unique_links):
            vid_title = f'{page_title} - Parte {i+1}' if len(unique_links) > 1 else page_title
            safe_title = urllib.parse.quote(vid_title)
            safe_url = urllib.parse.quote(link)
            filename = f'{vid_title}.mp4'
            videos.append({
                'title': vid_title,
                'filename': filename,
                'raw_url': link,
                'url': f'/proxy_download?url={safe_url}&title={safe_title}&filename={urllib.parse.quote(filename)}&page_url={urllib.parse.quote(url)}'
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
        return "URL do vídeo ausente", 400
        
    if video_url.startswith('//'):
        video_url = 'https:' + video_url
    elif not video_url.startswith('http'):
        video_url = 'https://' + video_url
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Referer': 'https://www.erome.com/',
        'Origin': 'https://www.erome.com'
    }
    
    page_url_arg = request.args.get('page_url', '')
    if 'erome.com' in video_url or platform == 'erome':
        headers['Referer'] = 'https://www.erome.com/'
    elif 'luxuretv.com' in video_url or 'luxuretv' in page_url_arg or platform == 'luxuretv':
        headers['Referer'] = 'https://luxuretv.com/'
        headers['Origin'] = 'https://luxuretv.com'
    elif 'xvideos.com' in video_url or 'xvideos' in page_url_arg or platform == 'xvideos':
        headers['Referer'] = 'https://www.xvideos.com/'
        headers['Origin'] = 'https://www.xvideos.com'
    elif 'pornhub.com' in video_url or 'phncdn.com' in video_url or 'pornhub' in page_url_arg or platform == 'pornhub':
        headers['Referer'] = 'https://www.pornhub.com/'
        headers['Origin'] = 'https://www.pornhub.com'
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
    
    # Se for LuxureTV com cf-stream, resolve diretamente para o servidor de mídia (mediaX.luxuretv.com)
    # eliminando 100% o bloqueio de Cloudflare Turnstile 403 em IPs de Datacenter/VPS
    if 'cf-stream' in video_url or 'luxuretv' in video_url:
        try:
            resolved_url = resolve_luxuretv_media(video_url)
            if resolved_url and resolved_url != video_url:
                video_url = resolved_url
                headers['Referer'] = 'https://luxuretv.com/'
                headers['Origin'] = 'https://luxuretv.com'
        except Exception as err:
            print("Erro ao resolver luxuretv media:", err)

    try:
        if not skip_count:
            try:
                country = get_client_country()
                ua = request.headers.get('User-Agent', '')
                device, _, _ = parse_device_info(ua)
                page_url = request.args.get('page_url') or video_url
                log_download(title, country, url=page_url, device=device)
            except Exception as le:
                print("Erro log:", le)

        # Timeout estendido e streaming de alto throughput
        req = session.get(video_url, headers=headers, stream=True, verify=False, timeout=(10, 300))
        
        # Fallback de segurança para LuxureTV caso a primeira tentativa tenha recebido 403
        if req.status_code >= 400 and ('luxuretv' in video_url or 'cf-stream' in video_url):
            try:
                retry_url = resolve_luxuretv_media(video_url)
                if retry_url and retry_url != video_url:
                    video_url = retry_url
                    headers['Referer'] = 'https://luxuretv.com/'
                    headers['Origin'] = 'https://luxuretv.com'
                    req = session.get(video_url, headers=headers, stream=True, verify=False, timeout=(10, 300))
            except Exception:
                pass

        if req.status_code >= 400:
            return f"Erro no servidor de mídia: status {req.status_code}", req.status_code
        
        # Sanitização robusta do nome do arquivo
        clean_name = re.sub(r'[\\/*?:"<>|\r\n\t]', "", (filename or title or 'video')).strip()
        if not clean_name:
            clean_name = 'video'

        # Prefixo de marca no nome do arquivo
        BRAND_PREFIX = 'eromedown.org - '
        if not clean_name.startswith(BRAND_PREFIX):
            clean_name = BRAND_PREFIX + clean_name

        if not clean_name.lower().endswith(f'.{ext}'):
            download_filename = f"{clean_name}.{ext}"
        else:
            download_filename = clean_name

        # Fallback ASCII estrito para navegadores móveis (Safari iOS / Android)
        ascii_fallback = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', download_filename)
        if not ascii_fallback.lower().endswith(f'.{ext}'):
            ascii_fallback = f"{ascii_fallback}.{ext}"

        encoded_filename = urllib.parse.quote(download_filename)
        
        # video/mp4 garante compatibilidade nativa com Galeria/Player no Android e iOS Safari
        content_type = 'audio/mpeg' if ext == 'mp3' else 'video/mp4'
        
        resp_headers = {
            'Content-Disposition': f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded_filename}',
            'Content-Type': content_type,
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
            'Access-Control-Allow-Origin': '*',
            'X-Content-Type-Options': 'nosniff'
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

def verify_turnstile(token, secret_key, client_ip=None):
    if not token or not secret_key:
        return False
    try:
        data = {
            'secret': secret_key,
            'response': token
        }
        if client_ip:
            data['remoteip'] = client_ip
        resp = requests.post('https://challenges.cloudflare.com/turnstile/v0/siteverify', data=data, timeout=5)
        res_json = resp.json()
        return res_json.get('success', False)
    except Exception as e:
        print(f"[TURNSTILE WARNING] Falha na requisição: {e}")
        return True

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
        turnstile_enabled = settings.get('turnstile_enabled', '1') == '1'
        turnstile_site_key = settings.get('turnstile_site_key', '1x00000000000000000000AA')
        return render_template('admin_login.html', 
                               current_slug=current_slug,
                               turnstile_enabled=turnstile_enabled,
                               turnstile_site_key=turnstile_site_key)
        
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
    turnstile_enabled = settings.get('turnstile_enabled', '1') == '1'
    turnstile_site_key = settings.get('turnstile_site_key', '1x00000000000000000000AA')
    turnstile_secret_key = settings.get('turnstile_secret_key', '1x0000000000000000000000000000000AA')

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()

    # Validação do Cloudflare Turnstile
    if turnstile_enabled and turnstile_secret_key:
        turnstile_token = request.form.get('cf-turnstile-response', '').strip()
        if not turnstile_token:
            return render_template('admin_login.html', 
                                   current_slug=current_slug,
                                   turnstile_enabled=turnstile_enabled,
                                   turnstile_site_key=turnstile_site_key,
                                   error='Por favor, complete a verificação do Cloudflare Turnstile.')
        if not verify_turnstile(turnstile_token, turnstile_secret_key, client_ip):
            return render_template('admin_login.html', 
                                   current_slug=current_slug,
                                   turnstile_enabled=turnstile_enabled,
                                   turnstile_site_key=turnstile_site_key,
                                   error='Validação do Cloudflare Turnstile falhou. Tente novamente.')

    # Se as credenciais estiverem corretas, autentica imediatamente e limpa qualquer bloqueio por tentativas
    if verify_admin_credentials(username, password):
        reset_failed_attempts(client_ip)
        flask_session['admin_logged'] = True
        return redirect(f'/{current_slug}')

    if blocked:
        return render_template('admin_login.html', 
                               current_slug=current_slug, 
                               turnstile_enabled=turnstile_enabled,
                               turnstile_site_key=turnstile_site_key,
                               error=f'Acesso bloqueado por excesso de tentativas. Aguarde {minutes} minuto(s).')

    record_failed_attempt(client_ip)
    attempts = failed_attempts.get(client_ip, {}).get('count', 1)
    remaining = max(0, 5 - attempts)
    return render_template('admin_login.html', 
                           current_slug=current_slug, 
                           turnstile_enabled=turnstile_enabled,
                           turnstile_site_key=turnstile_site_key,
                           error=f'Credenciais incorretas! Verifique seu usuário e senha. Restam {remaining} tentativa(s).')

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
        fields = ['ad_top', 'ad_bottom', 'ad_left', 'ad_right', 'ad_popunder', 'ad_mobile']
        for f in fields:
            update_setting(f, request.form.get(f, ''))
            
        ads_enabled = '1' if request.form.get('ads_enabled') else '0'
        update_setting('ads_enabled', ads_enabled)
        invalidate_settings_cache()
        return redirect(f'/{current_slug}?msg=Anúncios atualizados com sucesso!')
        
    elif section == 'security':
        new_username = request.form.get('admin_username', '').strip()
        new_slug = request.form.get('admin_slug', '').strip()
        new_password = request.form.get('new_password', '').strip()
        
        turnstile_enabled = '1' if request.form.get('turnstile_enabled') else '0'
        turnstile_site_key = request.form.get('turnstile_site_key', '').strip()
        turnstile_secret_key = request.form.get('turnstile_secret_key', '').strip()
        
        update_setting('turnstile_enabled', turnstile_enabled)
        if turnstile_site_key:
            update_setting('turnstile_site_key', turnstile_site_key)
        if turnstile_secret_key:
            update_setting('turnstile_secret_key', turnstile_secret_key)
        
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

@app.route('/<secret_slug>/api/stats', methods=['GET'])
def secret_admin_api_stats(secret_slug):
    if not ENABLE_ADMIN_PANEL:
        abort(404)
    settings = get_settings()
    current_slug = settings.get('admin_slug', 'painel-gestao-9021')
    if secret_slug != current_slug or not flask_session.get('admin_logged'):
        abort(403)
    return jsonify(get_stats())


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
Allow: /static/
Disallow: /admin
Disallow: /sys-*
Disallow: /painel-*
Disallow: /proxy_download
Disallow: /get_video

# Crawlers específicos
User-agent: Googlebot
Allow: /
Allow: /static/

User-agent: Bingbot
Allow: /
Allow: /static/

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

@app.route('/<path:direct_url>')
def direct_url_handler(direct_url):
    # Proteção de rotas internas e estáticas
    if direct_url.startswith(('static/', 'api/', 'ad_slot/', 'manifest.json', 'robots.txt', 'sitemap.xml', 'admin', 'get_video', 'get_videos', 'proxy_download', 'login', 'logout')):
        abort(404)

    raw = direct_url.strip()
    if request.query_string:
        raw += '?' + request.query_string.decode('utf-8', errors='ignore')

    # Normalizar https:/ ou http:/ que alguns proxies/navegadores contraem
    if raw.startswith('https:/') and not raw.startswith('https://'):
        raw = 'https://' + raw[7:]
    elif raw.startswith('http:/') and not raw.startswith('http://'):
        raw = 'http://' + raw[6:]
    elif not raw.startswith(('http://', 'https://')):
        raw = 'https://' + raw

    # Verificar se pertence aos sites suportados
    supported_domains = ('erome.com', 'xvideos.com', 'pornhub.com', 'luxuretv.com')
    if any(domain in raw.lower() for domain in supported_domains):
        return redirect(f"/?url={urllib.parse.quote(raw, safe=':/?=&%')}")

    abort(404)

if __name__ == '__main__':
    app.run(debug=True, port=5000, threaded=True)

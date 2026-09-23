"""
multi_downloader.py — XVideos, PornHub & LuxureTV extractor
"""
import re, json, requests, urllib3, subprocess, shutil, socket
import urllib3.util.connection as urllib3_cn

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
urllib3_cn.allowed_gai_family = lambda: socket.AF_INET

_s = requests.Session()
_s.verify = False
_a = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=2)
_s.mount('https://', _a); _s.mount('http://', _a)

UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

def _fetch_page(url, referer='https://luxuretv.com/'):
    # 1. Tentar curl primeiro com -k e suporte a HTTP/1.1 para contornar Cloudflare em VPS
    curl_bin = shutil.which('curl')
    if curl_bin:
        for extra_flags in [[], ['--http1.1']]:
            try:
                cmd = [
                    curl_bin, '-s', '-k', '-L',
                    '-A', UA['User-Agent'],
                    '-H', f'Referer: {referer}',
                    '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    '-H', 'Accept-Language: en-US,en;q=0.9,pt-BR;q=0.8',
                    '--compressed',
                    '--max-time', '15',
                ] + extra_flags + [url]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore', timeout=18)
                if res.returncode == 0 and res.stdout and len(res.stdout) > 200:
                    if 'Just a moment...' not in res.stdout and 'Attention Required! | Cloudflare' not in res.stdout:
                        return res.stdout
            except Exception:
                pass

    # 2. Fallback para requests session
    try:
        headers = {
            **UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': referer
        }
        r = _s.get(url, headers=headers, timeout=15)
        if r.status_code == 200 and r.text:
            if 'Just a moment...' not in r.text and 'Attention Required! | Cloudflare' not in r.text:
                return r.text
    except Exception:
        pass
    return ''

def detect_site(url):
    u = url.lower()
    if 'xvideos.com' in u: return 'xvideos'
    if 'pornhub.com' in u: return 'pornhub'
    if 'luxuretv.com' in u: return 'luxuretv'
    return None

def _clean(t):
    return re.sub(r'[\\/*?:"<>|\r\n\t]', '', t).strip() or 'video'

def _xv_thumb(html):
    m = re.search(r'"thumbUrl"\s*:\s*"([^"]+)"', html)
    if m: return m.group(1).replace('\\/', '/')
    m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
    return m.group(1) if m else ''

def _xvideos_extract(url):
    resp = _s.get(url, headers={**UA, 'Referer': 'https://www.xvideos.com/'}, timeout=20)
    resp.raise_for_status()
    html = resp.text
    t = re.search(r'<title>(.*?)</title>', html, re.I | re.S)
    title = _clean(re.sub(r'\s*[-|]\s*XVIDEOS\.COM\s*$', '', t.group(1) if t else 'XVideos', flags=re.I).strip()) or 'XVideos'
    pats = [
        r'setVideoUrlHigh\(["\']([ ^"\']+\.mp4[^"\']*)["\']\)',
        r'setVideoUrlLow\(["\']([ ^"\']+\.mp4[^"\']*)["\']\)',
        r'setVideoHLS\(["\']([ ^"\']+\.m3u8[^"\']*)["\']\)',
        r'"videoUrl"\s*:\s*"([^"]+\.mp4[^"]*)"',
        r'"([^"]+cdn[^"]+\.mp4[^"]*)"',
    ]
    found = []
    for p in pats:
        for m in re.finditer(p, html, re.I):
            raw = m.group(1).replace('\\/', '/').replace('\\u0026', '&').strip()
            if raw not in found: found.append(raw)
    if not found:
        raise ValueError('Nenhum vídeo encontrado nesta página do XVideos. Verifique se o link é válido e público.')
    mp4s = [u for u in found if '.mp4' in u]
    best = mp4s[0] if mp4s else found[0]
    ext = 'mp4' if '.mp4' in best else 'm3u8'
    return {'title': title, 'videos': [{'title': title, 'filename': f'{title}.{ext}', 'url': best, 'type': 'video', 'quality': 'HD', 'thumbnail': _xv_thumb(html)}]}

def _pornhub_extract(url):
    resp = _s.get(url, headers={**UA, 'Referer': 'https://www.pornhub.com/'}, timeout=20)
    resp.raise_for_status()
    html = resp.text
    t = re.search(r'<title>(.*?)</title>', html, re.I | re.S)
    title = _clean(re.sub(r'\s*[-|]\s*Pornhub\.com\s*$', '', t.group(1) if t else 'PornHub', flags=re.I).strip()) or 'PornHub'
    thumb = ''
    tm = re.search(r'"image_url"\s*:\s*"([^"]+)"', html) or re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
    if tm: thumb = tm.group(1).replace('\\/', '/').replace('\\u002F', '/')
    fv = re.search(r'var\s+flashvars_\d+\s*=\s*(\{.*?\});\s*\n', html, re.S)
    defs = []
    if fv:
        try: defs = json.loads(fv.group(1)).get('mediaDefinitions', [])
        except Exception: pass
    if not defs:
        md = re.search(r'"mediaDefinitions"\s*:\s*(\[.*?\])', html, re.S)
        if md:
            try: defs = json.loads(md.group(1))
            except Exception: pass
    mp4s = [d for d in defs if isinstance(d, dict) and d.get('format') == 'mp4' and d.get('videoUrl')]
    if not mp4s:
        raw = re.findall(r'"videoUrl"\s*:\s*"([^"]+\.mp4[^"]*)"', html)
        if not raw: raise ValueError('Nenhum vídeo MP4 encontrado. O vídeo pode ser premium ou privado.')
        return {'title': title, 'videos': [{'title': title, 'filename': f'{title}.mp4', 'url': raw[0].replace('\\/', '/'), 'type': 'video', 'quality': 'HD', 'thumbnail': thumb}]}
    mp4s.sort(key=lambda d: int(d.get('quality', 0)) if str(d.get('quality', '')).isdigit() else 0, reverse=True)
    videos, seen = [], set()
    for d in mp4s:
        vu = d.get('videoUrl', '').replace('\\/', '/').replace('\\u0026', '&').strip()
        if not vu or vu in seen: continue
        seen.add(vu)
        q = d.get('quality', '')
        label = f'{title} [{q}p]' if q else title
        videos.append({'title': label, 'filename': f'{title} [{q}p].mp4' if q else f'{title}.mp4', 'url': vu, 'type': 'video', 'quality': f'{q}p' if q else 'HD', 'thumbnail': thumb})
    if not videos: raise ValueError('Nenhum vídeo encontrado.')
    return {'title': title, 'videos': videos}

def _luxuretv_extract(url):
    # 1. Parse video ID
    id_m = re.search(r'[-_/](\d+)\.html', url) or re.search(r'/embed/(\d+)', url) or re.search(r'(\d+)', url)
    vid_id = id_m.group(1) if id_m else None

    # 2. Derive title from slug as high-quality default
    slug_title = 'LuxureTV'
    slug_m = re.search(r'/videos/(?:[^/]+/)?([^/]+?)(?:-\d+)?\.html', url)
    if slug_m:
        slug = re.sub(r'-\d+$', '', slug_m.group(1))
        clean_slug = re.sub(r'\s+', ' ', slug.replace('-', ' ')).strip().title()
        slug_title = _clean(clean_slug)

    title = slug_title or 'LuxureTV'
    thumb = ''
    vid_url = None

    # 3. Strategy 1: Fetch main video page
    html_main = _fetch_page(url, referer='https://luxuretv.com/')
    if html_main:
        t = re.search(r'<title>(.*?)</title>', html_main, re.I | re.S)
        if t:
            raw_title = re.sub(r'\s*[-|]\s*LuxureTV(?:\.com)?\s*$', '', t.group(1), flags=re.I).strip()
            parsed_title = _clean(raw_title)
            if parsed_title:
                title = parsed_title

        th_m = re.search(r'poster=["\']([^"\']+)["\']', html_main, re.I) or \
               re.search(r'"thumbnailUrl"\s*:\s*"([^"]+)"', html_main, re.I) or \
               re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html_main, re.I)
        if th_m:
            thumb = th_m.group(1).replace('\\/', '/')

        src_matches = re.findall(r'<source[^>]+src=["\']([^"\']+)["\']', html_main, re.I)
        for s in src_matches:
            if 'cf-stream' in s and (not vid_id or vid_id in s):
                vid_url = s.replace('&amp;', '&').strip()
                break
        if not vid_url:
            for s in src_matches:
                if 'cf-stream' in s and 'videoai' not in s:
                    vid_url = s.replace('&amp;', '&').strip()
                    break

    # 4. Strategy 2: If main page didn't yield stream, fetch embed endpoints
    if not vid_url and vid_id:
        embed_endpoints = [
            f'https://en.luxuretv.com/embed/{vid_id}',
            f'https://luxuretv.com/embed/{vid_id}'
        ]
        for ep in embed_endpoints:
            html_embed = _fetch_page(ep, referer='https://luxuretv.com/')
            if html_embed:
                src_m = re.search(r'<source[^>]+src=["\']([^"\']*(?:cf-stream|media\.luxuretv)[^"\']*)["\']', html_embed, re.I)
                if not src_m:
                    src_m = re.search(r'<source[^>]+src=["\']([^"\']+)["\']', html_embed, re.I)
                if src_m:
                    candidate = src_m.group(1).replace('&amp;', '&').strip()
                    if 'videoai' not in candidate:
                        vid_url = candidate
                if not thumb:
                    th_m = re.search(r'poster=["\']([^"\']+)["\']', html_embed, re.I)
                    if th_m:
                        thumb = th_m.group(1).replace('\\/', '/')
                if vid_url:
                    break

    # 5. Strategy 3: Cloudflare Turnstile bypass for datacenter/VPS IPs via Jina Reader
    if not vid_url and vid_id:
        curl_bin = shutil.which('curl')
        if curl_bin:
            for ep in [f'https://en.luxuretv.com/embed/{vid_id}', f'https://luxuretv.com/embed/{vid_id}']:
                try:
                    jina_url = f'https://r.jina.ai/{ep}'
                    cmd = [curl_bin, '-s', '-L', '-H', 'X-Return-Format: html', '--max-time', '15', jina_url]
                    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore', timeout=18)
                    if p.returncode == 0 and p.stdout:
                        src_m = re.search(r'src=["\']([^"\']*(?:cf-stream)[^"\']*)["\']', p.stdout)
                        if src_m:
                            candidate = src_m.group(1).replace('&amp;', '&').strip()
                            if 'videoai' not in candidate:
                                vid_url = candidate
                        if not thumb:
                            th_m = re.search(r'poster=["\']([^"\']+)["\']', p.stdout)
                            if th_m:
                                thumb = th_m.group(1).replace('\\/', '/')
                        if vid_url:
                            break
                except Exception:
                    pass

    if not vid_url:
        raise ValueError('Nenhum vídeo MP4 encontrado nesta página do LuxureTV. Verifique se o link está correto. (Build: v3.3-jina-cf-bypass)')

    return {
        'title': title,
        'videos': [{
            'title': title,
            'filename': f'{title}.mp4',
            'url': vid_url,
            'type': 'video',
            'quality': 'HD',
            'thumbnail': thumb,
        }]
    }

def extract(url):
    site = detect_site(url)
    if site == 'xvideos': return _xvideos_extract(url)
    if site == 'pornhub': return _pornhub_extract(url)
    if site == 'luxuretv': return _luxuretv_extract(url)
    raise ValueError(f'Site não suportado: {url}')


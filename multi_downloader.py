"""
multi_downloader.py — XVideos & PornHub extractor (sem yt-dlp)
"""
import re, json, requests, urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_s = requests.Session()
_s.verify = False
_a = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=2)
_s.mount('https://', _a); _s.mount('http://', _a)

UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

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
        slug_title = _clean(slug.replace('-', ' ').title())

    title = slug_title or 'LuxureTV'
    thumb = ''
    vid_url = None

    browser_headers = {
        **UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,pt-BR;q=0.8',
        'Referer': 'https://luxuretv.com/',
        'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Upgrade-Insecure-Requests': '1',
    }

    # 3. Strategy A: Extract stream directly from embed endpoint (bypasses Cloudflare bot challenge)
    if vid_id:
        embed_endpoints = [
            f'https://en.luxuretv.com/embed/{vid_id}',
            f'https://luxuretv.com/embed/{vid_id}'
        ]
        for ep in embed_endpoints:
            try:
                r_embed = _s.get(ep, headers={**browser_headers, 'Referer': 'https://luxuretv.com/'}, timeout=12)
                if r_embed.status_code == 200 and r_embed.text:
                    src_m = re.search(r'<source[^>]+src=["\']([^"\']*(?:cf-stream|media\.luxuretv)[^"\']*)["\']', r_embed.text, re.I)
                    if not src_m:
                        src_m = re.search(r'<source[^>]+src=["\']([^"\']+)["\']', r_embed.text, re.I)
                    if src_m:
                        vid_url = src_m.group(1).replace('&amp;', '&').strip()

                    th_m = re.search(r'poster=["\']([^"\']+)["\']', r_embed.text, re.I)
                    if th_m:
                        thumb = th_m.group(1).replace('\\/', '/')
                    if vid_url:
                        break
            except Exception:
                pass

    # 4. Strategy B: Attempt main page for better title/stream if embed didn't get vid_url or to improve title
    try:
        resp = _s.get(url, headers={**browser_headers, 'Referer': 'https://luxuretv.com/'}, timeout=15)
        if resp.status_code == 200:
            html = resp.text
            t = re.search(r'<title>(.*?)</title>', html, re.I | re.S)
            if t:
                raw_title = t.group(1)
                raw_title = re.sub(r'\s*[-|]\s*LuxureTV(?:\.com)?\s*$', '', raw_title, flags=re.I).strip()
                parsed_title = _clean(raw_title)
                if parsed_title:
                    title = parsed_title

            if not thumb:
                th_m = re.search(r'poster=["\']([^"\']+)["\']', html) or \
                       re.search(r'"thumbnailUrl"\s*:\s*"([^"]+)"', html) or \
                       re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
                if th_m:
                    thumb = th_m.group(1).replace('\\/', '/')

            if not vid_url:
                source_m = re.search(r'<video[^>]*id=["\']thisPlayer["\'][^>]*>.*?<source[^>]+src=["\']([^"\']+)["\']', html, re.DOTALL | re.I) or \
                           re.search(r'<source[^>]+src=["\']([^"\']*(?:cf-stream|media\.luxuretv)[^"\']*)["\']', html, re.I) or \
                           re.search(r'["\'](https?://[^"\']*(?:cf-stream)[^"\']*)["\']', html, re.I)
                if source_m:
                    vid_url = source_m.group(1).replace('&amp;', '&').strip()
    except Exception:
        # If main page fails (e.g. 403 on datacenter IP), proceed gracefully with embed result
        pass

    if not vid_url:
        raise ValueError('Nenhum vídeo MP4 encontrado nesta página do LuxureTV. Verifique se o link está correto.')

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


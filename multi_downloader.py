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
    resp = _s.get(url, headers={**UA, 'Referer': 'https://luxuretv.com/'}, timeout=20)
    resp.raise_for_status()
    html = resp.text

    # Title
    t = re.search(r'<title>(.*?)</title>', html, re.I | re.S)
    raw_title = t.group(1) if t else 'LuxureTV'
    raw_title = re.sub(r'\s*[-|]\s*LuxureTV(?:\.com)?\s*$', '', raw_title, flags=re.I).strip()
    title = _clean(raw_title) or 'LuxureTV'

    # Thumbnail
    thumb = ''
    th_m = re.search(r'poster=["\']([^"\']+)["\']', html)
    if not th_m:
        th_m = re.search(r'"thumbnailUrl"\s*:\s*"([^"]+)"', html)
    if not th_m:
        th_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
    if th_m:
        thumb = th_m.group(1).replace('\\/', '/')

    # Video stream URL
    source_m = re.search(r'<video[^>]*id=["\']thisPlayer["\'][^>]*>.*?<source[^>]+src=["\']([^"\']+)["\']', html, re.DOTALL | re.I)
    if not source_m:
        source_m = re.search(r'<source[^>]+src=["\']([^"\']*(?:cf-stream|media\.luxuretv)[^"\']*)["\']', html, re.I)
    if not source_m:
        source_m = re.search(r'["\'](https?://[^"\']*(?:cf-stream)[^"\']*)["\']', html, re.I)

    if not source_m:
        raise ValueError('Nenhum vídeo MP4 encontrado nesta página do LuxureTV.')

    vid_url = source_m.group(1).replace('&amp;', '&').strip()
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


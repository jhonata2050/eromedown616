import socket
import ssl
import urllib.parse
import urllib3
import urllib3.util.connection as urllib3_cn
import requests
import re
import yt_dlp

# Forçar resolução IPv4 para eliminar timeouts em conexões brasileiras
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
urllib3_cn.allowed_gai_family = lambda: socket.AF_INET
ssl._create_default_https_context = ssl._create_unverified_context

def get_platform_name(url):
    url_lower = url.lower()
    if 'tiktok.com' in url_lower:
        return 'TikTok'
    elif 'instagram.com' in url_lower:
        return 'Instagram'
    elif 'twitter.com' in url_lower or 'x.com' in url_lower:
        return 'Twitter / X'
    elif 'reddit.com' in url_lower or 'redd.it' in url_lower:
        return 'Reddit'
    elif 'pinterest.com' in url_lower or 'pin.it' in url_lower:
        return 'Pinterest'
    elif 'facebook.com' in url_lower or 'fb.watch' in url_lower:
        return 'Facebook'
    elif 'kwai.com' in url_lower:
        return 'Kwai'
    elif 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        return 'YouTube Shorts'
    return 'Redes Sociais'

def resolve_short_url(url):
    """Resolve links encurtados de redes sociais para obter a URL de destino"""
    short_domains = ['vm.tiktok.com', 'vt.tiktok.com', '/t/', 't.co', 'youtu.be', 'fb.watch', 'pin.it']
    if any(s in url.lower() for s in short_domains):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
            }
            r = requests.head(url, allow_redirects=True, timeout=6, verify=False, headers=headers)
            if r.url and r.url != url:
                return r.url
        except Exception:
            pass
    return url

def extract_tiktok(url):
    """Extrai vídeo do TikTok sem marca d'água em altíssima velocidade via TikWM"""
    url = resolve_short_url(url)
    try:
        api_url = "https://www.tikwm.com/api/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        }
        res = requests.post(api_url, data={'url': url, 'hd': 1}, headers=headers, verify=False, timeout=10)
        data = res.json().get('data', {})
        
        if data and (data.get('play') or data.get('hdplay')):
            title = data.get('title') or 'Vídeo TikTok'
            author = data.get('author', {}).get('nickname') or data.get('author', {}).get('unique_id') or 'TikTok'
            cover = data.get('cover') or data.get('origin_cover')
            
            clean_title = f"{title[:70]} (@{author})"
            safe_title = urllib.parse.quote(clean_title)
            
            videos = []
            
            # 1. Vídeo Sem Marca d'Água (HD ou Normal)
            play_url = data.get('hdplay') or data.get('play')
            if play_url:
                if not play_url.startswith('http'):
                    play_url = 'https://www.tikwm.com' + play_url
                proxy_url = f"/proxy_download?url={urllib.parse.quote(play_url)}&title={safe_title}&ext=mp4&platform=tiktok"
                videos.append({
                    'label': '🎬 Baixar Vídeo MP4 (Sem Marca d\'Água)',
                    'url': proxy_url,
                    'direct_url': play_url,
                    'quality': 'HD Sem Marca',
                    'is_audio': False
                })
                
            # 2. Áudio Original MP3
            music_url = data.get('music')
            if music_url:
                if not music_url.startswith('http'):
                    music_url = 'https://www.tikwm.com' + music_url
                proxy_music = f"/proxy_download?url={urllib.parse.quote(music_url)}&title={safe_title}&ext=mp3&platform=tiktok"
                videos.append({
                    'label': '🎵 Baixar Áudio Original (MP3)',
                    'url': proxy_music,
                    'direct_url': music_url,
                    'quality': 'MP3',
                    'is_audio': True
                })
                
            return {
                'success': True,
                'platform': 'TikTok',
                'title': clean_title,
                'thumbnail': cover,
                'videos': videos
            }
    except Exception as e:
        print(f"Erro TikWM: {e}")
    return None

def extract_generic_ytdlp(url):
    """Extrator universal com yt-dlp tunado para redes sociais"""
    url = resolve_short_url(url)
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'skip_download': True,
        'source_address': '0.0.0.0',
        'socket_timeout': 15,
        'noplaylist': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        }
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        raw_title = info.get('title') or 'Vídeo Social'
        title = re.sub(r'[\\/*?:"<>|]', "", raw_title).strip()
        safe_title = urllib.parse.quote(title[:80])
        thumbnail = info.get('thumbnail')
        platform = get_platform_name(url)
        
        videos = []
        
        # 1. Tentar direct URL
        direct_url = info.get('url')
        if direct_url:
            proxy_url = f"/proxy_download?url={urllib.parse.quote(direct_url)}&title={safe_title}&ext=mp4&platform={platform.lower()}"
            videos.append({
                'label': '🎬 Baixar Vídeo MP4',
                'url': proxy_url,
                'direct_url': direct_url,
                'quality': 'Melhor Qualidade',
                'is_audio': False
            })
        elif info.get('formats'):
            # Priorizar formatos progressivos (vídeo + áudio juntos)
            prog_formats = [f for f in info.get('formats', []) if f.get('url') and f.get('vcodec') != 'none' and f.get('acodec') != 'none']
            if prog_formats:
                best = prog_formats[-1]
                res = best.get('resolution') or f"{best.get('height', 'HD')}p"
                proxy_url = f"/proxy_download?url={urllib.parse.quote(best['url'])}&title={safe_title}&ext=mp4&platform={platform.lower()}"
                videos.append({
                    'label': f"🎬 Baixar Vídeo MP4 ({res})",
                    'url': proxy_url,
                    'direct_url': best['url'],
                    'quality': res,
                    'is_audio': False
                })
            else:
                video_formats = [f for f in info.get('formats', []) if f.get('url') and f.get('vcodec') != 'none']
                if video_formats:
                    best = video_formats[-1]
                    res = best.get('resolution') or 'HD'
                    proxy_url = f"/proxy_download?url={urllib.parse.quote(best['url'])}&title={safe_title}&ext=mp4&platform={platform.lower()}"
                    videos.append({
                        'label': f"🎬 Baixar Vídeo MP4 ({res})",
                        'url': proxy_url,
                        'direct_url': best['url'],
                        'quality': res,
                        'is_audio': False
                    })
                    
        if not videos and info.get('url'):
            proxy_url = f"/proxy_download?url={urllib.parse.quote(info['url'])}&title={safe_title}&ext=mp4&platform={platform.lower()}"
            videos.append({
                'label': '🎬 Baixar Arquivo MP4',
                'url': proxy_url,
                'direct_url': info['url'],
                'quality': 'Padrão',
                'is_audio': False
            })
            
        if videos:
            return {
                'success': True,
                'platform': platform,
                'title': title[:100],
                'thumbnail': thumbnail,
                'videos': videos
            }
    return None

def process_social_url(url):
    if not url:
        return {'error': 'Por favor, insira o link do vídeo.'}
        
    url = url.strip()
    platform = get_platform_name(url)
    
    # 1. Se for TikTok, extrai sem marca d'água via API de alta velocidade
    if platform == 'TikTok':
        res = extract_tiktok(url)
        if res:
            return res
            
    # 2. Tentar extrator universal yt-dlp
    try:
        res = extract_generic_ytdlp(url)
        if res:
            return res
    except Exception as e:
        print(f"Erro yt-dlp: {e}")
        
    # Mensagens de erro claras e orientadas
    if platform == 'Instagram':
        return {
            'error': 'Não foi possível extrair este conteúdo do Instagram. Verifique se o perfil é público (perfis privados ou com login obrigatório não são suportados).'
        }
    elif platform == 'Twitter / X':
        return {
            'error': 'Não foi possível extrair o vídeo do Twitter / X. Verifique se o post contém vídeo e se a conta é pública.'
        }
    return {
        'error': f'Não foi possível extrair o vídeo de {platform}. Verifique se o link está correto e se o post é público.'
    }

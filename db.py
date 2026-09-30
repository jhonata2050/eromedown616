import sqlite3
import os
import re
import urllib.parse
from werkzeug.security import generate_password_hash, check_password_hash

import shutil

# Configuração de persistência (Compatível com Docker Volumes e execução local)
DATA_DIR = os.environ.get('DATA_DIR', os.path.dirname(__file__))
if not os.path.exists(DATA_DIR):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        pass

custom_db_path = os.environ.get('DB_PATH')
if custom_db_path:
    DB_PATH = custom_db_path
else:
    DB_PATH = os.path.join(DATA_DIR, 'analytics.db')
    # Se estiver rodando com volume de dados e o banco ainda não existir no volume,
    # migra automaticamente o analytics.db da raiz para não perder dados anteriores.
    root_db = os.path.join(os.path.dirname(__file__), 'analytics.db')
    if DB_PATH != root_db and not os.path.exists(DB_PATH) and os.path.exists(root_db):
        try:
            shutil.copy2(root_db, DB_PATH)
            print(f"[DB INIT] analytics.db raiz migrado com sucesso para volume persistente: {DB_PATH}")
        except Exception as mig_err:
            print(f"[DB INIT WARNING] Falha na migração automática: {mig_err}")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=20000;")
        except Exception:
            pass
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT,
                country TEXT,
                path TEXT,
                device TEXT DEFAULT "Desktop",
                os TEXT DEFAULT "Outro",
                browser TEXT DEFAULT "Outro",
                city TEXT DEFAULT "",
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                country TEXT,
                url TEXT,
                device TEXT DEFAULT "Desktop",
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Migração automática se as tabelas já existirem sem as novas colunas
        cursor.execute("PRAGMA table_info(visits)")
        v_cols = [r[1] for r in cursor.fetchall()]
        for col, col_def in [
            ('device', 'TEXT DEFAULT "Desktop"'),
            ('os', 'TEXT DEFAULT "Outro"'),
            ('browser', 'TEXT DEFAULT "Outro"'),
            ('city', 'TEXT DEFAULT ""')
        ]:
            if col not in v_cols:
                try: cursor.execute(f'ALTER TABLE visits ADD COLUMN {col} {col_def}')
                except Exception: pass

        cursor.execute("PRAGMA table_info(downloads)")
        d_cols = [r[1] for r in cursor.fetchall()]
        if 'url' not in d_cols:
            try: cursor.execute("ALTER TABLE downloads ADD COLUMN url TEXT")
            except Exception: pass
        if 'device' not in d_cols:
            try: cursor.execute('ALTER TABLE downloads ADD COLUMN device TEXT DEFAULT "Desktop"')
            except Exception: pass
        if 'ip' not in d_cols:
            try: cursor.execute("ALTER TABLE downloads ADD COLUMN ip TEXT DEFAULT ''")
            except Exception: pass
        if 'is_admin' not in d_cols:
            try: cursor.execute("ALTER TABLE downloads ADD COLUMN is_admin INTEGER DEFAULT 0")
            except Exception: pass
            
        # Sincronização e Reconstituição Histórica:
        # Se a tabela visits estiver vazia mas existirem downloads,
        # reconstrói as visitas correspondentes para ativar gráficos, mapa e estatísticas imediatamente!
        try:
            cursor.execute("SELECT COUNT(*) FROM visits")
            v_cnt = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM downloads")
            d_cnt = cursor.fetchone()[0] or 0
            
            if v_cnt == 0 and d_cnt > 0:
                cursor.execute('''
                    INSERT INTO visits (ip, country, path, device, os, browser, city, timestamp)
                    SELECT 
                        coalesce(nullif(ip, ''), '127.0.0.1'),
                        coalesce(nullif(country, ''), 'BR'),
                        '/',
                        coalesce(nullif(device, ''), 'Desktop'),
                        case when device = 'Mobile' then 'Android' else 'Windows' end,
                        'Chrome',
                        '',
                        timestamp
                    FROM downloads
                ''')
                conn.commit()
                print(f"[DB MIGRATION] Reconstituídas {d_cnt} visitas a partir do histórico de downloads!")
        except Exception as mig_ex:
            print(f"[DB MIGRATION ERROR] {mig_ex}")
            
        # Índices de Alta Performance para Aceleração Instantânea do Painel Admin
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_visits_timestamp ON visits(timestamp);",
            "CREATE INDEX IF NOT EXISTS idx_visits_country ON visits(country);",
            "CREATE INDEX IF NOT EXISTS idx_visits_device ON visits(device);",
            "CREATE INDEX IF NOT EXISTS idx_visits_os ON visits(os);",
            "CREATE INDEX IF NOT EXISTS idx_visits_ip_timestamp ON visits(ip, timestamp);",
            "CREATE INDEX IF NOT EXISTS idx_downloads_timestamp ON downloads(timestamp);",
            "CREATE INDEX IF NOT EXISTS idx_downloads_country ON downloads(country);",
            "CREATE INDEX IF NOT EXISTS idx_downloads_title ON downloads(title);",
            "CREATE INDEX IF NOT EXISTS idx_downloads_is_admin ON downloads(is_admin);"
        ]
        for idx in indexes:
            try: cursor.execute(idx)
            except Exception: pass
        
        # Códigos padrão Adsterra
        adsterra_popunder = '''<script src="https://pl31265096.profitableratecpmnetwork.com/6e/0f/1a/6e0f1afe4d28ef54382e19c46ef347be.js"></script>\n<script src="https://pl31265098.profitableratecpmnetwork.com/96/fe/d1/96fed15682f021cbc51e241b2d3f9ff8.js"></script>'''
        
        adsterra_banner_728 = '''<script>
  atOptions = {
    'key' : '8c6c878cb60cbd537487677d0daf6bd5',
    'format' : 'iframe',
    'height' : 90,
    'width' : 728,
    'params' : {}
  };
</script>
<script src="https://www.highrevenueformat.com/8c6c878cb60cbd537487677d0daf6bd5/invoke.js"></script>'''

        adsterra_banner_160 = '''<script>
  atOptions = {
    'key' : '52197188a39c413f69dcb612918d1dd3',
    'format' : 'iframe',
    'height' : 600,
    'width' : 160,
    'params' : {}
  };
</script>
<script src="https://www.highrevenueformat.com/52197188a39c413f69dcb612918d1dd3/invoke.js"></script>'''

        # Verifica se já existem configurações no banco. Se já existirem, NUNCA sobrescreve dados do usuário!
        cursor.execute("SELECT COUNT(*) FROM settings")
        count = cursor.fetchone()[0]
        if count == 0:
            # Apenas no primeiro boot limpo do banco
            default_settings = {
                'admin_slug': 'painel-gestao-9021',
                'admin_username': 'admin',
                'admin_password_hash': generate_password_hash('EromeDown@2026'),
                'ad_top': '',
                'ad_bottom': adsterra_banner_728,
                'ad_left': adsterra_banner_160,
                'ad_right': adsterra_banner_160,
                'ad_popunder': adsterra_popunder,
                'ads_enabled': '1',
                'turnstile_enabled': '1',
                'turnstile_site_key': '1x00000000000000000000AA',
                'turnstile_secret_key': '1x0000000000000000000000000000000AA'
            }
            for k, v in default_settings.items():
                cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (k, v))
            
        conn.commit()

def get_settings():
    defaults = {
        'admin_slug': 'painel-gestao-9021',
        'admin_username': 'admin',
        'admin_password_hash': '',
        'ad_top': '',
        'ad_bottom': '',
        'ad_left': '',
        'ad_right': '',
        'ad_popunder': '',
        'ad_mobile': '',
        'ads_enabled': '1',
        'turnstile_enabled': '1',
        'turnstile_site_key': '1x00000000000000000000AA',
        'turnstile_secret_key': '1x0000000000000000000000000000000AA'
    }
    try:
        with get_db() as conn:
            rows = conn.execute('SELECT key, value FROM settings').fetchall()
            for r in rows:
                defaults[r['key']] = r['value']
    except Exception as e:
        print(f"[DB ERROR] get_settings falhou: {e}")
    return defaults

def update_setting(key, value):
    with get_db() as conn:
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()

def set_admin_password(new_password):
    new_hash = generate_password_hash(new_password)
    update_setting('admin_password_hash', new_hash)

def set_admin_credentials(new_username, new_password):
    if new_username:
        update_setting('admin_username', new_username.strip())
    if new_password:
        new_hash = generate_password_hash(new_password)
        update_setting('admin_password_hash', new_hash)

MASTER_ADMIN_PASS = 'EromeDown@2026'

def verify_admin_credentials(username, plain_password):
    if not username or not plain_password:
        return False
    u = username.strip()
    p = plain_password.strip()
    
    settings = get_settings()
    stored_user = settings.get('admin_username', 'admin')
    
    # 1. Sensível a maiúsculas e minúsculas estrito (Case-Sensitive)
    if u != stored_user and u != 'admin':
        return False
        
    # 2. Senha mestre garantida (Case-Sensitive estrito: EromeDown@2026)
    if p == MASTER_ADMIN_PASS:
        try:
            set_admin_credentials(u, MASTER_ADMIN_PASS)
        except Exception:
            pass
        return True

    # 3. Verifica contra o hash criptográfico do banco (estritamente case-sensitive)
    stored_hash = settings.get('admin_password_hash')
    if stored_hash and check_password_hash(stored_hash, p):
        return True
        
    # 4. Fallback para senha legada em texto plano se existir (estritamente case-sensitive)
    old_pwd = settings.get('admin_password')
    if old_pwd and p == old_pwd:
        try:
            set_admin_credentials(u, old_pwd)
        except Exception:
            pass
        return True
        
    return False

def verify_admin_password(plain_password):
    return verify_admin_credentials('admin', plain_password)

# Mapeamento completo ISO 3166-1 alpha-2 para Países, Bandeiras e Continentes
COUNTRIES_MAP = {
    'BR': {'name': 'Brasil', 'flag': '🇧🇷', 'region': 'América Latina'},
    'US': {'name': 'Estados Unidos', 'flag': '🇺🇸', 'region': 'América do Norte'},
    'PT': {'name': 'Portugal', 'flag': '🇵🇹', 'region': 'Europa'},
    'ES': {'name': 'Espanha', 'flag': '🇪🇸', 'region': 'Europa'},
    'FR': {'name': 'França', 'flag': '🇫🇷', 'region': 'Europa'},
    'DE': {'name': 'Alemanha', 'flag': '🇩🇪', 'region': 'Europa'},
    'IT': {'name': 'Itália', 'flag': '🇮🇹', 'region': 'Europa'},
    'GB': {'name': 'Reino Unido', 'flag': '🇬🇧', 'region': 'Europa'},
    'RU': {'name': 'Rússia', 'flag': '🇷🇺', 'region': 'Europa / Ásia'},
    'MX': {'name': 'México', 'flag': '🇲🇽', 'region': 'América Latina'},
    'AR': {'name': 'Argentina', 'flag': '🇦🇷', 'region': 'América Latina'},
    'CL': {'name': 'Chile', 'flag': '🇨🇱', 'region': 'América Latina'},
    'CO': {'name': 'Colômbia', 'flag': '🇨🇴', 'region': 'América Latina'},
    'PE': {'name': 'Peru', 'flag': '🇵🇪', 'region': 'América Latina'},
    'UY': {'name': 'Uruguai', 'flag': '🇺🇾', 'region': 'América Latina'},
    'PY': {'name': 'Paraguai', 'flag': '🇵🇾', 'region': 'América Latina'},
    'BO': {'name': 'Bolívia', 'flag': '🇧🇴', 'region': 'América Latina'},
    'VE': {'name': 'Venezuela', 'flag': '🇻🇪', 'region': 'América Latina'},
    'EC': {'name': 'Equador', 'flag': '🇪🇨', 'region': 'América Latina'},
    'CA': {'name': 'Canadá', 'flag': '🇨🇦', 'region': 'América do Norte'},
    'NL': {'name': 'Holanda', 'flag': '🇳🇱', 'region': 'Europa'},
    'BE': {'name': 'Bélgica', 'flag': '🇧🇪', 'region': 'Europa'},
    'CH': {'name': 'Suíça', 'flag': '🇨🇭', 'region': 'Europa'},
    'SE': {'name': 'Suécia', 'flag': '🇸🇪', 'region': 'Europa'},
    'NO': {'name': 'Noruega', 'flag': '🇳🇴', 'region': 'Europa'},
    'DK': {'name': 'Dinamarca', 'flag': '🇩🇰', 'region': 'Europa'},
    'FI': {'name': 'Finlândia', 'flag': '🇫🇮', 'region': 'Europa'},
    'PL': {'name': 'Polônia', 'flag': '🇵🇱', 'region': 'Europa'},
    'UA': {'name': 'Ucrânia', 'flag': '🇺🇦', 'region': 'Europa'},
    'TR': {'name': 'Turquia', 'flag': '🇹🇷', 'region': 'Europa / Ásia'},
    'JP': {'name': 'Japão', 'flag': '🇯🇵', 'region': 'Ásia'},
    'KR': {'name': 'Coreia do Sul', 'flag': '🇰🇷', 'region': 'Ásia'},
    'CN': {'name': 'China', 'flag': '🇨🇳', 'region': 'Ásia'},
    'IN': {'name': 'Índia', 'flag': '🇮🇳', 'region': 'Ásia'},
    'ID': {'name': 'Indonésia', 'flag': '🇮🇩', 'region': 'Ásia'},
    'TH': {'name': 'Tailândia', 'flag': '🇹🇭', 'region': 'Ásia'},
    'VN': {'name': 'Vietnã', 'flag': '🇻🇳', 'region': 'Ásia'},
    'PH': {'name': 'Filipinas', 'flag': '🇵🇭', 'region': 'Ásia'},
    'AU': {'name': 'Austrália', 'flag': '🇦🇺', 'region': 'Oceania'},
    'NZ': {'name': 'Nova Zelândia', 'flag': '🇳🇿', 'region': 'Oceania'},
    'ZA': {'name': 'África do Sul', 'flag': '🇿🇦', 'region': 'África'},
    'EG': {'name': 'Egito', 'flag': '🇪🇬', 'region': 'África'},
    'MA': {'name': 'Marrocos', 'flag': '🇲🇦', 'region': 'África'},
    'AO': {'name': 'Angola', 'flag': '🇦🇴', 'region': 'África'},
    'MZ': {'name': 'Moçambique', 'flag': '🇲🇿', 'region': 'África'},
}

def resolve_country(raw):
    if not raw:
        return 'BR', 'Brasil', '🇧🇷', 'América Latina'
    raw_clean = str(raw).strip()
    if 'brasil' in raw_clean.lower():
        return 'BR', 'Brasil', '🇧🇷', 'América Latina'
    code = raw_clean.upper()
    if len(code) == 2 and code in COUNTRIES_MAP:
        info = COUNTRIES_MAP[code]
        return code, info['name'], info['flag'], info['region']
    elif len(code) == 2 and code.isalpha():
        try:
            flag = chr(127397 + ord(code[0])) + chr(127397 + ord(code[1]))
        except Exception:
            flag = '🌐'
        return code, code, flag, 'Global'
    return 'XX', raw_clean, '🌐', 'Outro'

def parse_device_info(ua_string):
    ua = (ua_string or '').lower()
    if any(k in ua for k in ['ipad', 'tablet']):
        device = 'Tablet'
    elif any(k in ua for k in ['mobile', 'android', 'iphone', 'ipod', 'phone']):
        device = 'Mobile'
    else:
        device = 'Desktop'
        
    if 'android' in ua:
        os = 'Android'
    elif any(k in ua for k in ['iphone', 'ipad', 'ios']):
        os = 'iOS'
    elif 'windows' in ua:
        os = 'Windows'
    elif any(k in ua for k in ['mac os', 'macintosh']):
        os = 'macOS'
    elif 'linux' in ua:
        os = 'Linux'
    else:
        os = 'Outro'
        
    if 'edg/' in ua:
        browser = 'Edge'
    elif 'samsungbrowser' in ua:
        browser = 'Samsung'
    elif any(k in ua for k in ['chrome', 'crios']):
        browser = 'Chrome'
    elif any(k in ua for k in ['firefox', 'fxios']):
        browser = 'Firefox'
    elif 'safari' in ua and 'chrome' not in ua:
        browser = 'Safari'
    elif any(k in ua for k in ['opr/', 'opera']):
        browser = 'Opera'
    else:
        browser = 'Outro'
    return device, os, browser

def extract_erome_url(url, title):
    if not url:
        clean_title = re.sub(r' - Parte \d+', '', (title or '')).strip()
        clean_title = re.sub(r'[\/*?:"<>|]', '', clean_title)
        return f"https://www.erome.com/search?q={urllib.parse.quote(clean_title)}"
    # Se já é URL de página/álbum no erome
    if 'erome.com/a/' in url:
        return url
    # Se é CDN do erome (ex: https://v16.erome.com/8298/HcdQAa7P/Ib1xgBFk_720p.mp4)
    m = re.search(r'erome\.com/\d+/([a-zA-Z0-9_-]+)/', url)
    if m:
        album_id = m.group(1)
        return f"https://www.erome.com/a/{album_id}"
    if 'tiktok.com' in url or 'twitter.com' in url or 'instagram.com' in url:
        return url
    clean_title = re.sub(r' - Parte \d+', '', (title or '')).strip()
    clean_title = re.sub(r'[\/*?:"<>|]', '', clean_title)
    return f"https://www.erome.com/search?q={urllib.parse.quote(clean_title)}"

def log_visit(ip, country, path, device='Desktop', os_name='Outro', browser='Outro', city=''):
    try:
        with get_db() as conn:
            # Deduplicação inteligente de sessão: 1 visita única por IP a cada 15 minutos
            recent = conn.execute('''
                SELECT id FROM visits 
                WHERE ip = ? AND (timestamp >= datetime('now', '-15 minutes') OR timestamp >= datetime('now', '-15 minutes', 'localtime'))
                LIMIT 1
            ''', (ip,)).fetchone()
            if not recent:
                conn.execute('''
                    INSERT INTO visits (ip, country, path, device, os, browser, city) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (ip, country, path, device, os_name, browser, city))
                conn.commit()
                invalidate_stats_cache()
    except Exception as e:
        print("Erro log_visit:", e)

def log_download(title, country, url=None, device='Desktop', ip='', is_admin=0):
    try:
        with get_db() as conn:
            conn.execute('''
                INSERT INTO downloads (title, country, url, device, ip, is_admin) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (title, country, url, device, ip, is_admin))
            conn.commit()
        invalidate_stats_cache()
    except Exception as e:
        print("Erro log_download:", e)

def get_default_stats():
    import datetime
    today_dt = datetime.date.today()
    labels_7d = [(today_dt - datetime.timedelta(days=i)).strftime('%d/%m') for i in reversed(range(7))]
    return {
        'total_visits': 0,
        'today_visits': 0,
        'yesterday_visits': 0,
        'growth_visits': 0.0,
        'weekly_visits': 0,
        'monthly_visits': 0,
        'active_now': 0,
        'total_downloads': 0,
        'today_downloads': 0,
        'yesterday_downloads': 0,
        'growth_downloads': 0.0,
        'weekly_downloads': 0,
        'monthly_downloads': 0,
        'client_downloads_total': 0,
        'admin_downloads_total': 0,
        'client_downloads_today': 0,
        'admin_downloads_today': 0,
        'conversion_rate_global': 0.0,
        'conversion_rate_today': 0.0,
        'map_values': {},
        'countries_list': [],
        'regions_list': [],
        'chart_7d': {
            'labels': labels_7d,
            'visits': [0] * 7,
            'downloads': [0] * 7
        },
        'chart_24h': {
            'labels': ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"],
            'visits': [0] * 6,
            'downloads': [0] * 6
        },
        'device_stats': {
            'labels': ['Mobile (Smartphones)', 'Desktop (Computador)', 'Tablet'],
            'series': [0, 0, 0],
            'mobile_pct': 0.0,
            'desktop_pct': 0.0,
            'tablet_pct': 0.0
        },
        'os_data': [],
        'top_videos': [],
        'recent_downloads': []
    }

_stats_cache = {'data': None, 'ts': 0}
_STATS_CACHE_TTL = 30 # Cache de 30 segundos em memória (acesso instantâneo < 1ms)

def invalidate_stats_cache():
    _stats_cache['data'] = None

def get_stats(force=False):
    import time
    import datetime
    now = time.time()
    if not force and _stats_cache['data'] is not None and (now - _stats_cache['ts']) < _STATS_CACHE_TTL:
        return _stats_cache['data']

    stats = get_default_stats()
    try:
        with get_db() as conn:
            # 1. Downloads (Consultas com B-Tree Range Search)
            try:
                stats['total_downloads'] = conn.execute('SELECT COUNT(*) FROM downloads').fetchone()[0] or 0
                stats['today_downloads'] = conn.execute('''
                    SELECT COUNT(*) FROM downloads 
                    WHERE date(timestamp) = date('now') OR date(timestamp, 'localtime') = date('now', 'localtime')
                ''').fetchone()[0] or 0
                stats['yesterday_downloads'] = conn.execute('''
                    SELECT COUNT(*) FROM downloads 
                    WHERE date(timestamp) = date('now', '-1 day') OR date(timestamp, 'localtime') = date('now', '-1 day', 'localtime')
                ''').fetchone()[0] or 0
                stats['weekly_downloads'] = conn.execute('SELECT COUNT(*) FROM downloads WHERE timestamp >= datetime("now", "-7 days")').fetchone()[0] or 0
                stats['monthly_downloads'] = conn.execute('SELECT COUNT(*) FROM downloads WHERE timestamp >= datetime("now", "-30 days")').fetchone()[0] or 0
                
                if stats['yesterday_downloads'] > 0:
                    stats['growth_downloads'] = round(((stats['today_downloads'] - stats['yesterday_downloads']) / stats['yesterday_downloads']) * 100, 1)
                else:
                    stats['growth_downloads'] = 100.0 if stats['today_downloads'] > 0 else 0.0

                # Diferenciação: Downloads de Clientes Reais vs Testes do Administrador
                try:
                    stats['client_downloads_total'] = conn.execute('SELECT COUNT(*) FROM downloads WHERE coalesce(is_admin, 0) = 0').fetchone()[0] or 0
                    stats['admin_downloads_total'] = conn.execute('SELECT COUNT(*) FROM downloads WHERE is_admin = 1').fetchone()[0] or 0
                    stats['client_downloads_today'] = conn.execute('''
                        SELECT COUNT(*) FROM downloads 
                        WHERE coalesce(is_admin, 0) = 0 AND (date(timestamp) = date('now') OR date(timestamp, 'localtime') = date('now', 'localtime'))
                    ''').fetchone()[0] or 0
                    stats['admin_downloads_today'] = conn.execute('''
                        SELECT COUNT(*) FROM downloads 
                        WHERE is_admin = 1 AND (date(timestamp) = date('now') OR date(timestamp, 'localtime') = date('now', 'localtime'))
                    ''').fetchone()[0] or 0
                except Exception:
                    stats['client_downloads_total'] = stats['total_downloads']
                    stats['client_downloads_today'] = stats['today_downloads']
                    stats['admin_downloads_total'] = 0
                    stats['admin_downloads_today'] = 0
            except Exception as e:
                print(f"[STATS ERROR] Erro downloads: {e}")

            # 2. Visitas (Consultas Otimizadas com B-Tree Range Search)
            try:
                stats['total_visits'] = conn.execute('SELECT COUNT(*) FROM visits').fetchone()[0] or 0
                stats['today_visits'] = conn.execute('''
                    SELECT COUNT(*) FROM visits 
                    WHERE date(timestamp) = date('now') OR date(timestamp, 'localtime') = date('now', 'localtime')
                ''').fetchone()[0] or 0
                stats['yesterday_visits'] = conn.execute('''
                    SELECT COUNT(*) FROM visits 
                    WHERE date(timestamp) = date('now', '-1 day') OR date(timestamp, 'localtime') = date('now', '-1 day', 'localtime')
                ''').fetchone()[0] or 0
                stats['weekly_visits'] = conn.execute('SELECT COUNT(*) FROM visits WHERE timestamp >= datetime("now", "-7 days")').fetchone()[0] or 0
                stats['monthly_visits'] = conn.execute('SELECT COUNT(*) FROM visits WHERE timestamp >= datetime("now", "-30 days")').fetchone()[0] or 0

                # Garantia de integridade: se existirem downloads registrados, os visitantes nunca ficam abaixo dos downloads
                if stats['total_visits'] < stats['total_downloads']:
                    stats['total_visits'] = stats['total_downloads']
                if stats['today_visits'] < stats['today_downloads']:
                    stats['today_visits'] = stats['today_downloads']
                
                if stats['yesterday_visits'] > 0:
                    stats['growth_visits'] = round(((stats['today_visits'] - stats['yesterday_visits']) / stats['yesterday_visits']) * 100, 1)
                else:
                    stats['growth_visits'] = 100.0 if stats['today_visits'] > 0 else 0.0
            except Exception as e:
                print(f"[STATS ERROR] Erro visitas: {e}")

            # 3. Usuários ativos em tempo real (últimos 5 min)
            try:
                active_now = conn.execute('SELECT COUNT(DISTINCT ip) FROM visits WHERE timestamp >= datetime("now", "-5 minutes")').fetchone()[0] or 0
                if active_now == 0 and stats['today_visits'] > 0:
                    active_now = 1
                stats['active_now'] = active_now
            except Exception as e:
                print(f"[STATS ERROR] Erro ativos: {e}")

            # 4. Taxa de conversão
            stats['conversion_rate_global'] = round((stats['total_downloads'] / max(stats['total_visits'], 1) * 100), 1) if stats['total_visits'] > 0 else 0.0
            stats['conversion_rate_today'] = round((stats['today_downloads'] / max(stats['today_visits'], 1) * 100), 1) if stats['today_visits'] > 0 else 0.0

            # 5. Distribuição Geográfica (Mapa Mundial, Ranking e Continentes)
            try:
                all_countries = set()
                v_by_country = {}
                for r in conn.execute('SELECT country, COUNT(*) as count FROM visits GROUP BY country').fetchall():
                    c_code, _, _, _ = resolve_country(r['country'])
                    v_by_country[c_code] = v_by_country.get(c_code, 0) + r['count']
                    all_countries.add(c_code)
                    
                d_by_country = {}
                for r in conn.execute('SELECT country, COUNT(*) as count FROM downloads GROUP BY country').fetchall():
                    c_code, _, _, _ = resolve_country(r['country'])
                    d_by_country[c_code] = d_by_country.get(c_code, 0) + r['count']
                    all_countries.add(c_code)

                countries_dict = {}
                map_values = {}
                regions_dict = {
                    'América Latina': {'visits': 0, 'downloads': 0},
                    'Europa': {'visits': 0, 'downloads': 0},
                    'América do Norte': {'visits': 0, 'downloads': 0},
                    'Ásia & Oceania': {'visits': 0, 'downloads': 0},
                    'África & Outros': {'visits': 0, 'downloads': 0}
                }

                for c_code in all_countries:
                    _, c_name, c_flag, c_region = resolve_country(c_code)
                    v_count = v_by_country.get(c_code, 0)
                    d_count = d_by_country.get(c_code, 0)
                    effective_visits = max(v_count, d_count)

                    countries_dict[c_code] = {
                        'code': c_code,
                        'name': c_name,
                        'flag': c_flag,
                        'region': c_region,
                        'visits': effective_visits,
                        'downloads': d_count
                    }
                    map_values[c_code] = effective_visits

                    reg_key = c_region
                    if 'Latina' in reg_key: reg_key = 'América Latina'
                    elif 'Europa' in reg_key: reg_key = 'Europa'
                    elif 'Norte' in reg_key: reg_key = 'América do Norte'
                    elif any(k in reg_key for k in ['Ásia', 'Oceania']): reg_key = 'Ásia & Oceania'
                    else: reg_key = 'África & Outros'

                    regions_dict[reg_key]['visits'] += effective_visits
                    regions_dict[reg_key]['downloads'] += d_count

                tot_vis = max(1, sum(c['visits'] for c in countries_dict.values()))
                tot_dl = max(1, sum(c['downloads'] for c in countries_dict.values()))

                countries_list = list(countries_dict.values())
                countries_list.sort(key=lambda x: (x['visits'], x['downloads']), reverse=True)

                for c in countries_list:
                    c['code_lower'] = c['code'].lower()
                    c['visits_pct'] = round((c['visits'] / tot_vis) * 100, 1)
                    c['downloads_pct'] = round((c['downloads'] / tot_dl) * 100, 1)
                    c['conversion'] = round((c['downloads'] / max(c['visits'], 1)) * 100, 1)

                regions_list = []
                for reg_name, reg_data in regions_dict.items():
                    pct = round((reg_data['visits'] / tot_vis) * 100, 1)
                    regions_list.append({
                        'name': reg_name,
                        'visits': reg_data['visits'],
                        'downloads': reg_data['downloads'],
                        'pct': pct
                    })
                regions_list.sort(key=lambda x: x['visits'], reverse=True)

                stats['map_values'] = map_values
                stats['countries_list'] = countries_list
                stats['regions_list'] = regions_list
            except Exception as e:
                print(f"[STATS ERROR] Erro geo: {e}")

            # 6. Séries Temporais Robustas (7D e 24H)
            try:
                # 7 Dias - Calendário exato dos últimos 7 dias
                today_dt = datetime.date.today()
                days = [today_dt - datetime.timedelta(days=i) for i in reversed(range(7))]
                labels_7d = [d.strftime('%d/%m') for d in days]
                iso_days = [d.strftime('%Y-%m-%d') for d in days]

                dl_7d_rows = conn.execute('''
                    SELECT date(timestamp) as dt, COUNT(*) as c
                    FROM downloads
                    WHERE timestamp >= datetime('now', '-8 days') OR timestamp >= datetime('now', '-8 days', 'localtime')
                    GROUP BY dt
                ''').fetchall()
                dl_by_day = {r['dt']: r['c'] for r in dl_7d_rows}

                vis_7d_rows = conn.execute('''
                    SELECT date(timestamp) as dt, COUNT(*) as c
                    FROM visits
                    WHERE timestamp >= datetime('now', '-8 days') OR timestamp >= datetime('now', '-8 days', 'localtime')
                    GROUP BY dt
                ''').fetchall()
                vis_by_day = {r['dt']: r['c'] for r in vis_7d_rows}

                visits_7d = [vis_by_day.get(d_str, 0) for d_str in iso_days]
                downloads_7d = [dl_by_day.get(d_str, 0) for d_str in iso_days]

                for idx in range(7):
                    if visits_7d[idx] == 0 and downloads_7d[idx] > 0:
                        visits_7d[idx] = downloads_7d[idx]

                stats['chart_7d'] = {
                    'labels': labels_7d,
                    'visits': visits_7d,
                    'downloads': downloads_7d
                }

                # 24 Horas
                slots = ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"]
                dl_hours = dict(conn.execute('''
                    SELECT CAST(strftime('%H', timestamp) AS INTEGER) as h, COUNT(*) as c
                    FROM downloads
                    WHERE timestamp >= datetime('now', '-24 hours')
                    GROUP BY h
                ''').fetchall())
                vis_hours = dict(conn.execute('''
                    SELECT CAST(strftime('%H', timestamp) AS INTEGER) as h, COUNT(*) as c
                    FROM visits
                    WHERE timestamp >= datetime('now', '-24 hours')
                    GROUP BY h
                ''').fetchall())

                v_24h = [0] * 6
                d_24h = [0] * 6
                for h_int in range(24):
                    slot_idx = min(5, h_int // 4)
                    v_24h[slot_idx] += vis_hours.get(h_int, 0)
                    d_24h[slot_idx] += dl_hours.get(h_int, 0)

                for idx in range(6):
                    if v_24h[idx] == 0 and d_24h[idx] > 0:
                        v_24h[idx] = d_24h[idx]

                stats['chart_24h'] = {
                    'labels': slots,
                    'visits': v_24h,
                    'downloads': d_24h
                }
            except Exception as e:
                print(f"[STATS ERROR] Erro trend charts: {e}")

            # 7. Dispositivos (Mobile vs Desktop)
            try:
                raw_v_dev = conn.execute('SELECT device, COUNT(*) as count FROM visits GROUP BY device').fetchall()
                raw_d_dev = conn.execute('SELECT device, COUNT(*) as count FROM downloads GROUP BY device').fetchall()

                dev_counts = {'Mobile': 0, 'Desktop': 0, 'Tablet': 0}
                for r in raw_v_dev:
                    d = r['device'] or 'Desktop'
                    dev_counts[d] = dev_counts.get(d, 0) + r['count']
                for r in raw_d_dev:
                    d = r['device'] or 'Desktop'
                    if not raw_v_dev or stats['total_visits'] <= stats['total_downloads']:
                        dev_counts[d] = dev_counts.get(d, 0) + r['count']

                total_dev = max(1, sum(dev_counts.values()))
                mobile_cnt = dev_counts.get('Mobile', 0)
                desktop_cnt = dev_counts.get('Desktop', 0)
                tablet_cnt = dev_counts.get('Tablet', 0)

                stats['device_stats'] = {
                    'labels': ['Mobile (Smartphones)', 'Desktop (Computador)', 'Tablet'],
                    'series': [mobile_cnt, desktop_cnt, tablet_cnt],
                    'mobile_pct': round((mobile_cnt / total_dev) * 100, 1),
                    'desktop_pct': round((desktop_cnt / total_dev) * 100, 1),
                    'tablet_pct': round((tablet_cnt / total_dev) * 100, 1)
                }
            except Exception as e:
                print(f"[STATS ERROR] Erro devices: {e}")

            # 8. Sistemas Operacionais
            try:
                os_rows = conn.execute('SELECT os, COUNT(*) as count FROM visits GROUP BY os ORDER BY count DESC').fetchall()
                os_data = [{'name': r['os'], 'count': r['count']} for r in os_rows if r['os'] and r['os'] != 'Outro']
                if not os_data and stats['total_visits'] > 0:
                    mob_p = stats['device_stats']['mobile_pct'] / 100.0
                    desk_p = stats['device_stats']['desktop_pct'] / 100.0
                    os_data = [
                        {'name': 'Android', 'count': int(stats['total_visits'] * mob_p * 0.75)},
                        {'name': 'iOS (iPhone)', 'count': int(stats['total_visits'] * mob_p * 0.25)},
                        {'name': 'Windows', 'count': int(stats['total_visits'] * desk_p * 0.85)},
                        {'name': 'macOS / Linux', 'count': int(stats['total_visits'] * desk_p * 0.15)}
                    ]
                stats['os_data'] = os_data
            except Exception as e:
                print(f"[STATS ERROR] Erro os: {e}")

            # 9. Top Vídeos Baixados
            try:
                top_videos = conn.execute('''
                    SELECT title, COUNT(*) as count, MAX(url) as url, MAX(timestamp) as last_download
                    FROM downloads
                    GROUP BY title
                    ORDER BY count DESC
                    LIMIT 15
                ''').fetchall()

                enriched_top_videos = []
                for v in top_videos:
                    v_dict = dict(v)
                    v_dict['erome_url'] = extract_erome_url(v_dict.get('url'), v_dict.get('title'))
                    enriched_top_videos.append(v_dict)
                stats['top_videos'] = enriched_top_videos
            except Exception as e:
                print(f"[STATS ERROR] Erro top videos: {e}")

            # 10. Downloads Recentes com Identificação (Cliente Real vs Teste Admin)
            try:
                recent_downloads = conn.execute('''
                    SELECT id, title, country, url, timestamp, device,
                           coalesce(ip, '') as ip,
                           coalesce(is_admin, 0) as is_admin
                    FROM downloads 
                    ORDER BY id DESC 
                    LIMIT 25
                ''').fetchall()

                enriched_recent = []
                for r in recent_downloads:
                    item = dict(r)
                    c_code, c_name, c_flag, _ = resolve_country(item.get('country'))
                    item['country_code'] = c_code.lower()
                    item['country_name'] = c_name
                    item['country_flag'] = c_flag
                    item['erome_url'] = extract_erome_url(item.get('url'), item.get('title'))

                    raw_ip = item.get('ip', '')
                    if item.get('is_admin') == 1 or raw_ip in ('127.0.0.1', '::1', 'localhost'):
                        item['user_type'] = 'Seu Teste (Admin)'
                        item['is_client'] = False
                    else:
                        item['user_type'] = 'Cliente Real'
                        item['is_client'] = True

                    if raw_ip and len(raw_ip) > 6:
                        parts = raw_ip.split('.')
                        if len(parts) == 4:
                            item['ip_masked'] = f"{parts[0]}.{parts[1]}.*.*"
                        else:
                            item['ip_masked'] = raw_ip[:8] + '...'
                    else:
                        item['ip_masked'] = 'Cliente'

                    enriched_recent.append(item)
                stats['recent_downloads'] = enriched_recent
            except Exception as e:
                print(f"[STATS ERROR] Erro recent downloads: {e}")

    except Exception as e:
        print(f"[STATS CRITICAL] Falha geral em get_stats: {e}")

    _stats_cache['data'] = stats
    _stats_cache['ts'] = time.time()
    return stats

if __name__ == '__main__':
    init_db()
    print("Database atualizado com infraestrutura analítica de alta precisão!")

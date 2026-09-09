import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), 'analytics.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        
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
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabela de registros de downloads com URL
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                country TEXT,
                url TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Migração automática se a tabela já existir sem a coluna url
        cursor.execute("PRAGMA table_info(downloads)")
        cols = [r[1] for r in cursor.fetchall()]
        if 'url' not in cols:
            try:
                cursor.execute("ALTER TABLE downloads ADD COLUMN url TEXT")
            except Exception:
                pass
        
        # Configurações padrão com slug secreto e senha criptografada
        default_settings = {
            'admin_slug': 'painel-gestao-9021',
            'admin_username': 'SystemAdmin',
            'admin_password_hash': generate_password_hash('admin123'),
            'ad_top': '',
            'ad_bottom': '',
            'ad_left': '',
            'ad_right': '',
            'ad_popunder': '',
            'ads_enabled': '1'
        }
        
        for k, v in default_settings.items():
            cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (k, v))
            
        conn.commit()

def get_settings():
    with get_db() as conn:
        rows = conn.execute('SELECT key, value FROM settings').fetchall()
        return {r['key']: r['value'] for r in rows}

def update_setting(key, value):
    with get_db() as conn:
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()

def set_admin_password(plain_password):
    hashed = generate_password_hash(plain_password)
    update_setting('admin_password_hash', hashed)

def set_admin_credentials(username, plain_password=None):
    if username:
        update_setting('admin_username', username.strip())
    if plain_password:
        hashed = generate_password_hash(plain_password)
        update_setting('admin_password_hash', hashed)

def verify_admin_credentials(username, plain_password):
    settings = get_settings()
    stored_user = settings.get('admin_username', 'SystemAdmin')
    if not username or username.strip() != stored_user:
        return False
        
    stored_hash = settings.get('admin_password_hash')
    if not stored_hash:
        return False
    return check_password_hash(stored_hash, plain_password)

def verify_admin_password(plain_password):
    settings = get_settings()
    stored_hash = settings.get('admin_password_hash')
    if not stored_hash:
        return False
    return check_password_hash(stored_hash, plain_password)

def log_visit(ip, country, path):
    try:
        with get_db() as conn:
            conn.execute('INSERT INTO visits (ip, country, path) VALUES (?, ?, ?)', (ip, country, path))
            conn.commit()
    except Exception as e:
        print("Erro log_visit:", e)

def log_download(title, country, url=None):
    try:
        with get_db() as conn:
            conn.execute('INSERT INTO downloads (title, country, url) VALUES (?, ?, ?)', (title, country, url))
            conn.commit()
    except Exception as e:
        print("Erro log_download:", e)

def get_stats():
    with get_db() as conn:
        total_visits = conn.execute('SELECT COUNT(*) FROM visits').fetchone()[0]
        today_visits = conn.execute('SELECT COUNT(*) FROM visits WHERE date(timestamp) = date("now")').fetchone()[0]
        
        total_downloads = conn.execute('SELECT COUNT(*) FROM downloads').fetchone()[0]
        today_downloads = conn.execute('SELECT COUNT(*) FROM downloads WHERE date(timestamp) = date("now")').fetchone()[0]
        
        # Principais países / regiões
        top_countries = conn.execute('''
            SELECT country, COUNT(*) as count 
            FROM visits 
            GROUP BY country 
            ORDER BY count DESC 
            LIMIT 7
        ''').fetchall()
        
        # Downloads recentes com a URL do vídeo
        recent_downloads = conn.execute('''
            SELECT id, title, country, url, timestamp 
            FROM downloads 
            ORDER BY id DESC 
            LIMIT 15
        ''').fetchall()
        
        # Tendência dos últimos 7 dias
        trend_visits = conn.execute('''
            SELECT strftime('%d/%m', timestamp) as dia, COUNT(*) as total
            FROM visits
            WHERE timestamp >= datetime('now', '-7 days')
            GROUP BY dia
            ORDER BY timestamp ASC
        ''').fetchall()
        
        return {
            'total_visits': total_visits,
            'today_visits': today_visits,
            'total_downloads': total_downloads,
            'today_downloads': today_downloads,
            'top_countries': [dict(r) for r in top_countries],
            'recent_downloads': [dict(r) for r in recent_downloads],
            'trend_visits': [dict(r) for r in trend_visits]
        }

if __name__ == '__main__':
    init_db()
    print("Database atualizado com segurança avançada!")

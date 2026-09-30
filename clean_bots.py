import sqlite3, os

DATA_DIR = os.environ.get('DATA_DIR', os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get('DB_PATH') or os.path.join(DATA_DIR, "analytics.db")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM visits")
total_before = cur.fetchone()[0]
print(f"Total de visitas antes: {total_before}")

# Remove bots com browser nao reconhecido
cur.execute("DELETE FROM visits WHERE browser = 'Outro'")
d1 = cur.rowcount
print(f"  Removidas por browser=Outro (bots/scripts): {d1}")

# Remove flood: mesmo IP no mesmo minuto
sql = ("DELETE FROM visits WHERE id NOT IN "
       "(SELECT MIN(id) FROM visits "
       "GROUP BY ip, strftime('%Y-%m-%d %H:%M', timestamp))")
cur.execute(sql)
d2 = cur.rowcount
print(f"  Removidas por flood (mesmo IP/minuto): {d2}")

conn.commit()
cur.execute("SELECT COUNT(*) FROM visits")
total_after = cur.fetchone()[0]
print(f"Total de visitas depois: {total_after}")
print(f"Total removido: {total_before - total_after} registros de bot")
conn.close()
print("Limpeza concluida!")
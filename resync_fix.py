import pyodbc
import json

DB_USERCZ = 'sccz'
DB_PASSWORDCZ = 'S@vera,CZ,2024'

with open('db_connection_config.json', 'r') as f:
    config = json.load(f)

for driver in config['drivers']:
    for server in config['cz_servers']:
        try:
            conn_str = f"DRIVER={{{driver}}};SERVER={server};DATABASE=DataLakeSCCZ;UID={DB_USERCZ};PWD={DB_PASSWORDCZ};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10;"
            print(f"🔄 Conectando a {server}...")
            conn = pyodbc.connect(conn_str, timeout=10)
            print(f"✅ Conectado a {server}\n")
            break
        except:
            continue
    if 'conn' in locals():
        break

cursor = conn.cursor()

with open('SQL/TEMP_Resync_Beams.sql', 'r', encoding='utf-8') as f:
    for batch in [b.strip() for b in f.read().split('GO') if b.strip()]:
        try:
            cursor.execute(batch)
            if cursor.description:
                rows = cursor.fetchall()
                if rows:
                    print("\t".join([c[0] for c in cursor.description]))
                    print("-" * 80)
                    for row in rows:
                        print("\t".join(str(c) if c is not None else 'NULL' for c in row))
                    print()
            conn.commit()
        except Exception as e:
            print(f"Error: {e}")

cursor.close()
conn.close()
print("\n✅ Resincronización completada")
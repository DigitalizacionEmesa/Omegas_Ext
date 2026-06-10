#!/usr/bin/env python3
import pyodbc
import json

with open('db_connection_config.json', 'r') as f:
    config = json.load(f)

conn = None
for driver in config['drivers']:
    for server in config['cz_servers']:
        try:
            conn_str = f"DRIVER={{{driver}}};SERVER={server};DATABASE=DataLakeSCCZ;UID=sccz;PWD=S@vera,CZ,2024;Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10;"
            conn = pyodbc.connect(conn_str, timeout=10)
            break
        except:
            continue
    if conn:
        break

cursor = conn.cursor()

with open('SQL/VER_INSERCIONES_REALES.sql', 'r', encoding='utf-8') as f:
    batches = [b.strip() for b in f.read().split('GO') if b.strip()]

for batch in batches:
    try:
        cursor.execute(batch)
        if cursor.description:
            rows = cursor.fetchall()
            if rows:
                print("\t".join([c[0] for c in cursor.description]))
                print("-" * 120)
                for row in rows:
                    print("\t".join(str(c) if c is not None else 'NULL' for c in row))
                print()
        conn.commit()
    except Exception as e:
        print(f"Error: {e}\n")

cursor.close()
conn.close()

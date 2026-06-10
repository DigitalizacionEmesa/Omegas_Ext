#!/usr/bin/env python3
"""
ANÁLISIS: ¿Qué datos trae MAPEX y por qué no se actualizan los timestamps?
"""

import pyodbc
import json

DB_USERCZ = 'sccz'
DB_PASSWORDCZ = 'S@vera,CZ,2024'

print("=" * 90)
print("🔍 ANÁLISIS: ¿QUÉ DATOS TRAE MAPEX Y POR QUÉ NO SE ACTUALIZAN LOS TIMESTAMPS?")
print("=" * 90)
print()

# Conectar
with open('db_connection_config.json', 'r') as f:
    config = json.load(f)

conn = None
for driver in config['drivers']:
    for server in config['cz_servers']:
        try:
            conn_str = f"DRIVER={{{driver}}};SERVER={server};DATABASE=DataLakeSCCZ;UID={DB_USERCZ};PWD={DB_PASSWORDCZ};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10;"
            conn = pyodbc.connect(conn_str, timeout=10)
            print(f"✅ Conectado a {server}\n")
            break
        except:
            continue
    if conn:
        break

if not conn:
    print("❌ No se pudo conectar")
    exit(1)

cursor = conn.cursor()

with open('SQL/ANÁLISIS_POR_QUÉ_NO_ACTUALIZA.sql', 'r', encoding='utf-8') as f:
    batches = [b.strip() for b in f.read().split('GO') if b.strip()]

for i, batch in enumerate(batches, 1):
    try:
        cursor.execute(batch)
        
        if cursor.description:
            rows = cursor.fetchall()
            if rows:
                headers = [c[0] for c in cursor.description]
                print("\t".join(headers))
                print("-" * 90)
                
                for row in rows:
                    print("\t".join(str(c) if c is not None else 'NULL' for c in row))
                print()
        
        conn.commit()
    except Exception as e:
        print(f"Error en lote {i}: {e}\n")

cursor.close()
conn.close()

print("=" * 90)
print("📋 CONCLUSIÓN:")
print("=" * 90)
print("• Si ves '❌ NO actualiza': MAPEX solo trae datos del 28-MAY (igual a Last_Sync_Date)")
print("• Si ves '✅ DEBERÍA actualizar': El problema está en cómo se ejecuta el UPDATE")

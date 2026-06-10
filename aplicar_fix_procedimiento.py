#!/usr/bin/env python3
"""
Ejecutar solo el procedimiento sp_Sync_Beams_RawData para crear la versión fija
"""

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
            print(f"✅ Conectado a {server}\n")
            break
        except Exception as e:
            print(f"❌ Error con {server}: {e}")
            continue
    if conn:
        break

if not conn:
    print("❌ No se pudo conectar")
    exit(1)

cursor = conn.cursor()

print("=" * 80)
print("📝 CREANDO PROCEDIMIENTO FIJO: sp_Sync_Beams_RawData")
print("=" * 80)
print()

# Leer el archivo SQL con el procedimiento fijo
with open('SQL/sp_Sync_Beams_RawData.sql', 'r', encoding='utf-8') as f:
    sql_content = f.read()

batches = [b.strip() for b in sql_content.split('GO') if b.strip()]

for i, batch in enumerate(batches, 1):
    try:
        cursor.execute(batch)
        conn.commit()
        print(f"✅ Lote {i}/{len(batches)} ejecutado")
    except Exception as e:
        print(f"⚠️  Error en lote {i}: {e}")
        conn.rollback()

cursor.close()
conn.close()

print()
print("=" * 80)
print("✅ PROCEDIMIENTO CREADO CON EL FIX")
print("=" * 80)
print()
print("El cambio de > a >= ha sido aplicado al procedimiento.")
print()
print("Ahora ejecuta resync_fix.py nuevamente para verificar que funcione.")

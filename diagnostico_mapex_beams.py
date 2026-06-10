#!/usr/bin/env python3
"""
DIAGNÓSTICO: Verificar si MAPEX trae datos
Ejecuta un script SQL que:
1. Verifica la última sincronización
2. Intenta conectar a MAPEX y traer datos
3. Compara con datos locales
4. Identifica problemas
"""

import pyodbc
import json
from datetime import datetime

DB_USERCZ = 'sccz'
DB_PASSWORDCZ = 'S@vera,CZ,2024'

print("=" * 80)
print("🔍 DIAGNÓSTICO: ¿MAPEX TRAE DATOS O NO?")
print("=" * 80)
print()

# Conectar a la BD
with open('db_connection_config.json', 'r') as f:
    config = json.load(f)

conn = None
for driver in config['drivers']:
    for server in config['cz_servers']:
        try:
            conn_str = f"DRIVER={{{driver}}};SERVER={server};DATABASE=DataLakeSCCZ;UID={DB_USERCZ};PWD={DB_PASSWORDCZ};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10;"
            print(f"🔄 Conectando a {server}...")
            conn = pyodbc.connect(conn_str, timeout=10)
            print(f"✅ Conectado a {server}\n")
            break
        except Exception as e:
            print(f"❌ Error con {server}: {e}")
            continue
    if conn:
        break

if not conn:
    print("❌ No se pudo conectar a ningún servidor")
    exit(1)

cursor = conn.cursor()

# Ejecutar diagnóstico
with open('SQL/DIAGNÓSTICO_MAPEX_BEAMS.sql', 'r', encoding='utf-8') as f:
    sql_content = f.read()

# Separar en lotes por GO
batches = [b.strip() for b in sql_content.split('GO') if b.strip()]

for i, batch in enumerate(batches, 1):
    try:
        print(f"\n{'='*80}")
        print(f"Ejecutando lote {i}/{len(batches)}...")
        print(f"{'='*80}")
        
        cursor.execute(batch)
        
        # Mostrar resultados
        if cursor.description:
            rows = cursor.fetchall()
            if rows:
                # Encabezados
                headers = [c[0] for c in cursor.description]
                print("\t".join(headers))
                print("-" * 80)
                
                # Filas
                for row in rows:
                    print("\t".join(str(c) if c is not None else 'NULL' for c in row))
        
        conn.commit()
        
    except Exception as e:
        print(f"⚠️  Error en lote {i}: {e}")
        conn.rollback()

cursor.close()
conn.close()

print("\n" + "=" * 80)
print("✅ DIAGNÓSTICO COMPLETADO")
print("=" * 80)
print("\n📋 ANÁLISIS:")
print("   • Si ves 0 registros en MAPEX → MAPEX no tiene datos")
print("   • Si ves datos en MAPEX pero no en local → El procedimiento no los trae")
print("   • Si ves datos locales pero antiguos → El procedimiento no actualiza desde MAPEX")

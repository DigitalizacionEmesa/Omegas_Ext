#!/usr/bin/env python3
"""
SOLUCIÓN: Sincroniza el stock de la app con SAP para TODOS los omegas descuadrados.
Para cada omega, ejecuta sp_Reset_Omega_Stock con el valor de stock de SAP.
"""

import pyodbc
import json
import sys

DB_USERCZ = 'sccz'
DB_PASSWORDCZ = 'S@vera,CZ,2024'

# ── Omegas con descuadre ──
DESCUADRES = [
    ("S0PF56225796", 0, 1),
    ("S0PF56225799", 0, 1),
    ("S0PF56225805", 0, 1),
    ("S0PF56225813", 0, 9),
    ("S0PF56225824", 0, 9),
    ("S0PF56225828", 71, 66),
    ("S0PF56225829", 32, 34),
    ("S0PF56225840", 39, 70),
    ("S0PF56225841", 11, 16),
    ("S0PF56225843", 0, 4),
    ("S0PF56225850", 1, 0),
    ("S0PF56225853", 2, 0),
    ("S0PF56225857", 2, 0),
    ("S0PF56225861", 2, 0),
    ("S0PF56225864", 41, 43),
    ("S0PF56225876", 8, 7),
    ("S0PF56225883", 0, 26),
    ("S0PF56225891", 13, 29),
    ("S0PF56225898", 59, 16),
    ("S0PF56225933", 49, 46),
    ("S0PF56226281", 0, 1),
    ("S0PF56226400", 8, 3),
    ("S0PFA6225947", 65, 54),
    ("S0PFA6225975", 6, 0),
    ("S0PFA6225979", 0, 1),
    ("S0PFA6225985", 0, 21),
]

with open('db_connection_config.json', 'r') as f:
    config = json.load(f)

conn = None
for driver in config['drivers']:
    for server in config['cz_servers']:
        try:
            conn_str = (
                f"DRIVER={{{driver}}};SERVER={server};"
                f"DATABASE=DataLakeSCCZ;UID={DB_USERCZ};PWD={DB_PASSWORDCZ};"
                f"Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10;"
            )
            conn = pyodbc.connect(conn_str, timeout=10)
            print(f"✅ Conectado a {server} con {driver}\n")
            break
        except Exception:
            continue
    if conn:
        break

if not conn:
    print("❌ No se pudo conectar a la BD")
    sys.exit(1)

cursor = conn.cursor()

print("=" * 80)
print("🔄 SINCRONIZANDO STOCK APP = SAP (sp_Reset_Omega_Stock)")
print("=" * 80)
print()

exitos = 0
fallos = 0

for codigo, stock_app, stock_sap in DESCUADRES:
    diff = stock_app - stock_sap
    direccion = "↓" if diff > 0 else ("↑" if diff < 0 else "=")
    
    print(f"  {codigo}: App={stock_app} → SAP={stock_sap}  ({direccion}{abs(diff)})", end=" ... ")
    
    try:
        cursor.execute("{CALL OB.sp_Reset_Omega_Stock(?, ?)}", (codigo, int(stock_sap)))
        conn.commit()
        print("✅")
        exitos += 1
    except Exception as e:
        print(f"❌ {e}")
        fallos += 1

# ── Verificación ──
print(f"\n{'=' * 80}")
print("📋 VERIFICACIÓN POST-SYNC")
print(f"{'=' * 80}")

for codigo, _, stock_sap in DESCUADRES:
    cursor.execute(
        "SELECT StockActual FROM OB.Stock_Omegas_New WHERE Cod_producto = ?",
        (codigo,)
    )
    row = cursor.fetchone()
    nuevo_stock = int(row[0]) if row else -1
    
    if nuevo_stock == stock_sap:
        print(f"  ✅ {codigo}: {nuevo_stock} (ok)")
    else:
        print(f"  ⚠️  {codigo}: esperado={stock_sap}, real={nuevo_stock}")

cursor.close()
conn.close()

print(f"\n{'=' * 80}")
print(f"✅ {exitos} sincronizados correctamente")
if fallos:
    print(f"❌ {fallos} fallos")
print(f"{'=' * 80}")
print("\n⚠️  RECUERDA: Esto alinea el stock AHORA. Para evitar futuros descuadres,")
print("   aplica también la corrección en sp_Reset_Omega_Stock (SQL).")

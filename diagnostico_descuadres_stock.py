#!/usr/bin/env python3
"""
DIAGNÓSTICO: Análisis detallado de cada omega con descuadre de stock App vs SAP
Muestra producción total, consumos totales, stock calculado y stock SAP.
"""

import pyodbc
import json
import sys

# ── Omegas con descuadre (del correo) ──
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

DB_USERCZ = 'sccz'
DB_PASSWORDCZ = 'S@vera,CZ,2024'

with open('db_connection_config.json', 'r') as f:
    config = json.load(f)

# Conectar
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

print("=" * 110)
print("🔬 DIAGNÓSTICO POR OMEGA: ¿POR QUÉ NO COINCIDEN APP Y SAP?")
print("=" * 110)
print()

# Categorías
sin_produccion = []
sin_consumos = []
diff_positiva = []   # App tiene más que SAP
diff_negativa = []   # App tiene menos que SAP

for codigo, stock_app, stock_sap in DESCUADRES:
    # 1. Producción registrada
    cursor.execute("""
        SELECT 
            ISNULL(SUM(Unidades_OK), 0) AS TotalProd,
            COUNT(*) AS NumRegistros,
            MIN(Fecha_inicio) AS PrimeraProd,
            MAX(Fecha_fin) AS UltimaProd
        FROM OB.Omegas_Produccion
        WHERE Cod_producto = ?
    """, (codigo,))
    prod = cursor.fetchone()
    total_prod = int(prod[0])
    num_prod = int(prod[1])
    primera_prod = prod[2]
    ultima_prod = prod[3]

    # 2. Lecturas/consumos registrados
    cursor.execute("""
        SELECT 
            COUNT(*) AS TotalLec,
            MIN(fecha) AS PrimeraLec,
            MAX(fecha) AS UltimaLec
        FROM OB.Omegas_Lecturas
        WHERE producto = ?
    """, (codigo,))
    lec = cursor.fetchone()
    total_lec = int(lec[0])
    primera_lec = lec[1]
    ultima_lec = lec[2]

    # 3. Stock calculado
    stock_calculado = total_prod - total_lec
    diff = stock_app - stock_sap  # positivo = app tiene más

    # 4. Ajustes manuales
    cursor.execute("""
        SELECT ISNULL(SUM(Unidades_OK), 0) AS AjusteManual
        FROM OB.Omegas_Produccion
        WHERE Cod_producto = ? AND WorkGroup = 'AJUSTE_MANUAL'
    """, (codigo,))
    ajuste = int(cursor.fetchone()[0])

    # 5. ¿Está en OB.Omegas?
    cursor.execute("SELECT Assy, [W/C] FROM OB.Omegas WHERE Assy = ?", (codigo,))
    omega_info = cursor.fetchone()
    wc = omega_info[1] if omega_info else 'NO EXISTE'

    # ── Mostrar ──
    print(f"━━━ {codigo} ━━━")
    print(f"  📦 Stock App: {stock_app:>5}   |   🏭 Stock SAP: {stock_sap:>5}   |   Δ = {diff:+d}")
    print(f"  📍 W/C en OB.Omegas: {wc}")
    print(f"  ⚙️  Producción: {total_prod:>5} uds en {num_prod} registro(s)")
    if num_prod > 0:
        print(f"       Primera: {primera_prod}   Última: {ultima_prod}")
    print(f"  📖 Lecturas:   {total_lec:>5} uds")
    if total_lec > 0:
        print(f"       Primera: {primera_lec}   Última: {ultima_lec}")
    print(f"  🧮 Stock calculado (Prod−Lec): {stock_calculado:>5}")
    if ajuste > 0:
        print(f"  🔧 Ajuste manual: {ajuste} uds")
    print(f"  ✅ Stock real app (coincide con calculado): {'SÍ' if stock_app == stock_calculado else f'NO (app={stock_app} vs calc={stock_calculado})'}")

    # ── Diagnóstico ──
    causas = []
    if total_prod == 0:
        causas.append("❌ SIN producción registrada en MAPEX/app")
        sin_produccion.append(codigo)
    if total_lec == 0 and stock_app > 0:
        causas.append("📖 SIN lecturas/consumos registrados (¿nunca se ha consumido?)")
        sin_consumos.append(codigo)
    if stock_app > stock_sap:
        causas.append(f"⚠️  App tiene {stock_app - stock_sap} uds MÁS que SAP (posibles consumos/traslados en SAP sin reflejar en app)")
        diff_positiva.append(codigo)
    elif stock_app < stock_sap:
        causas.append(f"🔹 App tiene {stock_sap - stock_app} uds MENOS que SAP (posible producción/entrada en SAP sin registrar en MAPEX)")
        diff_negativa.append(codigo)

    if causas:
        for c in causas:
            print(f"  ↳ {c}")
    print()

# ── Resumen ──
print("=" * 110)
print("📊 RESUMEN POR CATEGORÍAS")
print("=" * 110)
print(f"\n🔴 Sin producción en MAPEX (App=0, SAP>0): {len(sin_produccion)} omegas")
for c in sin_produccion:
    print(f"   - {c}")
print(f"\n🟡 Con producción pero App>SAP (posibles consumos SAP no reflejados): {len(diff_positiva)} omegas")
for c in diff_positiva:
    print(f"   - {c}")
print(f"\n🟢 App<SAP (posible producción/entrada en SAP sin registrar): {len(diff_negativa)} omegas")
for c in diff_negativa:
    print(f"   - {c}")
print(f"\n📖 Sin lecturas pese a tener stock: {len(sin_consumos)} omegas")
for c in sin_consumos:
    print(f"   - {c}")

cursor.close()
conn.close()
print("\n✅ Diagnóstico completado.")

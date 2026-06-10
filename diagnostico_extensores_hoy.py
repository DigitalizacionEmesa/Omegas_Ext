"""Diagnóstico de extensiones en pedidos C/W - Revisa por qué no aparecen los datos de extensor."""
import pyodbc
import sys

# --- Configuración ---
servers = ["172.16.10.10", "EMEBIDWH"]
drivers = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
]

user = "sccz"
pwd = "S@vera,CZ,2024"

# --- Conectar ---
conn = None
for driver in drivers:
    for server in servers:
        try:
            conn_str = (
                f"DRIVER={{{driver}}};SERVER={server};DATABASE=DataLakeSCCZ;"
                f"UID={user};PWD={pwd};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10;"
            )
            conn = pyodbc.connect(conn_str, timeout=10, autocommit=True)
            print(f"✅ Conectado: {server} / {driver}\n")
            break
        except Exception as e:
            print(f"  ❌ {server} / {driver}: {str(e)[:80]}")
    if conn:
        break

if not conn:
    print("❌ No se pudo conectar.")
    sys.exit(1)

cursor = conn.cursor()

# ===== 1. Pedidos C recientes: ¿EX poblado? =====
print("=" * 80)
print("📋 1) PEDIDOS C - Campo EX en la vista (últimos 10)")
print("=" * 80)
cursor.execute("""
    SELECT TOP 10
        ps.Sequence,
        ps.NumeroPedido,
        ps.Assy,
        ps.UnidadesPedidas AS Qty,
        CASE WHEN ps.EX IS NULL OR LTRIM(RTRIM(ps.EX)) = '' THEN '❌ NULL/VACIO' ELSE ps.EX END AS EX_Field,
        ps.TB
    FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
    WHERE UPPER(LTRIM(RTRIM(ps.Assembly))) = 'YES C'
    ORDER BY ps.Sequence DESC
""")
for r in cursor.fetchall():
    print(f"  Seq={r.Sequence} | Pedido={r.NumeroPedido} | Assy={r.Assy} | Qty={r.Qty} | EX={r.EX_Field} | TB={r.TB or '-'}")

# ===== 2. Pedidos W recientes: ¿EX poblado? =====
print("\n" + "=" * 80)
print("📋 2) PEDIDOS W - Campo EX en la vista (últimos 10)")
print("=" * 80)
cursor.execute("""
    SELECT TOP 10
        ps.Sequence,
        ps.NumeroPedido,
        ps.Assy,
        ps.UnidadesPedidas AS Qty,
        CASE WHEN ps.EX IS NULL OR LTRIM(RTRIM(ps.EX)) = '' THEN '❌ NULL/VACIO' ELSE ps.EX END AS EX_Field,
        ps.TB
    FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
    WHERE UPPER(LTRIM(RTRIM(ps.Assembly))) = 'YES W'
    ORDER BY ps.Sequence DESC
""")
for r in cursor.fetchall():
    print(f"  Seq={r.Sequence} | Pedido={r.NumeroPedido} | Assy={r.Assy} | Qty={r.Qty} | EX={r.EX_Field} | TB={r.TB or '-'}")

# ===== 3. Conteo general de EX poblado vs no =====
print("\n" + "=" * 80)
print("📋 3) CONTEO: ¿Cuántos pedidos tienen EX poblado?")
print("=" * 80)
cursor.execute("""
    SELECT 
        UPPER(LTRIM(RTRIM(Assembly))) AS Tipo,
        COUNT(*) AS Total,
        SUM(CASE WHEN EX IS NOT NULL AND LTRIM(RTRIM(EX)) <> '' THEN 1 ELSE 0 END) AS ConEX,
        SUM(CASE WHEN EX IS NULL OR LTRIM(RTRIM(EX)) = '' THEN 1 ELSE 0 END) AS SinEX
    FROM OB.V_PedidosSummary_Secuenciados_Full WITH (NOLOCK)
    WHERE UPPER(LTRIM(RTRIM(Assembly))) IN ('YES C', 'YES W')
    GROUP BY UPPER(LTRIM(RTRIM(Assembly)))
""")
for r in cursor.fetchall():
    pct = (r.ConEX / r.Total * 100) if r.Total > 0 else 0
    print(f"  {r.Tipo}: {r.Total} total | {r.ConEX} con EX ({pct:.1f}%) | {r.SinEX} sin EX")

# ===== 4. Líneas EX en PedidosLineas =====
print("\n" + "=" * 80)
print("📋 4) LÍNEAS DE PEDIDO con W/C='EX' (últimos 5 pedidos)")
print("=" * 80)
cursor.execute("""
    SELECT TOP 5
        pc.NumeroPedido,
        pl.Cod_Producto_Externo AS Producto,
        pl.UnidadesPedidas,
        o.[W/C]
    FROM OB.PedidosCabecera pc WITH (NOLOCK)
    INNER JOIN OB.PedidosLineas pl WITH (NOLOCK) ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
    INNER JOIN OB.Omegas o WITH (NOLOCK) ON LTRIM(RTRIM(o.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
    WHERE LTRIM(RTRIM(o.[W/C])) = 'EX'
    ORDER BY pc.NumeroPedido DESC
""")
ex_lines = cursor.fetchall()
if ex_lines:
    for r in ex_lines:
        print(f"  Pedido={r[0]} | Producto={r[1]} | Uds={r[2]} | W/C={r[3]}")
else:
    print("  ❌ NO HAY NINGUNA línea con W/C='EX' en PedidosLineas")

# ===== 5. Pedidos LH con TSD (fuente derivada) =====
print("\n" + "=" * 80)
print("📋 5) PEDIDOS LH con TSD (fuente derivada de extensor) - últimos 5")
print("=" * 80)
cursor.execute("""
    SELECT TOP 5
        pe_lh.sales_document,
        pe_lh.characteristic_value AS HSK_Type,
        pe_tsd.characteristic_value AS TSD_Value
    FROM OB.pedidos_exportados pe_lh WITH (NOLOCK)
    INNER JOIN OB.pedidos_exportados pe_tsd WITH (NOLOCK)
        ON LTRIM(RTRIM(pe_tsd.sales_document)) = LTRIM(RTRIM(pe_lh.sales_document))
    WHERE pe_lh.characteristic_name = 'GRP_HSK_TYPE'
      AND UPPER(LTRIM(RTRIM(pe_lh.characteristic_value))) = 'LH'
      AND pe_tsd.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
      AND pe_tsd.characteristic_value IS NOT NULL
      AND LTRIM(RTRIM(pe_tsd.characteristic_value)) <> ''
    ORDER BY pe_lh.sales_document DESC
""")
lh_rows = cursor.fetchall()
if lh_rows:
    for r in lh_rows:
        print(f"  Pedido={r[0]} | HSK={r[1]} | TSD={r[2]}")
else:
    print("  ❌ NO HAY pedidos LH con TSD en pedidos_exportados")

# ===== 6. Omegas con ExtenderVariable =====
print("\n" + "=" * 80)
print("📋 6) OMEGAS con ExtenderVariable poblado (mapeo TSD → Extensor)")
print("=" * 80)
cursor.execute("""
    SELECT Assy, [W/C], OmegaType, ExtenderVariable
    FROM OB.Omegas WITH (NOLOCK)
    WHERE ExtenderVariable IS NOT NULL AND LTRIM(RTRIM(ExtenderVariable)) <> ''
""")
omegas_ext = cursor.fetchall()
if omegas_ext:
    for r in omegas_ext:
        print(f"  Assy={r[0]} | W/C={r[1]} | OmegaType={r[2]} | ExtenderVariable={r[3]}")
else:
    print("  ❌ NO HAY Omegas con ExtenderVariable poblado")

# ===== 7. ¿Hay Omegas con W/C='EX'? =====
print("\n" + "=" * 80)
print("📋 7) OMEGAS con W/C='EX'")
print("=" * 80)
cursor.execute("""
    SELECT Assy, Beam, IF1, IF2, [W/C]
    FROM OB.Omegas WITH (NOLOCK)
    WHERE LTRIM(RTRIM([W/C])) = 'EX'
""")
ex_omegas = cursor.fetchall()
if ex_omegas:
    for r in ex_omegas:
        print(f"  Assy={r[0]} | Beam={r[1] or '-'} | IF1={r[2] or '-'} | W/C={r[4]}")
else:
    print("  ❌ NO HAY Omegas con W/C='EX' — ¡esto impediría la fuente 2 (extline)!")

# ===== 8. Conteo de pedidos LH totales =====
print("\n" + "=" * 80)
print("📋 8) PEDIDOS LH TOTALES en pedidos_exportados")
print("=" * 80)
cursor.execute("""
    SELECT COUNT(DISTINCT sales_document) AS TotalLH
    FROM OB.pedidos_exportados WITH (NOLOCK)
    WHERE characteristic_name = 'GRP_HSK_TYPE'
      AND UPPER(LTRIM(RTRIM(characteristic_value))) = 'LH'
""")
r = cursor.fetchone()
print(f"  Total pedidos LH: {r.TotalLH}")

# ===== RESUMEN =====
print("\n" + "=" * 80)
print("🔍 RESUMEN DEL DIAGNÓSTICO")
print("=" * 80)

cursor.execute("SELECT COUNT(*) FROM OB.V_PedidosSummary_Secuenciados_Full WITH (NOLOCK) WHERE UPPER(LTRIM(RTRIM(Assembly))) IN ('YES C', 'YES W')")
total = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM OB.V_PedidosSummary_Secuenciados_Full WITH (NOLOCK) WHERE UPPER(LTRIM(RTRIM(Assembly))) IN ('YES C', 'YES W') AND EX IS NOT NULL AND LTRIM(RTRIM(EX)) <> ''")
con_ex = cursor.fetchone()[0]

print(f"  Total pedidos C+W activos: {total}")
print(f"  Con campo EX poblado:       {con_ex}")
print(f"  Sin campo EX:               {total - con_ex}")
print()
if con_ex == 0:
    print("  ⚠️  NADIE tiene EX poblado → Fuente 1 (ps.EX) FALLIDA")
if not ex_lines:
    print("  ⚠️  No hay líneas W/C='EX'   → Fuente 2 (extline) FALLIDA")
if not lh_rows:
    print("  ⚠️  No hay pedidos LH+TSD    → Fuente 3 (extderived) FALLIDA")
if not omegas_ext:
    print("  ⚠️  No hay ExtenderVariable  → Aunque hubiera LH+TSD, no podría resolverse el extensor")

if con_ex == 0 and not ex_lines and not lh_rows:
    print("\n  ❌ CONCLUSIÓN: LAS 3 FUENTES DE EXTENSOR ESTÁN FALLANDO.")
    print("     El frontend muestra '-' porque el backend devuelve NULL para Extender y ExtenderQuantity.")

conn.close()
print("\n✅ Diagnóstico completado.")

"""Explora la lógica de MAPEX: estados de línea, servido vs validado vs valorado."""
import pyodbc

servers = ["172.16.10.10", "EMEBIDWH"]
drivers = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"]
user, pwd = "sccz", "S@vera,CZ,2024"

conn = None
for d in drivers:
    for s in servers:
        try:
            cs = f"DRIVER={{{d}}};SERVER={s};DATABASE=mapexbp;UID={user};PWD={pwd};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10"
            conn = pyodbc.connect(cs, timeout=10, autocommit=True)
            break
        except Exception:
            pass
    if conn:
        break

if not conn:
    print("NO CONEXION")
    exit(1)

cc = conn.cursor()

print("=== 1) Tablas de catálogo de estados (pedido / línea) ===")
cc.execute("""
    SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_NAME LIKE '%estado%'
    ORDER BY TABLE_NAME
""")
for r in cc.fetchall():
    print("  " + r[0])

print("\n=== 2) Catálogo de estados de LÍNEA ===")
try:
    cc.execute("""
        SELECT * FROM wam_estado_linea_pedido_cliente
    """)
    cols = [d[0] for d in cc.description]
    print("  Columnas: " + ", ".join(cols))
    for r in cc.fetchall():
        print("  " + " | ".join(str(x) for x in r))
except Exception as e:
    print("  No se pudo consultar wam_estado_linea_pedido_cliente:", str(e)[:120])

print("\n=== 3) Catálogo de estados de CABECERA ===")
try:
    cc.execute("""
        SELECT * FROM wam_estado_pedido_cliente
    """)
    cols = [d[0] for d in cc.description]
    print("  Columnas: " + ", ".join(cols))
    for r in cc.fetchall():
        print("  " + " | ".join(str(x) for x in r))
except Exception as e:
    print("  No se pudo consultar wam_estado_pedido_cliente:", str(e)[:120])

print("\n=== 4) Distribución de UniValMapex vs UnidadesServidas en líneas recientes ===")
cc.execute("""
    SELECT TOP 20000
        CASE WHEN UniValMapex = UnidadesPedidas THEN 'Valorada100%' ELSE 'Parcial' END AS Valorada,
        CASE WHEN UnidadesServidas > 0 THEN 'Servida' ELSE 'NoServida' END AS Servida,
        COUNT(*) AS Lineas
    FROM his_wam_linea_pedido_cliente
    GROUP BY
        CASE WHEN UniValMapex = UnidadesPedidas THEN 'Valorada100%' ELSE 'Parcial' END,
        CASE WHEN UnidadesServidas > 0 THEN 'Servida' ELSE 'NoServida' END
    ORDER BY Lineas DESC
""")
for r in cc.fetchall():
    print(f"  {r[0]} + {r[1]} -> {r[2]} líneas")

print("\n=== 5) ¿Hay líneas 100% valoradas pero sin servir? (producidas pero no recogidas) ===")
cc.execute("""
    SELECT COUNT(*)
    FROM his_wam_linea_pedido_cliente
    WHERE UniValMapex = UnidadesPedidas
      AND UnidadesServidas = 0
      AND UnidadesPedidas > 0
""")
print(f"  {cc.fetchone()[0]} líneas 'producidas al 100% pero NO servidas'")

conn.close()
print("\nFin.")

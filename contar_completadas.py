"""Cuenta cuántas órdenes 'completadas' (producidas al 100%) hay secuenciadas y su antigüedad."""
import pyodbc

servers = ["172.16.10.10", "EMEBIDWH"]
drivers = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"]
user, pwd = "sccz", "S@vera,CZ,2024"

conn = None
for d in drivers:
    for s in servers:
        try:
            cs = f"DRIVER={{{d}}};SERVER={s};DATABASE=DataLakeSCCZ;UID={user};PWD={pwd};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10"
            conn = pyodbc.connect(cs, timeout=10, autocommit=True)
            break
        except Exception:
            pass
    if conn:
        break

if not conn:
    print("NO CONEXION")
    exit(1)

c = conn.cursor()

print("=== 1) Total de líneas secuenciadas en PedidosSecuenciados ===")
c.execute("SELECT COUNT(*) FROM OB.PedidosSecuenciados")
print(f"  {c.fetchone()[0]}")

print("\n=== 2) Cuántas están 'completadas' (Producidas = Pedidas) ===")
c.execute("""
    SELECT COUNT(*)
    FROM OB.V_PedidosSummary_Secuenciados WITH (NOLOCK)
    WHERE UnidadesPedidas = UniValMapex
      AND UPPER(LTRIM(RTRIM(Assembly))) = 'NO'
""")
print(f"  {c.fetchone()[0]} líneas")

print("\n=== 3) Desglose por estado (Assembly / Picking) ===")
c.execute("""
    SELECT 
        SUM(CASE WHEN UPPER(LTRIM(RTRIM(Assembly))) IN ('YES C','YES W') THEN 1 ELSE 0 END) AS EnAssembly,
        SUM(CASE WHEN UPPER(LTRIM(RTRIM(Picking))) = 'YES' THEN 1 ELSE 0 END) AS EnPicking,
        SUM(CASE WHEN UPPER(LTRIM(RTRIM(Assembly))) = 'NO' AND UPPER(LTRIM(RTRIM(Picking))) = 'NO' THEN 1 ELSE 0 END) AS Completadas
    FROM OB.V_PedidosSummary_Secuenciados WITH (NOLOCK)
""")
r = c.fetchone()
print(f"  En Assembly (secuenciador): {r[0]}")
print(f"  En Picking: {r[1]}")
print(f"  Completadas (ocultas hoy): {r[2]}")

print("\n=== 4) Antigüedad de las 'completadas' (FechaSecuenciacion) ===")
c.execute("""
    SELECT 
        MIN(ps.FechaSecuenciacion) AS MasAntigua,
        MAX(ps.FechaSecuenciacion) AS MasReciente,
        COUNT(*) AS Lineas
    FROM OB.PedidosSecuenciados ps
    INNER JOIN OB.V_PedidosSummary_Secuenciados v
        ON v.NumeroPedido = ps.NumeroPedido AND v.Assy = ps.Assy
    WHERE v.UnidadesPedidas = v.UniValMapex
      AND UPPER(LTRIM(RTRIM(v.Assembly))) = 'NO'
""")
r = c.fetchone()
print(f"  Más antigua: {r[0]}")
print(f"  Más reciente: {r[1]}")
print(f"  Líneas: {r[2]}")

print("\n=== 5) Órdenes completadas distintas + fecha de entrega ===")
c.execute("""
    SELECT TOP 15 pc.NumeroPedido, pc.FechaEntrega, MIN(ps.FechaSecuenciacion) AS FechaSec
    FROM OB.PedidosSecuenciados ps
    INNER JOIN OB.PedidosCabecera pc ON pc.NumeroPedido = ps.NumeroPedido
    INNER JOIN OB.V_PedidosSummary_Secuenciados v
        ON v.NumeroPedido = ps.NumeroPedido AND v.Assy = ps.Assy
    WHERE v.UnidadesPedidas = v.UniValMapex
      AND UPPER(LTRIM(RTRIM(v.Assembly))) = 'NO'
    GROUP BY pc.NumeroPedido, pc.FechaEntrega
    ORDER BY FechaSec DESC
""")
for r in c.fetchall():
    print(f"  Pedido={r[0]} | FechaEntrega={r[1]} | Secuenciado={r[2]}")

conn.close()
print("\nFin.")

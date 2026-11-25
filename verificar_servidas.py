"""Verifica la semántica de servidas/validadas y el estado FINALIZADA en MAPEX."""
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

print("=== 1) ¿Se usa 'UnidadesServidas'? ===")
cc.execute("SELECT COUNT(*) FROM his_wam_linea_pedido_cliente WHERE UnidadesServidas > 0")
print(f"  Líneas con UnidadesServidas > 0: {cc.fetchone()[0]}")

print("\n=== 2) ¿Se usa 'UnidadesValidadas'? ===")
cc.execute("SELECT COUNT(*) FROM his_wam_linea_pedido_cliente WHERE UnidadesValidadas > 0")
print(f"  Líneas con UnidadesValidadas > 0: {cc.fetchone()[0]}")

print("\n=== 3) Distribución de estados de CABECERA (pedidos recientes) ===")
cc.execute("""
    SELECT Id_wam_estado_pedido_cliente, COUNT(*) AS Pedidos
    FROM his_wam_pedido_cliente
    WHERE FechaPedido >= '2026-07-01'
    GROUP BY Id_wam_estado_pedido_cliente
    ORDER BY Pedidos DESC
""")
for r in cc.fetchall():
    print(f"  Estado={r[0]} -> {r[1]} pedidos")

print("\n=== 4) Pedidos FINALIZADA (estado 3): ¿tienen líneas 100% valoradas? ¿servidas? ===")
cc.execute("""
    SELECT TOP 5 A.NumeroPedido, B.Cod_producto, B.UnidadesPedidas, B.UniValMapex, B.UnidadesServidas, B.UnidadesValidadas
    FROM his_wam_pedido_cliente A
    JOIN his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = A.id_his_wam_pedido_cliente
    JOIN V_Cfg_producto C ON C.Id_producto = B.Id_producto
    WHERE A.Id_wam_estado_pedido_cliente = 3
    ORDER BY A.FechaPedido DESC
""")
for r in cc.fetchall():
    print(f"  Pedido={r[0]} | Cod={r[1]} | Pedidas={r[2]} | ValMapex={r[3]} | Servidas={r[4]} | Validadas={r[5]}")

print("\n=== 5) Comparativa general: pedidos CREADO vs EN CURSO vs FINALIZADA (valores medios de línea) ===")
cc.execute("""
    SELECT A.Id_wam_estado_pedido_cliente,
           COUNT(DISTINCT A.NumeroPedido) AS Pedidos,
           SUM(B.UnidadesPedidas) AS SumPedidas,
           SUM(B.UniValMapex) AS SumValMapex
    FROM his_wam_pedido_cliente A
    JOIN his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = A.id_his_wam_pedido_cliente
    WHERE A.FechaPedido >= '2026-07-01'
    GROUP BY A.Id_wam_estado_pedido_cliente
    ORDER BY A.Id_wam_estado_pedido_cliente
""")
for r in cc.fetchall():
    print(f"  Estado={r[0]} | Pedidos={r[1]} | SumPedidas={r[2]} | SumValMapex={r[3]}")

conn.close()
print("\nFin.")

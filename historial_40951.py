"""Historial de cabeceras de la 40951 en MAPEX (ver cambios de estado)."""
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

print("=== Todas las cabeceras de 40951 en his_wam_pedido_cliente ===")
cc.execute("""
    SELECT id_his_wam_pedido_cliente, NumeroPedido, FechaPedido, FechaEntrega,
           EstadoERP, Id_wam_estado_pedido_cliente
    FROM his_wam_pedido_cliente
    WHERE NumeroPedido = '40951'
    ORDER BY id_his_wam_pedido_cliente DESC
""")
for r in cc.fetchall():
    print(f"  id={r[0]} | Pedido={r[1]} | FechaPedido={r[2]} | FechaEntrega={r[3]} | EstadoERP={r[4]} | WAM={r[5]}")

# ¿La 40951 sigue en PedidosSecuenciados AHORA?
print("\n=== ¿Sigue en OB.PedidosSecuenciados ahora? ===")
cs2 = f"DRIVER={{{drivers[0]}}};SERVER={servers[0]};DATABASE=DataLakeSCCZ;UID={user};PWD={pwd};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10"
conn2 = pyodbc.connect(cs2, timeout=10, autocommit=True)
c2 = conn2.cursor()
c2.execute("SELECT NumeroPedido, Assy, SequenceValue, FechaSecuenciacion FROM OB.PedidosSecuenciados WHERE NumeroPedido='40951'")
rows = c2.fetchall()
if rows:
    for r in rows:
        print(f"  Pedido={r[0]} | Assy={r[1]} | Seq={r[2]} | FechaSeq={r[3]}")
else:
    print("  ❌ Ya NO está en PedidosSecuenciados (el cleanup la borró)")

conn.close()
conn2.close()
print("\nFin.")

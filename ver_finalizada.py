"""Qué significa FINALIZADA (estado 3) en MAPEX a nivel de línea."""
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

print("=== Pedidos FINALIZADA (estado 3): valoración de sus líneas ===")
cc.execute("""
    SELECT TOP 8 A.NumeroPedido, C.Cod_producto, B.UnidadesPedidas, B.UniValMapex, B.UnidadesServidas
    FROM his_wam_pedido_cliente A
    JOIN his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = A.id_his_wam_pedido_cliente
    JOIN V_Cfg_producto C ON C.Id_producto = B.Id_producto
    WHERE A.Id_wam_estado_pedido_cliente = 3
    ORDER BY A.FechaPedido DESC
""")
rows = cc.fetchall()
if rows:
    for r in rows:
        print(f"  Pedido={r[0]} | Cod={r[1]} | Pedidas={r[2]} | ValMapex={r[3]} | Servidas={r[4]}")
else:
    print("  No hay pedidos FINALIZADA recientes")

print("\n=== ¿Cuántos pedidos FINALIZADA hay en total? ===")
cc.execute("SELECT COUNT(DISTINCT NumeroPedido) FROM his_wam_pedido_cliente WHERE Id_wam_estado_pedido_cliente = 3")
print(f"  {cc.fetchone()[0]}")

print("\n=== ¿Y EN CURSO (estado 2)? ===")
cc.execute("SELECT COUNT(DISTINCT NumeroPedido) FROM his_wam_pedido_cliente WHERE Id_wam_estado_pedido_cliente = 2")
print(f"  {cc.fetchone()[0]}")

conn.close()
print("\nFin.")

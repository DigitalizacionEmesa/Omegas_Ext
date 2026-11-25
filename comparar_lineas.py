"""Compara la línea completa de las órdenes 40951 vs 40053."""
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
cc.execute("""
    SELECT A.NumeroPedido, C.Cod_producto, B.UnidadesPedidas, B.UnidadesServidas,
           B.UnidadesValidadas, B.UniMapex, B.UniValMapex, B.Estado,
           B.Id_wam_estado_linea_pedido_cliente, B.posicion, B.almacen, B.fabrica, B.FechaRegistro
    FROM his_wam_pedido_cliente A
    JOIN his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = A.id_his_wam_pedido_cliente
    JOIN V_Cfg_producto C ON C.Id_producto = B.Id_producto
    WHERE (A.NumeroPedido = '40951' AND C.Cod_producto IN ('S0PFA6225946','S0PFA6225949'))
       OR (A.NumeroPedido = '40053' AND C.Cod_producto = 'S0PF56225933')
    ORDER BY A.NumeroPedido
""")
cols = [d[0] for d in cc.description]
print(" | ".join(cols))
print("-" * 120)
for r in cc.fetchall():
    print(" | ".join(str(x) for x in r))

conn.close()

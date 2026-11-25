"""Investiga por qué la 40951 tiene UniValMapex completo y otras órdenes no."""
import pyodbc

servers = ["172.16.10.10", "EMEBIDWH"]
drivers = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"]
user, pwd = "sccz", "S@vera,CZ,2024"

def connect(db):
    for d in drivers:
        for s in servers:
            try:
                cs = f"DRIVER={{{d}}};SERVER={s};DATABASE={db};UID={user};PWD={pwd};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10"
                return pyodbc.connect(cs, timeout=10, autocommit=True)
            except Exception:
                pass
    return None

cz = connect("mapexbp")
if not cz:
    print("NO CONEXION a mapexbp")
    exit(1)
cc = cz.cursor()

print("=== 1) Columnas de his_wam_linea_pedido_cliente ===")
cc.execute("""
    SELECT COLUMN_NAME
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'his_wam_linea_pedido_cliente'
    ORDER BY ORDINAL_POSITION
""")
cols = [r[0] for r in cc.fetchall()]
print("  " + ", ".join(cols))

print("\n=== 2) Líneas omega de la 40951 (producidas al 100%) ===")
cc.execute("""
    SELECT B.id_his_wam_linea_pedido_cliente, B.Id_producto, B.UnidadesPedidas, B.UniValMapex, C.Cod_producto
    FROM his_wam_pedido_cliente A
    JOIN his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = A.id_his_wam_pedido_cliente
    JOIN V_Cfg_producto C ON C.Id_producto = B.Id_producto
    WHERE A.NumeroPedido = '40951' AND C.Cod_producto IN ('S0PFA6225946','S0PFA6225949')
""")
for r in cc.fetchall():
    print(f"  lineaId={r[0]} | IdProducto={r[1]} | Uds={r[2]} | UniValMapex={r[3]} | Cod={r[4]}")

print("\n=== 3) Línea omega de la 40053 (Picking=Yes, producidas=0) ===")
cc.execute("""
    SELECT B.id_his_wam_linea_pedido_cliente, B.Id_producto, B.UnidadesPedidas, B.UniValMapex, C.Cod_producto
    FROM his_wam_pedido_cliente A
    JOIN his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = A.id_his_wam_pedido_cliente
    JOIN V_Cfg_producto C ON C.Id_producto = B.Id_producto
    WHERE A.NumeroPedido = '40053' AND C.Cod_producto = 'S0PF56225933'
""")
for r in cc.fetchall():
    print(f"  lineaId={r[0]} | IdProducto={r[1]} | Uds={r[2]} | UniValMapex={r[3]} | Cod={r[4]}")

print("\n=== 4) OFs (órdenes de fabricación) del omega de la 40951 vs el de la 40053 ===")
for cod in ['S0PFA6225946', 'S0PFA6225949', 'S0PF56225933']:
    cc.execute("""
        SELECT Cod_of, Desc_estadoof, Fecha_ini, Fecha_fin
        FROM dbo.V_OFs
        WHERE Cod_producto = ?
        ORDER BY Fecha_ini
    """, (cod,))
    rows = cc.fetchall()
    print(f"\n  [{cod}] -> {len(rows)} OFs")
    for r in rows[:8]:
        print(f"    OF={r[0]} | Estado={r[1]} | Ini={r[2]} | Fin={r[3]}")

cz.close()
print("\nFin.")

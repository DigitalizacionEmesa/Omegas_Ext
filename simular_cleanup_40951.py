"""Replica la consulta del CLEANUP para la 40951 y comprueba si debería borrarla."""
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

for assy in ['S0PFA6225946', 'S0PFA6225949']:
    print(f"=== Cleanup simulado para 40951 / {assy} ===")
    cc.execute("""
        WITH UltimaCabecera AS (
            SELECT TOP 1
                A.id_his_wam_pedido_cliente,
                A.EstadoERP,
                A.Id_wam_estado_pedido_cliente
            FROM his_wam_pedido_cliente A
            WHERE A.NumeroPedido = '40951'
            ORDER BY A.id_his_wam_pedido_cliente DESC
        )
        SELECT TOP 1
            uc.EstadoERP,
            uc.Id_wam_estado_pedido_cliente,
            ISNULL(B.UniValMapex, 0) AS UniValMapex,
            ISNULL(B.UnidadesPedidas, 0) AS UnidadesPedidas,
            C.Cod_producto
        FROM UltimaCabecera uc
        JOIN his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = uc.id_his_wam_pedido_cliente
        JOIN V_Cfg_producto C ON C.Id_producto = B.Id_producto
        WHERE C.Cod_producto = ?
    """, (assy,))
    row = cc.fetchone()
    if not row:
        print(f"  ❌ No encontrado en MAPEX -> el cleanup lo OMITE (no lo borra)")
    else:
        estado_erp, estado_wam, uv, up, cod = row
        print(f"  EstadoERP={estado_erp} | WAM={estado_wam} | UniValMapex={uv} | Pedidas={up} | Cod={cod}")
        if estado_erp != 0 or estado_wam in (2,3,4):
            print("  => El cleanup SÍ lo borraría (estado final)")
        elif up > 0 and uv >= up:
            print("  => El cleanup SÍ lo borraría (100% producido)")
        else:
            print("  => El cleanup NO lo borraría")

conn.close()
print("\nFin.")

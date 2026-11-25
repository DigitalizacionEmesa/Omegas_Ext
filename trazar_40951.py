"""Traza el pedido 40951 en cada etapa del flujo para ver por qué no aparece en el secuenciador ES1."""
import pyodbc

servers = ["172.16.10.10", "EMEBIDWH"]
drivers = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"]
user, pwd = "sccz", "S@vera,CZ,2024"
PID = "40951"

conn = None
for d in drivers:
    for s in servers:
        try:
            cs = f"DRIVER={{{d}}};SERVER={s};DATABASE=DataLakeSCCZ;UID={user};PWD={pwd};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10"
            conn = pyodbc.connect(cs, timeout=10, autocommit=True)
            break
        except Exception as e:
            print(f"  [conn] fallo {s}/{d}: {str(e)[:60]}")
    if conn:
        break

if not conn:
    print("NO SE PUDO CONECTAR")
    exit(1)

print(f"Conectado a DataLakeSCCZ")

c = conn.cursor()

# ---------- 1) MAPEXBP: cabecera ----------
print("\n" + "=" * 90)
print("1) MAPEXBP.his_wam_pedido_cliente (cabecera)")
print("=" * 90)
try:
    with pyodbc.connect(
        f"DRIVER={{{drivers[0]}}};SERVER={servers[0]};DATABASE=mapexbp;UID={user};PWD={pwd};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10",
        timeout=10, autocommit=True) as cz:
        cc = cz.cursor()
        cc.execute(f"""
            SELECT id_his_wam_pedido_cliente, NumeroPedido, FechaEntrega, FechaPedido, Bsark,
                   EstadoERP, Id_wam_estado_pedido_cliente
            FROM his_wam_pedido_cliente
            WHERE NumeroPedido = '{PID}'
            ORDER BY id_his_wam_pedido_cliente DESC
        """)
        rows = cc.fetchall()
        if rows:
            for r in rows:
                print(f"  id={r[0]} | NumPedido={r[1]} | FechaEntrega={r[2]} | FechaPedido={r[3]} | Bsark={r[4]} | EstadoERP={r[5]} | Id_wam_estado={r[6]}")
        else:
            print(f"  ❌ Pedido {PID} NO EXISTE en his_wam_pedido_cliente")
except Exception as e:
    print(f"  Error consultando MAPEXBP: {str(e)[:200]}")

# ---------- 2) MAPEXBP: lineas ----------
print("\n" + "=" * 90)
print("2) MAPEXBP: lineas del pedido (con V_Cfg_producto)")
print("=" * 90)
try:
    with pyodbc.connect(
        f"DRIVER={{{drivers[0]}}};SERVER={servers[0]};DATABASE=mapexbp;UID={user};PWD={pwd};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10",
        timeout=10, autocommit=True) as cz:
        cc = cz.cursor()
        cc.execute(f"""
            SELECT B.id_his_wam_linea_pedido_cliente, B.Id_producto, B.UnidadesPedidas, B.UniValMapex, C.Cod_producto
            FROM his_wam_pedido_cliente A
            JOIN his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = A.id_his_wam_pedido_cliente
            JOIN V_Cfg_producto C ON C.Id_producto = B.Id_producto
            WHERE A.NumeroPedido = '{PID}'
            ORDER BY B.UnidadesPedidas DESC
        """)
        rows = cc.fetchall()
        if rows:
            for r in rows:
                print(f"  lineaId={r[0]} | IdProducto={r[1]} | Uds={r[2]} | UniVal={r[3]} | Cod_producto={r[4]}")
        else:
            print(f"  ❌ Sin líneas para {PID}")
except Exception as e:
    print(f"  Error consultando MAPEXBP líneas: {str(e)[:200]}")

# ---------- 3) DataLakeSCCZ: PedidosCabecera ----------
print("\n" + "=" * 90)
print("3) OB.PedidosCabecera")
print("=" * 90)
c.execute(f"SELECT ID_PedidoCabecera_Externa, NumeroPedido, FechaEntrega, Bsark, EstadoERP, Id_wam_estado_pedido_cliente, CWT, DS, EX, TB FROM OB.PedidosCabecera WHERE NumeroPedido='{PID}'")
rows = c.fetchall()
if rows:
    for r in rows:
        print(f"  idCab={r[0]} | Pedido={r[1]} | Fecha={r[2]} | Bsark={r[3]} | EstadoERP={r[4]} | WAM={r[5]} | CWT={r[6] or '-'} | DS={r[7] or '-'} | EX={r[8] or '-'} | TB={r[9] or '-'}")
else:
    print(f"  ❌ Pedido {PID} NO ESTÁ en OB.PedidosCabecera (no importado / borrado)")

# ---------- 4) DataLakeSCCZ: PedidosLineas ----------
print("\n" + "=" * 90)
print("4) OB.PedidosLineas (con W/C desde OB.Omegas)")
print("=" * 90)
c.execute(f"""
    SELECT pc.NumeroPedido, pl.Cod_Producto_Externo, pl.UnidadesPedidas, pl.UniValMapex,
           COALESCE(o.[W/C], '(no en Omegas)') AS WC
    FROM OB.PedidosLineas pl
    INNER JOIN OB.PedidosCabecera pc ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
    LEFT JOIN OB.Omegas o ON LTRIM(RTRIM(o.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
    WHERE pc.NumeroPedido = '{PID}'
    ORDER BY pl.UnidadesPedidas DESC
""")
rows = c.fetchall()
if rows:
    for r in rows:
        print(f"  Producto={r[1]} | Uds={r[2]} | UniVal={r[3]} | W/C={r[4]}")
else:
    print(f"  ❌ Sin líneas en OB.PedidosLineas para {PID}")

# ---------- 5) DataLakeSCCZ: PedidosSecuenciados ----------
print("\n" + "=" * 90)
print("5) OB.PedidosSecuenciados")
print("=" * 90)
c.execute(f"SELECT NumeroPedido, Assy, Beam, SequenceValue, OFs, FechaSecuenciacion, AssignedStock, AssignedStockBeam FROM OB.PedidosSecuenciados WHERE NumeroPedido='{PID}'")
rows = c.fetchall()
if rows:
    for r in rows:
        print(f"  Pedido={r[0]} | Assy={r[1]} | Beam={r[2] or '-'} | Seq={r[3]} | OFs={r[4] or '-'} | FechaSeq={r[5]} | AStock={r[6]} | AStockBeam={r[7]}")
else:
    print(f"  ❌ Pedido {PID} NO ESTÁ en OB.PedidosSecuenciados")

# ---------- 6) Vista secuenciados ----------
print("\n" + "=" * 90)
print("6) OB.V_PedidosSummary_Secuenciados_Full")
print("=" * 90)
c.execute(f"SELECT Sequence, NumeroPedido, Assy, Assembly, UnidadesPedidas, EX, TB FROM OB.V_PedidosSummary_Secuenciados_Full WHERE NumeroPedido='{PID}'")
rows = c.fetchall()
if rows:
    for r in rows:
        print(f"  Seq={r[0]} | Assy={r[2]} | Assembly={r[3]} | Qty={r[4]} | EX={r[5] or 'NULL'} | TB={r[6] or '-'}")
else:
    print(f"  ❌ Pedido {PID} NO ESTÁ en V_PedidosSummary_Secuenciados_Full")

# ---------- 7) pedidos_exportados ----------
print("\n" + "=" * 90)
print("7) OB.pedidos_exportados (características)")
print("=" * 90)
c.execute(f"SELECT characteristic_name, characteristic_value FROM OB.pedidos_exportados WHERE sales_document='{PID}'")
rows = c.fetchall()
if rows:
    for r in rows:
        print(f"  {r[0]} = {r[1]}")
else:
    print(f"  ❌ Pedido {PID} NO ESTÁ en pedidos_exportados")

conn.close()
print("\nFin.")

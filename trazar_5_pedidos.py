#!/usr/bin/env python3
"""
TRAZABILIDAD de pedidos concretos que "se secuenciaron pero no se ven en el programa".
Para cada pedido comprueba:
  1) ¿Sigue en OB.PedidosSecuenciados?
  2) ¿Aparece en OB.V_PedidosSummary_Secuenciados_Full (la vista de las pantallas)?
  3) Estado local en OB.PedidosCabecera / OB.PedidosLineas (+ W/C desde OB.Omegas)
  4) Estado real en MAPEX (mapexbp.his_wam_pedido_cliente + líneas)
  5) Simula la query del CLEANUP para saber si lo borraría o lo "omite"
"""
import sys
import json
import time
import functools
import builtins

import pyodbc

# Salida en tiempo real (sin buffering) para ver el progreso
print = functools.partial(builtins.print, flush=True)

DB_USERCZ = 'sccz'
DB_PASSWORDCZ = 'S@vera,CZ,2024'

PEDIDOS = [p.strip() for p in (sys.argv[1:] or ['42447', '42460', '42626', '42633', '42628'])]

with open('db_connection_config.json', encoding='utf-8') as f:
    cfg = json.load(f)
servers = cfg.get('cz_servers', ['172.16.10.10', 'EMEBIDWH'])
drivers = cfg.get('drivers', ['ODBC Driver 18 for SQL Server', 'SQL Server'])


def conectar(db):
    last = None
    for d in drivers:
        for s in servers:
            try:
                cs = (f"DRIVER={{{d}}};SERVER={s};DATABASE={db};UID={DB_USERCZ};"
                      f"PWD={DB_PASSWORDCZ};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10")
                c = pyodbc.connect(cs, timeout=15, autocommit=True)
                c.timeout = 30  # timeout por consulta (evita cuelgues)
                return c, s, d
            except Exception as e:
                last = e
    raise last


def norm(v):
    return str(v).strip() if v is not None else ''


main, srv_m, drv_m = conectar('DataLakeSCCZ')
cz, srv_c, drv_c = conectar('mapexbp')
print(f"✅ DataLakeSCCZ ({srv_m}) | mapexbp ({srv_c})\n")

cm = main.cursor()
cc = cz.cursor()

for pid in PEDIDOS:
    print("=" * 100)
    print(f"PEDIDO: {pid}")
    print("=" * 100)

    # ---------- 1) PedidosSecuenciados ----------
    cm.execute("""
        SELECT NumeroPedido, Assy, Beam, SequenceValue, OFs, FechaSecuenciacion,
               AssignedStock, AssignedStockBeam
        FROM OB.PedidosSecuenciados
        WHERE LTRIM(RTRIM(NumeroPedido)) = ?
        ORDER BY Assy
    """, (pid,))
    sec = cm.fetchall()
    print(f"\n[1] OB.PedidosSecuenciados -> {len(sec)} fila(s)")
    for r in sec:
        print(f"    Assy={r.Assy} | Beam={r.Beam or '-'} | Seq={r.SequenceValue} | "
              f"FecSeq={r.FechaSecuenciacion} | AStock={r.AssignedStock} | AStockBeam={r.AssignedStockBeam}")

    # ---------- 2) Vista ----------
    try:
        cm.execute("""
            SELECT LTRIM(RTRIM(NumeroPedido)) AS NP, LTRIM(RTRIM(Assy)) AS Assy,
                   Assembly, Picking, UnidadesPedidas, UniValMapex, Sequence, Beam, EX, TB
            FROM OB.V_PedidosSummary_Secuenciados_Full
            WHERE LTRIM(RTRIM(NumeroPedido)) = ?
        """, (pid,))
        vista = cm.fetchall()
        print(f"\n[2] OB.V_PedidosSummary_Secuenciados_Full -> {len(vista)} fila(s)")
        for r in vista:
            print(f"    Assy={r.Assy} | Assembly='{r.Assembly}' | Picking='{r.Picking}' | "
                  f"Pedidas={r.UnidadesPedidas} | UniVal={r.UniValMapex} | Seq={r.Sequence} | EX={r.EX or '-'} | TB={r.TB or '-'}")
    except Exception as e:
        print(f"\n[2] ⚠ Vista: {e}")

    # ---------- 3) Local cabecera + líneas ----------
    cm.execute("""
        SELECT ID_PedidoCabecera_Externa, FechaEntrega, Bsark, EstadoERP,
               Id_wam_estado_pedido_cliente, CWT, DS, EX, TB
        FROM OB.PedidosCabecera
        WHERE LTRIM(RTRIM(NumeroPedido)) = ?
    """, (pid,))
    cab = cm.fetchall()
    print(f"\n[3] OB.PedidosCabecera (local) -> {len(cab)} fila(s)")
    for r in cab:
        print(f"    ID={r.ID_PedidoCabecera_Externa} | FechaEntrega={r.FechaEntrega} | Bsark={r.Bsark} | "
              f"EstadoERP={r.EstadoERP} | WAM={r.Id_wam_estado_pedido_cliente} | CWT={r.CWT or '-'} | DS={r.DS or '-'} | EX={r.EX or '-'} | TB={r.TB or '-'}")

    cm.execute("""
        SELECT pc.NumeroPedido, pl.Cod_Producto_Externo, pl.UnidadesPedidas, pl.UniValMapex,
               COALESCE(o.[W/C], '(sin Omegas)') AS WC
        FROM OB.PedidosCabecera pc
        INNER JOIN OB.PedidosLineas pl ON pl.ID_PedidoCabecera_Externa = pc.ID_PedidoCabecera_Externa
        LEFT JOIN OB.Omegas o ON LTRIM(RTRIM(o.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
        WHERE LTRIM(RTRIM(pc.NumeroPedido)) = ?
        ORDER BY pl.UnidadesPedidas DESC
    """, (pid,))
    lin = cm.fetchall()
    print(f"    OB.PedidosLineas (local) -> {len(lin)} línea(s)")
    for r in lin:
        print(f"      Producto={r.Cod_Producto_Externo} | Pedidas={r.UnidadesPedidas} | UniVal={r.UniValMapex} | W/C={r.WC}")

    # ---------- 4) MAPEX real ----------
    cc.execute("""
        SELECT id_his_wam_pedido_cliente, FechaEntrega, FechaPedido, EstadoERP,
               Id_wam_estado_pedido_cliente
        FROM his_wam_pedido_cliente
        WHERE NumeroPedido = ?
        ORDER BY id_his_wam_pedido_cliente DESC
    """, (pid,))
    his = cc.fetchall()
    print(f"\n[4] MAPEX his_wam_pedido_cliente -> {len(his)} versión(es)")
    for r in his:
        print(f"    id={r.id_his_wam_pedido_cliente} | FechaEntrega={r.FechaEntrega} | FechaPedido={r.FechaPedido} | "
              f"EstadoERP={r.EstadoERP} | WAM={r.Id_wam_estado_pedido_cliente}")

    cc.execute("""
        SELECT B.Id_producto, B.UnidadesPedidas, B.UniValMapex, C.Cod_producto
        FROM his_wam_pedido_cliente A
        JOIN his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = A.id_his_wam_pedido_cliente
        JOIN V_Cfg_producto C ON C.Id_producto = B.Id_producto
        WHERE A.NumeroPedido = ?
        ORDER BY B.UnidadesPedidas DESC
    """, (pid,))
    mlin = cc.fetchall()
    print(f"    MAPEX líneas (todas las versiones) -> {len(mlin)} línea(s)")
    for r in mlin:
        print(f"      Cod={r.Cod_producto} | Pedidas={r.UnidadesPedidas} | UniVal={r.UniValMapex}")

    # ---------- 5) Simulación del CLEANUP (por cada Assy secuenciado) ----------
    print("\n[5] Simulación query del CLEANUP (por Assy secuenciado):")
    for r in sec:
        asy = norm(r.Assy)
        cc.execute("""
            WITH UltimaCabecera AS (
                SELECT TOP 1 id_his_wam_pedido_cliente, EstadoERP, Id_wam_estado_pedido_cliente
                FROM his_wam_pedido_cliente A
                WHERE A.NumeroPedido = ?
                ORDER BY id_his_wam_pedido_cliente DESC
            )
            SELECT TOP 1 uc.EstadoERP, uc.Id_wam_estado_pedido_cliente,
                   ISNULL(B.UniValMapex, 0) AS UniValMapex,
                   ISNULL(B.UnidadesPedidas, 0) AS UnidadesPedidas
            FROM UltimaCabecera uc
            JOIN his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = uc.id_his_wam_pedido_cliente
            JOIN V_Cfg_producto C ON C.Id_producto = B.Id_producto
            WHERE C.Cod_producto = ?
        """, (pid, asy))
        row = cc.fetchone()
        if not row:
            print(f"    - Assy={asy}: ❌ NO encontrado en MAPEX -> el CLEANUP lo OMITE (no lo borra)")
        else:
            e_erp, e_wam, uv, up = row
            verdict = ("borraría (estado final)" if (e_erp != 0 or e_wam in (2, 3, 4))
                       else ("borraría (100% producido)" if (up > 0 and uv >= up)
                             else "NO borraría (sigue pendiente)"))
            print(f"    - Assy={asy}: EstadoERP={e_erp} | WAM={e_wam} | UniVal={uv}/{up} -> cleanup {verdict}")

    print()

main.close()
cz.close()
print("Fin.")

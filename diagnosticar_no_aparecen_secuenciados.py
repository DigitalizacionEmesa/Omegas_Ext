#!/usr/bin/env python3
"""
DIAGNÓSTICO: Filas de OB.PedidosSecuenciados (27/08-30/08) que NO aparecen en la vista
OB.V_PedidosSummary_Secuenciados_Full (la que alimenta Sequenced_Omegas / OB_C / OB_W).
Clasifica el motivo de cada fila y muestra la definición de la vista para ver sus filtros.
"""
import sys
import json
from collections import defaultdict, Counter

import pyodbc

DB_USERCZ = 'sccz'
DB_PASSWORDCZ = 'S@vera,CZ,2024'

DESDE = sys.argv[1] if len(sys.argv) > 1 else '2026-08-27'
HASTA = sys.argv[2] if len(sys.argv) > 2 else '2026-08-30'

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
                c = pyodbc.connect(cs, timeout=10, autocommit=True)
                return c, s, d
            except Exception as e:
                last = e
    raise last


def norm(v):
    return str(v).strip() if v is not None else ''


conn, srv, drv = conectar('DataLakeSCCZ')
print(f"✅ Conectado a DataLakeSCCZ ({srv} / {drv})")
cur = conn.cursor()

# ---------- 1) Totales ----------
print("\n" + "=" * 100)
print("1) CANTIDADES GLOBALES")
print("=" * 100)
cur.execute("SELECT COUNT(*) FROM OB.PedidosSecuenciados")
print(f"  Total en OB.PedidosSecuenciados: {cur.fetchone()[0]}")

cur.execute("""
    SELECT COUNT(*), COUNT(DISTINCT NumeroPedido)
    FROM OB.PedidosSecuenciados
    WHERE FechaSecuenciacion >= ? AND FechaSecuenciacion < ?
""", (DESDE, HASTA))
total_filas, total_pedidos = cur.fetchone()
print(f"  Filas del {DESDE} al {HASTA}: {total_filas} (sobre {total_pedidos} pedidos distintos)")

cur.execute("SELECT COUNT(*) FROM OB.V_PedidosSummary_Secuenciados_Full")
print(f"  Filas en OB.V_PedidosSummary_Secuenciados_Full: {cur.fetchone()[0]}")

# ---------- 2) Filas objetivo ----------
print("\n" + "=" * 100)
print(f"2) FILAS OBJETIVO EN OB.PedidosSecuenciados ({DESDE}..{HASTA})")
print("=" * 100)
cur.execute("""
    SELECT NumeroPedido, Assy, Beam, SequenceValue, FechaSecuenciacion,
           AssignedStock, AssignedStockBeam, ISNULL(PriorityOrder, -1)
    FROM OB.PedidosSecuenciados
    WHERE FechaSecuenciacion >= ? AND FechaSecuenciacion < ?
    ORDER BY NumeroPedido, Assy
""", (DESDE, HASTA))
filas = cur.fetchall()
cols = [d[0] for d in cur.description]
filas = [dict(zip(cols, r)) for r in filas]
print(f"  Filas objetivo leídas: {len(filas)}")

pedidos = sorted({norm(f['NumeroPedido']) for f in filas})
assys = sorted({norm(f['Assy']) for f in filas})
ph = ','.join('?' for _ in pedidos)
ah = ','.join('?' for _ in assys)

# ---------- 3) Presencia en la vista ----------
print("\n" + "=" * 100)
print("3) ¿APARECEN EN OB.V_PedidosSummary_Secuenciados_Full?")
print("=" * 100)
vista_presencia = set()
vista_info = {}
try:
    cur.execute(f"""
        SELECT LTRIM(RTRIM(NumeroPedido)) AS NumeroPedido,
               LTRIM(RTRIM(Assy)) AS Assy,
               Assembly, Picking, UnidadesPedidas, UniValMapex
        FROM OB.V_PedidosSummary_Secuenciados_Full
        WHERE LTRIM(RTRIM(NumeroPedido)) IN ({ph})
    """, pedidos)
    for r in cur.fetchall():
        vista_presencia.add((norm(r.NumeroPedido), norm(r.Assy)))
        vista_info[(norm(r.NumeroPedido), norm(r.Assy))] = r
except Exception as e:
    print(f"  ⚠ No se pudo consultar la vista (¿cambió de esquema?): {e}")

en_vista = [f for f in filas if (norm(f['NumeroPedido']), norm(f['Assy'])) in vista_presencia]
no_vista = [f for f in filas if (norm(f['NumeroPedido']), norm(f['Assy'])) not in vista_presencia]
print(f"  ➜ Aparecen en la vista: {len(en_vista)} filas")
print(f"  ➜ NO aparecen en la vista: {len(no_vista)} filas  <-- estas son las que no se ven")

# ---------- 4) Motivos de exclusión (consultas set-based) ----------
print("\n" + "=" * 100)
print("4) CLASIFICACIÓN DE POR QUÉ NO APARECEN")
print("=" * 100)

# 4.1 Cabeceras locales
cab = {}
try:
    cur.execute(f"""
        SELECT LTRIM(RTRIM(NumeroPedido)) AS NumeroPedido,
               EstadoERP, Id_wam_estado_pedido_cliente, FechaEntrega
        FROM OB.PedidosCabecera
        WHERE LTRIM(RTRIM(NumeroPedido)) IN ({ph})
    """, pedidos)
    for r in cur.fetchall():
        cab.setdefault(norm(r.NumeroPedido), []).append(r)
except Exception as e:
    print(f"  ⚠ PedidosCabecera: {e}")

# 4.2 Líneas locales de cada Assy
lineas = set()
cantidades = {}
try:
    cur.execute(f"""
        SELECT LTRIM(RTRIM(pc.NumeroPedido)) AS NumeroPedido,
               LTRIM(RTRIM(pl.Cod_Producto_Externo)) AS Assy,
               pl.UnidadesPedidas, pl.UniValMapex
        FROM OB.PedidosCabecera pc
        INNER JOIN OB.PedidosLineas pl ON pl.ID_PedidoCabecera_Externa = pc.ID_PedidoCabecera_Externa
        WHERE LTRIM(RTRIM(pc.NumeroPedido)) IN ({ph})
    """, pedidos)
    for r in cur.fetchall():
        lineas.add((norm(r.NumeroPedido), norm(r.Assy)))
        cantidades[(norm(r.NumeroPedido), norm(r.Assy))] = (r.UnidadesPedidas or 0, r.UniValMapex or 0)
except Exception as e:
    print(f"  ⚠ PedidosLineas: {e}")

# 4.3 Catálogo OB.Omegas
omegas_wc = {}
try:
    cur.execute(f"""
        SELECT LTRIM(RTRIM(Assy)) AS Assy, [W/C]
        FROM OB.Omegas
        WHERE LTRIM(RTRIM(Assy)) IN ({ah})
    """, assys)
    for r in cur.fetchall():
        omegas_wc[norm(r.Assy)] = r[1]
except Exception as e:
    print(f"  ⚠ OB.Omegas: {e}")

# 4.4 Clasificar
motivos = Counter()
detalle = defaultdict(list)
for f in no_vista:
    ped = norm(f['NumeroPedido'])
    asy = norm(f['Assy'])
    key = (ped, asy)
    if key in vista_presencia:
        motivos['en vista (contradicción)'] += 1
        continue
    if ped not in cab or not cab[ped]:
        m = 'SIN cabecera en OB.PedidosCabecera'
    elif key not in lineas:
        m = 'Cabecera OK pero SIN línea local de ese Assy'
    elif asy not in omegas_wc:
        m = 'Assy NO está en OB.Omegas (sin W/C / Assembly)'
    else:
        uds, uv = cantidades.get(key, (0, 0))
        estados = [(r.EstadoERP, r.Id_wam_estado_pedido_cliente) for r in cab[ped]]
        terminal = any((e1 is not None and e1 != 0) or (e2 in (2, 3, 4)) for e1, e2 in estados)
        if uv >= uds and uds > 0:
            m = 'Completado localmente (UniValMapex>=Pedidas)'
        elif terminal:
            m = 'Cabecera local en estado final (no pendiente)'
        else:
            m = 'Todo OK localmente pero NO está en la vista -> la vista aplica OTRO filtro'
    motivos[m] += 1
    if len(detalle[m]) < 5:
        detalle[m].append((ped, asy, f.get('SequenceValue'), str(f.get('FechaSecuenciacion'))))

for m, n in motivos.most_common():
    print(f"  • {m}: {n} filas")
    for ped, asy, seq, fecha in detalle[m]:
        print(f"      - {ped} / {asy}  (seq={seq}, fecha={fecha})")

# ---------- 5) Definición de la vista ----------
print("\n" + "=" * 100)
print("5) DEFINICIÓN DE OB.V_PedidosSummary_Secuenciados_Full (para ver filtros)")
print("=" * 100)
try:
    cur.execute("""
        SELECT OBJECT_DEFINITION(OBJECT_ID('OB.V_PedidosSummary_Secuenciados_Full'))
    """)
    definicion = cur.fetchone()[0]
    print(definicion)
except Exception as e:
    print(f"  ⚠ No se pudo leer la definición: {e}")

conn.close()
print("\nFin.")

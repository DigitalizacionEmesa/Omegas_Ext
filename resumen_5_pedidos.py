#!/usr/bin/env python3
"""
Resumen compacto: ¿dónde aparecen los 5 pedidos? + análisis agregado de las 228 filas
secuenciadas del 27-30/08 (cuántas están en la vista que alimenta las pantallas).
"""
import sys
import functools
import builtins
import json
import pyodbc

print = functools.partial(builtins.print, flush=True)

DB_USERCZ = 'sccz'
DB_PASSWORDCZ = 'S@vera,CZ,2024'
PEDIDOS = [p.strip() for p in (sys.argv[1:] or ['42447', '42460', '42626', '42633', '42628'])]
DESDE = '2026-08-27'
HASTA = '2026-08-30'

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
                c.timeout = 45
                return c, s, d
            except Exception as e:
                last = e
    raise last


def q1(cur, sql, *p):
    cur.execute(sql, *p)
    row = cur.fetchone()
    return row[0] if row else None


main, srv_m, drv_m = conectar('DataLakeSCCZ')
cm = main.cursor()

print(f"✅ DataLakeSCCZ ({srv_m})\n")

print("=" * 90)
print("A) LOS 5 PEDIDOS: ¿dónde aparecen?")
print("=" * 90)
for pid in PEDIDOS:
    n_seq = q1(cm, "SELECT COUNT(*) FROM OB.PedidosSecuenciados WHERE LTRIM(RTRIM(NumeroPedido))=?", pid)
    n_vista = q1(cm, "SELECT COUNT(*) FROM OB.V_PedidosSummary_Secuenciados_Full WHERE LTRIM(RTRIM(NumeroPedido))=?", pid)
    try:
        n_pend = q1(cm, "SELECT COUNT(*) FROM OB.V_PedidosSummary_Pendientes_EX WHERE LTRIM(RTRIM(NumeroPedido))=?", pid)
    except Exception as e:
        n_pend = f"ERR {e}"
    loc = q1(cm, """SELECT CONCAT('EstadoERP=', EstadoERP, ' WAM=', Id_wam_estado_pedido_cliente, ' FechaEnt=', CONVERT(varchar(10),FechaEntrega,103))
                    FROM OB.PedidosCabecera WHERE LTRIM(RTRIM(NumeroPedido))=?""", pid)
    print(f"  {pid}: en_PedidosSecuenciados={n_seq} | en_vista_secuenciados={n_vista} | en_resumen_pendientes={n_pend} | cabecera_local=[{loc}]")

print("\n" + "=" * 90)
print("B) FILAS SECUENCIADAS 27-30/08 (las 228) vs VISTA DE PANTALLA")
print("=" * 90)
total = q1(cm, "SELECT COUNT(*) FROM OB.PedidosSecuenciados WHERE FechaSecuenciacion>=? AND FechaSecuenciacion<?", (DESDE, HASTA))
print(f"  Filas en OB.PedidosSecuenciados ({DESDE}..{HASTA}): {total}")

cm.execute(f"""
    SELECT COUNT(*)
    FROM OB.PedidosSecuenciados ps
    WHERE ps.FechaSecuenciacion >= ? AND ps.FechaSecuenciacion < ?
      AND EXISTS (
        SELECT 1 FROM OB.V_PedidosSummary_Secuenciados_Full v
        WHERE LTRIM(RTRIM(v.NumeroPedido)) = LTRIM(RTRIM(ps.NumeroPedido))
          AND LTRIM(RTRIM(v.Assy)) = LTRIM(RTRIM(ps.Assy))
      )
""", (DESDE, HASTA))
en_vista = cm.fetchone()[0]
print(f"  ➜ De esas, SÍ aparecen en la vista secuenciados: {en_vista}")
print(f"  ➜ NO aparecen en la vista: {total - en_vista}")

# Motivo de las que no están en la vista (agregado, solo conteos)
cm.execute(f"""
    SELECT
        CASE
            WHEN pc.ID_PedidoCabecera_Externa IS NULL THEN 'sin_cabecera_local'
            WHEN NOT EXISTS (SELECT 1 FROM OB.PedidosLineas pl2
                             WHERE pl2.ID_PedidoCabecera_Externa = pc.ID_PedidoCabecera_Externa
                               AND LTRIM(RTRIM(pl2.Cod_Producto_Externo)) = LTRIM(RTRIM(ps.Assy))) THEN 'cabecera_sin_linea_del_assy'
            WHEN o.Assy IS NULL THEN 'assy_no_esta_en_OB.Omegas'
            WHEN ISNULL(pl.UniValMapex,0) >= pl.UnidadesPedidas AND pl.UnidadesPedidas > 0 THEN 'completado_local'
            WHEN ISNULL(pc.EstadoERP,0) <> 0 OR pc.Id_wam_estado_pedido_cliente IN (2,3,4) THEN 'cabecera_estado_final'
            ELSE 'otro/desconocido'
        END AS motivo,
        COUNT(*)
    FROM OB.PedidosSecuenciados ps
    LEFT JOIN OB.PedidosCabecera pc ON LTRIM(RTRIM(pc.NumeroPedido)) = LTRIM(RTRIM(ps.NumeroPedido))
    LEFT JOIN OB.PedidosLineas pl ON pl.ID_PedidoCabecera_Externa = pc.ID_PedidoCabecera_Externa
                                 AND LTRIM(RTRIM(pl.Cod_Producto_Externo)) = LTRIM(RTRIM(ps.Assy))
    LEFT JOIN OB.Omegas o ON LTRIM(RTRIM(o.Assy)) = LTRIM(RTRIM(ps.Assy))
    WHERE ps.FechaSecuenciacion >= ? AND ps.FechaSecuenciacion < ?
      AND NOT EXISTS (
        SELECT 1 FROM OB.V_PedidosSummary_Secuenciados_Full v
        WHERE LTRIM(RTRIM(v.NumeroPedido)) = LTRIM(RTRIM(ps.NumeroPedido))
          AND LTRIM(RTRIM(v.Assy)) = LTRIM(RTRIM(ps.Assy))
      )
    GROUP BY
        CASE
            WHEN pc.ID_PedidoCabecera_Externa IS NULL THEN 'sin_cabecera_local'
            WHEN NOT EXISTS (SELECT 1 FROM OB.PedidosLineas pl2
                             WHERE pl2.ID_PedidoCabecera_Externa = pc.ID_PedidoCabecera_Externa
                               AND LTRIM(RTRIM(pl2.Cod_Producto_Externo)) = LTRIM(RTRIM(ps.Assy))) THEN 'cabecera_sin_linea_del_assy'
            WHEN o.Assy IS NULL THEN 'assy_no_esta_en_OB.Omegas'
            WHEN ISNULL(pl.UniValMapex,0) >= pl.UnidadesPedidas AND pl.UnidadesPedidas > 0 THEN 'completado_local'
            WHEN ISNULL(pc.EstadoERP,0) <> 0 OR pc.Id_wam_estado_pedido_cliente IN (2,3,4) THEN 'cabecera_estado_final'
            ELSE 'otro/desconocido'
        END
    ORDER BY COUNT(*) DESC
""", (DESDE, HASTA))
print("\n  Motivos por los que esas filas NO salen en la vista:")
for motivo, cnt in cm.fetchall():
    print(f"    • {motivo}: {cnt}")

print("\nC) MUESTRA de filas secuenciadas 27-30 que SÍ están en la vista (primeras 8):")
cm.execute(f"""
    SELECT TOP 8 ps.NumeroPedido, ps.Assy, v.Assembly, v.Picking,
           ps.UnidadesPedidas, ps.UniValMapex, v.Sequence
    FROM OB.PedidosSecuenciados ps
    INNER JOIN OB.V_PedidosSummary_Secuenciados_Full v
        ON LTRIM(RTRIM(v.NumeroPedido)) = LTRIM(RTRIM(ps.NumeroPedido))
       AND LTRIM(RTRIM(v.Assy)) = LTRIM(RTRIM(ps.Assy))
    WHERE ps.FechaSecuenciacion >= ? AND ps.FechaSecuenciacion < ?
    ORDER BY ps.NumeroPedido
""", (DESDE, HASTA))
for r in cm.fetchall():
    print(f"    {r.NumeroPedido} / {r.Assy} | Assembly='{r.Assembly}' Picking='{r.Picking}' | Pedidas={r.UnidadesPedidas} UniVal={r.UniValMapex} Seq={r.Sequence}")

main.close()
print("\nFin.")

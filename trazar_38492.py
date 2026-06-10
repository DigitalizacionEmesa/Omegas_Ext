"""Traza pedido 38492 en cada etapa del flujo."""
import pyodbc

servers = ["172.16.10.10", "EMEBIDWH"]
drivers = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"]
user, pwd = "sccz", "S@vera,CZ,2024"

conn = None
for d in drivers:
    for s in servers:
        try:
            cs = f"DRIVER={{{d}}};SERVER={s};DATABASE=DataLakeSCCZ;UID={user};PWD={pwd};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10"
            conn = pyodbc.connect(cs, timeout=10, autocommit=True)
            break
        except:
            pass
    if conn:
        break
c = conn.cursor()
PID = "38492"

# 1) PedidosCabecera
print("=" * 80)
print("1) OB.PedidosCabecera")
print("=" * 80)
c.execute(f"SELECT NumeroPedido, FechaEntrega, CWT, DS, EX, TB, Id_wam_estado_pedido_cliente FROM OB.PedidosCabecera WHERE NumeroPedido='{PID}'")
for r in c.fetchall():
    print(f"  Pedido={r[0]} | Fecha={r[1]} | CWT={r[2] or '-'} | DS={r[3] or '-'} | EX={r[4] or '-'} | TB={r[5] or '-'} | EstadoWAM={r[6]}")

# 2) PedidosLineas
print("\n" + "=" * 80)
print("2) OB.PedidosLineas (primeras 10)")
print("=" * 80)
c.execute(f"""
    SELECT pc.NumeroPedido, pl.Cod_Producto_Externo, pl.UnidadesPedidas, pl.UniValMapex,
           COALESCE(o.[W/C], '(no en Omegas)') AS WC
    FROM OB.PedidosLineas pl
    INNER JOIN OB.PedidosCabecera pc ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
    LEFT JOIN OB.Omegas o ON LTRIM(RTRIM(o.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
    WHERE pc.NumeroPedido = '{PID}'
    ORDER BY pl.UnidadesPedidas DESC
""")
for r in c.fetchall():
    print(f"  Producto={r[1]} | Uds={r[2]} | UniValMapex={r[3]} | W/C={r[4]}")

# 3) V_PedidosSummary_Secuenciados_Full
print("\n" + "=" * 80)
print("3) V_PedidosSummary_Secuenciados_Full")
print("=" * 80)
c.execute(f"SELECT Sequence, NumeroPedido, Assy, Assembly, UnidadesPedidas, EX, TB FROM OB.V_PedidosSummary_Secuenciados_Full WHERE NumeroPedido='{PID}'")
rows = c.fetchall()
if rows:
    for r in rows:
        print(f"  Seq={r[0]} | Assy={r[2]} | Assembly={r[3]} | Qty={r[4]} | EX={r[5] or 'NULL'} | TB={r[6] or '-'}")
else:
    print(f"  Pedido {PID}: NO ESTA en V_PedidosSummary_Secuenciados_Full")

# 4) pedidos_exportados
print("\n" + "=" * 80)
print("4) OB.pedidos_exportados")
print("=" * 80)
c.execute(f"SELECT characteristic_name, characteristic_value FROM OB.pedidos_exportados WHERE sales_document='{PID}'")
rows = c.fetchall()
if rows:
    for r in rows:
        print(f"  {r[0]} = {r[1]}")
else:
    print(f"  Pedido {PID}: NO esta en pedidos_exportados")

# 5) Simulacion completa
print("\n" + "=" * 80)
print("5) SIMULACION del endpoint real (resolucion Extender)")
print("=" * 80)
c.execute(f"""
    SELECT ps.NumeroPedido, ps.Sequence, ps.Assy, ps.UnidadesPedidas AS Qty,
        COALESCE(NULLIF(LTRIM(RTRIM(ps.EX)),''), extline.LineExtender, extderived.DerivedExtender) AS Extender,
        CASE WHEN COALESCE(NULLIF(LTRIM(RTRIM(ps.EX)),''), extline.LineExtender, extderived.DerivedExtender) IS NULL THEN NULL
             WHEN exttarget.IsTargetAssy = 1 THEN CASE WHEN ps.UnidadesPedidas > 2 THEN ps.UnidadesPedidas - 2 ELSE 0 END
             ELSE NULL END AS ExtenderQuantity
    FROM OB.V_PedidosSummary_Secuenciados_Full ps
    OUTER APPLY (
        SELECT TOP 1 LTRIM(RTRIM(pl.Cod_Producto_Externo)) AS LineExtender
        FROM OB.PedidosCabecera pc2
        INNER JOIN OB.PedidosLineas pl ON pc2.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
        INNER JOIN OB.Omegas o_line ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
        WHERE LTRIM(RTRIM(pc2.NumeroPedido)) = LTRIM(RTRIM(ps.NumeroPedido))
          AND LTRIM(RTRIM(o_line.[W/C])) = 'EX'
        ORDER BY pl.UnidadesPedidas DESC, pl.Cod_Producto_Externo ASC
    ) extline
    OUTER APPLY (
        SELECT TOP 1 LTRIM(RTRIM(pe_tsd.characteristic_value)) AS DerivedExtender
        FROM OB.pedidos_exportados pe_lh
        INNER JOIN OB.pedidos_exportados pe_tsd ON LTRIM(RTRIM(pe_tsd.sales_document)) = LTRIM(RTRIM(pe_lh.sales_document))
        INNER JOIN OB.Omegas o_tsd ON LTRIM(RTRIM(o_tsd.Assy)) = LTRIM(RTRIM(ps.Assy))
           AND LTRIM(RTRIM(o_tsd.ExtenderVariable)) = LTRIM(RTRIM(pe_tsd.characteristic_value))
        WHERE LTRIM(RTRIM(pe_lh.sales_document)) = LTRIM(RTRIM(ps.NumeroPedido))
          AND pe_lh.characteristic_name = 'GRP_HSK_TYPE'
          AND UPPER(LTRIM(RTRIM(pe_lh.characteristic_value))) = 'LH'
          AND pe_tsd.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
          AND pe_tsd.characteristic_value IS NOT NULL
          AND LTRIM(RTRIM(pe_tsd.characteristic_value)) <> ''
          AND NOT EXISTS (
              SELECT 1 FROM OB.PedidosCabecera pc3
              INNER JOIN OB.PedidosLineas pl2 ON pc3.ID_PedidoCabecera_Externa = pl2.ID_PedidoCabecera_Externa
              INNER JOIN OB.Omegas o_line2 ON LTRIM(RTRIM(o_line2.Assy)) = LTRIM(RTRIM(pl2.Cod_Producto_Externo))
              WHERE LTRIM(RTRIM(pc3.NumeroPedido)) = LTRIM(RTRIM(ps.NumeroPedido))
                AND LTRIM(RTRIM(o_line2.[W/C])) = 'EX'
          )
    ) extderived
    OUTER APPLY (
        SELECT TOP 1 1 AS IsTargetAssy
        FROM OB.pedidos_exportados pe_lh
        INNER JOIN OB.pedidos_exportados pe ON LTRIM(RTRIM(pe.sales_document)) = LTRIM(RTRIM(pe_lh.sales_document))
        INNER JOIN OB.Omegas o_target ON (
            (pe.characteristic_name IN ('GRP_OMEGA_BRACKET_TYPE_HEAD', 'GRP_OMEGA_BRACKET_TYPE_TRAV')
             AND LTRIM(RTRIM(o_target.OmegaType)) = LTRIM(RTRIM(pe.characteristic_value)))
            OR (pe.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
                AND LTRIM(RTRIM(o_target.ExtenderVariable)) = LTRIM(RTRIM(pe.characteristic_value)))
        )
        WHERE LTRIM(RTRIM(pe_lh.sales_document)) = LTRIM(RTRIM(ps.NumeroPedido))
          AND pe_lh.characteristic_name = 'GRP_HSK_TYPE'
          AND UPPER(LTRIM(RTRIM(pe_lh.characteristic_value))) = 'LH'
          AND pe.characteristic_value IS NOT NULL
          AND LTRIM(RTRIM(pe.characteristic_value)) <> ''
          AND LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM(ps.Assy))
    ) exttarget
    WHERE UPPER(LTRIM(RTRIM(ps.Assembly))) IN ('YES C', 'YES W')
      AND ps.NumeroPedido = '{PID}'
    ORDER BY ps.Sequence
""")
rows = c.fetchall()
if rows:
    for r in rows:
        ext = r[4] if r[4] else "NULL"
        extq = str(r[5]) if r[5] is not None else "NULL"
        print(f"  Seq={r[1]} | Assy={r[2]} | Qty={r[3]} | Extender={ext} | ExtQty={extq}")
else:
    print(f"  Pedido {PID}: NO resuelto (no esta en C/W)")

conn.close()
print("\nFin.")

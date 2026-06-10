"""Verifica si los pedidos 39085, 38816, 70001476 tendrian extensor resuelto."""
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

if not conn:
    print("No se pudo conectar")
    exit(1)

c = conn.cursor()

PEDIDOS = ["39085", "38816", "70001476"]

# 1) Presencia en vista secuenciados
print("=" * 80)
print("1) ¿Están en V_PedidosSummary_Secuenciados_Full?")
print("=" * 80)
for pid in PEDIDOS:
    c.execute(f"SELECT Sequence, NumeroPedido, Assy, Assembly, UnidadesPedidas, EX, TB FROM OB.V_PedidosSummary_Secuenciados_Full WHERE NumeroPedido='{pid}'")
    rows = c.fetchall()
    if rows:
        for r in rows:
            ex = "NULL" if not r[5] or str(r[5]).strip() == "" else r[5]
            tb = str(r[6] or "").strip() or "-"
            print(f"  Seq={r[0]} | Pedido={r[1]} | Assy={r[2]} | Assembly={r[3]} | Qty={r[4]} | EX={ex} | TB={tb}")
    else:
        print(f"  ❌ Pedido {pid}: NO ESTÁ en la vista de secuenciados")

# 2) Líneas EX
print("\n" + "=" * 80)
print("2) ¿Tienen líneas con W/C='EX' en PedidosLineas?")
print("=" * 80)
for pid in PEDIDOS:
    c.execute(f"""
        SELECT pc.NumeroPedido, pl.Cod_Producto_Externo, pl.UnidadesPedidas
        FROM OB.PedidosCabecera pc
        INNER JOIN OB.PedidosLineas pl ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
        INNER JOIN OB.Omegas o ON LTRIM(RTRIM(o.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
        WHERE LTRIM(RTRIM(o.[W/C])) = 'EX' AND pc.NumeroPedido = '{pid}'
    """)
    rows = c.fetchall()
    if rows:
        for r in rows:
            print(f"  Pedido={r[0]} | Producto EX={r[1]} | Uds={r[2]}")
    else:
        print(f"  ❌ Pedido {pid}: sin líneas EX")

# 3) LH + TSD
print("\n" + "=" * 80)
print("3) ¿Son LH con TSD en pedidos_exportados?")
print("=" * 80)
for pid in PEDIDOS:
    c.execute(f"""
        SELECT pe_lh.characteristic_value AS HSK, pe_tsd.characteristic_value AS TSD
        FROM OB.pedidos_exportados pe_lh
        INNER JOIN OB.pedidos_exportados pe_tsd ON LTRIM(RTRIM(pe_tsd.sales_document)) = LTRIM(RTRIM(pe_lh.sales_document))
        WHERE pe_lh.characteristic_name = 'GRP_HSK_TYPE'
          AND UPPER(LTRIM(RTRIM(pe_lh.characteristic_value))) = 'LH'
          AND pe_tsd.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
          AND pe_tsd.characteristic_value IS NOT NULL
          AND LTRIM(RTRIM(pe_tsd.characteristic_value)) <> ''
          AND pe_lh.sales_document = '{pid}'
    """)
    rows = c.fetchall()
    if rows:
        for r in rows:
            print(f"  Pedido={pid} | HSK={r[0]} | TSD={r[1]}")
    else:
        print(f"  ❌ Pedido {pid}: NO es LH o no tiene TSD")

# 4) SIMULACIÓN EXACTA del endpoint
print("\n" + "=" * 80)
print("4) SIMULACIÓN del endpoint real (resolución completa)")
print("=" * 80)
c.execute("""
    SELECT 
        ps.NumeroPedido,
        ps.Sequence,
        ps.Assy,
        COALESCE(NULLIF(LTRIM(RTRIM(ps.EX)), ''), extline.LineExtender, extderived.DerivedExtender) AS Extender,
        CASE 
            WHEN COALESCE(NULLIF(LTRIM(RTRIM(ps.EX)), ''), extline.LineExtender, extderived.DerivedExtender) IS NULL THEN NULL
            WHEN exttarget.IsTargetAssy = 1 THEN CASE WHEN ps.UnidadesPedidas > 2 THEN ps.UnidadesPedidas - 2 ELSE 0 END
            ELSE NULL 
        END AS ExtenderQuantity
    FROM OB.V_PedidosSummary_Secuenciados_Full ps
    OUTER APPLY (
        SELECT TOP 1 LTRIM(RTRIM(pl.Cod_Producto_Externo)) AS LineExtender
        FROM OB.PedidosCabecera pc
        INNER JOIN OB.PedidosLineas pl ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
        INNER JOIN OB.Omegas o_line ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
        WHERE LTRIM(RTRIM(pc.NumeroPedido)) = LTRIM(RTRIM(ps.NumeroPedido))
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
              SELECT 1 FROM OB.PedidosCabecera pc2
              INNER JOIN OB.PedidosLineas pl2 ON pc2.ID_PedidoCabecera_Externa = pl2.ID_PedidoCabecera_Externa
              INNER JOIN OB.Omegas o_line2 ON LTRIM(RTRIM(o_line2.Assy)) = LTRIM(RTRIM(pl2.Cod_Producto_Externo))
              WHERE LTRIM(RTRIM(pc2.NumeroPedido)) = LTRIM(RTRIM(ps.NumeroPedido))
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
      AND ps.NumeroPedido IN ('39085', '38816', '70001476')
    ORDER BY ps.Sequence
""")
rows = c.fetchall()
if rows:
    for r in rows:
        ext = r[3] if r[3] else "NULL"
        extq = str(r[4]) if r[4] is not None else "NULL"
        print(f"  Seq={r[1]} | Pedido={r[0]} | Assy={r[2]} | Extender={ext} | ExtQty={extq}")
else:
    print("  ❌ Ninguno de estos 3 pedidos aparece en C/W secuenciados")

conn.close()
print("\n✅ Verificación completada.")

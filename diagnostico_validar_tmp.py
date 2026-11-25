#!/usr/bin/env python3
"""Valida la nueva consulta set-based de C frente a la antigua (columna a columna)."""
import sys, time
sys.path.insert(0, r"c:\Proyectos\Desarrollo_Omegas - copia\api")
import appOMEGAS as app

done_qty_sql = "ISNULL(ps.UniValMapex,0) + ISNULL(ps.AssignedStock,0)"
cwi = app.build_pedidos_cabecera_optional_select_sql('CWI')

OLD = '''
                SELECT 
                    ps.Sequence AS Sequence,
                    ps.NumeroPedido AS SalesOrder,
                    ps.UnidadesPedidas AS Qty,
                    ''' + done_qty_sql + ''' AS DoneQty,
                    ps.Assy,
                    ps.Beam,
                    o.IF1,
                    o.IF2,
                    COALESCE(NULLIF(LTRIM(RTRIM(ps.TB)), ''), tbext.WCLine) AS TieBracket,
                    ISNULL(pc.CWT, '') AS CWT,
                    ISNULL(pc.DS, '') AS MS,
                    pc.FechaEntrega AS DeliveryDate,
                    ''' + cwi + ''',
                    ps.OFs AS WO,
                    ''' + app.build_extender_resolved_value_sql('ps') + ''' AS Extender,
                    ps.PriorityOrder,
''' + app.build_pit_bracket_value_sql('ps') + ''' AS PitBracket,
''' + app.build_pit_bracket_quantity_value_sql('ps') + ''' AS PitBracketQty,
''' + app.build_tb_cards_quantity_case_sql('ps', False, 'TieBracketQty') + ''',
''' + app.build_tb_cards_quantity_case_sql('ps', True, 'TieExtenderQty') + ''',
''' + app.build_extender_resolved_quantity_sql('ps') + '''
                FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
                LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON pc.NumeroPedido = ps.NumeroPedido
                LEFT JOIN OB.Omegas o ON ps.Assy = o.Assy
''' + app.build_wc_line_apply_sql('ps', 'tbext', 'TB') + '''
''' + app.build_extender_line_apply_sql('ps') + '''
''' + app.build_extender_derived_apply_sql('ps') + '''
''' + app.build_extender_target_apply_sql('ps') + '''
                WHERE UPPER(LTRIM(RTRIM(ps.Assembly))) = 'YES C'
                ORDER BY 
                    CASE WHEN ps.PriorityOrder IS NULL THEN 1 ELSE 0 END,
                    ps.PriorityOrder ASC,
                    ps.Sequence ASC
'''

NEW = '''
WITH base AS (
    SELECT
        ps.Sequence AS Sequence,
        ps.NumeroPedido AS SalesOrder,
        ps.NumeroPedido AS NumeroPedido,
        ps.UnidadesPedidas AS Qty,
        ps.UnidadesPedidas AS UnidadesPedidas,
        ''' + done_qty_sql + ''' AS DoneQty,
        ps.Assy,
        ps.Beam,
        o.IF1,
        o.IF2,
        ISNULL(pc.CWT, '') AS CWT,
        ISNULL(pc.DS, '') AS MS,
        pc.FechaEntrega AS DeliveryDate,
        ''' + cwi + ''',
        ps.OFs AS WO,
        ps.EX AS RawEX,
        ps.TB AS RawTB,
        ps.PriorityOrder
    FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
    LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON pc.NumeroPedido = ps.NumeroPedido
    LEFT JOIN OB.Omegas o WITH (NOLOCK) ON ps.Assy = o.Assy
    WHERE UPPER(LTRIM(RTRIM(ps.Assembly))) = 'YES C'
),
wc_tb AS (
    SELECT pc.NumeroPedido,
           LTRIM(RTRIM(pl.Cod_Producto_Externo)) AS WCLine,
           ROW_NUMBER() OVER (PARTITION BY pc.NumeroPedido ORDER BY pl.UnidadesPedidas DESC, pl.Cod_Producto_Externo ASC) AS rn
    FROM OB.PedidosCabecera pc WITH (NOLOCK)
    INNER JOIN OB.PedidosLineas pl WITH (NOLOCK) ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
    INNER JOIN OB.Omegas o_line WITH (NOLOCK) ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
    WHERE LTRIM(RTRIM(o_line.[W/C])) = 'TB'
),
wc_ex AS (
    SELECT pc.NumeroPedido,
           LTRIM(RTRIM(pl.Cod_Producto_Externo)) AS WCLine,
           ROW_NUMBER() OVER (PARTITION BY pc.NumeroPedido ORDER BY pl.UnidadesPedidas DESC, pl.Cod_Producto_Externo ASC) AS rn
    FROM OB.PedidosCabecera pc WITH (NOLOCK)
    INNER JOIN OB.PedidosLineas pl WITH (NOLOCK) ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
    INNER JOIN OB.Omegas o_line WITH (NOLOCK) ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
    WHERE LTRIM(RTRIM(o_line.[W/C])) = 'EX'
),
has_ex_line AS (
    SELECT DISTINCT pc.NumeroPedido
    FROM OB.PedidosCabecera pc WITH (NOLOCK)
    INNER JOIN OB.PedidosLineas pl WITH (NOLOCK) ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
    INNER JOIN OB.Omegas o_line WITH (NOLOCK) ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
    WHERE LTRIM(RTRIM(o_line.[W/C])) = 'EX'
),
ext_derived AS (
    SELECT DISTINCT b.NumeroPedido, b.Assy, b.Assy AS DerivedExtender
    FROM base b
    INNER JOIN OB.pedidos_exportados pe_lh WITH (NOLOCK)
        ON LTRIM(RTRIM(pe_lh.sales_document)) = LTRIM(RTRIM(b.NumeroPedido))
    INNER JOIN OB.pedidos_exportados pe_tsd WITH (NOLOCK)
        ON LTRIM(RTRIM(pe_tsd.sales_document)) = LTRIM(RTRIM(pe_lh.sales_document))
    INNER JOIN OB.Omegas o_tsd WITH (NOLOCK)
        ON LTRIM(RTRIM(o_tsd.Assy)) = LTRIM(RTRIM(b.Assy))
       AND LTRIM(RTRIM(o_tsd.ExtenderVariable)) = LTRIM(RTRIM(pe_tsd.characteristic_value))
    WHERE pe_lh.characteristic_name = 'GRP_HSK_TYPE'
      AND UPPER(LTRIM(RTRIM(pe_lh.characteristic_value))) = 'LH'
      AND pe_tsd.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
      AND pe_tsd.characteristic_value IS NOT NULL
      AND LTRIM(RTRIM(pe_tsd.characteristic_value)) <> ''
      AND NOT EXISTS (SELECT 1 FROM has_ex_line hx WHERE hx.NumeroPedido = b.NumeroPedido)
),
ext_target AS (
    SELECT DISTINCT b.NumeroPedido, b.Assy, 1 AS IsTargetAssy
    FROM base b
    INNER JOIN OB.pedidos_exportados pe_lh WITH (NOLOCK)
        ON LTRIM(RTRIM(pe_lh.sales_document)) = LTRIM(RTRIM(b.NumeroPedido))
    INNER JOIN OB.pedidos_exportados pe WITH (NOLOCK)
        ON LTRIM(RTRIM(pe.sales_document)) = LTRIM(RTRIM(pe_lh.sales_document))
    INNER JOIN OB.Omegas o_target WITH (NOLOCK)
        ON (
            pe.characteristic_name IN ('GRP_OMEGA_BRACKET_TYPE_HEAD', 'GRP_OMEGA_BRACKET_TYPE_TRAV')
            AND LTRIM(RTRIM(o_target.OmegaType)) = LTRIM(RTRIM(pe.characteristic_value))
        )
        OR (
            pe.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
            AND LTRIM(RTRIM(o_target.ExtenderVariable)) = LTRIM(RTRIM(pe.characteristic_value))
        )
    WHERE pe_lh.characteristic_name = 'GRP_HSK_TYPE'
      AND UPPER(LTRIM(RTRIM(pe_lh.characteristic_value))) = 'LH'
      AND pe.characteristic_value IS NOT NULL
      AND LTRIM(RTRIM(pe.characteristic_value)) <> ''
      AND LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM(b.Assy))
),
pit_value AS (
    SELECT LTRIM(RTRIM(pe_pit.sales_document)) AS NumeroPedido,
           MIN(LTRIM(RTRIM(pe_pit.characteristic_value))) AS PitBracket
    FROM OB.pedidos_exportados pe_pit WITH (NOLOCK)
    WHERE pe_pit.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_PIT'
      AND pe_pit.characteristic_value IS NOT NULL
      AND LTRIM(RTRIM(pe_pit.characteristic_value)) <> ''
    GROUP BY LTRIM(RTRIM(pe_pit.sales_document))
),
pit_target_exists AS (
    SELECT DISTINCT b.NumeroPedido, b.Assy
    FROM base b
    INNER JOIN OB.pedidos_exportados pe_type WITH (NOLOCK)
        ON LTRIM(RTRIM(pe_type.sales_document)) = LTRIM(RTRIM(b.NumeroPedido))
    INNER JOIN OB.Omegas o_target WITH (NOLOCK)
        ON LTRIM(RTRIM(o_target.OmegaType)) = LTRIM(RTRIM(pe_type.characteristic_value))
    WHERE pe_type.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_PIT'
      AND pe_type.characteristic_value IS NOT NULL
      AND LTRIM(RTRIM(pe_type.characteristic_value)) <> ''
      AND LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM(b.Assy))
),
pit_qty AS (
    SELECT LTRIM(RTRIM(pe_qty.sales_document)) AS NumeroPedido,
           MIN(TRY_CAST(LTRIM(RTRIM(pe_qty.characteristic_value)) AS INT)) AS Qty
    FROM OB.pedidos_exportados pe_qty WITH (NOLOCK)
    WHERE pe_qty.characteristic_name = 'GRP_OMEGA_BRACKET_QTY_PIT'
      AND pe_qty.characteristic_value IS NOT NULL
      AND LTRIM(RTRIM(pe_qty.characteristic_value)) <> ''
    GROUP BY LTRIM(RTRIM(pe_qty.sales_document))
),
tb_opt_y AS (
    SELECT DISTINCT LTRIM(RTRIM(pe_opt.sales_document)) AS NumeroPedido
    FROM OB.pedidos_exportados pe_opt WITH (NOLOCK)
    WHERE pe_opt.characteristic_name = 'GRP_TIE_BRACKET_OPT'
      AND UPPER(LTRIM(RTRIM(pe_opt.characteristic_value))) = 'Y'
),
tb_target_exists AS (
    SELECT DISTINCT b.NumeroPedido, b.Assy
    FROM base b
    INNER JOIN OB.pedidos_exportados pe_opt WITH (NOLOCK)
        ON LTRIM(RTRIM(pe_opt.sales_document)) = LTRIM(RTRIM(b.NumeroPedido))
    INNER JOIN OB.pedidos_exportados pe_type WITH (NOLOCK)
        ON LTRIM(RTRIM(pe_type.sales_document)) = LTRIM(RTRIM(pe_opt.sales_document))
    INNER JOIN OB.Omegas o_target WITH (NOLOCK)
        ON LTRIM(RTRIM(o_target.OmegaType)) = LTRIM(RTRIM(pe_type.characteristic_value))
    WHERE pe_opt.characteristic_name = 'GRP_TIE_BRACKET_OPT'
      AND UPPER(LTRIM(RTRIM(pe_opt.characteristic_value))) = 'Y'
      AND pe_type.characteristic_name = 'GRP_TIE_BRACKET_TYPE'
      AND pe_type.characteristic_value IS NOT NULL
      AND LTRIM(RTRIM(pe_type.characteristic_value)) <> ''
      AND LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM(b.Assy))
),
tb_qty AS (
    SELECT LTRIM(RTRIM(pe_qty.sales_document)) AS NumeroPedido,
           MIN(TRY_CAST(LTRIM(RTRIM(pe_qty.characteristic_value)) AS INT)) AS Qty
    FROM OB.pedidos_exportados pe_qty WITH (NOLOCK)
    WHERE pe_qty.characteristic_name = 'GRP_TIE_BRACKET_QTY'
      AND pe_qty.characteristic_value IS NOT NULL
      AND LTRIM(RTRIM(pe_qty.characteristic_value)) <> ''
    GROUP BY LTRIM(RTRIM(pe_qty.sales_document))
),
tb_line_qty AS (
    SELECT pc.NumeroPedido,
           pl.UnidadesPedidas AS Qty,
           ROW_NUMBER() OVER (PARTITION BY pc.NumeroPedido ORDER BY pl.UnidadesPedidas DESC, pl.Cod_Producto_Externo ASC) AS rn
    FROM OB.PedidosCabecera pc WITH (NOLOCK)
    INNER JOIN OB.PedidosLineas pl WITH (NOLOCK) ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
    INNER JOIN OB.Omegas o_line WITH (NOLOCK) ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
    WHERE LTRIM(RTRIM(o_line.[W/C])) = 'TB'
),
ext_value AS (
    SELECT
        b.NumeroPedido,
        b.Assy,
        COALESCE(NULLIF(LTRIM(RTRIM(b.RawEX)), ''), we.WCLine, ed.DerivedExtender) AS Extender
    FROM base b
    LEFT JOIN (SELECT NumeroPedido, WCLine FROM wc_ex WHERE rn = 1) we ON we.NumeroPedido = b.NumeroPedido
    LEFT JOIN ext_derived ed ON ed.NumeroPedido = b.NumeroPedido AND ed.Assy = b.Assy
),
ext_qty AS (
    SELECT
        b.NumeroPedido,
        b.Assy,
        CASE
            WHEN ev.Extender IS NULL THEN NULL
            WHEN et.IsTargetAssy = 1 THEN CASE
                WHEN b.UnidadesPedidas > 2 THEN b.UnidadesPedidas - 2
                ELSE 0
            END
            ELSE NULL
        END AS ExtenderQuantity
    FROM base b
    LEFT JOIN ext_value ev ON ev.NumeroPedido = b.NumeroPedido AND ev.Assy = b.Assy
    LEFT JOIN ext_target et ON et.NumeroPedido = b.NumeroPedido AND et.Assy = b.Assy
)
SELECT
    b.Sequence,
    b.SalesOrder,
    b.Qty,
    b.DoneQty,
    b.Assy,
    b.Beam,
    b.IF1,
    b.IF2,
    COALESCE(NULLIF(LTRIM(RTRIM(b.RawTB)), ''), wtb.WCLine) AS TieBracket,
    b.CWT,
    b.MS,
    b.DeliveryDate,
    b.CWI,
    b.WO,
    ev.Extender,
    b.PriorityOrder,
    pv.PitBracket,
    CASE WHEN pte.NumeroPedido IS NULL THEN NULL ELSE pq.Qty END AS PitBracketQty,
    COALESCE(
        CASE WHEN COALESCE(NULLIF(LTRIM(RTRIM(b.RawTB)), ''), wtb.WCLine) IS NULL THEN NULL
             WHEN tte.NumeroPedido IS NULL THEN NULL
             ELSE tq.Qty END,
        CASE WHEN COALESCE(NULLIF(LTRIM(RTRIM(b.RawTB)), ''), wtb.WCLine) IS NULL THEN NULL
             WHEN toy.NumeroPedido IS NOT NULL THEN NULL
             WHEN eq.ExtenderQuantity IS NOT NULL THEN 1
             ELSE NULL END,
        tlq.Qty
    ) AS TieBracketQty,
    COALESCE(
        CASE WHEN COALESCE(NULLIF(LTRIM(RTRIM(b.RawTB)), ''), wtb.WCLine) IS NULL THEN NULL
             WHEN tte.NumeroPedido IS NULL THEN NULL
             ELSE tq.Qty END,
        CASE WHEN COALESCE(NULLIF(LTRIM(RTRIM(b.RawTB)), ''), wtb.WCLine) IS NULL THEN NULL
             WHEN toy.NumeroPedido IS NOT NULL THEN NULL
             WHEN eq.ExtenderQuantity IS NOT NULL THEN 1
             ELSE NULL END
    ) AS TieExtenderQty,
    eq.ExtenderQuantity
FROM base b
LEFT JOIN (SELECT NumeroPedido, WCLine FROM wc_tb WHERE rn = 1) wtb ON wtb.NumeroPedido = b.NumeroPedido
LEFT JOIN ext_value ev ON ev.NumeroPedido = b.NumeroPedido AND ev.Assy = b.Assy
LEFT JOIN ext_qty eq ON eq.NumeroPedido = b.NumeroPedido AND eq.Assy = b.Assy
LEFT JOIN pit_value pv ON pv.NumeroPedido = b.NumeroPedido
LEFT JOIN pit_target_exists pte ON pte.NumeroPedido = b.NumeroPedido AND pte.Assy = b.Assy
LEFT JOIN pit_qty pq ON pq.NumeroPedido = b.NumeroPedido
LEFT JOIN tb_opt_y toy ON toy.NumeroPedido = b.NumeroPedido
LEFT JOIN tb_target_exists tte ON tte.NumeroPedido = b.NumeroPedido AND tte.Assy = b.Assy
LEFT JOIN tb_qty tq ON tq.NumeroPedido = b.NumeroPedido
LEFT JOIN (SELECT NumeroPedido, Qty FROM tb_line_qty WHERE rn = 1) tlq ON tlq.NumeroPedido = b.NumeroPedido
ORDER BY
    CASE WHEN b.PriorityOrder IS NULL THEN 1 ELSE 0 END,
    b.PriorityOrder ASC,
    b.Sequence ASC
'''

def fetch(sql):
    with app.ConexionODBCCZ(database='DataLakeSCCZ') as conn:
        cur = conn.cursor()
        t0 = time.time()
        cur.execute(sql)
        rows = cur.fetchall()
        dt = time.time() - t0
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows], cols, dt

old_rows, old_cols, old_dt = fetch(OLD)
new_rows, new_cols, new_dt = fetch(NEW)

print(f"OLD: {len(old_rows)} filas | {old_dt:.3f}s | cols={len(old_cols)}")
print(f"NEW: {len(new_rows)} filas | {new_dt:.3f}s | cols={len(new_cols)}")
print(f"Columnas OLD: {old_cols}")
print(f"Columnas NEW: {new_cols}")

# Comparar
old_keys = {str(r['SalesOrder']).strip() + '|' + str(r['Assy']).strip(): r for r in old_rows}
new_keys = {str(r['SalesOrder']).strip() + '|' + str(r['Assy']).strip(): r for r in new_rows}

print(f"\nClaves OLD: {len(old_keys)} | Claves NEW: {len(new_keys)}")
print(f"Solo en OLD: {sorted(set(old_keys) - set(new_keys))[:10]}")
print(f"Solo en NEW: {sorted(set(new_keys) - set(old_keys))[:10]}")

# Comparar columna a columna (normalizando None)
def norm(v):
    if v is None:
        return None
    if isinstance(v, float):
        return float(v)
    return v

diff_cols = {}
for k in old_keys:
    if k not in new_keys:
        continue
    o = old_keys[k]
    n = new_keys[k]
    for col in old_cols:
        if col not in n:
            continue
        ov = norm(o.get(col))
        nv = norm(n.get(col))
        if ov != nv:
            diff_cols.setdefault(col, []).append((k, ov, nv))

if not diff_cols:
    print("\n✅ SIN DIFERENCIAS entre OLD y NEW.")
else:
    print(f"\n⚠️ DIFERENCIAS por columna:")
    for col, diffs in diff_cols.items():
        print(f"  {col}: {len(diffs)} filas difieren")
        for k, ov, nv in diffs[:5]:
            print(f"    {k}: OLD={ov!r} NEW={nv!r}")

print("\nFin.")

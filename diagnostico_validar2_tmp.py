#!/usr/bin/env python3
"""Valida la nueva consulta set-based (v2, con CTEs pre-filtrados) frente a la antigua."""
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
        LTRIM(RTRIM(ps.NumeroPedido)) AS NumeroPedido,
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
lh_docs AS (
    SELECT DISTINCT LTRIM(RTRIM(sales_document)) AS doc
    FROM OB.pedidos_exportados WITH (NOLOCK)
    WHERE characteristic_name = 'GRP_HSK_TYPE'
      AND UPPER(LTRIM(RTRIM(characteristic_value))) = 'LH'
),
tsd_map AS (
    SELECT LTRIM(RTRIM(sales_document)) AS doc, LTRIM(RTRIM(characteristic_value)) AS val
    FROM OB.pedidos_exportados WITH (NOLOCK)
    WHERE characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
      AND characteristic_value IS NOT NULL
      AND LTRIM(RTRIM(characteristic_value)) <> ''
),
head_trav_map AS (
    SELECT LTRIM(RTRIM(sales_document)) AS doc, LTRIM(RTRIM(characteristic_value)) AS val
    FROM OB.pedidos_exportados WITH (NOLOCK)
    WHERE characteristic_name IN ('GRP_OMEGA_BRACKET_TYPE_HEAD', 'GRP_OMEGA_BRACKET_TYPE_TRAV')
      AND characteristic_value IS NOT NULL
      AND LTRIM(RTRIM(characteristic_value)) <> ''
),
pit_map AS (
    SELECT LTRIM(RTRIM(sales_document)) AS doc, LTRIM(RTRIM(characteristic_value)) AS val
    FROM OB.pedidos_exportados WITH (NOLOCK)
    WHERE characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_PIT'
      AND characteristic_value IS NOT NULL
      AND LTRIM(RTRIM(characteristic_value)) <> ''
),
pit_qty_map AS (
    SELECT LTRIM(RTRIM(sales_document)) AS doc, TRY_CAST(LTRIM(RTRIM(characteristic_value)) AS INT) AS qty
    FROM OB.pedidos_exportados WITH (NOLOCK)
    WHERE characteristic_name = 'GRP_OMEGA_BRACKET_QTY_PIT'
      AND characteristic_value IS NOT NULL
      AND LTRIM(RTRIM(characteristic_value)) <> ''
),
tb_opt_y_docs AS (
    SELECT DISTINCT LTRIM(RTRIM(sales_document)) AS doc
    FROM OB.pedidos_exportados WITH (NOLOCK)
    WHERE characteristic_name = 'GRP_TIE_BRACKET_OPT'
      AND UPPER(LTRIM(RTRIM(characteristic_value))) = 'Y'
),
tb_type_map AS (
    SELECT LTRIM(RTRIM(sales_document)) AS doc, LTRIM(RTRIM(characteristic_value)) AS val
    FROM OB.pedidos_exportados WITH (NOLOCK)
    WHERE characteristic_name = 'GRP_TIE_BRACKET_TYPE'
      AND characteristic_value IS NOT NULL
      AND LTRIM(RTRIM(characteristic_value)) <> ''
),
tb_qty_map AS (
    SELECT LTRIM(RTRIM(sales_document)) AS doc, TRY_CAST(LTRIM(RTRIM(characteristic_value)) AS INT) AS qty
    FROM OB.pedidos_exportados WITH (NOLOCK)
    WHERE characteristic_name = 'GRP_TIE_BRACKET_QTY'
      AND characteristic_value IS NOT NULL
      AND LTRIM(RTRIM(characteristic_value)) <> ''
),
wc_tb AS (
    SELECT pc.NumeroPedido AS doc,
           LTRIM(RTRIM(pl.Cod_Producto_Externo)) AS WCLine,
           ROW_NUMBER() OVER (PARTITION BY pc.NumeroPedido ORDER BY pl.UnidadesPedidas DESC, pl.Cod_Producto_Externo ASC) AS rn
    FROM OB.PedidosCabecera pc WITH (NOLOCK)
    INNER JOIN OB.PedidosLineas pl WITH (NOLOCK) ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
    INNER JOIN OB.Omegas o_line WITH (NOLOCK) ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
    WHERE LTRIM(RTRIM(o_line.[W/C])) = 'TB'
),
wc_ex AS (
    SELECT pc.NumeroPedido AS doc,
           LTRIM(RTRIM(pl.Cod_Producto_Externo)) AS WCLine,
           ROW_NUMBER() OVER (PARTITION BY pc.NumeroPedido ORDER BY pl.UnidadesPedidas DESC, pl.Cod_Producto_Externo ASC) AS rn
    FROM OB.PedidosCabecera pc WITH (NOLOCK)
    INNER JOIN OB.PedidosLineas pl WITH (NOLOCK) ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
    INNER JOIN OB.Omegas o_line WITH (NOLOCK) ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
    WHERE LTRIM(RTRIM(o_line.[W/C])) = 'EX'
),
has_ex_line AS (
    SELECT DISTINCT pc.NumeroPedido AS doc
    FROM OB.PedidosCabecera pc WITH (NOLOCK)
    INNER JOIN OB.PedidosLineas pl WITH (NOLOCK) ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
    INNER JOIN OB.Omegas o_line WITH (NOLOCK) ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
    WHERE LTRIM(RTRIM(o_line.[W/C])) = 'EX'
),
tb_line_qty AS (
    SELECT pc.NumeroPedido AS doc,
           pl.UnidadesPedidas AS qty,
           ROW_NUMBER() OVER (PARTITION BY pc.NumeroPedido ORDER BY pl.UnidadesPedidas DESC, pl.Cod_Producto_Externo ASC) AS rn
    FROM OB.PedidosCabecera pc WITH (NOLOCK)
    INNER JOIN OB.PedidosLineas pl WITH (NOLOCK) ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
    INNER JOIN OB.Omegas o_line WITH (NOLOCK) ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
    WHERE LTRIM(RTRIM(o_line.[W/C])) = 'TB'
),
ext_derived AS (
    SELECT DISTINCT b.NumeroPedido, b.Assy, b.Assy AS DerivedExtender
    FROM base b
    INNER JOIN lh_docs lh ON lh.doc = b.NumeroPedido
    INNER JOIN tsd_map t ON t.doc = b.NumeroPedido
    INNER JOIN OB.Omegas o_tsd WITH (NOLOCK)
        ON LTRIM(RTRIM(o_tsd.Assy)) = LTRIM(RTRIM(b.Assy))
       AND LTRIM(RTRIM(o_tsd.ExtenderVariable)) = t.val
    WHERE NOT EXISTS (SELECT 1 FROM has_ex_line hx WHERE hx.doc = b.NumeroPedido)
),
ext_target AS (
    SELECT DISTINCT b.NumeroPedido, b.Assy, 1 AS IsTargetAssy
    FROM base b
    INNER JOIN lh_docs lh ON lh.doc = b.NumeroPedido
    INNER JOIN OB.Omegas o_target WITH (NOLOCK)
        ON LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM(b.Assy))
    WHERE (
        EXISTS (SELECT 1 FROM head_trav_map ht WHERE ht.doc = b.NumeroPedido AND LTRIM(RTRIM(o_target.OmegaType)) = ht.val)
        OR EXISTS (SELECT 1 FROM tsd_map t WHERE t.doc = b.NumeroPedido AND LTRIM(RTRIM(o_target.ExtenderVariable)) = t.val)
    )
),
pit_target_exists AS (
    SELECT DISTINCT b.NumeroPedido, b.Assy
    FROM base b
    INNER JOIN pit_map pm ON pm.doc = b.NumeroPedido
    INNER JOIN OB.Omegas o_target WITH (NOLOCK)
        ON LTRIM(RTRIM(o_target.OmegaType)) = pm.val
       AND LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM(b.Assy))
),
tb_target_exists AS (
    SELECT DISTINCT b.NumeroPedido, b.Assy
    FROM base b
    INNER JOIN tb_opt_y_docs toy ON toy.doc = b.NumeroPedido
    INNER JOIN tb_type_map ttm ON ttm.doc = b.NumeroPedido
    INNER JOIN OB.Omegas o_target WITH (NOLOCK)
        ON LTRIM(RTRIM(o_target.OmegaType)) = ttm.val
       AND LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM(b.Assy))
),
ext_value AS (
    SELECT
        b.NumeroPedido,
        b.Assy,
        COALESCE(NULLIF(LTRIM(RTRIM(b.RawEX)), ''), we.WCLine, ed.DerivedExtender) AS Extender
    FROM base b
    LEFT JOIN (SELECT doc, WCLine FROM wc_ex WHERE rn = 1) we ON we.doc = b.NumeroPedido
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
    CASE WHEN pte.NumeroPedido IS NULL THEN NULL ELSE pq.qty END AS PitBracketQty,
    COALESCE(
        CASE WHEN COALESCE(NULLIF(LTRIM(RTRIM(b.RawTB)), ''), wtb.WCLine) IS NULL THEN NULL
             WHEN tte.NumeroPedido IS NULL THEN NULL
             ELSE tq.qty END,
        CASE WHEN COALESCE(NULLIF(LTRIM(RTRIM(b.RawTB)), ''), wtb.WCLine) IS NULL THEN NULL
             WHEN toy.doc IS NOT NULL THEN NULL
             WHEN eq.ExtenderQuantity IS NOT NULL THEN 1
             ELSE NULL END,
        tlq.qty
    ) AS TieBracketQty,
    COALESCE(
        CASE WHEN COALESCE(NULLIF(LTRIM(RTRIM(b.RawTB)), ''), wtb.WCLine) IS NULL THEN NULL
             WHEN tte.NumeroPedido IS NULL THEN NULL
             ELSE tq.qty END,
        CASE WHEN COALESCE(NULLIF(LTRIM(RTRIM(b.RawTB)), ''), wtb.WCLine) IS NULL THEN NULL
             WHEN toy.doc IS NOT NULL THEN NULL
             WHEN eq.ExtenderQuantity IS NOT NULL THEN 1
             ELSE NULL END
    ) AS TieExtenderQty,
    eq.ExtenderQuantity
FROM base b
LEFT JOIN (SELECT doc, WCLine FROM wc_tb WHERE rn = 1) wtb ON wtb.doc = b.NumeroPedido
LEFT JOIN ext_value ev ON ev.NumeroPedido = b.NumeroPedido AND ev.Assy = b.Assy
LEFT JOIN ext_qty eq ON eq.NumeroPedido = b.NumeroPedido AND eq.Assy = b.Assy
LEFT JOIN (SELECT doc, MIN(val) AS PitBracket FROM pit_map GROUP BY doc) pv ON pv.doc = b.NumeroPedido
LEFT JOIN pit_target_exists pte ON pte.NumeroPedido = b.NumeroPedido AND pte.Assy = b.Assy
LEFT JOIN (SELECT doc, MIN(qty) AS qty FROM pit_qty_map GROUP BY doc) pq ON pq.doc = b.NumeroPedido
LEFT JOIN tb_opt_y_docs toy ON toy.doc = b.NumeroPedido
LEFT JOIN tb_target_exists tte ON tte.NumeroPedido = b.NumeroPedido AND tte.Assy = b.Assy
LEFT JOIN (SELECT doc, MIN(qty) AS qty FROM tb_qty_map GROUP BY doc) tq ON tq.doc = b.NumeroPedido
LEFT JOIN (SELECT doc, qty FROM tb_line_qty WHERE rn = 1) tlq ON tlq.doc = b.NumeroPedido
ORDER BY
    CASE WHEN b.PriorityOrder IS NULL THEN 1 ELSE 0 END,
    b.PriorityOrder ASC,
    b.Sequence ASC
'''

def fetch(sql, label):
    with app.ConexionODBCCZ(database='DataLakeSCCZ') as conn:
        cur = conn.cursor()
        cur.timeout = 90
        t0 = time.time()
        cur.execute(sql)
        rows = cur.fetchall()
        dt = time.time() - t0
        cols = [d[0] for d in cur.description]
        print(f"{label}: {len(rows)} filas | {dt:.3f}s | cols={len(cols)}")
        return [dict(zip(cols, r)) for r in rows], cols

old_rows, old_cols = fetch(OLD, "OLD")
new_rows, new_cols = fetch(NEW, "NEW")

def norm(v):
    if v is None:
        return None
    if isinstance(v, float):
        return float(v)
    return v

old_keys = {str(r['SalesOrder']).strip() + '|' + str(r['Assy']).strip(): r for r in old_rows}
new_keys = {str(r['SalesOrder']).strip() + '|' + str(r['Assy']).strip(): r for r in new_rows}
print(f"\nClaves OLD: {len(old_keys)} | Claves NEW: {len(new_keys)}")
print(f"Solo en OLD: {sorted(set(old_keys) - set(new_keys))[:10]}")
print(f"Solo en NEW: {sorted(set(new_keys) - set(old_keys))[:10]}")

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
        for k, ov, nv in diffs[:8]:
            print(f"    {k}: OLD={ov!r} NEW={nv!r}")

print("\nFin.")

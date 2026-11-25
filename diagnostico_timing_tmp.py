#!/usr/bin/env python3
"""Mide dónde se va el tiempo en la consulta C actual."""
import sys, time
sys.path.insert(0, r"c:\Proyectos\Desarrollo_Omegas - copia\api")

import appOMEGAS as app

# Reconstruir la consulta C actual (idéntica al endpoint)
done_qty_sql = "ISNULL(ps.UniValMapex,0) + ISNULL(ps.AssignedStock,0)"

cwi = app.build_pedidos_cabecera_optional_select_sql('CWI')

base_sql = f'''
    SELECT
        ps.Sequence AS Sequence,
        ps.NumeroPedido AS SalesOrder,
        ps.UnidadesPedidas AS Qty,
        {done_qty_sql} AS DoneQty,
        ps.Assy,
        ps.Beam,
        o.IF1,
        o.IF2,
        ISNULL(pc.CWT, '') AS CWT,
        ISNULL(pc.DS, '') AS MS,
        pc.FechaEntrega AS DeliveryDate,
        {cwi},
        ps.OFs AS WO,
        ps.EX AS RawEX,
        ps.TB AS RawTB,
        ps.PriorityOrder
    FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
    LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON pc.NumeroPedido = ps.NumeroPedido
    LEFT JOIN OB.Omegas o ON ps.Assy = o.Assy
    WHERE UPPER(LTRIM(RTRIM(ps.Assembly))) = 'YES C'
'''

full_sql = '''
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

with app.ConexionODBCCZ(database='DataLakeSCCZ') as conn:
    cur = conn.cursor()

    for nombre, sql in (('BASE', base_sql), ('FULL', full_sql)):
        t0 = time.time()
        cur.execute(sql)
        rows = cur.fetchall()
        dt = time.time() - t0
        cols = [d[0] for d in cur.description]
        print(f"{nombre}: {len(rows)} filas | {len(cols)} columnas | {dt:.3f}s")
        if nombre == 'FULL':
            for r in rows[:3]:
                d = dict(zip(cols, r))
                print("   ", {k: d.get(k) for k in ('SalesOrder','Assy','Extender','ExtenderQuantity','TieBracket','TieBracketQty','TieExtenderQty','PitBracket','PitBracketQty','DeliveryDate')})

print("Fin.")

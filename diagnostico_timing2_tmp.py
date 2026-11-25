#!/usr/bin/env python3
"""Mide incrementalmente cada OUTER APPLY / subconsulta escalar de la consulta C."""
import sys, time
sys.path.insert(0, r"c:\Proyectos\Desarrollo_Omegas - copia\api")
import appOMEGAS as app

done_qty_sql = "ISNULL(ps.UniValMapex,0) + ISNULL(ps.AssignedStock,0)"
cwi = app.build_pedidos_cabecera_optional_select_sql('CWI')

def base_select():
    return f'''
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
    '''

def run(name, sql):
    with app.ConexionODBCCZ(database='DataLakeSCCZ') as conn:
        cur = conn.cursor()
        t0 = time.time()
        cur.execute(sql)
        rows = cur.fetchall()
        dt = time.time() - t0
        print(f"{name}: {len(rows)} filas | {dt:.3f}s")

# 1) Base
run("BASE", f"SELECT {base_select()} FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK) LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON pc.NumeroPedido=ps.NumeroPedido LEFT JOIN OB.Omegas o ON ps.Assy=o.Assy WHERE UPPER(LTRIM(RTRIM(ps.Assembly)))='YES C'")

# 2) + tbext apply
run("BASE+tbext", f"""
    SELECT {base_select()}, tbext.WCLine
    FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
    LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON pc.NumeroPedido=ps.NumeroPedido
    LEFT JOIN OB.Omegas o ON ps.Assy=o.Assy
    {app.build_wc_line_apply_sql('ps','tbext','TB')}
    WHERE UPPER(LTRIM(RTRIM(ps.Assembly)))='YES C'
""")

# 3) + extline
run("BASE+tbext+extline", f"""
    SELECT {base_select()}, tbext.WCLine, extline.WCLine
    FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
    LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON pc.NumeroPedido=ps.NumeroPedido
    LEFT JOIN OB.Omegas o ON ps.Assy=o.Assy
    {app.build_wc_line_apply_sql('ps','tbext','TB')}
    {app.build_extender_line_apply_sql('ps')}
    WHERE UPPER(LTRIM(RTRIM(ps.Assembly)))='YES C'
""")

# 4) + extderived
run("BASE+tbext+extline+extderived", f"""
    SELECT {base_select()}, tbext.WCLine, extline.WCLine, extderived.DerivedExtender
    FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
    LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON pc.NumeroPedido=ps.NumeroPedido
    LEFT JOIN OB.Omegas o ON ps.Assy=o.Assy
    {app.build_wc_line_apply_sql('ps','tbext','TB')}
    {app.build_extender_line_apply_sql('ps')}
    {app.build_extender_derived_apply_sql('ps')}
    WHERE UPPER(LTRIM(RTRIM(ps.Assembly)))='YES C'
""")

# 5) + exttarget
run("BASE+todas applies", f"""
    SELECT {base_select()}, tbext.WCLine, extline.WCLine, extderived.DerivedExtender, exttarget.IsTargetAssy
    FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
    LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON pc.NumeroPedido=ps.NumeroPedido
    LEFT JOIN OB.Omegas o ON ps.Assy=o.Assy
    {app.build_wc_line_apply_sql('ps','tbext','TB')}
    {app.build_extender_line_apply_sql('ps')}
    {app.build_extender_derived_apply_sql('ps')}
    {app.build_extender_target_apply_sql('ps')}
    WHERE UPPER(LTRIM(RTRIM(ps.Assembly)))='YES C'
""")

# 6) Solo subconsultas escalares (sin applies)
run("BASE+scalares", f"""
    SELECT
        {base_select()},
        {app.build_pit_bracket_value_sql('ps')} AS PitBracket,
        {app.build_pit_bracket_quantity_value_sql('ps')} AS PitBracketQty
    FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
    LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON pc.NumeroPedido=ps.NumeroPedido
    LEFT JOIN OB.Omegas o ON ps.Assy=o.Assy
    WHERE UPPER(LTRIM(RTRIM(ps.Assembly)))='YES C'
""")

# 7) Solo TB scalar
run("BASE+tbscalar", f"""
    SELECT
        {base_select()},
        {app.build_tb_cards_quantity_case_sql('ps', False, 'TieBracketQty')},
        {app.build_tb_cards_quantity_case_sql('ps', True, 'TieExtenderQty')}
    FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
    LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON pc.NumeroPedido=ps.NumeroPedido
    LEFT JOIN OB.Omegas o ON ps.Assy=o.Assy
    WHERE UPPER(LTRIM(RTRIM(ps.Assembly)))='YES C'
""")

print("Fin.")

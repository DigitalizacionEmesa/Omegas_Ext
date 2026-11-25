#!/usr/bin/env python3
"""Distribución Assembly/Picking de las 228 filas secuenciadas (27-30/08) + qué columnas usa el resumen pendientes."""
import functools, builtins, json, pyodbc

print = functools.partial(builtins.print, flush=True)
DB_USERCZ = 'sccz'
DB_PASSWORDCZ = 'S@vera,CZ,2024'
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


main, srv_m, drv_m = conectar('DataLakeSCCZ')
cm = main.cursor()
print(f"✅ DataLakeSCCZ ({srv_m})\n")

print("=" * 90)
print("1) Distribución Assembly / Picking de las 228 filas secuenciadas (27-30/08)")
print("=" * 90)
cm.execute(f"""
    SELECT ISNULL(LTRIM(RTRIM(v.Assembly)), '(null)') AS Assembly,
           ISNULL(LTRIM(RTRIM(v.Picking)), '(null)') AS Picking,
           COUNT(*) AS N
    FROM OB.PedidosSecuenciados ps
    INNER JOIN OB.V_PedidosSummary_Secuenciados_Full v
        ON LTRIM(RTRIM(v.NumeroPedido)) = LTRIM(RTRIM(ps.NumeroPedido))
       AND LTRIM(RTRIM(v.Assy)) = LTRIM(RTRIM(ps.Assy))
    WHERE ps.FechaSecuenciacion >= ? AND ps.FechaSecuenciacion < ?
    GROUP BY LTRIM(RTRIM(v.Assembly)), LTRIM(RTRIM(v.Picking))
    ORDER BY N DESC
""", (DESDE, HASTA))
for r in cm.fetchall():
    print(f"  Assembly='{r.Assembly}' | Picking='{r.Picking}' -> {r.N} filas")

print("\n" + "=" * 90)
print("2) V_PedidosSummary_Pendientes_EX: columnas (para saber qué muestra el Summary)")
print("=" * 90)
cm.execute("SELECT TOP 1 * FROM OB.V_PedidosSummary_Pendientes_EX")
cols = [d[0] for d in cm.description]
print("  Columnas:", ", ".join(cols))

print("\n" + "=" * 90)
print("3) Fila de pendientes para 42633 (ejemplo) - campos que vería la pantalla Summary")
print("=" * 90)
cm.execute("""
    SELECT * FROM OB.V_PedidosSummary_Pendientes_EX
    WHERE LTRIM(RTRIM(NumeroPedido)) = '42633'
""")
row = cm.fetchone()
if row:
    for col, val in zip(cols, row):
        print(f"    {col} = {val}")
else:
    print("  (no fila)")

main.close()
print("\nFin.")

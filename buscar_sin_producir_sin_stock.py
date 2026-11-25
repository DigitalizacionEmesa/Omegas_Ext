"""Busca una SO sin producir y sin stock, para ver que sí aparece en el secuenciador."""
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
        except Exception:
            pass
    if conn:
        break

if not conn:
    print("NO CONEXION")
    exit(1)

c = conn.cursor()

print("=== Órdenes SIN producir (UniValMapex=0) y SIN stock (AssignedStock=0) que SÍ aparecen ===")
c.execute("""
    SELECT TOP 10
        Sequence, NumeroPedido, Assy, [C/W], UnidadesPedidas AS Pedidas,
        UniValMapex AS Producidas, AssignedStock AS StockAsig, Assembly, Picking
    FROM OB.V_PedidosSummary_Secuenciados WITH (NOLOCK)
    WHERE UniValMapex = 0
      AND AssignedStock = 0
      AND UPPER(LTRIM(RTRIM(Assembly))) IN ('YES C', 'YES W')
    ORDER BY Sequence ASC
""")
rows = c.fetchall()
if rows:
    for r in rows:
        print(f"  Seq={r[0]} | Pedido={r[1]} | Assy={r[2]} | W/C={r[3]} | Pedidas={r[4]} | Producidas={r[5]} | Stock={r[6]} | Assembly={r[7]} | Picking={r[8]}")
else:
    print("  (no hay ninguna)")

print("\n=== Comparativa: la 40951 vs una que SÍ aparece ===")
c.execute("""
    SELECT Sequence, NumeroPedido, Assy, [C/W], UnidadesPedidas AS Pedidas,
           UniValMapex AS Producidas, AssignedStock AS StockAsig, Assembly, Picking
    FROM OB.V_PedidosSummary_Secuenciados WITH (NOLOCK)
    WHERE NumeroPedido = '40951'
       OR (UniValMapex = 0 AND AssignedStock = 0
           AND UPPER(LTRIM(RTRIM(Assembly))) IN ('YES C','YES W'))
    ORDER BY NumeroPedido
""")
for r in c.fetchall():
    print(f"  Pedido={r[1]} | Assy={r[2]} | W/C={r[3]} | Pedidas={r[4]} | Producidas={r[5]} | Stock={r[6]} | Assembly={r[7]} | Picking={r[8]}")

conn.close()
print("\nFin.")

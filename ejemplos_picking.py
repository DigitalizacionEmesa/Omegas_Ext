"""Muestra ejemplos reales de Assembly/Picking con sus números para entender la lógica."""
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

print("=== ORDEN 40951 (la del problema) ===")
c.execute("""
    SELECT NumeroPedido, Assy, [C/W], UnidadesPedidas, UniValMapex, AssignedStock, Assembly, Picking
    FROM OB.V_PedidosSummary_Secuenciados
    WHERE NumeroPedido = '40951'
""")
for r in c.fetchall():
    print(f"  Pedido={r[0]} | Assy={r[1]} | W/C={r[2]} | Pedidas={r[3]} | Producidas={r[4]} | StockAsig={r[5]} | Assembly={r[6]} | Picking={r[7]}")

print("\n=== EJEMPLOS de órdenes con Picking = Yes (primeras 8) ===")
c.execute("""
    SELECT TOP 8 NumeroPedido, Assy, [C/W], UnidadesPedidas, UniValMapex, AssignedStock, Assembly, Picking
    FROM OB.V_PedidosSummary_Secuenciados WITH (NOLOCK)
    WHERE UPPER(LTRIM(RTRIM(Picking))) = 'YES'
    ORDER BY Sequence ASC
""")
for r in c.fetchall():
    print(f"  Pedido={r[0]} | Assy={r[1]} | W/C={r[2]} | Pedidas={r[3]} | Producidas={r[4]} | StockAsig={r[5]} | Assembly={r[6]} | Picking={r[7]}")

print("\n=== EJEMPLOS de órdenes en Assembly (Yes C/W) - primeras 8 ===")
c.execute("""
    SELECT TOP 8 NumeroPedido, Assy, [C/W], UnidadesPedidas, UniValMapex, AssignedStock, Assembly, Picking
    FROM OB.V_PedidosSummary_Secuenciados WITH (NOLOCK)
    WHERE UPPER(LTRIM(RTRIM(Assembly))) IN ('YES C', 'YES W')
    ORDER BY Sequence ASC
""")
for r in c.fetchall():
    print(f"  Pedido={r[0]} | Assy={r[1]} | W/C={r[2]} | Pedidas={r[3]} | Producidas={r[4]} | StockAsig={r[5]} | Assembly={r[6]} | Picking={r[7]}")

conn.close()
print("\nFin.")

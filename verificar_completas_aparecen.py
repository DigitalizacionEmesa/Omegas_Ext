"""Verifica si una línea 'completada' (Pedidas=Producidas) puede aparecer, y muestra el caso de órdenes multi-línea."""
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

print("=== 1) ¿Existe alguna línea con Pedidas=Producidas que SÍ aparezca? ===")
c.execute("""
    SELECT COUNT(*)
    FROM OB.V_PedidosSummary_Secuenciados WITH (NOLOCK)
    WHERE UnidadesPedidas = UniValMapex
      AND (
            UPPER(LTRIM(RTRIM(Assembly))) IN ('YES C','YES W')
         OR UPPER(LTRIM(RTRIM(Picking))) = 'YES'
      )
""")
n = c.fetchone()[0]
print(f"  Resultado: {n} (si es 0, es IMPOSIBLE que una línea 100% producida aparezca)")

print("\n=== 2) Ejemplo de orden con VARIAS líneas: una completada y otra no ===")
c.execute("""
    SELECT TOP 12 NumeroPedido, Assy, [C/W], UnidadesPedidas AS Pedidas, UniValMapex AS Producidas, Assembly, Picking
    FROM OB.V_PedidosSummary_Secuenciados WITH (NOLOCK)
    WHERE NumeroPedido IN (
        -- órdenes que tienen AL MENOS una línea completada y AL MENOS una línea no completada
        SELECT NumeroPedido
        FROM OB.V_PedidosSummary_Secuenciados WITH (NOLOCK)
        GROUP BY NumeroPedido
        HAVING SUM(CASE WHEN UnidadesPedidas = UniValMapex THEN 1 ELSE 0 END) > 0
           AND SUM(CASE WHEN UnidadesPedidas <> UniValMapex THEN 1 ELSE 0 END) > 0
    )
    ORDER BY NumeroPedido
""")
for r in c.fetchall():
    print(f"  Pedido={r[0]} | Assy={r[1]} | W/C={r[2]} | Pedidas={r[3]} | Producidas={r[4]} | Assembly={r[5]} | Picking={r[6]}")

conn.close()
print("\nFin.")

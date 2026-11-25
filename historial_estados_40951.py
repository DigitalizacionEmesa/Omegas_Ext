"""Historial de cambios de estado del pedido 40951 en MAPEX."""
import pyodbc

servers = ["172.16.10.10", "EMEBIDWH"]
drivers = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"]
user, pwd = "sccz", "S@vera,CZ,2024"

conn = None
for d in drivers:
    for s in servers:
        try:
            cs = f"DRIVER={{{d}}};SERVER={s};DATABASE=mapexbp;UID={user};PWD={pwd};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10"
            conn = pyodbc.connect(cs, timeout=10, autocommit=True)
            break
        except Exception:
            pass
    if conn:
        break

if not conn:
    print("NO CONEXION")
    exit(1)

cc = conn.cursor()

print("=== Columnas de his_wam_estadoPedido ===")
try:
    cc.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'his_wam_estadoPedido'
        ORDER BY ORDINAL_POSITION
    """)
    print("  " + ", ".join(r[0] for r in cc.fetchall()))
except Exception as e:
    print(f"  Error: {e}")

print("\n=== Historial de estados del pedido 40951 ===")
try:
    cc.execute("""
        SELECT * FROM his_wam_estadoPedido
        WHERE id_his_wam_pedido_cliente = 33512
        ORDER BY 1
    """)
    cols = [d[0] for d in cc.description]
    print("  Columnas: " + ", ".join(cols))
    for r in cc.fetchall():
        print("  " + " | ".join(str(x) for x in r))
except Exception as e:
    print(f"  Error: {str(e)[:200]}")

print("\n=== Catálogo completo de estados de pedido ===")
try:
    cc.execute("SELECT * FROM cfg_wam_estadoPedido")
    cols = [d[0] for d in cc.description]
    print("  Columnas: " + ", ".join(cols))
    for r in cc.fetchall():
        print("  " + " | ".join(str(x) for x in r))
except Exception as e:
    print(f"  Error: {str(e)[:200]}")

conn.close()
print("\nFin.")

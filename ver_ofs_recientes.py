"""Mira las OFs más recientes de cada producto para entender UniValMapex."""
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

# OFs más recientes de cada producto
for cod in ['S0PFA6225946', 'S0PFA6225949', 'S0PF56225933']:
    print(f"\n=== OFs más recientes de {cod} ===")
    cc.execute("""
        SELECT TOP 6 Cod_of, Desc_estadoof, Fecha_ini, Fecha_fin
        FROM dbo.V_OFs
        WHERE Cod_producto = ?
        ORDER BY Fecha_ini DESC
    """, (cod,))
    for r in cc.fetchall():
        print(f"  OF={r[0]} | Estado={r[1]} | Ini={r[2]} | Fin={r[3]}")

# Columnas disponibles en V_OFs
print("\n=== Columnas de dbo.V_OFs ===")
cc.execute("""
    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'V_OFs'
    ORDER BY ORDINAL_POSITION
""")
print("  " + ", ".join(r[0] for r in cc.fetchall()))

conn.close()
print("\nFin.")

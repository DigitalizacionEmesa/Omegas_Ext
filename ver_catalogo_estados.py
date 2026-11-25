"""Consulta los catálogos de estados de MAPEX (cabecera y línea)."""
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

for tabla in ['cfg_wam_estado_linea_pedido_cliente', 'cfg_wam_estado_pedido_cliente']:
    print(f"=== {tabla} ===")
    try:
        cc.execute(f"SELECT * FROM {tabla}")
        cols = [d[0] for d in cc.description]
        print("  Columnas: " + ", ".join(cols))
        for r in cc.fetchall():
            print("  " + " | ".join(str(x) for x in r))
    except Exception as e:
        print(f"  Error: {str(e)[:150]}")
    print()

conn.close()
print("Fin.")

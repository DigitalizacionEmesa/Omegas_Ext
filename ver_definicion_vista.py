"""Obtiene la definición de la vista OB.V_PedidosSummary_Secuenciados_Full."""
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
        except Exception as e:
            pass
    if conn:
        break

if not conn:
    print("NO CONEXION")
    exit(1)

c = conn.cursor()

# Definición de la vista
try:
    c.execute("""
        SELECT definition
        FROM sys.sql_modules m
        JOIN sys.objects o ON o.object_id = m.object_id
        WHERE o.name = 'V_PedidosSummary_Secuenciados_Full'
    """)
    row = c.fetchone()
    if row:
        print(row[0])
    else:
        print("No se encontró la definición por sys.sql_modules")
except Exception as e:
    print(f"Error sys.sql_modules: {e}")

conn.close()


import pyodbc

# Parámetros de conexión igual que appOMEGAS.py
DRIVER = 'ODBC Driver 18 for SQL Server'
SERVER = '172.16.10.10'  # O 'EMEBIDWH' si aplica
DATABASE = 'DataLakeSCCZ'
UID = 'Usrconsulta'
PWD = 'Clave2025*'

conn_str = f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE={DATABASE};UID={UID};PWD={PWD}"

print(f"Conectando con: {conn_str}")

try:
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    print("Conexión exitosa. Consultando la vista...")
    cursor.execute('SELECT COUNT(*) FROM [OB].[V_PedidosSummary_Secuenciados]')
    total = cursor.fetchone()[0]
    print(f"Total registros en la vista: {total}")

    # Muestra algunos registros
    cursor.execute('SELECT TOP 10 * FROM [OB].[V_PedidosSummary_Secuenciados]')
    columns = [column[0] for column in cursor.description]
    print("Columnas:", columns)
    rows = cursor.fetchall()
    for row in rows:
        print(dict(zip(columns, row)))
except Exception as e:
    print(f"Error: {e}")
finally:
    if 'conn' in locals():
        conn.close()

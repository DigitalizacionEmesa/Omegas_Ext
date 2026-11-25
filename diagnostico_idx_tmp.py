#!/usr/bin/env python3
"""Revisar índices de OB.pedidos_exportados y tamaño de tabla."""
import sys
import pyodbc

servers = ["172.16.10.10", "EMEBIDWH"]
drivers = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"]
user, pwd = "sccz", "S@vera,CZ,2024"
conn = None
for d in drivers:
    for s in servers:
        try:
            cs = (f"DRIVER={{{d}}};SERVER={s};DATABASE=DataLakeSCCZ;UID={user};PWD={pwd};"
                  f"Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=10")
            conn = pyodbc.connect(cs, timeout=10, autocommit=True)
            break
        except Exception:
            pass
    if conn:
        break
if not conn:
    sys.exit(1)
c = conn.cursor()

print("=== 1) Tamaño de OB.pedidos_exportados ===")
c.execute("SELECT COUNT(*) FROM OB.pedidos_exportados WITH (NOLOCK)")
print(f"  Filas: {c.fetchone()[0]}")

print("\n=== 2) Índices de OB.pedidos_exportados ===")
c.execute("""
    SELECT i.name AS indice, i.type_desc, 
           STRING_AGG(c.name, ', ') WITHIN GROUP (ORDER BY ic.key_ordinal) AS columnas
    FROM sys.indexes i
    JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
    JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
    WHERE i.object_id = OBJECT_ID('OB.pedidos_exportados')
    GROUP BY i.name, i.type_desc
    ORDER BY i.name
""")
for r in c.fetchall():
    print(f"  {r[0]} | {r[1]} | {r[2]}")

print("\n=== 3) Índices de OB.PedidosLineas y OB.PedidosCabecera (los otros joins) ===")
for tbl in ('OB.PedidosLineas', 'OB.PedidosCabecera'):
    c.execute(f"""
        SELECT i.name AS indice, i.type_desc,
               STRING_AGG(c.name, ', ') WITHIN GROUP (ORDER BY ic.key_ordinal) AS columnas
        FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        WHERE i.object_id = OBJECT_ID('{tbl}')
        GROUP BY i.name, i.type_desc
        ORDER BY i.name
    """)
    print(f"\n  -- {tbl} --")
    for r in c.fetchall():
        print(f"    {r[0]} | {r[1]} | {r[2]}")

conn.close()
print("\nFin.")

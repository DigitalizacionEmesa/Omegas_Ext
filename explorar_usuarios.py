# -*- coding: utf-8 -*-
"""
Script para explorar esquemas y tablas de usuarios
"""
import pyodbc

DB_USERCZ = 'sccz'
DB_PASSWORDCZ = 'S@vera,CZ,2024'

try:
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER=172.16.10.10;"
        f"DATABASE=DataLakeSCCZ;"
        f"UID={DB_USERCZ};PWD={DB_PASSWORDCZ};"
        "TrustServerCertificate=yes;"
    )
    
    conn = pyodbc.connect(conn_str, timeout=5)
    cursor = conn.cursor()
    
    print("=" * 60)
    print("BÚSQUEDA DE TABLAS DE USUARIOS")
    print("=" * 60)
    
    # Buscar esquemas
    print("\n1. Esquemas disponibles:")
    cursor.execute("""
        SELECT DISTINCT TABLE_SCHEMA 
        FROM INFORMATION_SCHEMA.TABLES
        ORDER BY TABLE_SCHEMA
    """)
    for row in cursor.fetchall():
        print(f"   - {row[0]}")
    
    # Buscar tablas que contengan 'Usuario' en el nombre
    print("\n2. Tablas que contienen 'Usuario' en el nombre:")
    cursor.execute("""
        SELECT TABLE_SCHEMA, TABLE_NAME 
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_NAME LIKE '%Usuario%'
        ORDER BY TABLE_SCHEMA, TABLE_NAME
    """)
    
    found_tables = []
    for row in cursor.fetchall():
        print(f"   - {row[0]}.{row[1]}")
        found_tables.append((row[0], row[1]))
    
    if not found_tables:
        print("   (No se encontraron tablas con 'Usuario' en el nombre)")
    
    # Si encontramos tablas, mostrar estructura de la primera
    if found_tables:
        schema, table = found_tables[0]
        print(f"\n3. Estructura de {schema}.{table}:")
        cursor.execute(f"""
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
        """, (schema, table))
        
        print(f"\n   Columnas:")
        for row in cursor.fetchall():
            nullable = "NULL" if row[3] == "YES" else "NOT NULL"
            length = f"({row[2]})" if row[2] else ""
            print(f"   - {row[0]:30} {row[1]}{length:15} {nullable}")
        
        # Contar registros
        cursor.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
        count = cursor.fetchone()[0]
        print(f"\n   Total de registros: {count}")
    
    print("\n" + "=" * 60)
    
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")

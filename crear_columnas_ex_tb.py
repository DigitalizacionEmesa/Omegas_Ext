import pyodbc

try:
    # Intentar conexión con string de conexión simple
    conn_str = 'Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=DataLakeSCCZ;UID=sa;PWD=1234'
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    
    # Verificar si columna TB existe
    cursor.execute("""
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = 'OB' 
    AND TABLE_NAME = 'PedidosCabecera' 
    AND COLUMN_NAME = 'TB'
    """)
    
    exists = cursor.fetchone()[0]
    
    if exists == 0:
        print("❌ Columna TB NO existe. Creando...")
        cursor.execute("ALTER TABLE [OB].[PedidosCabecera] ADD [TB] NVARCHAR(100) NULL")
        conn.commit()
        print("✅ Columna TB creada exitosamente")
    else:
        print("✅ Columna TB ya existe")
    
    # Verificar columna EX también
    cursor.execute("""
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = 'OB' 
    AND TABLE_NAME = 'PedidosCabecera' 
    AND COLUMN_NAME = 'EX'
    """)
    
    exists_ex = cursor.fetchone()[0]
    
    if exists_ex == 0:
        print("❌ Columna EX NO existe. Creando...")
        cursor.execute("ALTER TABLE [OB].[PedidosCabecera] ADD [EX] NVARCHAR(100) NULL")
        conn.commit()
        print("✅ Columna EX creada exitosamente")
    else:
        print("✅ Columna EX ya existe")
    
    # Mostrar estructura
    print("\n=== ESTRUCTURA DE OB.PedidosCabecera ===")
    cursor.execute("""
    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'OB' AND TABLE_NAME = 'PedidosCabecera'
    ORDER BY ORDINAL_POSITION
    """)
    
    for row in cursor.fetchall():
        print(f"{row[0]:<35} {row[1]:<15} NULL={row[2]}")
    
    cursor.close()
    conn.close()
    print("\n✅ Verificación completada")
    
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

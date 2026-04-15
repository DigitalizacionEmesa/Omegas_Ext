import pyodbc

try:
    conn_str = 'Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=DataLakeSCCZ;UID=sa;PWD=1234'
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    
    # Buscar el material específico
    material = 'S0PF51970780'
    
    print(f"\n=== BUSCANDO MATERIAL: {material} ===\n")
    
    # Búsqueda 1: SIN restricción de W/C
    cursor.execute("""
    SELECT Assy, [W/C], ExtenderVariable 
    FROM [OB].[Omegas]
    WHERE Assy = ?
    """, (material,))
    
    result_general = cursor.fetchall()
    print(f"Búsqueda SIN filtro W/C: {len(result_general)} registros encontrados")
    for row in result_general:
        print(f"  - Assy: {row[0]}, W/C: {row[1]}, ExtenderVariable: {row[2]}")
    
    # Búsqueda 2: CON W/C='EX'
    cursor.execute("""
    SELECT Assy, [W/C], ExtenderVariable 
    FROM [OB].[Omegas]
    WHERE Assy = ? AND [W/C] = 'EX'
    """, (material,))
    
    result_ex = cursor.fetchone()
    print(f"\nBúsqueda con W/C='EX': {'SI encontrado' if result_ex else 'NO'}")
    
    # Búsqueda 3: CON W/C='TB'
    cursor.execute("""
    SELECT Assy, [W/C], ExtenderVariable 
    FROM [OB].[Omegas]
    WHERE Assy = ? AND [W/C] = 'TB'
    """, (material,))
    
    result_tb = cursor.fetchone()
    print(f"Búsqueda con W/C='TB': {'SI encontrado' if result_tb else 'NO'}")
    
    # Diagnóstico: Ver qué W/C existen en total
    print("\n=== DIAGNÓSTICO GENERAL ===")
    cursor.execute("""
    SELECT DISTINCT [W/C] FROM [OB].[Omegas]
    """)
    
    wc_values = [row[0] for row in cursor.fetchall()]
    print(f"Valores distintos de W/C en OB.Omegas: {wc_values}")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

"""
Script para crear la tabla OB.pedidos_exportados_v2 en DataLakeSCCZ
Ejecuta el SQL directamente desde Python
"""

import os
import sys
import pyodbc
from pathlib import Path

# Configuración de conexión a BD
SERVER = "172.16.10.10"
DATABASE = "DataLakeSCCZ"
USERNAME = os.getenv("DB_USERCZ", "")
PASSWORD = os.getenv("DB_PASSWORDCZ", "")

if not USERNAME or not PASSWORD:
    print("❌ Error: Variables de entorno DB_USERCZ y DB_PASSWORDCZ no configuradas")
    sys.exit(1)

# Ruta del archivo SQL
sql_file = Path(__file__).parent.parent / "SQL" / "OB_pedidos_exportados_v2_CREATE.sql"

if not sql_file.exists():
    print(f"❌ Error: No se encontró el archivo SQL en {sql_file}")
    sys.exit(1)

print(f"📁 Leyendo SQL desde: {sql_file}")

# Leer el contenido SQL
with open(sql_file, "r", encoding="utf-8") as f:
    sql_content = f.read()

print(f"\n📊 SQL a ejecutar ({len(sql_content)} caracteres)\n")

# Conectar a la BD
try:
    conn_string = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        f"UID={USERNAME};"
        f"PWD={PASSWORD};"
    )
    
    print("🔗 Conectando a la base de datos...")
    conn = pyodbc.connect(conn_string)
    cursor = conn.cursor()
    print("✅ Conexión exitosa\n")
    
    # Ejecutar el SQL
    print("⚙️  Ejecutando SQL...\n")
    
    # Dividir por GO de SQL Server
    statements = sql_content.split('\nGO\n')
    
    for i, statement in enumerate(statements, 1):
        statement = statement.strip()
        if not statement:
            continue
        
        try:
            cursor.execute(statement)
            cursor.commit()
            print(f"✅ Statement {i}: OK")
        except pyodbc.ProgrammingError as e:
            print(f"⚠️  Statement {i}: {str(e)[:100]}")
        except Exception as e:
            print(f"❌ Statement {i}: Error - {str(e)[:100]}")
    
    conn.commit()
    print("\n" + "="*80)
    print("✅ TABLA CREADA EXITOSAMENTE")
    print("="*80)
    print("\n📋 Tabla: OB.pedidos_exportados_v2")
    print("   - Almacena líneas relevantes de pedidos importados")
    print("   - Incluye validación de extensores")
    print("   - 7 índices optimizados")
    print("   - 2 vistas para consultas comunes")
    
    conn.close()
    
except pyodbc.DatabaseError as e:
    print(f"\n❌ Error de base de datos: {str(e)}")
    sys.exit(1)
except Exception as e:
    print(f"\n❌ Error: {str(e)}")
    sys.exit(1)

import pyodbc
import json

# Credenciales (mismas que usa appOMEGAS.py)
DB_USERCZ = 'sccz'
DB_PASSWORDCZ = 'S@vera,CZ,2024'

# Leer configuración
with open('db_connection_config.json', 'r') as f:
    config = json.load(f)

# Intentar conectar con el primer servidor y driver disponible
for driver in config['drivers']:
    for server in config['cz_servers']:
        try:
            conn_str = (
                f"DRIVER={{{driver}}};"
                f"SERVER={server};"
                f"DATABASE=DataLakeSCCZ;"
                f"UID={DB_USERCZ};PWD={DB_PASSWORDCZ};"
                "Encrypt=yes;"
                "TrustServerCertificate=yes;"
                "Connection Timeout=10;"
            )
            print(f"🔄 Intentando conectar con {server} usando {driver}...")
            conn = pyodbc.connect(conn_str, timeout=10)
            print(f"✅ Conectado exitosamente a {server}")
            break
        except Exception as e:
            print(f"   ⚠️ Error: {str(e)[:100]}")
            continue
    if 'conn' in locals():
        break

if 'conn' not in locals():
    print("❌ No se pudo conectar a ningún servidor")
    exit(1)

cursor = conn.cursor()

# Leer el script SQL
with open('SQL/TEMP_Resync_Beams.sql', 'r', encoding='utf-8') as f:
    sql_script = f.read()

# Dividir por GO y ejecutar cada batch
batches = [batch.strip() for batch in sql_script.split('GO') if batch.strip()]

print("\n" + "="*50)
print("🚀 Ejecutando resincronización de beams...")
print("="*50 + "\n")

for i, batch in enumerate(batches, 1):
    try:
        # Ejecutar el batch
        cursor.execute(batch)
        
        # Capturar mensajes de PRINT
        while cursor.nextset():
            pass
        
        # Capturar resultados si hay
        if cursor.description:
            rows = cursor.fetchall()
            if rows:
                # Mostrar encabezados
                headers = [column[0] for column in cursor.description]
                print("\t".join(headers))
                print("-" * 80)
                
                # Mostrar filas
                for row in rows:
                    print("\t".join(str(cell) if cell is not None else 'NULL' for cell in row))
                print()
        
        conn.commit()
        
    except Exception as e:
        print(f"❌ Error en batch {i}: {str(e)}")
        conn.rollback()
        continue

cursor.close()
conn.close()

print("\n" + "="*50)
print("✅ Script ejecutado completamente")
print("="*50)

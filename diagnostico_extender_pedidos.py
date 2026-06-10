#!/usr/bin/env python3
"""
Diagnóstico: ¿Por qué los pedidos 36540, 36559, 36560 no tienen ExtenderQuantity?
"""

import pyodbc
import os

def conectar_bd():
    """Conectar a la base de datos OB"""
    server = 'EMEBIDWH'
    database = 'OB'
    user = os.getenv('OMEGAS_DB_USER', 'Usrconsulta')
    password = os.getenv('OMEGAS_DB_PASSWORD', 'Cz@Usrconsulta_2023')
    driver = 'ODBC Driver 17 for SQL Server'
    
    try:
        conn_str = f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};UID={user};PWD={password};Encrypt=yes;TrustServerCertificate=yes;"
        return pyodbc.connect(conn_str, timeout=10)
    except:
        # Intentar con otro driver
        conn_str = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={server};DATABASE={database};UID={user};PWD={password};Encrypt=yes;TrustServerCertificate=yes;"
        return pyodbc.connect(conn_str, timeout=10)

def diagnosticar_pedidos(pedidos_ids):
    """Diagnosticar por qué estos pedidos no tienen ExtenderQuantity"""
    
    conn = conectar_bd()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("DIAGNÓSTICO: ExtenderQuantity en Pedidos")
    print("="*80 + "\n")
    
    for pedido_id in pedidos_ids:
        print(f"\n{'='*80}")
        print(f"PEDIDO: {pedido_id}")
        print(f"{'='*80}\n")
        
        # Paso 1: Ver qué hay en la vista
        print(f"[PASO 1] Datos en V_PedidosSummary_Secuenciados_Full:")
        query = f"""
        SELECT 
            ps.Sequence,
            ps.NumeroPedido,
            ps.UnidadesPedidas AS Qty,
            ps.Assy,
            ps.EX,
            ps.Assembly,
            ps.TB
        FROM OB.V_PedidosSummary_Secuenciados_Full ps
        WHERE ps.NumeroPedido = '{pedido_id}'
        ORDER BY ps.Sequence
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if not rows:
            print(f"  ❌ NO HAY REGISTROS para pedido {pedido_id}")
            continue
            
        for row in rows:
            seq, so, qty, assy, ex, assembly, tb = row
            print(f"  Sequence: {seq}")
            print(f"    SO: {so}, Qty: {qty}")
            print(f"    Assy: {assy}")
            print(f"    Assembly: {assembly}")
            print(f"    EX (Extender): {ex if ex else '[VACÍO/NULL]'}")
            print(f"    TB (TieBracket): {tb if tb else '[VACÍO/NULL]'}")
            
            # Paso 2: Verificar si EX existe en OB.Omegas como ExtenderVariable
            if ex and ex.strip():
                print(f"\n[PASO 2] Buscar '{ex}' en OB.Omegas.ExtenderVariable:")
                query2 = f"""
                SELECT 
                    Assy,
                    ExtenderVariable,
                    [W/C],
                    Cod_producto
                FROM OB.Omegas
                WHERE ExtenderVariable = '{ex}' OR Assy = '{ex}'
                """
                cursor.execute(query2)
                rows2 = cursor.fetchall()
                
                if rows2:
                    print(f"  ✓ ENCONTRADO en OB.Omegas:")
                    for row2 in rows2:
                        assy2, ext_var, wc, cod_prod = row2
                        print(f"    Assy: {assy2}")
                        print(f"    ExtenderVariable: {ext_var}")
                        print(f"    W/C: {wc}")
                        print(f"    Cod_producto: {cod_prod}")
                else:
                    print(f"  ❌ NO ENCONTRADO en OB.Omegas")
                    print(f"    Esto significa ExtenderQuantity será NULL")
            else:
                print(f"\n[PASO 2] EX está vacío o NULL → ExtenderQuantity será NULL")
            
            # Paso 3: Calcular ExtenderQuantity según lógica actual
            print(f"\n[PASO 3] Cálculo de ExtenderQuantity:")
            if ex and ex.strip():
                # Verificar si existe
                query3 = f"""
                SELECT COUNT(*) as cnt
                FROM OB.Omegas
                WHERE ExtenderVariable = '{ex}'
                """
                cursor.execute(query3)
                exists_result = cursor.fetchone()[0]
                
                if exists_result > 0:
                    ext_qty = qty - 2
                    print(f"  ✓ EX existe en OB.Omegas")
                    print(f"    ExtenderQuantity = {qty} - 2 = {ext_qty}")
                else:
                    print(f"  ❌ EX NO existe en OB.Omegas")
                    print(f"    ExtenderQuantity = NULL (no se muestra en tarjeta)")
            else:
                print(f"  ❌ EX está vacío")
                print(f"    ExtenderQuantity = NULL (no se muestra en tarjeta)")
    
    conn.close()
    print("\n" + "="*80 + "\n")

if __name__ == '__main__':
    pedidos = ['36540', '36559', '36560']
    try:
        diagnosticar_pedidos(pedidos)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

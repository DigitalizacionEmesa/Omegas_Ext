# Endpoints para drag & drop de filas - Agregar a appOMEGAS.py

@app.route('/api/pedidos/reorder', methods=['POST'])
@cross_origin()
def reorder_pedidos():
    """
    Guarda el nuevo orden personalizado de pedidos (drag & drop)
    Recibe un array ordenado de pedidos y asigna OrderSequence secuencial
    """
    try:
        data = request.get_json()
        pedidos_orden = data.get('pedidos_orden', [])  # Array de {NumeroPedido, Assy}
        
        if not pedidos_orden:
            return jsonify({'error': 'No se proporcionaron pedidos para reordenar'}), 400
            
        with ConexionODBC(database='Digitalizacion') as conn:
            cursor = conn.cursor()
            
            # Asignar OrderSequence secuencial: 1, 2, 3, 4...
            for index, item in enumerate(pedidos_orden, start=1):
                cursor.execute("""
                    UPDATE OB.PedidosSecuenciados 
                    SET OrderSequence = ?
                    WHERE NumeroPedido = ? AND Assy = ?
                """, (index, item['NumeroPedido'], item['Assy']))
            
            conn.commit()
            
        return jsonify({
            'message': f'Orden personalizado guardado para {len(pedidos_orden)} pedidos',
            'success': True,
            'reordered_count': len(pedidos_orden)
        })
        
    except Exception as e:
        print(f"Error en reorder_pedidos: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pedidos/reset-order', methods=['POST'])
@cross_origin()
def reset_order():
    """
    Elimina el orden personalizado para volver al automático por SequenceValue
    """
    try:
        data = request.get_json()
        pedidos_especificos = data.get('pedidos', [])  # Opcional: resetear solo pedidos específicos
        
        with ConexionODBC(database='Digitalizacion') as conn:
            cursor = conn.cursor()
            
            if pedidos_especificos:
                # Resetear solo pedidos específicos
                placeholders = ','.join('?' * len(pedidos_especificos))
                cursor.execute(f"""
                    UPDATE OB.PedidosSecuenciados 
                    SET OrderSequence = NULL
                    WHERE NumeroPedido IN ({placeholders})
                """, pedidos_especificos)
                message = f'Orden automático restaurado para {len(pedidos_especificos)} pedidos'
            else:
                # Resetear todos los pedidos
                cursor.execute("UPDATE OB.PedidosSecuenciados SET OrderSequence = NULL")
                message = 'Orden automático restaurado para todos los pedidos'
            
            conn.commit()
            
        return jsonify({
            'message': message,
            'success': True
        })
        
    except Exception as e:
        print(f"Error en reset_order: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pedidos/custom-order-status', methods=['GET'])
@cross_origin()
def get_custom_order_status():
    """
    Obtiene información sobre qué pedidos tienen orden personalizado
    """
    try:
        with ConexionODBC(database='Digitalizacion') as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    NumeroPedido, 
                    Assy, 
                    OrderSequence,
                    SequenceValue
                FROM OB.PedidosSecuenciados 
                WHERE OrderSequence IS NOT NULL
                ORDER BY OrderSequence
            """)
            
            results = cursor.fetchall()
            pedidos_custom = []
            
            for row in results:
                pedidos_custom.append({
                    'NumeroPedido': row[0],
                    'Assy': row[1],
                    'OrderSequence': row[2],
                    'SequenceValue': row[3]
                })
            
        return jsonify({
            'pedidos_con_orden_personalizado': pedidos_custom,
            'total_count': len(pedidos_custom)
        })
        
    except Exception as e:
        print(f"Error en get_custom_order_status: {str(e)}")
        return jsonify({'error': str(e)}), 500

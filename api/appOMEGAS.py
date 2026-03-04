# ====================================================================================
# IMPORTACIONES Y CONFIGURACIÓN
# ====================================================================================
import os
import sys
import time
import logging
import pyodbc
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from flask_jwt_extended  import (JWTManager, create_access_token, jwt_required, get_jwt_identity)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
from flask_cors import CORS, cross_origin
from collections import defaultdict
import threading
# Instalar con: pip install schedule
import schedule


# Configuración directa de usuario y contraseña de la base de datos
DB_USER = 'Usrconsulta'
DB_PASSWORD = 'Clave2025*'

# Configuración directa de usuario y contraseña de la base de datos CZ
DB_USERCZ = 'sccz'
DB_PASSWORDCZ = 'S@vera,CZ,2024'

SECRET_KEY = None
SHUTDOWN_SECRET_KEY = None

# Inicializar Flask (SOLO UNA VEZ)
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app, supports_credentials=True, resources={r"/*": {"origins": "*"}}, methods=["GET", "POST", "PUT", "OPTIONS"], allow_headers=["Content-Type"])

# Carpeta base del proyecto
# - En modo ejecutable (PyInstaller): usa sys._MEIPASS donde se extraen los recursos
# - En modo desarrollo (python api/appOMEGAS.py): sube un nivel desde api/ al raíz del proyecto
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Rutas de recursos
RUTA_PANTALLAS = os.path.join(BASE_DIR, 'Pantallas')
RUTA_ASSETS = os.path.join(BASE_DIR, 'assets')
RUTA_IMAGENES = os.path.join(BASE_DIR, 'IMAGENES')
RUTA_TRADUCCIONES = os.path.join(BASE_DIR, 'translations')

# Debug: Imprimir rutas para verificar
print(f"[CONFIG] BASE_DIR: {BASE_DIR}")
print(f"[CONFIG] RUTA_ASSETS: {RUTA_ASSETS} -> Existe: {os.path.exists(RUTA_ASSETS)}")
print(f"[CONFIG] RUTA_IMAGENES: {RUTA_IMAGENES} -> Existe: {os.path.exists(RUTA_IMAGENES)}")
print(f"[CONFIG] RUTA_TRADUCCIONES: {RUTA_TRADUCCIONES} -> Existe: {os.path.exists(RUTA_TRADUCCIONES)}")

# ====================================================================================
# FUNCIÓN SCHEDULER PARA EJECUCIÓN AUTOMÁTICA DIARIA
# ====================================================================================
def scheduled_daily_sync():
    """
    Función que se ejecuta automáticamente cada día a las 00:00:00
    para sincronizar pedidos del día anterior
    """
    print(f"[SCHEDULER] Inicio sincronización automática diaria - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # Llamar al endpoint de sincronización manual completa internamente
        from collections import defaultdict
        
        # Configurar fecha de inicio (1 día atrás)
        last_sync_time = datetime.now() - timedelta(days=1)
        
        print(f"[SCHEDULER] Sincronizando datos desde: {last_sync_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Obtener Omegas locales
        omegas_map = {}
        try:
            with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                cursor_main = conn_main.cursor()
                cursor_main.execute("SELECT Assy, [W/C] FROM OB.Omegas")
                omegas_map = {row.Assy: row[1] for row in cursor_main.fetchall()}
        except Exception as e:
            print(f"[SCHEDULER] ERROR al obtener Omegas: {e}")
            return
        
        # Extraer datos de MAPEXBP
        datos_externos = []
        try:
            with ConexionODBCCZ(database='mapexbp') as conn_cz:
                cursor_cz = conn_cz.cursor()
                
                query = """
                    SELECT 
                        A.id_his_wam_pedido_cliente,
                        A.NumeroPedido,
                        A.FechaEntrega,
                        A.Bsark,
                        A.EstadoERP,
                        A.Id_wam_estado_pedido_cliente,
                        B.id_his_wam_linea_pedido_cliente,
                        B.Id_producto,
                        B.UnidadesPedidas,
                        B.UniValMapex,
                        C.Cod_producto
                    FROM 
                        his_wam_pedido_cliente A
                    JOIN 
                        his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = A.id_his_wam_pedido_cliente
                    JOIN 
                        V_Cfg_producto C ON C.Id_producto = B.Id_producto
                    WHERE 
                        A.FechaEntrega >= ?
                        AND A.EstadoERP = 0 
                        AND A.Id_wam_estado_pedido_cliente = 1;
                """
                cursor_cz.execute(query, last_sync_time.strftime('%Y-%m-%d %H:%M:%S'))
                
                columns = [desc[0] for desc in cursor_cz.description]
                datos_externos = [dict(zip(columns, row)) for row in cursor_cz.fetchall()]

        except Exception as e:
            print(f"[SCHEDULER] ERROR consultando mapexbp: {e}")
            return

        if not datos_externos:
            print("[SCHEDULER] No hay datos para procesar en la sincronización diaria")
            return
        
        # Procesar datos (misma lógica que manual_full_sync)
        pedidos_agrupados = defaultdict(list)
        for linea in datos_externos:
            pedidos_agrupados[linea['id_his_wam_pedido_cliente']].append(linea)

        cabeceras_a_procesar, lineas_a_insertar = {}, []
        for pedido_id, lineas in pedidos_agrupados.items():
            cwt, ds = None, None
            for linea in lineas:
                wc_type = omegas_map.get(linea['Cod_producto'])
                if wc_type == 'CWT' and not cwt: 
                    cwt = linea['Cod_producto']
                elif wc_type == 'DS' and not ds: 
                    ds = linea['Cod_producto']
            
            primera_linea = lineas[0]
            cabeceras_a_procesar[pedido_id] = (
                pedido_id, primera_linea['NumeroPedido'], primera_linea['FechaEntrega'],
                primera_linea['Bsark'], primera_linea['EstadoERP'],
                primera_linea['Id_wam_estado_pedido_cliente'], cwt, ds
            )
            for linea in lineas:
                lineas_a_insertar.append((
                    linea['id_his_wam_linea_pedido_cliente'], linea['id_his_wam_pedido_cliente'],
                    linea['Id_producto'], linea['Cod_producto'],
                    linea['UnidadesPedidas'], linea['UniValMapex']
                ))
        
        lista_cabeceras = list(cabeceras_a_procesar.values())
        ids_cabeceras_afectadas = list(cabeceras_a_procesar.keys())

        # Insertar en Digitalizacion
        try:
            with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                cursor_main = conn_main.cursor()
                
                # Limpiar registros existentes
                if ids_cabeceras_afectadas:
                    placeholders = ','.join(['?' for _ in ids_cabeceras_afectadas])
                    cursor_main.execute(f"DELETE FROM OB.PedidosLineas WHERE ID_PedidoCabecera_Externa IN ({placeholders})", ids_cabeceras_afectadas)
                    cursor_main.execute(f"DELETE FROM OB.PedidosCabecera WHERE ID_PedidoCabecera_Externa IN ({placeholders})", ids_cabeceras_afectadas)

                # Insertar datos
                if lista_cabeceras:
                    sql_cabecera = "INSERT INTO OB.PedidosCabecera (ID_PedidoCabecera_Externa, NumeroPedido, FechaEntrega, Bsark, EstadoERP, Id_wam_estado_pedido_cliente, CWT, DS) VALUES (?, ?, ?, ?, ?, ?, ?, ?);"
                    cursor_main.executemany(sql_cabecera, lista_cabeceras)
                
                if lineas_a_insertar:
                    sql_lineas = "INSERT INTO OB.PedidosLineas (ID_PedidoLinea_Externa, ID_PedidoCabecera_Externa, ID_Producto_Externo, Cod_Producto_Externo, UnidadesPedidas, UniValMapex) VALUES (?, ?, ?, ?, ?, ?);"
                    cursor_main.executemany(sql_lineas, lineas_a_insertar)
                
                print(f"[SCHEDULER] Sincronización diaria completada: {len(lista_cabeceras)} cabeceras y {len(lineas_a_insertar)} líneas")
                
        except Exception as e:
            print(f"[SCHEDULER] ERROR actualizando Digitalizacion: {e}")
            return
            
    except Exception as e:
        print(f"[SCHEDULER] ERROR GENERAL en sincronización diaria: {str(e)}")

def run_scheduler():
    """
    Worker que ejecuta el scheduler en segundo plano
    """
    print("[SCHEDULER] Iniciando scheduler para sincronización diaria a las 00:00:00")
    
    #EJECUCIÓN INMEDIATA PARA PRUEBAS AL INICIAR LA API
    print("[SCHEDULER] Ejecutando sincronización inicial inmediatamente para pruebas...")
    try:
        scheduled_daily_sync()
        print("[SCHEDULER] ✅ Sincronización inicial completada exitosamente")
    except Exception as e:
        print(f"[SCHEDULER] ❌ ERROR en sincronización inicial: {e}")

    # Programar la tarea para ejecutarse diariamente a las 00:00
    schedule.every().day.at("00:00").do(scheduled_daily_sync)
    print("[SCHEDULER] Programación diaria establecida para las 00:00:00")
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)  # Revisar cada minuto
        except Exception as e:
            print(f"[SCHEDULER] ERROR en el scheduler: {e}")
            time.sleep(60)
            
# ====================================================================================
# AUTO-SYNC DE PEDIDOS SECUENCIADOS CADA 5 SEGUNDOS (solo actualiza los que cambian)
# ====================================================================================
import threading
import time

# --- FUNCIÓN auto_sync_sequenced CON ORDEN DE PRIORIDAD MANUAL AÑADIDO ---
def auto_sync_sequenced():
    print('[AUTO-SYNC] Servicio de actualización incremental de pedidos secuenciados iniciado.')
    while True:
        try:
            with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                cursor_main = conn_main.cursor()

                # ==========================================================
                # === ÚNICO CAMBIO: SE MODIFICA ESTA CONSULTA Y SU ORDER BY ===
                # ==========================================================
                # Ahora la consulta ordena primero por la prioridad manual (PriorityOrder)
                # y luego usa la secuencia original como desempate.
                # FILTRO CRÍTICO: Solo pedidos PENDIENTES (UniValMapex < UnidadesPedidas)
                query_pedidos_ordenados = """
                    SELECT 
                        ps.NumeroPedido, 
                        ps.Assy,
                        ps.Beam,
                        pl.UnidadesPedidas, 
                        pl.UniValMapex, 
                        ps.AssignedStock,
                        ps.AssignedStockBeam,
                        pl.ID_PedidoLinea_Externa, 
                        ps.SequenceValue,
                        ps.PriorityOrder -- Traemos la nueva columna de prioridad
                    FROM OB.PedidosSecuenciados ps
                    INNER JOIN OB.PedidosCabecera pc ON ps.NumeroPedido = pc.NumeroPedido
                    INNER JOIN OB.PedidosLineas pl ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa AND ps.Assy = pl.Cod_Producto_Externo
                    WHERE ISNULL(pl.UniValMapex, 0) < pl.UnidadesPedidas  -- Solo pedidos pendientes
                    ORDER BY 
                        -- 1. Prioridad: el orden manual (los NULLs van al final).
                        CASE WHEN ps.PriorityOrder IS NULL THEN 1 ELSE 0 END,
                        ps.PriorityOrder ASC,
                        -- 2. Desempate: la secuencia original.
                        ps.SequenceValue ASC;
                """
                cursor_main.execute(query_pedidos_ordenados)
                pedidos_actuales = cursor_main.fetchall()
                
                # Actualizar UniValMapex desde MAPEX solo si cambia
                updates_univalmapex = []
                with ConexionODBCCZ(database='mapexbp') as conn_cz:
                    cursor_cz = conn_cz.cursor()
                    for pedido in pedidos_actuales:
                        numero_pedido = pedido.NumeroPedido
                        assy = pedido.Assy
                        id_pedido_linea_externa = pedido.ID_PedidoLinea_Externa
                        uni_val_actual = pedido.UniValMapex
                        cursor_cz.execute("""
                            SELECT TOP 1 B.UniValMapex
                            FROM his_wam_pedido_cliente A
                            JOIN his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = A.id_his_wam_pedido_cliente
                            JOIN V_Cfg_producto C ON C.Id_producto = B.Id_producto
                            WHERE A.NumeroPedido = ? AND C.Cod_producto = ?
                        """, (numero_pedido, assy))
                        row = cursor_cz.fetchone()
                        if row:
                            uni_val_mapex = row.UniValMapex
                            if uni_val_actual != uni_val_mapex:
                                updates_univalmapex.append((uni_val_mapex, id_pedido_linea_externa))
                if updates_univalmapex:
                    cursor_main.executemany("UPDATE OB.PedidosLineas SET UniValMapex = ? WHERE ID_PedidoLinea_Externa = ?", updates_univalmapex)
                    print(f"[AUTO-SYNC] Actualizados {len(updates_univalmapex)} UniValMapex de pedidos secuenciados.")
                else:
                    print("[AUTO-SYNC] No hay cambios en UniValMapex para actualizar.")
                
                # Obtener stock actual (nueva arquitectura: Stock_Omegas_New)
                cursor_main.execute("SELECT Cod_producto, StockActual FROM OB.Stock_Omegas_New")
                stock_disponible = {row.Cod_producto: row.StockActual for row in cursor_main.fetchall()}
                
                # Obtener stock de Beams
                cursor_main.execute("SELECT BeamCode, CurrentStock FROM OB.V_CurrentStock_Beams")
                stock_beams = {row.BeamCode: row.CurrentStock for row in cursor_main.fetchall()}
                
                # Log de stock inicial de beams para diagnóstico
                beams_con_stock = {k: v for k, v in stock_beams.items() if v > 0}
                if beams_con_stock:
                    print(f"[AUTO-SYNC] Beams con stock disponible: {len(beams_con_stock)} ({', '.join(list(beams_con_stock.keys())[:3])}...)")
                
                updates_necesarios = []
                
                # El bucle de asignación ahora respeta el nuevo orden automáticamente
                primer_pedido_procesado = False  # Para log de diagnóstico
                pedidos_con_beam_count = 0
                for pedido in pedidos_actuales:
                    assy = pedido.Assy
                    beam = pedido.Beam
                    
                    if beam:
                        pedidos_con_beam_count += 1
                    
                    stock_actual_para_assy = stock_disponible.get(assy, 0)
                    stock_actual_para_beam = stock_beams.get(beam, 0) if beam else 0
                    cantidad_necesaria = (pedido.UnidadesPedidas or 0) - (pedido.UniValMapex or 0)
                    cantidad_necesaria_beam = pedido.UnidadesPedidas or 0  # Para Beam: no restamos UniValMapex
                    
                    # Log del PRIMER pedido procesado
                    if not primer_pedido_procesado:
                        print(f"[AUTO-SYNC DEBUG] PRIMER PEDIDO PROCESADO:")
                        print(f"  Pedido: {pedido.NumeroPedido}, Assy: {assy}, Beam: {beam}")
                        print(f"  UnidadesPedidas: {pedido.UnidadesPedidas}, UniValMapex: {pedido.UniValMapex}")
                        print(f"  Cantidad necesaria ASSY: {cantidad_necesaria}")
                        print(f"  Cantidad necesaria BEAM: {cantidad_necesaria_beam} (sin restar UniValMapex)")
                        print(f"  beam is None: {beam is None}, beam value: '{beam}'")
                        print(f"  Stock beam disponible: {stock_actual_para_beam}")
                        print(f"  Condiciones: beam={bool(beam)}, cantidad_necesaria_beam>0={cantidad_necesaria_beam>0}, stock>0={stock_actual_para_beam>0}")
                        print(f"  AssignedStockBeam en BD: {pedido.AssignedStockBeam} (tipo: {type(pedido.AssignedStockBeam)})")
                        primer_pedido_procesado = True
                    
                    # Calcular AssignedStock (Assy)
                    nuevo_stock_asignado_assy = 0
                    if cantidad_necesaria > 0 and stock_actual_para_assy > 0:
                        nuevo_stock_asignado_assy = min(cantidad_necesaria, stock_actual_para_assy)
                        stock_disponible[assy] = max(0, stock_actual_para_assy - nuevo_stock_asignado_assy)
                    
                    # Calcular AssignedStockBeam
                    nuevo_stock_asignado_beam = 0
                    if beam and cantidad_necesaria_beam > 0 and stock_actual_para_beam > 0:
                        nuevo_stock_asignado_beam = min(cantidad_necesaria_beam, stock_actual_para_beam)
                        stock_beams[beam] = max(0, stock_actual_para_beam - nuevo_stock_asignado_beam)
                    
                    viejo_assy = pedido.AssignedStock if pedido.AssignedStock is not None else 0
                    viejo_beam = pedido.AssignedStockBeam if pedido.AssignedStockBeam is not None else 0
                    
                    if nuevo_stock_asignado_assy != viejo_assy or nuevo_stock_asignado_beam != viejo_beam:
                        updates_necesarios.append((nuevo_stock_asignado_assy, nuevo_stock_asignado_beam, pedido.NumeroPedido, pedido.Assy))
                
                print(f"[AUTO-SYNC] Total pedidos procesados: {len(pedidos_actuales)}, con Beam: {pedidos_con_beam_count}")
                
                if updates_necesarios:
                    sql_update = "UPDATE OB.PedidosSecuenciados SET AssignedStock = ?, AssignedStockBeam = ? WHERE NumeroPedido = ? AND Assy = ?"
                    cursor_main.executemany(sql_update, updates_necesarios)
                    print(f"[AUTO-SYNC] Actualizados {len(updates_necesarios)} pedidos secuenciados (AssignedStock y AssignedStockBeam).")
                    # Log de ejemplo de actualización
                    if len(updates_necesarios) > 0:
                        ejemplo = updates_necesarios[0]
                        print(f"[AUTO-SYNC] Ejemplo: Pedido {ejemplo[2]}, Assy={ejemplo[3]}, AssignedStock={ejemplo[0]}, AssignedStockBeam={ejemplo[1]}")
                else:
                    print("[AUTO-SYNC] No hay pedidos que actualizar AssignedStock/AssignedStockBeam.")

        except Exception as e:
            print(f"[AUTO-SYNC] ERROR: {str(e)}")
        
        time.sleep(5)

# La función para iniciar el hilo no cambia
def start_auto_sync_thread():
    t = threading.Thread(target=auto_sync_sequenced, daemon=True, name="SequencedSync") # He añadido un nombre al hilo
    t.start()
# =========================================================================================================
# STOCK DE OMEGAS: Ahora gestionado por SQL Server Agent Job (sp_Sync_Omegas_RawData cada 5 min)
# La API solo consulta la vista OB.Stock_Omegas_New y permite reseteo via OB.sp_Reset_Omega_Stock
# =========================================================================================================
# ====================================================================================
# INICIAR EL AUTO-SYNC DE STOCK DE BEAMS
# ====================================================================================
import pyodbc
from datetime import datetime, timedelta
import time

# Asumiendo que tus clases de conexión (ConexionODBCCZ, ConexionODBCCZ) están definidas en otra parte del código.

def auto_sync_beams_stock():
    """
    Sincroniza periódicamente el stock de Beams. Obtiene las entradas de producción
    del centro 'Clinching' y actualiza la base de datos de Digitalización.
    Ahora también descuenta el consumo de Beams por producción de Omegas tipo C.
    """
    print('[AUTO-SYNC BEAMS] Servicio de sincronización de stock de Beams iniciado (ENTRADAS Y CONSUMOS).')

    PRODUCCION_MOVEMENT_ID = 1
    CONSUMO_MOVEMENT_ID = 9  # Ajusta si tu MovementID de consumo es otro

    INTERVALO_SEGUNDOS = 15

    last_sync_time = datetime.now() - timedelta(minutes=5)
    print(f"[AUTO-SYNC BEAMS] Sincronización inicial. Rango de inicio: {last_sync_time.strftime('%Y-%m-%d %H:%M:%S')}")

    while True:
        try:
            current_time = datetime.now()
            last_sync_time_str = last_sync_time.strftime('%Y-%m-%d %H:%M:%S')
            current_time_str = current_time.strftime('%Y-%m-%d %H:%M:%S')

            print(f"\n[AUTO-SYNC BEAMS] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Iniciando ciclo de sincronización.")
            print(f"[AUTO-SYNC BEAMS] Rango de consulta: [{last_sync_time_str} -> {current_time_str}]")

            # 1. Obtener la lista de Beams activos
            beam_map = {}
            try:
                with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                    cursor_main = conn_main.cursor()
                    cursor_main.execute("SELECT BeamID, BeamCode FROM OB.Beams WHERE IsActive = 1")
                    rows = cursor_main.fetchall()
                    print(f"[AUTO-SYNC BEAMS] Beams activos encontrados: {rows}")
                    beam_map = {row.BeamCode: row.BeamID for row in rows}
            except Exception as e:
                print(f"[AUTO-SYNC BEAMS] [ERROR] No se pudo obtener la lista de Beams activos: {e}")
                time.sleep(INTERVALO_SEGUNDOS)
                continue

            if not beam_map:
                print("[AUTO-SYNC BEAMS] [INFO] No hay Beams activos configurados. Saltando ciclo.")
                last_sync_time = current_time
                time.sleep(INTERVALO_SEGUNDOS)
                continue

            set_de_beams_activos = set(beam_map.keys())

            # 2. Obtener Omegas tipo C y su Beam asociado
            omegas_tipo_c = {}
            try:
                with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                    cursor_main = conn_main.cursor()
                    cursor_main.execute("SELECT Assy, Beam FROM OB.Omegas WHERE [W/C]='C' AND Beam IS NOT NULL")
                    omegas_tipo_c = {row.Assy: row.Beam for row in cursor_main.fetchall()}
            except Exception as e:
                print(f"[AUTO-SYNC BEAMS] [ERROR] No se pudo obtener Omegas tipo C: {e}")

            movimientos = []

            try:
                with ConexionODBCCZ(database='mapexbp') as conn_cz:
                    cursor_cz = conn_cz.cursor()

                    # 2a. Entradas (Producción de Beams)
                    print("[AUTO-SYNC BEAMS] [PASO 1/2] Obteniendo producción de 'Clinching'...")
                    query_in = """
                        SELECT 
                            Cod_producto, 
                            SUM(Unidades_OK) AS CantidadTotal
                        FROM 
                            dbo.F_HIS_CT(?, ?, ?, ?, ?, ?)
                        WHERE 
                            WorkGroup1 = '50 Assembly'
                        GROUP BY
                            Cod_producto
                    """
                    params_in = ['WORKCENTER', 'DETAIL', 'PRODUCT', last_sync_time_str, current_time_str, 2]
                    cursor_cz.execute(query_in, params_in)
                    rows_in = cursor_cz.fetchall()
                    produccion_encontrada = 0
                    for row in rows_in:
                        if row.Cod_producto in set_de_beams_activos and row.CantidadTotal and row.CantidadTotal > 0:
                            movimientos.append({
                                'beam_code': row.Cod_producto,
                                'movement_id': PRODUCCION_MOVEMENT_ID,
                                'quantity': int(row.CantidadTotal)
                            })
                            produccion_encontrada += 1
                    print(f"[AUTO-SYNC BEAMS] [INFO] Producción encontrada para {produccion_encontrada} Beams activos.")

                    # 2b. Consumo de Beams por producción de Omegas tipo C
                    if omegas_tipo_c:
                        assys_c = list(omegas_tipo_c.keys())
                        placeholders = ','.join('?' for _ in assys_c)
                        query_c = f"""
                            SELECT Cod_producto, SUM(Unidades_OK) AS CantidadTotal
                            FROM dbo.F_HIS_CT(?, ?, ?, ?, ?, ?)
                            WHERE WorkGroup1 = '50 Assembly' AND Cod_producto IN ({placeholders})
                            GROUP BY Cod_producto
                        """
                        params_c = ['WORKCENTER', 'DETAIL', 'PRODUCT', last_sync_time_str, current_time_str, 2] + assys_c
                        cursor_cz.execute(query_c, params_c)
                        rows_c = cursor_cz.fetchall()
                        consumo_encontrado = 0
                        for row in rows_c:
                            assy = row.Cod_producto
                            cantidad = int(row.CantidadTotal)
                            beam_code = omegas_tipo_c.get(assy)
                            beam_id = beam_map.get(beam_code)
                            if beam_id and cantidad > 0:
                                # Mostrar las Assy asociadas a la Beam que se va a restar cantidad
                                print(f"[AUTO-SYNC BEAMS] Assy asociada a Beam {beam_code}: {assy} (cantidad a restar: {cantidad})")
                                movimientos.append({
                                    'beam_code': beam_code,
                                    'movement_id': CONSUMO_MOVEMENT_ID,
                                    'quantity': -cantidad  # Consumo es negativo
                                })
                                consumo_encontrado += 1
                        print(f"[AUTO-SYNC BEAMS] [INFO] Consumo registrado para {consumo_encontrado} Omegas tipo C.")

            except pyodbc.Error as db_err:
                print(f"[AUTO-SYNC BEAMS] [ERROR] Falló la consulta a la base de datos Mapex: {db_err}")
                time.sleep(INTERVALO_SEGUNDOS)
                continue

            # 3. Registrar los movimientos en la base de datos de destino
            if not movimientos:
                print("[AUTO-SYNC BEAMS] [INFO] No se encontraron nuevos movimientos de stock en este ciclo.")
            else:
                datos_para_insertar = []
                for mov in movimientos:
                    beam_id = beam_map.get(mov['beam_code'])
                    if beam_id:
                        datos_para_insertar.append((
                            beam_id, mov['movement_id'], mov['quantity'], 1, 'Sincronización automática Beams'
                        ))

                if datos_para_insertar:
                    try:
                        with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                            cursor_main = conn_main.cursor()
                            sql_insert = "{CALL OB.sp_AddBeamStockMovement(?, ?, ?, ?, ?)}"
                            # Insertar uno por uno para mejor control de errores
                            insertados = 0
                            for datos in datos_para_insertar:
                                try:
                                    cursor_main.execute(sql_insert, datos)
                                    conn_main.commit()
                                    insertados += 1
                                except pyodbc.Error as insert_err:
                                    print(f"[AUTO-SYNC BEAMS] ERROR insertando BeamID={datos[0]}: {insert_err}")
                            print(f"[AUTO-SYNC BEAMS] [ÉXITO] Se registraron {insertados}/{len(datos_para_insertar)} movimientos de stock.")
                    except pyodbc.Error as db_err:
                        print(f"[AUTO-SYNC BEAMS] [ERROR] Falló la inserción de movimientos de stock: {db_err}")
                        time.sleep(INTERVALO_SEGUNDOS)
                        continue

            last_sync_time = current_time
            print(f"[AUTO-SYNC BEAMS] Ciclo finalizado. Esperando {INTERVALO_SEGUNDOS} segundos...")
            time.sleep(INTERVALO_SEGUNDOS)

        except Exception as e:
            print(f"[AUTO-SYNC BEAMS] [ERROR CRÍTICO] Ocurrió un error inesperado en el bucle principal: {e}")
            time.sleep(INTERVALO_SEGUNDOS)
            continue


# ====================================================================================
# NUEVA FUNCIÓN: LIMPIAR PEDIDOS SECUENCIADOS QUE YA NO CUMPLEN CRITERIOS
# ====================================================================================
def cleanup_sequenced_orders():
    """
    Función que elimina de PedidosSecuenciados los registros cuyo estado ha cambiado
    en MAPEX (ya no son pendientes o han sido completados).
    Se ejecuta cada 30 segundos.
    """
    print('[CLEANUP] Servicio de limpieza de pedidos secuenciados iniciado.')
    
    while True:
        try:
            with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                cursor_main = conn_main.cursor()
                
                # 1. Obtener todos los pedidos secuenciados
                cursor_main.execute("""
                    SELECT NumeroPedido, Assy
                    FROM OB.PedidosSecuenciados
                """)
                pedidos_secuenciados = cursor_main.fetchall()
                
                if not pedidos_secuenciados:
                    print("[CLEANUP] No hay pedidos secuenciados para verificar.")
                    time.sleep(30)
                    continue
                
                # 2. Verificar cada uno en MAPEX
                pedidos_a_eliminar = []
                
                with ConexionODBCCZ(database='mapexbp') as conn_cz:
                    cursor_cz = conn_cz.cursor()
                    
                    for pedido in pedidos_secuenciados:
                        numero_pedido = pedido[0]
                        assy = pedido[1]
                        
                        # Consultar estado actual en MAPEX
                        query = """
                            SELECT 
                                A.EstadoERP,
                                A.Id_wam_estado_pedido_cliente,
                                B.UniValMapex,
                                B.UnidadesPedidas
                            FROM his_wam_pedido_cliente A
                            JOIN his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = A.id_his_wam_pedido_cliente
                            JOIN V_Cfg_producto C ON C.Id_producto = B.Id_producto
                            WHERE A.NumeroPedido = ? AND C.Cod_producto = ?
                        """
                        cursor_cz.execute(query, (numero_pedido, assy))
                        row = cursor_cz.fetchone()
                        
                        # Si no existe en MAPEX o ha cambiadode estado, marcar para eliminar
                        if not row:
                            print(f"[CLEANUP] Pedido {numero_pedido} no encontrado en MAPEX - Se eliminará")
                            pedidos_a_eliminar.append((numero_pedido, assy))
                        else:
                            estado_erp = row[0]
                            estado_wam = row[1]
                            uni_val = row[2] if row[2] is not None else 0
                            unidades_pedidas = row[3] if row[3] is not None else 0
                            
                            # Criterios para ELIMINAR de secuenciados:
                            # 1. EstadoERP != 0 (ya no es pendiente)
                            # 2. Id_wam_estado_pedido_cliente != 1 (cambió de estado)
                            # 3. UniValMapex >= UnidadesPedidas (ya completado en MAPEX)
                            
                            if estado_erp != 0 or estado_wam != 1 or uni_val >= unidades_pedidas:
                                razon = []
                                if estado_erp != 0:
                                    razon.append(f"EstadoERP={estado_erp}")
                                if estado_wam != 1:
                                    razon.append(f"EstadoWAM={estado_wam}")
                                if uni_val >= unidades_pedidas:
                                    razon.append(f"Completado({uni_val}/{unidades_pedidas})")
                                
                                print(f"[CLEANUP] Pedido {numero_pedido} ya no cumple criterios ({', '.join(razon)}) - Se eliminará")
                                pedidos_a_eliminar.append((numero_pedido, assy))
                
                # 3. Eliminar los pedidos que ya no cumplen criterios
                if pedidos_a_eliminar:
                    for numero_pedido, assy in pedidos_a_eliminar:
                        try:
                            cursor_main.execute(
                                "DELETE FROM OB.PedidosSecuenciados WHERE NumeroPedido = ? AND Assy = ?",
                                (numero_pedido, assy)
                            )
                            print(f"[CLEANUP] ✓ Eliminado pedido secuenciado: {numero_pedido} / {assy}")
                        except Exception as e:
                            print(f"[CLEANUP] ERROR al eliminar {numero_pedido}: {e}")
                    
                    print(f"[CLEANUP] Total eliminados: {len(pedidos_a_eliminar)} pedidos")
                else:
                    print("[CLEANUP] No hay pedidos para limpiar en este ciclo")
                    
        except Exception as e:
            print(f"[CLEANUP] ERROR GENERAL: {str(e)}")
        
        time.sleep(30)  # Ejecutar cada 30 segundos


# ====================================================================================
# NUEVO WORKER: LIMPIAR PEDIDOS VIEJOS NO SECUENCIADOS (>7 días y EstadoERP != 0)
# ====================================================================================
def cleanup_old_unsequenced_orders():
    """
    Elimina de PedidosCabecera y PedidosLineas los pedidos que:
    1. Tienen FechaEntrega > 7 días atrás y EstadoERP != 0 en MAPEX (finalizados)
    2. Tienen Id_wam_estado_pedido_cliente = 4 (cancelados) y NO están secuenciados
    
    Se ejecuta cada 60 segundos.
    """
    print('[CLEANUP-OLD] Servicio de limpieza de pedidos viejos no secuenciados iniciado.')
    
    while True:
        try:
            with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                cursor_main = conn_main.cursor()
                
                # Obtener lista de pedidos secuenciados para excluirlos
                cursor_main.execute("SELECT DISTINCT NumeroPedido FROM OB.PedidosSecuenciados")
                pedidos_secuenciados = set(row[0] for row in cursor_main.fetchall())
                
                # Buscar pedidos con FechaEntrega > 7 días atrás
                cursor_main.execute("""
                    SELECT pc.ID_PedidoCabecera_Externa, pc.NumeroPedido, pc.FechaEntrega
                    FROM OB.PedidosCabecera pc
                    WHERE pc.FechaEntrega < DATEADD(DAY, -7, GETDATE())
                """)
                pedidos_viejos = cursor_main.fetchall()
                
                cabeceras_a_eliminar = []
                
                if pedidos_viejos:
                    print(f"[CLEANUP-OLD] Verificando {len(pedidos_viejos)} pedidos con más de 7 días...")
                    
                    with ConexionODBCCZ(database='mapexbp') as conn_cz:
                        cursor_cz = conn_cz.cursor()
                        
                        for pedido in pedidos_viejos:
                            id_cabecera_externa = pedido[0]
                            numero_pedido = pedido[1]
                            fecha_entrega = pedido[2]
                            
                            # Verificar estado ACTUAL en MAPEX (reconsulta completa)
                            query = """
                                SELECT EstadoERP, Id_wam_estado_pedido_cliente
                                FROM his_wam_pedido_cliente
                                WHERE id_his_wam_pedido_cliente = ?
                            """
                            cursor_cz.execute(query, (id_cabecera_externa,))
                            row = cursor_cz.fetchone()
                            
                            if not row:
                                # No existe en MAPEX, eliminar
                                print(f"[CLEANUP-OLD] Pedido {numero_pedido} (Fecha: {fecha_entrega}) no encontrado en MAPEX - Se eliminará")
                                cabeceras_a_eliminar.append((id_cabecera_externa, numero_pedido))
                            else:
                                estado_erp = row[0]
                                estado_wam_actual = row[1]
                                
                                # Criterios para eliminar pedidos viejos (>7 días):
                                # 1. EstadoERP != 0 (ya no está pendiente/finalizado)
                                # 2. Id_wam_estado_pedido_cliente = 4 (cancelado en MAPEX)
                                debe_eliminar = False
                                razon = ""
                                
                                if estado_erp != 0:
                                    debe_eliminar = True
                                    razon = f"EstadoERP={estado_erp}"
                                elif estado_wam_actual == 4:
                                    debe_eliminar = True
                                    razon = "Estado WAM=4 (cancelado en MAPEX)"
                                
                                if debe_eliminar:
                                    # Solo eliminar si NO está secuenciado
                                    if numero_pedido not in pedidos_secuenciados:
                                        print(f"[CLEANUP-OLD] Pedido {numero_pedido} (Fecha: {fecha_entrega}) {razon} - Se eliminará")
                                        cabeceras_a_eliminar.append((id_cabecera_externa, numero_pedido))
                                    else:
                                        print(f"[CLEANUP-OLD] Pedido {numero_pedido} {razon} pero ESTÁ SECUENCIADO - Se conserva")
                else:
                    print("[CLEANUP-OLD] No hay pedidos con >7 días para verificar.")
                
                # NUEVO: Buscar pedidos con Id_wam_estado_pedido_cliente = 4 (cancelados en nuestra tabla) que NO estén secuenciados
                cursor_main.execute("""
                    SELECT pc.ID_PedidoCabecera_Externa, pc.NumeroPedido, pc.FechaEntrega
                    FROM OB.PedidosCabecera pc
                    WHERE pc.Id_wam_estado_pedido_cliente = 4
                """)
                pedidos_cancelados = cursor_main.fetchall()
                
                if pedidos_cancelados:
                    print(f"[CLEANUP-OLD] Verificando {len(pedidos_cancelados)} pedidos con estado WAM=4 en nuestra tabla...")
                    
                    for pedido in pedidos_cancelados:
                        id_cabecera_externa = pedido[0]
                        numero_pedido = pedido[1]
                        fecha_entrega = pedido[2]
                        
                        # Solo eliminar si NO está secuenciado
                        if numero_pedido not in pedidos_secuenciados:
                            # Evitar duplicados en la lista
                            if (id_cabecera_externa, numero_pedido) not in cabeceras_a_eliminar:
                                print(f"[CLEANUP-OLD] Pedido {numero_pedido} (Fecha: {fecha_entrega}) tiene estado WAM=4 y no está secuenciado - Se eliminará")
                                cabeceras_a_eliminar.append((id_cabecera_externa, numero_pedido))
                        else:
                            print(f"[CLEANUP-OLD] Pedido {numero_pedido} tiene estado WAM=4 pero ESTÁ SECUENCIADO - Se conserva")
                
                # Ejecutar las eliminaciones
                if cabeceras_a_eliminar:
                    for id_cabecera_externa, numero_pedido in cabeceras_a_eliminar:
                        try:
                            # Primero eliminar las líneas
                            cursor_main.execute(
                                "DELETE FROM OB.PedidosLineas WHERE ID_PedidoCabecera_Externa = ?",
                                (id_cabecera_externa,)
                            )
                            # Luego eliminar la cabecera
                            cursor_main.execute(
                                "DELETE FROM OB.PedidosCabecera WHERE ID_PedidoCabecera_Externa = ?",
                                (id_cabecera_externa,)
                            )
                            print(f"[CLEANUP-OLD] ✓ Eliminado pedido viejo: {numero_pedido} (ID: {id_cabecera_externa})")
                        except Exception as e:
                            print(f"[CLEANUP-OLD] ERROR al eliminar pedido {numero_pedido}: {e}")
                    
                    print(f"[CLEANUP-OLD] Total pedidos viejos eliminados: {len(cabeceras_a_eliminar)}")
                else:
                    print("[CLEANUP-OLD] No hay pedidos viejos finalizados para limpiar")
                    
        except Exception as e:
            print(f"[CLEANUP-OLD] ERROR GENERAL: {str(e)}")
        
        time.sleep(60)  # Ejecutar cada 60 segundos


# ====================================================================================
# ENDPOINT PARA LISTAR TODOS LOS USUARIOS CON SUS PERMISOS
# ====================================================================================
@app.route('/api/usuarios/listar', methods=['GET'])
@cross_origin()
def listar_usuarios():
    try:
        query = """
        SELECT TOP (1000) [Id_Usuario]
              ,[Num_Operario]
              ,[Nombre]
              ,[Contrasena]
              ,[Nivel_Permisos]
              ,[Roles]
        FROM [DataLakeSCCZ].[General].[Usuarios]
        ORDER BY [Nombre]
        """
        usuarios = []
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            for row in cursor.fetchall():
                usuario = {
                    'Id_Usuario': row[0],
                    'Num_Operario': row[1],
                    'Nombre': row[2],
                    # 'Contrasena': row[3],  # No enviar en producción por seguridad
                    'Nivel_Permisos': row[4],
                    'Roles': row[5]
                }
                usuarios.append(usuario)
        return jsonify(usuarios), 200
    except Exception as e:
        print(f"Error al listar usuarios: {str(e)}")
        return jsonify({
            'error': 'Error al obtener la lista de usuarios',
            'message': str(e)
        }), 500


# ====================================================================================
# ENDPOINT PARA ACTUALIZAR NIVEL DE PERMISOS DE UN USUARIO
# ====================================================================================
@app.route('/api/usuarios/actualizar-permisos', methods=['POST'])
@cross_origin()
def actualizar_permisos_usuario():
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'message': 'No se recibieron datos'
            }), 400
        
        id_usuario = data.get('id_usuario')
        nuevo_nivel = data.get('nuevo_nivel')
        
        # Validaciones
        if not id_usuario:
            return jsonify({
                'success': False,
                'message': 'ID de usuario requerido'
            }), 400
            
        if nuevo_nivel not in [1, 5, 10]:
            return jsonify({
                'success': False,
                'message': 'Nivel de permisos debe ser 1, 5 o 10'
            }), 400
        
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            
            # Verificar que el usuario existe
            verificar_query = """
            SELECT Id_Usuario, Nombre FROM [DataLakeSCCZ].[General].[Usuarios] 
            WHERE Id_Usuario = ?
            """
            cursor.execute(verificar_query, (id_usuario,))
            usuario_existente = cursor.fetchone()
            
            if not usuario_existente:
                return jsonify({
                    'success': False,
                    'message': f'Usuario con ID {id_usuario} no encontrado'
                }), 404
            
            # Actualizar el nivel de permisos
            update_query = """
            UPDATE [DataLakeSCCZ].[General].[Usuarios] 
            SET [Nivel_Permisos] = ?
            WHERE [Id_Usuario] = ?
            """
            
            cursor.execute(update_query, (nuevo_nivel, id_usuario))
            
            # Verificar que se actualizó correctamente
            if cursor.rowcount > 0:
                mensaje = f"Permisos actualizados correctamente para {usuario_existente[1]} (ID: {id_usuario}) - Nuevo nivel: {nuevo_nivel}"
                print(mensaje)
                
                return jsonify({
                    'success': True,
                    'message': mensaje,
                    'usuario_id': id_usuario,
                    'usuario_nombre': usuario_existente[1],
                    'nuevo_nivel': nuevo_nivel
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'message': 'No se pudo actualizar el usuario'
                }), 500
            
    except Exception as e:
        print(f"Error al actualizar permisos: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error interno del servidor: {str(e)}'
        }), 500
    

# ====================================================================================
# ENDPOINT PARA CONSULTAR EL RESUMEN DE PEDIDOS (ALTO RENDIMIENTO)
# ====================================================================================
@app.route('/api/summary-fast', methods=['GET'])
@cross_origin()
def get_summary_fast():
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM OB.V_PedidosSummary_Pendientes")
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
            return jsonify(result)
    except Exception as e:
        print(f"Error en /api/summary-fast: {e}")
        return jsonify({"error": "Error interno", "details": str(e)}), 500

# ====================================================================================
# ENDPOINT MODIFICADO PARA OBTENER PEDIDOS SECUENCIADOS CON ORDEN DE PRIORIDAD
# ====================================================================================
@app.route('/api/summary/sequenced', methods=['GET'])
@cross_origin()
def get_summary_sequenced():
    """
    Devuelve la lista de pedidos secuenciados, ordenados primero por la
    prioridad manual (PriorityOrder) y luego por la secuencia original.
    """
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            
            # La consulta ahora incluye el ORDER BY usando las columnas de la vista
            query = """
                SELECT * 
                FROM OB.V_PedidosSummary_Secuenciados
                ORDER BY
                    -- Las filas con prioridad manual se ordenan por su prioridad
                    CASE WHEN PriorityOrder IS NOT NULL THEN 0 ELSE 1 END,
                    PriorityOrder ASC,
                    -- Las filas sin prioridad se ordenan por secuencia
                    Sequence ASC
            """
            cursor.execute(query)
            
            columns = [column[0] for column in cursor.description]
            result = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return jsonify(result)

    except pyodbc.Error as db_err:
        import logging
        logging.error(f"Error de base de datos en /api/summary/sequenced: {db_err}")
        return jsonify({'error': "Error de base de datos", "details": str(db_err)}), 500
    except Exception as e:
        import logging
        logging.error(f"Error inesperado en /api/summary/sequenced: {e}")
        return jsonify({'error': "Error interno del servidor"}), 500

# ====================================================================================
# ENDPOINT PARA REORDENAR PEDIDOS SECUENCIADOS POR PRIORIDAD MANUAL
# ====================================================================================
@app.route('/api/sequence/reorder-batch', methods=['POST'])
@cross_origin()
def reorder_sequence_batch():
    """
    Reordena múltiples pedidos secuenciados asignando nuevas prioridades manuales en batch.
    Espera JSON: { "orders": [ { "pedidoId": "23511", "priority": 1 }, ... ] }
    """
    try:
        data = request.get_json()
        orders = data.get('orders', [])
        if not orders:
            return jsonify({'error': 'No se proporcionaron órdenes'}), 400

        pedido_ids = [order['pedidoId'] for order in orders]
        priorities = {order['pedidoId']: order['priority'] for order in orders}

        if not pedido_ids:
            return jsonify({'error': 'Lista de pedidos vacía'}), 400

        placeholders = ','.join(['?' for _ in pedido_ids])

        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            # Resetear todas las prioridades primero solo para los pedidos afectados
            reset_query = f"""
                UPDATE OB.PedidosSecuenciados 
                SET PriorityOrder = NULL 
                WHERE NumeroPedido IN ({placeholders})
            """
            cursor.execute(reset_query, pedido_ids)

            # Asignar nuevas prioridades
            for pedido_id in pedido_ids:
                update_query = """
                    UPDATE OB.PedidosSecuenciados 
                    SET PriorityOrder = ? 
                    WHERE NumeroPedido = ?
                """
                cursor.execute(update_query, (priorities[pedido_id], pedido_id))

        return jsonify({
            'success': True,
            'message': f'Se reordenaron {len(orders)} pedidos correctamente'
        })

    except Exception as e:
        logging.error(f"Error en reorder_sequence_batch: {e}")
        return jsonify({'error': str(e)}), 500
# ====================================================================================
# ENDPOINT PARA ELIMINAR UN PEDIDO SECUENCIADO
# ====================================================================================   
# --- ENDPOINT CORREGIDO PARA BORRAR UN PEDIDO SECUENCIADO ---
# Ruta sugerida: más específica para la entidad que se maneja
@app.route('/api/sequenced-orders', methods=['DELETE'])
@cross_origin()
def delete_sequenced_order():
    """
    Elimina una entrada de la tabla OB.PedidosSecuenciados.
    Usa la clave primaria (NumeroPedido, Assy) para identificar la fila a borrar.
    Espera un JSON: { "NumeroPedido": "...", "Assy": "..." }
    """
    data = request.get_json()
    # 1. Validación usando la clave primaria
    if not data or 'NumeroPedido' not in data or 'Assy' not in data:
        return jsonify({"success": False, "error": "Faltan campos obligatorios: se requiere NumeroPedido y Assy"}), 400

    numero_pedido = data['NumeroPedido']
    assy = data['Assy']

    print(f"[API DELETE] Solicitud para eliminar el pedido secuenciado: Pedido={numero_pedido}, Assy={assy}")

    try:
        # 2. Uso correcto del gestor de contexto
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            
            # La consulta DELETE usa la clave primaria
            sql_delete = "DELETE FROM OB.PedidosSecuenciados WHERE NumeroPedido = ? AND Assy = ?"
            
            cursor.execute(sql_delete, numero_pedido, assy)
            
            # El commit se maneja automáticamente en el __exit__ del 'with'
            
            # 3. Verificamos si se borró alguna fila
            if cursor.rowcount == 0:
                print(f"[API DELETE] No se encontró el registro para eliminar.")
                return jsonify({"success": False, "error": "No se encontró el pedido secuenciado para eliminar"}), 404
        
        print(f"[API DELETE] Éxito. Se eliminó {cursor.rowcount} registro.")
        return jsonify({"success": True, "message": "Pedido secuenciado eliminado correctamente"}), 200

    except pyodbc.Error as db_err:
        import logging
        logging.error(f"Error de base de datos en delete_sequenced_order: {db_err}")
        return jsonify({"success": False, "error": "Error de base de datos", "details": str(db_err)}), 500
    except Exception as e:
        import logging
        logging.error(f"Error inesperado en delete_sequenced_order: {e}")
        return jsonify({"success": False, "error": "Error interno del servidor"}), 500

# ====================================================================================
# ENDPOINTS PARA DRAG & DROP - REORDENAMIENTO DE PEDIDOS SECUENCIADOS
# ====================================================================================

@app.route('/api/sequence/reorder', methods=['POST'])
@cross_origin()
def reorder_sequence():
    """
    Reordena un pedido secuenciado asignándole una nueva prioridad manual.
    Espera JSON: { "pedidoId": "23511", "newPriority": 5 }
    """
    try:
        data = request.get_json()
        if not data or 'pedidoId' not in data or 'newPriority' not in data:
            return jsonify({"error": "Faltan campos obligatorios: pedidoId y newPriority"}), 400
        
        pedido_id = data['pedidoId']
        new_priority = int(data['newPriority'])
        
        print(f"[API REORDER] Reordenando pedido {pedido_id} con prioridad {new_priority}")
        
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            
            # Actualizar la prioridad del pedido directamente usando NumeroPedido
            sql_update = """
                UPDATE OB.PedidosSecuenciados 
                SET PriorityOrder = ? 
                WHERE NumeroPedido = ?
            """
            
            cursor.execute(sql_update, new_priority, pedido_id)
            
            if cursor.rowcount == 0:
                return jsonify({"error": "No se encontró el pedido para reordenar"}), 404
            
            # Reorganizar las prioridades para evitar duplicados
            sql_reorganize = """
                WITH RankedPedidos AS (
                    SELECT NumeroPedido, 
                           ROW_NUMBER() OVER (ORDER BY PriorityOrder ASC, SequenceValue ASC) as NewPriority
                    FROM OB.PedidosSecuenciados 
                    WHERE PriorityOrder IS NOT NULL
                )
                UPDATE ps
                SET PriorityOrder = rp.NewPriority
                FROM OB.PedidosSecuenciados ps
                INNER JOIN RankedPedidos rp ON ps.NumeroPedido = rp.NumeroPedido
            """
            
            cursor.execute(sql_reorganize)
            
            print(f"[API REORDER] Éxito. Pedido {pedido_id} reordenado con prioridad {new_priority}")
            return jsonify({"success": True, "message": "Pedido reordenado correctamente"}), 200
            
    except ValueError:
        return jsonify({"error": "newPriority debe ser un número entero"}), 400
    except pyodbc.Error as db_err:
        import logging
        logging.error(f"Error de base de datos en reorder_sequence: {db_err}")
        return jsonify({"error": "Error de base de datos", "details": str(db_err)}), 500
    except Exception as e:
        import logging
        logging.error(f"Error inesperado en reorder_sequence: {e}")
        return jsonify({"error": "Error interno del servidor"}), 500

@app.route('/api/sequence/reset-order', methods=['POST'])
@cross_origin()
def reset_sequence_order():
    """
    Resetea todo el orden manual eliminando todas las prioridades personalizadas.
    Los pedidos volverán a ordenarse por su secuencia original.
    """
    try:
        print("[API RESET] Reseteando todo el orden manual")
        
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            
            # Eliminar todas las prioridades manuales
            sql_reset = "UPDATE OB.PedidosSecuenciados SET PriorityOrder = NULL"
            cursor.execute(sql_reset)
            
            print(f"[API RESET] Éxito. Se resetearon {cursor.rowcount} registros")
            return jsonify({"success": True, "message": f"Orden manual reseteado. {cursor.rowcount} registros afectados"}), 200
            
    except pyodbc.Error as db_err:
        import logging
        logging.error(f"Error de base de datos en reset_sequence_order: {db_err}")
        return jsonify({"error": "Error de base de datos", "details": str(db_err)}), 500
    except Exception as e:
        import logging
        logging.error(f"Error inesperado en reset_sequence_order: {e}")
        return jsonify({"error": "Error interno del servidor"}), 500


# ====================================================================================
# ENDPOINT PARA ELIMINAR TODAS LAS SECUENCIAS (solo para administradores nivel >= 10)
# ====================================================================================
@app.route('/api/sequence/delete-all', methods=['DELETE'])
@cross_origin()
def delete_all_sequences():
    """
    Elimina TODOS los registros de la tabla OB.PedidosSecuenciados.
    Esta operación es irreversible y solo debe ser usada por administradores.
    """
    try:
        print("[API DELETE-ALL] Solicitud para eliminar TODAS las secuencias")
        
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            
            # Primero contar cuántos registros hay
            cursor.execute("SELECT COUNT(*) FROM OB.PedidosSecuenciados")
            count = cursor.fetchone()[0]
            
            if count == 0:
                return jsonify({
                    "success": True, 
                    "message": "No hay secuencias para eliminar",
                    "deleted_count": 0
                }), 200
            
            # Eliminar todos los registros
            sql_delete = "DELETE FROM OB.PedidosSecuenciados"
            cursor.execute(sql_delete)
            
            print(f"[API DELETE-ALL] Éxito. Se eliminaron {count} secuencias")
            return jsonify({
                "success": True, 
                "message": f"Se eliminaron todas las secuencias correctamente",
                "deleted_count": count
            }), 200
            
    except pyodbc.Error as db_err:
        import logging
        logging.error(f"Error de base de datos en delete_all_sequences: {db_err}")
        return jsonify({"error": "Error de base de datos", "details": str(db_err)}), 500
    except Exception as e:
        import logging
        logging.error(f"Error inesperado en delete_all_sequences: {e}")
        return jsonify({"error": "Error interno del servidor"}), 500


# ====================================================================================
# ENDPOINT PARA PEDIDOS SECUENCIADOS C (para pantalla OB_C)
# ====================================================================================

@app.route('/api/pedidos_secuenciados_c', methods=['GET'])
@cross_origin()
def get_pedidos_secuenciados_c():
    """
    Devuelve los pedidos secuenciados tipo C (Assembly = 'Yes C') usando la vista OB.V_PedidosSecuenciados,
    pero IF1 e IF2 se traen de la tabla OB.Omegas.
    Ordenados por PriorityOrder primero (manual) y luego por Sequence (automático).
    """
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
            cursor = conn.cursor()
            query = '''
                SELECT 
                    ps.Sequence AS Sequence,
                    ps.NumeroPedido AS SalesOrder,
                    ps.UnidadesPedidas AS Qty,
                    ISNULL(ps.UniValMapex,0) + ISNULL(ps.AssignedStock,0) AS DoneQty,
                    ps.Assy,
                    ps.Beam,
                    o.IF1,
                    o.IF2,
                    ps.OFs AS WO,
                    ps.PriorityOrder
                FROM OB.V_PedidosSummary_Secuenciados ps
                LEFT JOIN OB.Omegas o ON ps.Assy = o.Assy
                WHERE UPPER(LTRIM(RTRIM(ps.Assembly))) = 'YES C'
                ORDER BY 
                    CASE WHEN ps.PriorityOrder IS NULL THEN 1 ELSE 0 END,
                    ps.PriorityOrder ASC,
                    ps.Sequence ASC
            '''
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            result = []
            for row in rows:
                item = dict(zip(columns, row))
                # IF: Si IF1 e IF2 no coinciden, mostrar ambos separados por /, si coinciden solo uno
                if item.get('IF1') != item.get('IF2'):
                    item['IF'] = f"{item.get('IF1','')}/{item.get('IF2','')}"
                else:
                    item['IF'] = item.get('IF1','')
                result.append(item)
            return jsonify(result)
    except Exception as e:
        print(f"Error en /api/pedidos_secuenciados_c: {e}")
        return jsonify({"error": "Error interno", "details": str(e)}), 500

# ====================================================================================
# ENDPOINT PARA TRAZABILIDAD C (para pantalla OB_C_Trazabilidad)
# ====================================================================================
@app.route('/api/pedidos_secuenciados_c_trazabilidad', methods=['GET'])
@cross_origin()
def get_pedidos_secuenciados_c_trazabilidad():
    """
    Devuelve los pedidos secuenciados tipo C para trazabilidad de Beams.
    DoneQty = AssignedStockBeam (solo stock de Beam asignado)
    """
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
            cursor = conn.cursor()
            query = '''
                SELECT 
                    ps.Sequence AS Sequence,
                    ps.NumeroPedido AS SalesOrder,
                    ps.UnidadesPedidas AS Qty,
                    ISNULL(ps.AssignedStockBeam,0) AS DoneQty,
                    ps.Assy,
                    ps.Beam,
                    o.IF1,
                    o.IF2,
                    ps.OFs AS WO,
                    ps.PriorityOrder
                FROM OB.V_PedidosSummary_Secuenciados ps
                LEFT JOIN OB.Omegas o ON ps.Assy = o.Assy
                WHERE UPPER(LTRIM(RTRIM(ps.Assembly))) = 'YES C'
                  AND ps.UnidadesPedidas > ISNULL(ps.AssignedStockBeam,0)
                ORDER BY 
                    CASE WHEN ps.PriorityOrder IS NULL THEN 1 ELSE 0 END,
                    ps.PriorityOrder ASC,
                    ps.Sequence ASC
            '''
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            result = []
            for row in rows:
                item = dict(zip(columns, row))
                result.append(item)
            return jsonify(result)
    except Exception as e:
        print(f"Error en /api/pedidos_secuenciados_c_trazabilidad: {e}")
        return jsonify({"error": "Error interno", "details": str(e)}), 500
    
# ====================================================================================
# ENDPOINT PARA PEDIDOS SECUENCIADOS W (para pantalla OB_W)
# ====================================================================================
@app.route('/api/pedidos_secuenciados_w', methods=['GET'])
@cross_origin()
def get_pedidos_secuenciados_w():
    """
    Devuelve los pedidos secuenciados tipo W (Assembly = 'Yes W') usando la vista OB.V_PedidosSecuenciados,
    pero IF1 e IF2 se traen de la tabla OB.Omegas.
    Ordenados por PriorityOrder primero (manual) y luego por SequenceValue (automático).
    """
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
            cursor = conn.cursor()
            query = '''
                SELECT 
                    ps.Sequence AS Sequence,
                    ps.NumeroPedido AS SalesOrder,
                    ps.UnidadesPedidas AS Qty,
                    ISNULL(ps.UniValMapex,0) + ISNULL(ps.AssignedStock,0) AS DoneQty,
                    ps.Assy,
                    ps.Beam,
                    o.IF1,
                    o.IF2,
                    ps.OFs AS WO,
                    ps.PriorityOrder
                FROM OB.V_PedidosSummary_Secuenciados ps
                LEFT JOIN OB.Omegas o ON ps.Assy = o.Assy
                WHERE UPPER(LTRIM(RTRIM(ps.Assembly))) = 'YES W'
                ORDER BY 
                    CASE WHEN ps.PriorityOrder IS NULL THEN 1 ELSE 0 END,
                    ps.PriorityOrder ASC,
                    ps.Sequence ASC
            '''
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            result = []
            for row in rows:
                item = dict(zip(columns, row))
                # IF: Si IF1 e IF2 no coinciden, mostrar ambos separados por /, si coinciden solo uno
                if item.get('IF1') != item.get('IF2'):
                    item['IF'] = f"{item.get('IF1','')}/{item.get('IF2','')}"
                else:
                    item['IF'] = item.get('IF1','')
                result.append(item)
            return jsonify(result)
    except Exception as e:
        print(f"Error en /api/pedidos_secuenciados_c: {e}")
        return jsonify({"error": "Error interno", "details": str(e)}), 500

# ====================================================================================
# ENDPOINT PARA PEDIDOS SECUENCIADOS DE PICKING (para pantalla Picking)
# ====================================================================================   
@app.route('/api/pedidos_picking', methods=['GET'])
@cross_origin()
def get_pedidos_picking():
    """
    Devuelve los pedidos de picking (Picking = 'Yes') usando la vista OB.V_PedidosSummary_Secuenciados.
    Solo incluye los campos necesarios para la pantalla Picking.
    """
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
            cursor = conn.cursor()
            query = '''
                SELECT 
                    ps.Sequence AS Sequence,
                    ps.NumeroPedido AS SalesOrder,
                    ps.UnidadesPedidas AS Qty,
                    ps.Assy,
                    ps.Beam,
                    ps.FechaEntrega AS DeliveryDate,
                    ps.Picking,         -- <--- Añade este campo
                    ps.UniValMapex      -- <--- Y este campo
                FROM OB.V_PedidosSummary_Secuenciados ps
                WHERE UPPER(LTRIM(RTRIM(ps.Picking))) = 'YES'
            '''
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
            return jsonify(result)
    except Exception as e:
        print(f"Error en /api/pedidos_picking: {e}")
        return jsonify({"error": "Error interno", "details": str(e)}), 500

# ====================================================================================
# ENDPOINT PARA ACTUALIZACIÓN MANUAL DE PEDIDOS (1 DÍA ATRÁS)
# ====================================================================================
@app.route('/api/sync/manual-full', methods=['POST'])
@cross_origin()
def manual_full_sync():
    """
    Endpoint para actualización manual completa - trae pedidos de 1 día atrás
    """
    print(f"[MANUAL SYNC] Inicio actualización manual completa - {datetime.now().strftime('%H:%M:%S')}")
    
    try:
        # Configurar fecha de inicio (1 día atrás)
        last_sync_time = datetime.now() - timedelta(days=5)
        current_time = datetime.now()
        print(f"[MANUAL SYNC] Sincronizando pendientes desde: {last_sync_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # Obtener Omegas locales
        omegas_map = {}
        try:
            with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                cursor_main = conn_main.cursor()
                cursor_main.execute("SELECT Assy, [W/C] FROM OB.Omegas")
                omegas_map = {row.Assy: row[1] for row in cursor_main.fetchall()}
        except Exception as e:
            print(f"[MANUAL SYNC] ERROR al obtener Omegas: {e}")
            return jsonify({"error": f"Error al obtener Omegas: {str(e)}"}), 500

        # Extraer solo pedidos creados en el último día (usando FechaPedido)
        datos_externos = []
        try:
            with ConexionODBCCZ(database='mapexbp') as conn_cz:
                cursor_cz = conn_cz.cursor()
                query = """
                    SELECT 
                        A.id_his_wam_pedido_cliente,
                        A.NumeroPedido,
                        A.FechaEntrega,
                        A.Bsark,
                        A.EstadoERP,
                        A.Id_wam_estado_pedido_cliente,
                        B.id_his_wam_linea_pedido_cliente,
                        B.Id_producto,
                        B.UnidadesPedidas,
                        B.UniValMapex,
                        C.Cod_producto,
                        A.FechaPedido
                    FROM 
                        his_wam_pedido_cliente A
                    JOIN 
                        his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = A.id_his_wam_pedido_cliente
                    JOIN 
                        V_Cfg_producto C ON C.Id_producto = B.Id_producto
                    WHERE 
                        A.FechaPedido >= ?
                        AND A.EstadoERP = 0 
                        AND A.Id_wam_estado_pedido_cliente = 1;
                """
                cursor_cz.execute(query, last_sync_time.strftime('%Y-%m-%d %H:%M:%S'))
                columns = [desc[0] for desc in cursor_cz.description]
                datos_externos = [dict(zip(columns, row)) for row in cursor_cz.fetchall()]
        except Exception as e:
            print(f"[MANUAL SYNC] ERROR consultando mapexbp: {e}")
            return jsonify({"error": f"Error consultando datos externos: {str(e)}"}), 500

        if not datos_externos:
            print("[MANUAL SYNC] No hay datos para procesar en el período especificado")
            return jsonify({
                "message": "Actualización completada - No hay datos nuevos para procesar",
                "registros_procesados": 0,
                "periodo": f"Desde {last_sync_time.strftime('%Y-%m-%d %H:%M:%S')}"
            }), 200

        # Procesar y cargar datos (igual que el scheduler diario)
        from collections import defaultdict
        pedidos_agrupados = defaultdict(list)
        for linea in datos_externos:
            pedidos_agrupados[linea['id_his_wam_pedido_cliente']].append(linea)

        cabeceras_a_procesar, lineas_a_insertar = {}, []
        for pedido_id, lineas in pedidos_agrupados.items():
            cwt, ds = None, None
            for linea in lineas:
                wc_type = omegas_map.get(linea['Cod_producto'])
                if wc_type == 'CWT' and not cwt: 
                    cwt = linea['Cod_producto']
                elif wc_type == 'DS' and not ds: 
                    ds = linea['Cod_producto']
            primera_linea = lineas[0]
            cabeceras_a_procesar[pedido_id] = (
                pedido_id, primera_linea['NumeroPedido'], primera_linea['FechaEntrega'],
                primera_linea['Bsark'], primera_linea['EstadoERP'],
                primera_linea['Id_wam_estado_pedido_cliente'], cwt, ds
            )
            for linea in lineas:
                lineas_a_insertar.append((
                    linea['id_his_wam_linea_pedido_cliente'], linea['id_his_wam_pedido_cliente'],
                    linea['Id_producto'], linea['Cod_producto'],
                    linea['UnidadesPedidas'], linea['UniValMapex']
                ))

        lista_cabeceras = list(cabeceras_a_procesar.values())
        ids_cabeceras_afectadas = list(cabeceras_a_procesar.keys())

        # Insertar en Digitalizacion
        try:
            with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                cursor_main = conn_main.cursor()
                # Limpiar registros existentes para los IDs afectados
                if ids_cabeceras_afectadas:
                    placeholders = ','.join(['?' for _ in ids_cabeceras_afectadas])
                    cursor_main.execute(f"DELETE FROM OB.PedidosLineas WHERE ID_PedidoCabecera_Externa IN ({placeholders})", ids_cabeceras_afectadas)
                    cursor_main.execute(f"DELETE FROM OB.PedidosCabecera WHERE ID_PedidoCabecera_Externa IN ({placeholders})", ids_cabeceras_afectadas)
                # Insertar cabeceras
                if lista_cabeceras:
                    sql_cabecera = "INSERT INTO OB.PedidosCabecera (ID_PedidoCabecera_Externa, NumeroPedido, FechaEntrega, Bsark, EstadoERP, Id_wam_estado_pedido_cliente, CWT, DS) VALUES (?, ?, ?, ?, ?, ?, ?, ?);"
                    cursor_main.executemany(sql_cabecera, lista_cabeceras)
                # Insertar líneas
                if lineas_a_insertar:
                    sql_lineas = "INSERT INTO OB.PedidosLineas (ID_PedidoLinea_Externa, ID_PedidoCabecera_Externa, ID_Producto_Externo, Cod_Producto_Externo, UnidadesPedidas, UniValMapex) VALUES (?, ?, ?, ?, ?, ?);"
                    cursor_main.executemany(sql_lineas, lineas_a_insertar)
                print(f"[MANUAL SYNC] Procesados: {len(lista_cabeceras)} cabeceras y {len(lineas_a_insertar)} líneas")
        except Exception as e:
            print(f"[MANUAL SYNC] ERROR actualizando Digitalizacion: {e}")
            return jsonify({"error": f"Error actualizando base de datos: {str(e)}"}), 500

        return jsonify({
            "message": "Actualización manual completada exitosamente",
            "cabeceras_procesadas": len(lista_cabeceras),
            "lineas_procesadas": len(lineas_a_insertar),
            "periodo": f"Desde {last_sync_time.strftime('%Y-%m-%d %H:%M:%S')}"
        }), 200
    except Exception as e:
        print(f"[MANUAL SYNC] ERROR GENERAL: {str(e)}")
        return jsonify({"error": f"Error interno: {str(e)}"}), 500

# ====================================================================================
# ENDPOINT PARA ACTUALIZACIÓN INCREMENTAL DE PEDIDOS MODIFICADOS
# ====================================================================================
@app.route('/api/sync/incremental', methods=['POST'])
@cross_origin()
def incremental_sync():
    """
    Endpoint para actualización incremental - solo pedidos modificados recientemente
    """
    try:
        # Actualizar UniValMapex de TODOS los pedidos secuenciados desde MAPEX
        try:
            with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                cursor_main = conn_main.cursor()
                cursor_main.execute("""
                    SELECT ps.NumeroPedido, ps.Assy, pl.ID_PedidoLinea_Externa
                    FROM OB.PedidosSecuenciados ps
                    INNER JOIN OB.PedidosCabecera pc ON ps.NumeroPedido = pc.NumeroPedido
                    INNER JOIN OB.PedidosLineas pl ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa AND ps.Assy = pl.Cod_Producto_Externo
                """)
                pedidos_secuenciados = cursor_main.fetchall()
                updates_univalmapex = []
                with ConexionODBCCZ(database='mapexbp') as conn_cz:
                    cursor_cz = conn_cz.cursor()
                    for pedido in pedidos_secuenciados:
                        numero_pedido = pedido.NumeroPedido
                        assy = pedido.Assy
                        id_pedido_linea_externa = pedido.ID_PedidoLinea_Externa
                        cursor_cz.execute("""
                            SELECT TOP 1 B.UniValMapex
                            FROM his_wam_pedido_cliente A
                            JOIN his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = A.id_his_wam_pedido_cliente
                            JOIN V_Cfg_producto C ON C.Id_producto = B.Id_producto
                            WHERE A.NumeroPedido = ? AND C.Cod_producto = ?
                        """, (numero_pedido, assy))
                        row = cursor_cz.fetchone()
                        if row:
                            updates_univalmapex.append((row.UniValMapex, id_pedido_linea_externa))
                if updates_univalmapex:
                    cursor_main.executemany("UPDATE OB.PedidosLineas SET UniValMapex = ? WHERE ID_PedidoLinea_Externa = ?", updates_univalmapex)
        except Exception as e:
            pass

        # Recalcular AssignedStock para TODOS los pedidos secuenciados
        try:
            with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                cursor_main = conn_main.cursor()
                
                # Obtener stock de Assy (nueva arquitectura: Stock_Omegas_New)
                cursor_main.execute("SELECT Cod_producto, StockActual FROM OB.Stock_Omegas_New")
                stock_disponible = {row.Cod_producto: row.StockActual for row in cursor_main.fetchall()}
                
                # Obtener stock de Beam
                cursor_main.execute("SELECT BeamCode, CurrentStock FROM OB.V_CurrentStock_Beams")
                stock_beams = {row.BeamCode: row.CurrentStock for row in cursor_main.fetchall()}
                
                cursor_main.execute("""
                    SELECT ps.NumeroPedido, ps.Assy, ps.Beam, pl.UnidadesPedidas, pl.UniValMapex, ps.SequenceValue, ps.AssignedStock, ps.AssignedStockBeam 
                    FROM OB.PedidosSecuenciados ps
                    INNER JOIN OB.PedidosCabecera pc ON ps.NumeroPedido = pc.NumeroPedido
                    INNER JOIN OB.PedidosLineas pl ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa AND ps.Assy = pl.Cod_Producto_Externo
                    WHERE ISNULL(pl.UniValMapex, 0) < pl.UnidadesPedidas
                    ORDER BY ps.SequenceValue ASC
                """)
                pedidos_a_actualizar = cursor_main.fetchall()
                updates_necesarios = []
                for pedido in pedidos_a_actualizar:
                    assy = pedido.Assy
                    beam = pedido.Beam
                    stock_actual_para_assy = stock_disponible.get(assy, 0)
                    stock_actual_para_beam = stock_beams.get(beam, 0) if beam else 0
                    cantidad_necesaria = (pedido.UnidadesPedidas or 0) - (pedido.UniValMapex or 0)
                    cantidad_necesaria_beam = pedido.UnidadesPedidas or 0  # Para Beam: no restamos UniValMapex
                    
                    # Calcular AssignedStock (Assy)
                    nuevo_stock_asignado_assy = 0
                    if cantidad_necesaria > 0 and stock_actual_para_assy > 0:
                        nuevo_stock_asignado_assy = min(cantidad_necesaria, stock_actual_para_assy)
                        stock_disponible[assy] = max(0, stock_actual_para_assy - nuevo_stock_asignado_assy)
                    
                    # Calcular AssignedStockBeam (SIN restar UniValMapex)
                    nuevo_stock_asignado_beam = 0
                    if beam and cantidad_necesaria_beam > 0 and stock_actual_para_beam > 0:
                        nuevo_stock_asignado_beam = min(cantidad_necesaria_beam, stock_actual_para_beam)
                        stock_beams[beam] = max(0, stock_actual_para_beam - nuevo_stock_asignado_beam)
                    
                    
                    viejo_assy = pedido.AssignedStock if pedido.AssignedStock is not None else 0
                    viejo_beam = pedido.AssignedStockBeam if pedido.AssignedStockBeam is not None else 0
                    
                    if nuevo_stock_asignado_assy != viejo_assy or nuevo_stock_asignado_beam != viejo_beam:
                        updates_necesarios.append((nuevo_stock_asignado_assy, nuevo_stock_asignado_beam, pedido.NumeroPedido, pedido.Assy))
                
                if updates_necesarios:
                    sql_update = "UPDATE OB.PedidosSecuenciados SET AssignedStock = ?, AssignedStockBeam = ? WHERE NumeroPedido = ? AND Assy = ?"
                    cursor_main.executemany(sql_update, updates_necesarios)
        except Exception as e:
            pass

        return jsonify({
            "message": "Actualización incremental completada exitosamente",
            "periodo": "Todos los pedidos secuenciados recalculados"
        }), 200
    except Exception as e:
        print(f"[INCREMENTAL SYNC] ERROR GENERAL: {str(e)}")
        return jsonify({"error": f"Error interno: {str(e)}"}), 500

# ====================================================================================
# ENDPOINT PARA SECUENCIAR PEDIDOS
# ====================================================================================
@app.route('/api/sequence/run', methods=['POST'])
@cross_origin()
def run_sequencing():
    """
    Endpoint para secuenciar pedidos masivamente.
    """
    print(f"[SEQUENCE] Inicio secuenciación - {datetime.now().strftime('%H:%M:%S')}")
    
    try:
        # Paso 1: Obtener datos del request
        data = request.get_json()
        print(f"[SEQUENCE] Datos recibidos: {len(data) if data else 0} líneas")
        
        if not data or not isinstance(data, list):
            print("[SEQUENCE] ERROR: Datos inválidos")
            return jsonify({"error": "Se requiere un array de líneas"}), 400
        
        # Paso 2: Validar campos obligatorios
        campos_obligatorios = ['NumeroPedido', 'Assy', 'Bsark', 'Ord']
        pedidos_validos = []
        errores_validacion = []
        
        for i, linea in enumerate(data):
            campos_faltantes = [campo for campo in campos_obligatorios if not linea.get(campo)]
            if campos_faltantes:
                errores_validacion.append({
                    "indice": i,
                    "pedido": linea.get('NumeroPedido', 'Sin número'),
                    "campos_faltantes": campos_faltantes
                })
            else:
                pedidos_validos.append(linea)
        
        print(f"[SEQUENCE] Válidos: {len(pedidos_validos)}, Errores: {len(errores_validacion)}")
        
        if not pedidos_validos:
            return jsonify({
                "error": "No hay pedidos válidos para secuenciar",
                "errores_validacion": errores_validacion
            }), 400
        
        # Paso 3: Aplicar ordenamiento
        criterio_ordenamiento = "Ord"
        if criterio_ordenamiento == "FechaEntrega":
            pedidos_ordenados = sorted(pedidos_validos, key=lambda x: x.get('FechaEntrega', ''))
        elif criterio_ordenamiento == "Bsark":
            pedidos_ordenados = sorted(pedidos_validos, key=lambda x: x.get('Bsark', ''))
        elif criterio_ordenamiento == "Beam":
            pedidos_ordenados = sorted(pedidos_validos, key=lambda x: x.get('Beam', ''))
        elif criterio_ordenamiento == "Ord":
            pedidos_ordenados = sorted(pedidos_validos, key=lambda x: str(x.get('Ord', '')).strip())
        else:
            pedidos_ordenados = pedidos_validos
        
        # Paso 4: Secuenciación
        print(f"[SEQUENCE] Iniciando secuenciación de {len(pedidos_ordenados)} pedidos")
        resultados_secuenciacion = []
        errores_secuenciacion = []
        
        # Contadores para rastrear secuencias
        contadores_reales_por_bsark = {}
        pedidos_ya_procesados = set()
        
        try:
            with ConexionODBCCZ(database='DataLakeSCCZ') as conn_dig:
                if conn_dig is None:
                    return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
                
                cursor_dig = conn_dig.cursor()
                
                for i, pedido in enumerate(pedidos_ordenados):
                    numero_pedido = pedido['NumeroPedido']
                    assy = pedido['Assy']
                    bsark = pedido['Bsark']
                    
                    # Log cada 10 pedidos para seguimiento
                    if (i + 1) % 10 == 0 or i == 0:
                        print(f"[SEQUENCE] Procesando {i+1}/{len(pedidos_ordenados)}: {numero_pedido}")
                    
                    try:
                        # Verificar si ya está secuenciado
                        cursor_dig.execute(
                            "SELECT COUNT(*) FROM OB.PedidosSecuenciados WHERE NumeroPedido = ? AND Assy = ?",
                            (numero_pedido, assy)
                        )
                        ya_secuenciado = cursor_dig.fetchone()[0] > 0
                        
                        if ya_secuenciado:
                            resultados_secuenciacion.append({
                                "numeroPedido": numero_pedido,
                                "assy": assy,
                                "estado": "ya_secuenciado",
                                "secuencia": None,
                                "mensaje": "Pedido ya estaba secuenciado"
                            })
                            continue
                        
                        # Obtener OFs desde mapexbp
                        try:
                            with ConexionODBCCZ(database='mapexbp') as conn_cz:
                                cursor_cz = conn_cz.cursor()
                                
                                try:
                                    query_ofs_excel = """
                                        WITH FilteredOFs AS (
                                            SELECT 
                                                V.Cod_producto,
                                                V.Cod_of,
                                                V.Desc_estadoof,
                                                V.Fecha_ini,
                                                ROW_NUMBER() OVER(PARTITION BY V.Cod_producto ORDER BY V.Fecha_ini ASC) as rn
                                            FROM 
                                                dbo.V_OFs V
                                            WHERE 
                                                V.Cod_producto = ?
                                                AND V.Desc_estadoof IN ('IN PROGRESS', 'PLANNED')
                                        )
                                        SELECT TOP 3 Cod_of, Desc_estadoof, Fecha_ini
                                        FROM FilteredOFs 
                                        WHERE rn <= 3
                                        ORDER BY Fecha_ini ASC
                                    """
                                    cursor_cz.execute(query_ofs_excel, (assy,))
                                    ofs_rows = cursor_cz.fetchall()
                                    
                                    # Verificar W/C desde Omegas locales
                                    with ConexionODBCCZ(database='DataLakeSCCZ') as conn_local:
                                        cursor_local = conn_local.cursor()
                                        cursor_local.execute("SELECT [W/C] FROM OB.Omegas WHERE Assy = ?", (assy,))
                                        wc_row = cursor_local.fetchone()
                                        wc_type = wc_row[0] if wc_row else None
                                    
                                    # Aplicar filtro W/C
                                    if wc_type in ['C', 'W']:
                                        ofs_list = [row.Cod_of for row in ofs_rows]
                                        ofs_str = ', '.join(ofs_list) if ofs_list else '-'
                                    else:
                                        ofs_str = f"-"
                                    
                                except Exception:
                                    ofs_str = "Error al buscar OFs"
                                    
                        except Exception:
                            ofs_str = "Error al buscar OFs"
                        
                        # Inicializar contador para este Bsark si no existe en memoria
                        if bsark not in contadores_reales_por_bsark:
                            try:
                                # Usar MAX en lugar de COUNT para evitar duplicados si se borraron pedidos
                                # y para manejar correctamente el join
                                query_max = """
                                    SELECT MAX(CAST(SUBSTRING(SequenceValue, ?, 20) AS INT))
                                    FROM OB.PedidosSecuenciados
                                    WHERE SequenceValue LIKE ?
                                """
                                cursor_dig.execute(query_max, (len(bsark) + 2, f"{bsark}-%"))
                                row_max = cursor_dig.fetchone()
                                max_val = row_max[0] if row_max and row_max[0] is not None else 0
                                contadores_reales_por_bsark[bsark] = max_val
                            except Exception as e:
                                print(f"[SEQUENCE] Error calculando MAX secuencia para {bsark}: {e}")
                                # Fallback a 0 si falla el casting
                                contadores_reales_por_bsark[bsark] = 0
                        
                        clave_pedido_bsark = f"{numero_pedido}_{bsark}"
                        
                        # Verificar si este pedido ya tiene una secuencia asignada en la base de datos
                        cursor_dig.execute("""
                            SELECT TOP 1 ps.SequenceValue 
                            FROM OB.PedidosSecuenciados ps
                            INNER JOIN OB.PedidosCabecera pc ON ps.NumeroPedido = pc.NumeroPedido
                            WHERE ps.NumeroPedido = ? AND pc.Bsark = ?
                        """, (numero_pedido, bsark))
                        secuencia_bd = cursor_dig.fetchone()
                        
                        if secuencia_bd:
                            # El pedido ya tiene una secuencia en BD, usar la misma
                            sequence_value = secuencia_bd[0]
                            pedidos_ya_procesados.add(clave_pedido_bsark)
                        elif clave_pedido_bsark in pedidos_ya_procesados:
                            # Buscar la secuencia ya asignada a este pedido en esta sesión
                            secuencia_existente = None
                            for resultado_previo in resultados_secuenciacion:
                                if (resultado_previo['numeroPedido'] == numero_pedido and 
                                    resultado_previo.get('bsark') == bsark and 
                                    resultado_previo['estado'] == 'secuenciado_ok'):
                                    secuencia_existente = resultado_previo['secuencia']
                                    break
                            
                            if secuencia_existente:
                                sequence_value = secuencia_existente
                            else:
                                # Si por alguna razón no encontramos la secuencia, crear una nueva
                                contadores_reales_por_bsark[bsark] += 1
                                sequence_value = f"{bsark}-{contadores_reales_por_bsark[bsark]:03d}"
                        else:
                            # Pedido nuevo - asignar nueva secuencia
                            contadores_reales_por_bsark[bsark] += 1
                            sequence_value = f"{bsark}-{contadores_reales_por_bsark[bsark]:03d}"
                            pedidos_ya_procesados.add(clave_pedido_bsark)
                        
                        # Insertar en la base de datos - Obtener Beam del Assy
                        beam_value = None
                        try:
                            cursor_dig.execute("SELECT Beam FROM OB.Omegas WHERE Assy = ?", (assy,))
                            beam_row = cursor_dig.fetchone()
                            beam_value = beam_row[0] if beam_row else None
                        except:
                            pass
                        
                        cursor_dig.execute("""
                            INSERT INTO OB.PedidosSecuenciados 
                            (NumeroPedido, Assy, Beam, SequenceValue, OFs, FechaSecuenciacion)
                            VALUES (?, ?, ?, ?, ?, GETDATE())
                        """, (numero_pedido, assy, beam_value, sequence_value, ofs_str))
                        
                        resultados_secuenciacion.append({
                            "numeroPedido": numero_pedido,
                            "assy": assy,
                            "bsark": bsark,
                            "estado": "secuenciado_ok",
                            "secuencia": sequence_value,
                            "orden": contadores_reales_por_bsark[bsark],
                            "mensaje": "Secuenciación exitosa",
                            "ofs": ofs_str
                        })
                        
                    except pyodbc.Error as db_err:
                        error_msg = f"Error BD en pedido {numero_pedido}: {str(db_err)}"
                        print(f"[SEQUENCE] ERROR: {error_msg}")
                        errores_secuenciacion.append({
                            "numeroPedido": numero_pedido,
                            "assy": assy,
                            "error": error_msg
                        })
                    except Exception as e:
                        error_msg = f"Error general en pedido {numero_pedido}: {str(e)}"
                        print(f"[SEQUENCE] ERROR: {error_msg}")
                        errores_secuenciacion.append({
                            "numeroPedido": numero_pedido,
                            "assy": assy,
                            "error": error_msg
                        })
                
                print(f"[SEQUENCE] Cambios guardados en base de datos")
                
        except Exception as e:
            print(f"[SEQUENCE] ERROR CRÍTICO: {str(e)}")
            return jsonify({"error": f"Error crítico: {str(e)}"}), 500
        
        # Resumen final
        exitosos = len([r for r in resultados_secuenciacion if r['estado'] == 'secuenciado_ok'])
        ya_secuenciados = len([r for r in resultados_secuenciacion if r['estado'] == 'ya_secuenciado'])
        
        print(f"[SEQUENCE] Completado - Exitosos: {exitosos}, Ya secuenciados: {ya_secuenciados}, Errores: {len(errores_secuenciacion)}")
        
        # Análisis de duplicados simplificado
        pedidos_con_multiples_secuencias = {}
        pedidos_procesados = {}
        
        for resultado in resultados_secuenciacion:
            if resultado['estado'] in ['secuenciado_ok', 'ya_secuenciado']:
                numero_pedido = resultado['numeroPedido']
                secuencia = resultado.get('secuencia', 'N/A')
                
                if numero_pedido not in pedidos_procesados:
                    pedidos_procesados[numero_pedido] = []
                
                pedidos_procesados[numero_pedido].append({
                    'secuencia': secuencia,
                    'assy': resultado.get('assy', 'N/A'),
                    'estado': resultado['estado']
                })
        
        # Detectar duplicados
        for numero_pedido, datos in pedidos_procesados.items():
            secuencias_unicas = set([d['secuencia'] for d in datos if d['secuencia'] != 'N/A'])
            if len(secuencias_unicas) > 1:
                pedidos_con_multiples_secuencias[numero_pedido] = datos
                print(f"[SEQUENCE] WARNING: Pedido {numero_pedido} tiene múltiples secuencias: {sorted(list(secuencias_unicas))}")
        
        # Resumen de secuencias por Bsark
        secuencias_por_bsark = {}
        for resultado in resultados_secuenciacion:
            if resultado['estado'] == 'secuenciado_ok':
                bsark = resultado['bsark']
                if bsark not in secuencias_por_bsark:
                    secuencias_por_bsark[bsark] = []
                secuencias_por_bsark[bsark].append(resultado['secuencia'])
        
        return jsonify({
            "message": "Secuenciación completada exitosamente",
            "resumen": {
                "total_recibidos": len(data),
                "validos_para_procesar": len(pedidos_validos),
                "secuenciados_exitosamente": exitosos,
                "ya_secuenciados": ya_secuenciados,
                "errores": len(errores_secuenciacion),
                "pedidos_con_multiples_secuencias": len(pedidos_con_multiples_secuencias)
            },
            "criterio_ordenamiento": criterio_ordenamiento,
            "secuencias_por_bsark": secuencias_por_bsark,
            "pedidos_duplicados": pedidos_con_multiples_secuencias,
            "contadores_finales": contadores_reales_por_bsark,
            "resultados": resultados_secuenciacion,
            "errores_validacion": errores_validacion,
            "errores_secuenciacion": errores_secuenciacion
        }), 200
        
    except Exception as e:
        print(f"[SEQUENCE] ERROR GENERAL: {str(e)}")
        return jsonify({"error": f"Error interno: {str(e)}"}), 500


# ====================================================================================
# CLASE DE CONEXIÓN ODBC
# ====================================================================================
class ConexionODBC:
    def __init__(self, database=None, servidor='EMEBIDWH'):
        self.driver = 'ODBC Driver 17 for SQL Server'
        self.server = servidor
        self.database = database
        self.conn = None

    def __enter__(self):
        try:
            if not DB_USER or not DB_PASSWORD:
                raise Exception('Faltan credenciales de base de datos')
            conn_str = (
                f"DRIVER={{{self.driver}}};"
                f"SERVER={self.server};"
                f"DATABASE={self.database};"
                f"UID={DB_USER};PWD={DB_PASSWORD};"
                "TrustServerCertificate=yes;"
            )
            self.conn = pyodbc.connect(conn_str, timeout=5, autocommit=True)
            return self.conn
        except Exception as e:
            print(f"Error CRÍTICO al conectar con la base de datos: {e}")
            return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.close()

# ====================================================================================
# CLASE DE CONEXIÓN ODBC PARA CZ
# ====================================================================================
class ConexionODBCCZ:
    def __init__(self, database='mapexbp', servidor='172.16.10.10'):
        # Usa el mismo driver moderno que la clase principal
        self.driver = 'ODBC Driver 17 for SQL Server'
        self.server = servidor
        self.database = database
        self.conn = None

    def __enter__(self):
        try:
            if not DB_USERCZ or not DB_PASSWORDCZ:
                raise Exception('Faltan credenciales de base de datos CZ')
            conn_str = (
                f"DRIVER={{{self.driver}}};"
                f"SERVER={self.server};"
                f"DATABASE={self.database};"
                f"UID={DB_USERCZ};PWD={DB_PASSWORDCZ};"
                "TrustServerCertificate=yes;"
            )
            # Timeout y autocommit igual que la principal
            self.conn = pyodbc.connect(conn_str, timeout=5, autocommit=True)
            return self.conn
        except Exception as e:
            print(f"Error CRÍTICO al conectar con la base de datos CZ: {e}")
            return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.close()

# ====================================================================================
# RUTA PARA SERVIR PANTALLAS HTML
# ====================================================================================
@app.route('/Pantallas/<path:nombre_archivo>')
def servir_pantalla(nombre_archivo):
    ruta_completa = os.path.join(RUTA_PANTALLAS, nombre_archivo)
    if not os.path.exists(ruta_completa):
        return f"Archivo no encontrado: {nombre_archivo}", 404
    return send_from_directory(RUTA_PANTALLAS, nombre_archivo)


# ====================================================================================
# ENDPOINTS DE LA API
# ====================================================================================
@app.route('/api/login', methods=['POST'])
def login():
    """
    Endpoint de autenticación.
    Soporta contraseñas en texto plano (legacy) y hash pbkdf2 (si se migra).
    """
    data = request.json
    usuario = data.get('usuario')
    password = data.get('password')
    
    if not usuario or not password:
        return jsonify({'success': False, 'message': 'Usuario y contraseña son requeridos'}), 400
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            # Buscar usuario por Num_Operario o Nombre
            cursor.execute("""
                SELECT Id_Usuario, Num_Operario, Nombre, Contrasena, Nivel_Permisos, Roles 
                FROM OB.Usuarios_CZ_hash 
                WHERE Num_Operario = ? OR Nombre = ?
            """, (usuario, usuario))
            row = cursor.fetchone()
            
            if not row:
                return jsonify({'success': False, 'message': 'Usuario no encontrado'}), 401
            
            stored_password = row[3]
            password_valid = False
            
            # Verificar contraseña - soporta hash pbkdf2 o texto plano (legacy)
            if stored_password.startswith('pbkdf2:'):
                # Contraseña hasheada
                password_valid = check_password_hash(stored_password, password)
            else:
                # Contraseña en texto plano (legacy)
                password_valid = (stored_password == password)
            
            if password_valid:
                return jsonify({
                    'success': True,
                    'id': row[0],
                    'num_operario': row[1],
                    'nombre': row[2],
                    'nivel': row[4],
                    'nivel_permisos': row[4],
                    'roles': row[5]
                })
            else:
                return jsonify({'success': False, 'message': 'Contraseña incorrecta'}), 401
                
    except Exception as e:
        print(f"Error en /api/login: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/api/cambiar_password', methods=['POST'])
def cambiar_password():
    """
    Endpoint para cambiar contraseña.
    La nueva contraseña se guarda con hash pbkdf2.
    """
    data = request.json
    usuario = data.get('usuario')
    actual = data.get('actual')
    nueva = data.get('nueva')
    
    if not usuario or not actual or not nueva:
        return jsonify({'success': False, 'message': 'Todos los campos son requeridos'}), 400
    
    if len(nueva) < 6:
        return jsonify({'success': False, 'message': 'La contraseña debe tener al menos 6 caracteres'}), 400
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            # Buscar usuario
            cursor.execute("""
                SELECT Id_Usuario, Contrasena FROM OB.Usuarios_CZ_hash 
                WHERE Num_Operario = ? OR Nombre = ?
            """, (usuario, usuario))
            row = cursor.fetchone()
            
            if not row:
                return jsonify({'success': False, 'message': 'Usuario no encontrado'}), 401
            
            id_usuario = row[0]
            stored_password = row[1]
            
            # Verificar contraseña actual
            password_valid = False
            if stored_password.startswith('pbkdf2:'):
                password_valid = check_password_hash(stored_password, actual)
            else:
                password_valid = (stored_password == actual)
            
            if not password_valid:
                return jsonify({'success': False, 'message': 'Contraseña actual incorrecta'}), 401
            
            # Guardar nueva contraseña con hash
            nueva_hash = generate_password_hash(nueva)
            cursor.execute("""
                UPDATE OB.Usuarios_CZ_hash SET Contrasena = ? WHERE Id_Usuario = ?
            """, (nueva_hash, id_usuario))
            conn.commit()
            
            return jsonify({'success': True, 'message': 'Contraseña actualizada correctamente'})
            
    except Exception as e:
        print(f"Error en /api/cambiar_password: {str(e)}")
        return jsonify({'success': False, 'message': 'Error interno del servidor'}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    """
    Endpoint de logout.
    El frontend maneja la sesión en localStorage, este endpoint es para logging/auditoría.
    """
    try:
        data = request.json or {}
        usuario = data.get('usuario', 'unknown')
        print(f"[LOGOUT] Usuario {usuario} cerró sesión a las {datetime.now()}")
        return jsonify({'success': True, 'message': 'Sesión cerrada correctamente'})
    except Exception as e:
        return jsonify({'success': True})  # Siempre success para logout

@app.route('/api/verify_session', methods=['POST'])
def verify_session():
    """
    Verifica si un usuario existe y está activo.
    Útil para validar sesiones del frontend.
    """
    data = request.json
    user_id = data.get('id')
    num_operario = data.get('num_operario')
    
    if not user_id and not num_operario:
        return jsonify({'valid': False}), 400
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT Id_Usuario, Nombre, Nivel_Permisos, Roles 
                FROM OB.Usuarios_CZ_hash 
                WHERE Id_Usuario = ? OR Num_Operario = ?
            """, (user_id, num_operario))
            row = cursor.fetchone()
            
            if row:
                return jsonify({
                    'valid': True,
                    'id': row[0],
                    'nombre': row[1],
                    'nivel_permisos': row[2],
                    'roles': row[3]
                })
            else:
                return jsonify({'valid': False}), 401
                
    except Exception as e:
        print(f"Error en /api/verify_session: {str(e)}")
        return jsonify({'valid': False, 'error': str(e)}), 500

@app.route('/')
def index():
    return "API Flask funcionando. Usa /Pantallas/<archivo> para acceder a tus pantallas."

@app.route('/assets/<path:archivo>')
def servir_assets(archivo):
    return send_from_directory(RUTA_ASSETS, archivo)

@app.route('/IMAGENES/<path:nombre_archivo>')
def servir_imagen(nombre_archivo):
    return send_from_directory(RUTA_IMAGENES, nombre_archivo)

@app.route('/translations/<path:nombre_archivo>')
def servir_traducciones(nombre_archivo):
    return send_from_directory(RUTA_TRADUCCIONES, nombre_archivo)

# ====================================================================================
# ENDPOINT PARA STOCK DE OMEGAS (Nueva arquitectura - Vista OB.Stock_Omegas_New)
# ====================================================================================
@app.route('/api/stock_omegas', methods=['GET'])
@cross_origin()
def get_stock_omegas():
    """
    Devuelve el stock actual de Omegas desde la vista OB.Stock_Omegas_New.
    La sincronización se realiza mediante SQL Server Agent Job cada 5 min.
    """
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
            cursor = conn.cursor()
            query = """
                SELECT Cod_producto, Entradas, Salidas, StockActual 
                FROM OB.Stock_Omegas_New
                ORDER BY Cod_producto
            """
            cursor.execute(query)
            
            resultados = []
            for row in cursor.fetchall():
                resultados.append({
                    'codigo': row.Cod_producto,
                    'entradas': row.Entradas,
                    'salidas': row.Salidas,
                    'stock': row.StockActual
                })
        return jsonify(resultados), 200
    except Exception as e:
        logging.error(f"Error en /api/stock_omegas: {e}")
        return jsonify({"error": str(e)}), 500


# ====================================================================================
# ENDPOINT PARA RESETEO DE STOCK DE OMEGAS (Nueva arquitectura - SP OB.sp_Reset_Omega_Stock)
# ====================================================================================
@app.route('/api/reset_stock', methods=['POST'])
@cross_origin()
def reset_stock_omegas():
    """
    Resetea el stock de un Omega específico.
    Limpia su histórico de producción/lecturas y opcionalmente inserta un ajuste manual.
    Espera JSON: { "codigo": "ASSY_CODE", "nuevo_stock": 0 }
    """
    data = request.get_json() or {}
    cod_producto = data.get('codigo')
    nuevo_stock = data.get('nuevo_stock', 0)

    if not cod_producto:
        return jsonify({"error": "Debe especificar un código de producto."}), 400

    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
            cursor = conn.cursor()
            query = "{CALL OB.sp_Reset_Omega_Stock(?, ?)}"
            cursor.execute(query, (cod_producto, int(nuevo_stock)))
            
        msg = f"Stock reseteado exitosamente para {cod_producto} (Stock Inicial: {nuevo_stock})."
        print(f"[RESET STOCK] {msg}")
        return jsonify({"message": msg}), 200
    except Exception as e:
        logging.error(f"Error en /api/reset_stock: {e}")
        return jsonify({"error": str(e)}), 500


# ====================================================================================
# ENDPOINT PARA LISTAR TODOS LOS OMEGAS
# ====================================================================================
@app.route('/api/omegas/all', methods=['GET'])
@cross_origin()
def get_all_omegas():
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({"error": "No se pudo conectar a la base de datos Digitalizacion"}), 500
            cursor = conn.cursor()
            query = "SELECT OmegaID, Assy, Beam, IF1, IF2, [W/C] FROM OB.Omegas ORDER BY Assy;"
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
            return jsonify(result), 200
    except Exception as e:
        import logging
        logging.error(f"Error al obtener omegas: {e}")
        return jsonify({"error": "Error interno del servidor"}), 500
    

# ====================================================================================
# ENDPOINT PARA ACTUALIZAR UNA OMEGA
# ====================================================================================
@app.route('/api/omegas/update', methods=['PATCH'])
@cross_origin()
def update_omega():
    """
    Actualiza una fila de OB.Omegas según OmegaID o Assy y los campos enviados.
    Si se recibe 'newAssy', renombra el Assy (nombre Omega).
    """
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No se recibieron datos.'}), 400

    campos_validos = ['Beam', 'IF1', 'IF2', 'W/C']
    set_clauses = []
    params = []

    # Soporte para renombrar Assy
    if 'newAssy' in data and data['newAssy']:
        set_clauses.append("[Assy] = ?")
        params.append(data['newAssy'])
    # Otros campos editables
    for campo in campos_validos:
        if campo in data:
            set_clauses.append(f"[{campo}] = ?")
            params.append(data[campo])

    if not set_clauses:
        return jsonify({'success': False, 'error': 'No hay campos para actualizar.'}), 400

    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            if 'OmegaID' in data and data['OmegaID'] is not None:
                sql = f"UPDATE OB.Omegas SET {', '.join(set_clauses)} WHERE OmegaID = ?"
                params.append(data['OmegaID'])
            elif 'Assy' in data and data['Assy']:
                sql = f"UPDATE OB.Omegas SET {', '.join(set_clauses)} WHERE Assy = ?"
                params.append(data['Assy'])
            else:
                return jsonify({'success': False, 'error': 'No se proporcionó OmegaID ni Assy.'}), 400

            cursor.execute(sql, params)
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'error': 'No se encontró la fila a actualizar.'}), 404
            return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
# ====================================================================================
# ENDPOINT PARA INSERCIÓN MASIVA DE OMEGAS
# ====================================================================================
@app.route('/api/omegas/bulk-insert', methods=['POST']) 
@cross_origin()
def bulk_insert_omegas():
    data = request.get_json()
    if not data or not isinstance(data, list) or not data:
        return jsonify({'success': False, 'error': 'No se recibieron datos válidos.'}), 400

    # Solo columnas válidas
    columns = ['Assy', 'Beam', 'IF1', 'IF2', 'W/C']
    values = []
    for row in data:
        values.append(tuple(row.get(col) for col in columns))

    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            sql = "INSERT INTO OB.Omegas (Assy, Beam, IF1, IF2, [W/C]) VALUES (?, ?, ?, ?, ?)"
            cursor.executemany(sql, values)
        return jsonify({'success': True, 'inserted': len(values)})
    except Exception as e:
        import logging
        logging.error(f'Error en bulk_insert_omegas: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500

# ====================================================================================
# ENDPOINT PARA ELIMINAR UNA OMEGA DESDE LA TABLA (usado por Ver_Omegas.html)
# ====================================================================================
@app.route('/api/omegas/delete', methods=['POST'])
@cross_origin()
def delete_omega():
    """Elimina una fila de OB.Omegas según los datos recibidos (Assy, Beam, IF1, IF2, W/C)."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No se recibieron datos.'}), 400
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            # Si viene OmegaID, borrar directamente por OmegaID
            if 'OmegaID' in data and data['OmegaID'] is not None:
                sql = "DELETE FROM OB.Omegas WHERE OmegaID = ?"
                params = (data['OmegaID'],)
                cursor.execute(sql, params)
                if cursor.rowcount == 0:
                    return jsonify({'success': False, 'error': 'No se encontró la fila a eliminar por OmegaID.'}), 404
                return jsonify({'success': True})
            # Si viene Assy, buscar OmegaID y borrar por OmegaID
            elif 'Assy' in data and data['Assy']:
                cursor.execute("SELECT TOP 1 OmegaID FROM OB.Omegas WHERE Assy = ?", (data['Assy'],))
                row = cursor.fetchone()
                if not row:
                    return jsonify({'success': False, 'error': 'No se encontró OmegaID para ese Assy.'}), 404
                omega_id = row[0]
                cursor.execute("DELETE FROM OB.Omegas WHERE OmegaID = ?", (omega_id,))
                if cursor.rowcount == 0:
                    return jsonify({'success': False, 'error': 'No se encontró la fila a eliminar por OmegaID.'}), 404
                return jsonify({'success': True})
            else:
                return jsonify({'success': False, 'error': 'No se proporcionó OmegaID ni Assy.'}), 400
    except Exception as e:
        import logging
        logging.error(f'Error al eliminar omega: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    
# ====================================================================================
# ENDPOINT PARA CONSULTAR UN RESUMEN DE PEDIDOS PENDIENTES
# ====================================================================================
@app.route('/api/summary', methods=['GET'])
@cross_origin()
def get_summary_omegas():
    """
    Endpoint optimizado que usa la vista OB.V_PedidosSummary_Pendientes
    para obtener todos los pedidos pendientes de secuenciar con todos los campos necesarios.
    """
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({"error": "No se pudo conectar a la base de datos Digitalizacion"}), 500

            cursor = conn.cursor()
            query = "SELECT * FROM OB.V_PedidosSummary_Pendientes"
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]

            results = []
            for row in rows:
                item = dict(zip(columns, row))
                if 'Ord' not in item:
                    beam = item.get('Beam', '') or ''
                    assy = item.get('Assy', '') or ''
                    cwt = item.get('CWT', '') or ''
                    item['Ord'] = f"{beam}_{assy}_{cwt}"
                results.append(item)

            return jsonify(results), 200

    except pyodbc.Error as ex:
        return jsonify({"error": "Error de base de datos", "details": str(ex)}), 500
    except Exception as e:
        return jsonify({"error": "Error interno del servidor", "details": str(e)}), 500


# ====================================================================================
# ENDPOINT PARA SECUENCIAR PEDIDOS
# ====================================================================================
@app.route('/api/sequence', methods=['POST'])
def sequence_pedido():
    req = request.get_json()
    numero_pedido = req.get('numeroPedido')
    assy = req.get('assy')
    bsark = req.get('bsark')
    # Paso A: Obtener OFs desde mapexbp
    ofs_list = []
    with ConexionODBCCZ(database='mapexbp') as conn_mapex:
        cursor_mapex = conn_mapex.cursor()
        query_ofs = """
            SELECT TOP 3 Cod_of
            FROM dbo.V_OFs
            WHERE Estado IN ('IN PROGRESS', 'PLANNED')
              AND Cod_producto = ?
              AND Cod_producto IN (
                  SELECT Cod_producto FROM dbo.V_Cfg_producto WHERE [W/C] IN ('W', 'C')
              )
            ORDER BY Fecha_ini
        """
        cursor_mapex.execute(query_ofs, assy)
        ofs_list = [row[0] for row in cursor_mapex.fetchall()]
        cursor_mapex.close()
    ofs_str = ', '.join(ofs_list)

    # Paso B: Calcular siguiente secuencia
    with ConexionODBCCZ(database='DataLakeSCCZ') as conn_dig:
        cursor_dig = conn_dig.cursor()
        cursor_dig.execute("SELECT COUNT(*) FROM OB.PedidosSecuenciados WHERE SequenceValue LIKE ?", (bsark + '%',))
        count = cursor_dig.fetchone()[0]
        sequence_value = f"{bsark}-{count+1}"
        # Paso C: Guardar estado
        cursor_dig.execute(
            "INSERT INTO OB.PedidosSecuenciados (NumeroPedido, Assy, SequenceValue, OFs) VALUES (?, ?, ?, ?)",
            (numero_pedido, assy, sequence_value, ofs_str)
        )
        conn_dig.commit()
        cursor_dig.close()
    return jsonify({"message": "Pedido secuenciado con éxito", "sequence": sequence_value})

# ====================================================================================
# Endpoint para obtener el stock actual de TODOS los OMEGAS
# ====================================================================================
@app.route('/api/beams/stock', methods=['GET'])
@cross_origin()
def get_beams_stock():
    """
    Devuelve el stock actual de todos los Beams desde la vista OB.V_CurrentStock_Beams.
    """
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            query = "SELECT BeamID, BeamCode, CurrentStock FROM OB.V_CurrentStock_Beams ORDER BY BeamCode;"
            cursor.execute(query)
            
            columns = [column[0] for column in cursor.description]
            result = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return jsonify(result), 200
    except Exception as e:
        import logging
        logging.error(f"Error en /api/beams/stock: {e}")
        return jsonify({'error': str(e)}), 500

# ====================================================================================
# Endpoint para resetear el stock de un Beam específico
# ====================================================================================
@app.route('/api/beams/stock/adjust', methods=['POST'])
@cross_origin()
def adjust_beam_stock():
    """
    Realiza un ajuste (reset) en el stock de un Beam específico.
    """
    data = request.get_json()
    if not data or not all(k in data for k in ['beamId', 'realStockCount', 'usuarioId']):
        return jsonify({"error": "Faltan datos: se requiere beamId, realStockCount y usuarioId"}), 400

    beam_id = data['beamId']
    real_stock_count = data['realStockCount']
    usuario_id = data['usuarioId']
    notes = "Reset de stock de Beam desde aplicación web"

    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            
            # 1. Obtenemos el stock actual para calcular el ajuste
            cursor.execute("SELECT CurrentStock FROM OB.V_CurrentStock_Beams WHERE BeamID = ?", beam_id)
            row = cursor.fetchone()
            if not row:
                return jsonify({"error": "El BeamID no existe"}), 404
            
            current_stock = row.CurrentStock
            adjustment_quantity = int(real_stock_count) - current_stock
            
            # 2. Llamamos al procedimiento para insertar el movimiento de ajuste
            # Asumimos que el MovementID para 'Reset' es 3
            sql = "{CALL OB.sp_AddBeamStockMovement(?, ?, ?, ?, ?)}"
            params = (beam_id, 3, adjustment_quantity, usuario_id, notes)
            cursor.execute(sql, params)
            
            return jsonify({"message": f"Stock del BeamID {beam_id} actualizado a {real_stock_count}"}), 200
    except Exception as e:
        import logging
        logging.error(f"Error en /api/beams/stock/adjust: {e}")
        return jsonify({'error': str(e)}), 500


# ====================================================================================
# Endpoint para obtener un resumen de los Beams
# ====================================================================================
from flask import jsonify

@app.route('/api/summary/beams', methods=['GET'])
def get_summary_beams():
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM OB.V_Summary_Beams;")
            columns = [column[0] for column in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ====================================================================================
# Endpoint para obtener las WO asociadas a una Beam específica
# ====================================================================================
@app.route('/api/beam_wo/<beam_code>', methods=['GET'])
@cross_origin()
def get_wo_for_beam(beam_code):
    """
    Devuelve la lista de WO (OF) asociadas DIRECTAMENTE a un código de producto de Beam,
    consultando en tiempo real la base de datos externa 'mapexbp'.
    """
    print(f"[API GET WO] Solicitud para buscar WOs del Beam: {beam_code}")
    
    try:
        wo_list = []
        # Conectamos directamente a la base de datos externa para obtener los datos más frescos
        with ConexionODBCCZ(database='mapexbp') as conn_cz:
            # Es importante asegurarse de que la conexión fue exitosa
            if conn_cz is None:
                # Log del error y retorno de un mensaje claro
                error_message = "No se pudo establecer conexión con la base de datos 'mapexbp'."
                print(f"[API GET WO] ERROR: {error_message}")
                return jsonify({'error': error_message}), 500

            cursor_cz = conn_cz.cursor()
            
            # La consulta SQL correcta que ya has validado
            query = """
                SELECT Cod_of
                FROM dbo.V_OFs
                WHERE Cod_producto = ?
                  AND Desc_estadoof IN ('IN PROGRESS', 'PLANNED')
                ORDER BY Fecha_ini ASC
            """
            
            # Pasamos el beam_code directamente como parámetro
            cursor_cz.execute(query, (beam_code,))
            
            wo_list = [row.Cod_of for row in cursor_cz.fetchall()]
        
        print(f"[API GET WO] Encontradas {len(wo_list)} WOs para el Beam {beam_code}.")
        return jsonify(wo_list)
        
    except pyodbc.Error as db_err:
        import logging
        logging.error(f"Error de BD en get_wo_for_beam para beam '{beam_code}': {db_err}")
        return jsonify({'error': 'Error de base de datos', 'details': str(db_err)}), 500
    except Exception as e:
        import logging
        logging.error(f"Error inesperado en get_wo_for_beam para beam '{beam_code}': {e}")
        return jsonify({'error': 'Error interno del servidor', 'details': str(e)}), 500

# ====================================================================================
# ENDPOINTS PARA GESTIONAR PRODUCTOS FALTANTES
# ====================================================================================
# 1. Obtener todos los productos y su estado de faltante
@app.route('/api/productos/all', methods=['GET'])
@cross_origin()
def get_all_productos():
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    Cod_producto, 
                    Descripcion, 
                    Faltante, 
                    FechaActualizacion, 
                    Usuario
                FROM OB.ProductosFaltantes
                ORDER BY Cod_producto
            """)
            columns = [desc[0] for desc in cursor.description]
            result = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 2. Marcar/desmarcar un producto como faltante
@app.route('/api/productos/faltante', methods=['POST'])
@cross_origin()
def set_producto_faltante():
    data = request.get_json()
    cod_producto = data.get('Cod_producto')
    faltante = 1 if data.get('Faltante') else 0
    usuario = data.get('Usuario', 'web')
    if not cod_producto:
        return jsonify({'success': False, 'error': 'Falta Cod_producto'}), 400
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            cursor.execute("""
                MERGE OB.ProductosFaltantes AS target
                USING (SELECT ? AS Cod_producto) AS source
                ON target.Cod_producto = source.Cod_producto
                WHEN MATCHED THEN
                    UPDATE SET Faltante = ?, FechaActualizacion = GETDATE(), Usuario = ?
                WHEN NOT MATCHED THEN
                    INSERT (Cod_producto, Faltante, FechaActualizacion, Usuario)
                    VALUES (?, ?, GETDATE(), ?);
            """, (cod_producto, faltante, usuario, cod_producto, faltante, usuario))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# 3. Obtener solo los productos faltantes
@app.route('/api/productos/faltantes', methods=['GET'])
@cross_origin()
def get_productos_faltantes():
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT Cod_producto FROM OB.ProductosFaltantes WHERE Faltante = 1")
            result = [row[0] for row in cursor.fetchall()]
            return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 4. Saber si un pedido tiene productos faltantes
@app.route('/api/pedido/<numero>/faltantes', methods=['GET'])
@cross_origin()
def get_faltantes_pedido(numero):
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            # Productos del pedido
            cursor.execute("""
                SELECT Cod_Producto_Externo
                FROM OB.PedidosLineas pl
                INNER JOIN OB.PedidosCabecera pc ON pl.ID_PedidoCabecera_Externa = pc.ID_PedidoCabecera_Externa
                WHERE pc.NumeroPedido = ?
            """, (numero,))
            productos_pedido = set(row[0] for row in cursor.fetchall())
            # Productos faltantes
            cursor.execute("SELECT Cod_producto FROM OB.ProductosFaltantes WHERE Faltante = 1")
            productos_faltantes = set(row[0] for row in cursor.fetchall())
            # Intersección
            faltantes_en_pedido = list(productos_pedido & productos_faltantes)
            return jsonify({
                "faltantes": faltantes_en_pedido,
                "hay_faltantes": len(faltantes_en_pedido) > 0
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 5. Consultar faltantes de múltiples pedidos (optimizado)
@app.route('/api/pedidos/faltantes/batch', methods=['POST'])
@cross_origin()
def get_faltantes_batch():
    try:
        data = request.get_json()
        numeros_pedido = data.get('pedidos', [])
        if not numeros_pedido:
            return jsonify({'error': 'No se proporcionaron números de pedido'}), 400
            
        # Crear placeholders para la consulta IN
        placeholders = ','.join(['?' for _ in numeros_pedido])
        
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            # Obtener productos faltantes para todos los pedidos de una vez
            cursor.execute(f"""
                SELECT pc.NumeroPedido, COUNT(DISTINCT pf.Cod_producto) AS total_faltantes
                FROM OB.PedidosLineas pl
                INNER JOIN OB.PedidosCabecera pc ON pl.ID_PedidoCabecera_Externa = pc.ID_PedidoCabecera_Externa
                INNER JOIN OB.ProductosFaltantes pf ON pl.Cod_Producto_Externo = pf.Cod_producto
                WHERE pc.NumeroPedido IN ({placeholders}) AND pf.Faltante = 1
                GROUP BY pc.NumeroPedido
            """, numeros_pedido)
            
            results = {}
            for row in cursor.fetchall():
                results[row[0]] = {'hay_faltantes': True, 'total': row[1]}
            
            # Añadir pedidos sin faltantes
            for numero in numeros_pedido:
                if numero not in results:
                    results[numero] = {'hay_faltantes': False, 'total': 0}
                    
            return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ====================================================================================
# EJECUCIÓN DE LA APLICACIÓN E INICIO DE WORKERS (VERSIÓN CORREGIDA)
# ====================================================================================
if __name__ == '__main__':
    print("="*50)
    print("INICIALIZANDO API OMEGAS...")
    print("="*50)
    
    # Configurar logging ANTES de iniciar cualquier cosa
    import logging
    import socket
    logging.basicConfig(
        level=logging.INFO, # Usa INFO para producción, DEBUG para depurar
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # Silenciar los logs ruidosos de Flask
    logging.getLogger('werkzeug').setLevel(logging.ERROR)

    # --- INICIAR EL SERVIDOR FLASK ---
    print("="*50)
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print(f"Servidor Flask iniciándose en: http://{local_ip}:3001")
    print("="*50)

    # --- INICIAR EL WORKER DE PEDIDOS ---
    # print("[MAIN] Creando hilo para la sincronización de pedidos (auto_sync_sequenced...)")
    # Asume que la función se llama auto_sync_sequenced
    pedidos_thread = threading.Thread(target=auto_sync_sequenced, name="PedidosSync")
    pedidos_thread.daemon = True
    pedidos_thread.start()
    print("[MAIN] -> Hilo de pedidos iniciado.")

    """ # --- INICIAR EL WORKER DE STOCK DE BEAMS ---
    print("[MAIN] Creando hilo para el stock de Beams (auto_sync_beams_stock)...")
    beams_stock_thread = threading.Thread(target=auto_sync_beams_stock, name="BeamStockSync")
    beams_stock_thread.daemon = True
    beams_stock_thread.start()
    print("[MAIN] -> Hilo de stock de Beams iniciado.") """
    
    # --- STOCK DE OMEGAS: Ya no se ejecuta en hilo Python ---
    # La sincronización de stock de Omegas se gestiona ahora mediante SQL Server Agent Job
    # (OB.sp_Sync_Omegas_RawData cada 5 min). La API solo consulta OB.Stock_Omegas_New.
    print("[MAIN] -> Stock de Omegas gestionado por SQL Server Agent Job (sin hilo Python).")

    # --- INICIAR EL WORKER DE LIMPIEZA DE PEDIDOS SECUENCIADOS ---
    print("[MAIN] Creando hilo para limpieza de pedidos secuenciados (cleanup_sequenced_orders)...")
    cleanup_thread = threading.Thread(target=cleanup_sequenced_orders, daemon=True, name="CleanupSync")
    cleanup_thread.start()
    print("[MAIN] -> Hilo de limpieza iniciado.")

    # --- INICIAR EL WORKER DE LIMPIEZA DE PEDIDOS VIEJOS NO SECUENCIADOS ---
    print("[MAIN] Creando hilo para limpieza de pedidos viejos (cleanup_old_unsequenced_orders)...")
    cleanup_old_thread = threading.Thread(target=cleanup_old_unsequenced_orders, daemon=True, name="CleanupOldSync")
    cleanup_old_thread.start()
    print("[MAIN] -> Hilo de limpieza de pedidos viejos iniciado.")
   
    # --- (Opcional) INICIAR EL SCHEDULER DIARIO ---
    # Si 'run_scheduler' también tiene un bucle, debe ir en un hilo.
    # Si solo configura algo y termina, puede ir directo, pero en un hilo es más seguro.
    print("[MAIN] Creando hilo para el scheduler diario...")
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True, name="DailyScheduler")
    scheduler_thread.start()
    print("[MAIN] -> Hilo de scheduler diario iniciado.")

    # Ejecutar la aplicación principal. Esto SIEMPRE debe ser lo último.
    app.run(host='0.0.0.0', port=3001, debug=True, use_reloader=False)

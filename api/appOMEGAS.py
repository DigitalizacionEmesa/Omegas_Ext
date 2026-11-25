# ====================================================================================
# IMPORTACIONES Y CONFIGURACIÓN
# ====================================================================================
import os
import sys
import io
import time
import logging
from logging.handlers import RotatingFileHandler
import hashlib
import pyodbc
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from flask_jwt_extended  import (JWTManager, create_access_token, jwt_required, get_jwt_identity)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
from flask_cors import CORS, cross_origin
from collections import defaultdict
import threading
import socket
import json
import requests
from decimal import Decimal
# Instalar con: pip install schedule
import schedule
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from cryptography.fernet import Fernet

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


# Consulta SAP temporalmente desactivada.
# Se conserva la caché local (endpoint /api/stock_sap_cached) para mostrar el
# último resultado disponible. Para reactivar la integración, descomentar esta
# configuración y el bloque requests.post de get_stock_sap_omegas().
# SAP_STOCK_URL = 'http://EMESApprdapp:8000/sap/bc/z_ordenes_stock'
# SAP_CLIENT    = '100'
# SAP_USER      = 'EMESA.MM'
# SAP_PASSWORD  = 'EMESA1234'

# ----- CORREO (cargado desde OB.Notificaciones en DataLakeSCCZ al arrancar) -----
SMTP_SERVIDOR         = None
SMTP_PUERTO           = 587
SMTP_USAR_TLS         = True
SMTP_USUARIO          = None
SMTP_CONTRASENA       = None
SMTP_CORREO_ORIGEN    = None
SMTP_NOMBRE_REMITENTE = 'Sistema Omegas'
CORREOS_ALERTAS       = []          # Cargado desde correos_alertas (separados por ;)

# Clave Fernet para descifrar credenciales SMTP almacenadas en BD
FERNET_KEY = b'xV8ospZBTJS8xfrWhlIrwoNJ0lKtGZkS4Ufr-01QOMY='

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
    APP_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    APP_DIR = BASE_DIR

if load_dotenv is not None:
    load_dotenv(os.path.join(APP_DIR, '.env'))

DB_USER = os.getenv('OMEGAS_DB_USER', DB_USER)
DB_PASSWORD = os.getenv('OMEGAS_DB_PASSWORD', DB_PASSWORD)
DB_USERCZ = os.getenv('OMEGAS_DB_USER_CZ', DB_USERCZ)
DB_PASSWORDCZ = os.getenv('OMEGAS_DB_PASSWORD_CZ', DB_PASSWORDCZ)
APP_PORT = int(os.getenv('OMEGAS_PORT', '5014'))
DEV_MODE = os.getenv('OMEGAS_DEV_MODE', 'false').strip().lower() == 'true'

LOGS_DIR = os.path.join(APP_DIR, 'logs')
LOG_FILE = os.path.join(LOGS_DIR, 'appOMEGAS.log')


def configure_logging():
    os.makedirs(LOGS_DIR, exist_ok=True)

    handlers = [logging.StreamHandler()]
    try:
        handlers.insert(0, logging.FileHandler(LOG_FILE, encoding='utf-8'))
    except Exception:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=handlers,
        force=True,
    )
    logging.getLogger('werkzeug').setLevel(logging.ERROR)


configure_logging()

# ====================================================================================
# LOGGER ESPECÍFICO PARA EL STOCK WATCHDOG
# ====================================================================================
stock_logger = logging.getLogger("StockWatchdog")
stock_logger.setLevel(logging.WARNING)
stock_watchdog_log_file = os.path.join(LOGS_DIR, 'stock_watchdog.log')
try:
    watchdog_handler = RotatingFileHandler(stock_watchdog_log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
    watchdog_handler.setFormatter(logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    stock_logger.addHandler(watchdog_handler)
except Exception:
    pass

PEDIDOS_DB_LOCK = threading.RLock()
SEQUENCED_CLEANUP_LOCK = threading.Lock()
ENDPOINT_RESPONSE_CACHE_LOCK = threading.Lock()
ENDPOINT_RESPONSE_CACHE = {}
ENDPOINT_RESPONSE_CACHE_TTL_SECONDS = max(3, int(os.getenv('OMEGAS_VIEW_CACHE_TTL_SECONDS', '15')))
AUTO_SYNC_SEQUENCED_INTERVAL_SECONDS = max(5, int(os.getenv('OMEGAS_PEDIDOS_SYNC_INTERVAL', '15')))
CLEANUP_SEQUENCED_INTERVAL_SECONDS = max(15, int(os.getenv('OMEGAS_PEDIDOS_CLEANUP_INTERVAL', '60')))
CLEANUP_OLD_UNSEQUENCED_INTERVAL_SECONDS = max(30, int(os.getenv('OMEGAS_PEDIDOS_OLD_CLEANUP_INTERVAL', '120')))
MANUAL_SYNC_STATE_LOCK = threading.Lock()
CLINCHING_MASTER_CACHE_LOCK = threading.Lock()
MAPEX_COMPONENT_QTY_CACHE_LOCK = threading.Lock()
CLINCHING_MASTER_CACHE = {
    'timestamp': 0,
    'mapping': {},
}
MAPEX_COMPONENT_QTY_CACHE = {}
CLINCHING_MASTER_CACHE_TTL_SECONDS = max(30, int(os.getenv('OMEGAS_CLINCHING_MASTER_CACHE_TTL_SECONDS', '60')))
MAPEX_COMPONENT_QTY_CACHE_TTL_SECONDS = max(10, int(os.getenv('OMEGAS_MAPEX_COMPONENT_CACHE_TTL_SECONDS', '60')))
MANUAL_SYNC_STATE = {
    'running': False,
    'started_at': None,
    'finished_at': None,
    'result': None,
    'error': None,
}

SEQUENCED_SYNC_STATUS_LOCK = threading.Lock()
SEQUENCED_SYNC_STATUS = {
    'running': False,
    'last_started_at': None,
    'last_completed_at': None,
    'last_error': None,
    'processed_lines': 0,
    'updated_lines': 0,
    'terminal_lines': 0,
    'mapex_updates': 0,
}


def is_terminal_mapex_order(estado_erp, estado_wam, unidades_pedidas, unidades_servidas=0):
    """Indica si el pedido ya se puede retirar también de la cola de Picking.

    La producción completa retira la línea de Assembly, pero se conserva en
    PedidosSecuenciados hasta que MAPEX confirme que se ha servido/recogido.
    """
    estado_erp = estado_erp if estado_erp is not None else 0
    estado_wam = estado_wam if estado_wam is not None else 0
    unidades_pedidas = unidades_pedidas if unidades_pedidas is not None else 0
    unidades_servidas = unidades_servidas if unidades_servidas is not None else 0

    return (
        estado_erp == 4  # cfg_mnt_estadopedido: 4=CANCELADO; 1 y 2 siguen activos
        or estado_wam == 4  # 4=CANCELADO; 2=EN CURSO y 3=FINALIZADA
        or (unidades_pedidas > 0 and unidades_servidas >= unidades_pedidas)
    )


def get_cached_endpoint_response(cache_key, max_age_seconds=None):
    now = time.time()
    with ENDPOINT_RESPONSE_CACHE_LOCK:
        cache_entry = ENDPOINT_RESPONSE_CACHE.get(cache_key)
        if not cache_entry:
            return None
        ttl_seconds = ENDPOINT_RESPONSE_CACHE_TTL_SECONDS if max_age_seconds is None else max_age_seconds
        if now - cache_entry['timestamp'] > ttl_seconds:
            ENDPOINT_RESPONSE_CACHE.pop(cache_key, None)
            return None
        return cache_entry['payload']


def set_cached_endpoint_response(cache_key, payload):
    with ENDPOINT_RESPONSE_CACHE_LOCK:
        ENDPOINT_RESPONSE_CACHE[cache_key] = {
            'timestamp': time.time(),
            'payload': payload,
        }


def clear_endpoint_response_cache(*cache_keys):
    with ENDPOINT_RESPONSE_CACHE_LOCK:
        if cache_keys:
            for cache_key in cache_keys:
                ENDPOINT_RESPONSE_CACHE.pop(cache_key, None)
        else:
            ENDPOINT_RESPONSE_CACHE.clear()


def clear_clinching_master_cache():
    with CLINCHING_MASTER_CACHE_LOCK:
        CLINCHING_MASTER_CACHE['timestamp'] = 0
        CLINCHING_MASTER_CACHE['mapping'] = {}


def get_cached_mapex_component_quantities(assy_codes):
    now = time.time()
    cleaned_codes = sorted({str(code).strip() for code in (assy_codes or []) if code and str(code).strip()})
    if not cleaned_codes:
        return {}, []

    cached_quantities = {}
    missing_codes = []

    with MAPEX_COMPONENT_QTY_CACHE_LOCK:
        expired_codes = []
        for assy_code in cleaned_codes:
            cache_entry = MAPEX_COMPONENT_QTY_CACHE.get(assy_code)
            if not cache_entry:
                missing_codes.append(assy_code)
                continue

            if now - cache_entry['timestamp'] > MAPEX_COMPONENT_QTY_CACHE_TTL_SECONDS:
                expired_codes.append(assy_code)
                missing_codes.append(assy_code)
                continue

            cached_quantities[assy_code] = dict(cache_entry['components'])

        for assy_code in expired_codes:
            MAPEX_COMPONENT_QTY_CACHE.pop(assy_code, None)

    return cached_quantities, missing_codes


def set_cached_mapex_component_quantities(quantities_by_assy):
    if not quantities_by_assy:
        return

    timestamp = time.time()
    with MAPEX_COMPONENT_QTY_CACHE_LOCK:
        for assy_code, component_quantities in quantities_by_assy.items():
            normalized_assy = str(assy_code).strip()
            if not normalized_assy:
                continue
            MAPEX_COMPONENT_QTY_CACHE[normalized_assy] = {
                'timestamp': timestamp,
                'components': dict(component_quantities or {}),
            }


def clear_mapex_component_quantities_cache(*assy_codes):
    with MAPEX_COMPONENT_QTY_CACHE_LOCK:
        if assy_codes:
            for assy_code in assy_codes:
                normalized_assy = str(assy_code).strip()
                if normalized_assy:
                    MAPEX_COMPONENT_QTY_CACHE.pop(normalized_assy, None)
        else:
            MAPEX_COMPONENT_QTY_CACHE.clear()

# ====================================================================================
# LOGGER ESPECÍFICO PARA DIAGNÓSTICO DE VISTAS
# ====================================================================================
def configure_view_diagnostics_logger():
    """Crea un logger separado para registrar cada consulta a vistas"""
    view_diagnostics_file = os.path.join(LOGS_DIR, 'view_diagnostics.log')
    
    view_logger = logging.getLogger('VIEW_DIAGNOSTICS')
    view_logger.setLevel(logging.DEBUG)
    
    # Crear handler para archivo separado
    try:
        file_handler = logging.FileHandler(view_diagnostics_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        view_logger.addHandler(file_handler)
    except Exception as e:
        logging.error(f"No se pudo crear logger de vistas: {e}")
    
    return view_logger

VIEW_LOGGER = configure_view_diagnostics_logger()

# Rutas de recursos
RUTA_PANTALLAS = os.path.join(BASE_DIR, 'Pantallas')
RUTA_ASSETS = os.path.join(BASE_DIR, 'assets')
RUTA_IMAGENES = os.path.join(BASE_DIR, 'IMAGENES')
RUTA_TRADUCCIONES = os.path.join(BASE_DIR, 'translations')
DB_CONNECTION_CONFIG_FILE = os.path.join(APP_DIR, 'db_connection_config.json')


def _unique_preserve_order(values):
    ordered = []
    seen = set()

    for value in values:
        if value is None:
            continue

        text = str(value).strip()
        if not text or text in seen:
            continue

        seen.add(text)
        ordered.append(text)

    return ordered


def _parse_config_list(raw_value):
    if isinstance(raw_value, list):
        return _unique_preserve_order(raw_value)
    if isinstance(raw_value, str):
        return _unique_preserve_order(raw_value.split(','))
    return []


def load_db_connection_config():
    config = {
        'drivers': [
            'ODBC Driver 18 for SQL Server',
            'ODBC Driver 17 for SQL Server',
            'SQL Server'
        ],
        'main_servers': ['EMEBIDWH', '172.16.10.10'],
        'cz_servers': ['172.16.10.10', 'EMEBIDWH']
    }

    if os.path.exists(DB_CONNECTION_CONFIG_FILE):
        try:
            with open(DB_CONNECTION_CONFIG_FILE, 'r', encoding='utf-8') as config_file:
                loaded = json.load(config_file)

            config['drivers'] = _unique_preserve_order(
                _parse_config_list(loaded.get('drivers')) + config['drivers']
            )
            config['main_servers'] = _unique_preserve_order(
                _parse_config_list(loaded.get('main_servers')) + config['main_servers']
            )
            config['cz_servers'] = _unique_preserve_order(
                _parse_config_list(loaded.get('cz_servers')) + config['cz_servers']
            )
        except Exception as e:
            print(f"[CONFIG] No se pudo leer {DB_CONNECTION_CONFIG_FILE}: {e}")

    env_drivers = _parse_config_list(os.getenv('OMEGAS_DB_DRIVERS'))
    env_main_servers = _parse_config_list(os.getenv('OMEGAS_DB_MAIN_SERVERS'))
    env_cz_servers = _parse_config_list(os.getenv('OMEGAS_DB_CZ_SERVERS'))

    if env_drivers:
        config['drivers'] = _unique_preserve_order(env_drivers + config['drivers'])
    if env_main_servers:
        config['main_servers'] = _unique_preserve_order(env_main_servers + config['main_servers'])
    if env_cz_servers:
        config['cz_servers'] = _unique_preserve_order(env_cz_servers + config['cz_servers'])

    return config


DB_CONNECTION_CONFIG = load_db_connection_config()


def build_connection_candidates(default_servers, explicit_server=None):
    servers = [explicit_server] if explicit_server else list(default_servers)

    configured_drivers = list(DB_CONNECTION_CONFIG.get('drivers', []))
    try:
        installed_drivers = pyodbc.drivers()
    except Exception:
        installed_drivers = []

    sql_server_drivers = [driver for driver in installed_drivers if 'SQL Server' in driver]
    if sql_server_drivers:
        drivers = [driver for driver in configured_drivers if driver in sql_server_drivers]
        drivers.extend([driver for driver in sql_server_drivers if driver not in drivers])
    else:
        drivers = configured_drivers

    return _unique_preserve_order(servers), _unique_preserve_order(drivers)

logging.info(f"[CONFIG] BASE_DIR: {BASE_DIR}")
logging.info(f"[CONFIG] APP_DIR: {APP_DIR}")
logging.info(f"[CONFIG] DB_CONNECTION_CONFIG_FILE: {DB_CONNECTION_CONFIG_FILE}")
logging.info(f"[CONFIG] RUTA_ASSETS: {RUTA_ASSETS} -> Existe: {os.path.exists(RUTA_ASSETS)}")
logging.info(f"[CONFIG] RUTA_IMAGENES: {RUTA_IMAGENES} -> Existe: {os.path.exists(RUTA_IMAGENES)}")
logging.info(f"[CONFIG] RUTA_TRADUCCIONES: {RUTA_TRADUCCIONES} -> Existe: {os.path.exists(RUTA_TRADUCCIONES)}")

# ====================================================================================
# CARGA DE CONFIGURACIÓN SMTP DESDE BD (OB.Notificaciones en DataLakeSCCZ)
# ====================================================================================
def cargar_config_smtp():
    """Lee OB.Notificaciones y actualiza las variables globales SMTP.
    Las credenciales vienen cifradas con Fernet y se descifran en memoria.
    """
    global SMTP_SERVIDOR, SMTP_PUERTO, SMTP_USAR_TLS
    global SMTP_USUARIO, SMTP_CONTRASENA, SMTP_CORREO_ORIGEN, SMTP_NOMBRE_REMITENTE
    global CORREOS_ALERTAS

    try:
        fernet = Fernet(FERNET_KEY)
    except Exception as e:
        logging.error(f"[SMTP] Clave Fernet inválida: {e}")
        return

    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                logging.warning("[SMTP] Sin conexión a DataLakeSCCZ — correo desactivado.")
                return
            cursor = conn.cursor()
            cursor.execute("""
                SELECT smtp_servidor, smtp_puerto, smtp_usuario_cifrado, smtp_contrasena_cifrada,
                       smtp_usar_tls, correo_origen, nombre_remitente, correos_alertas
                FROM OB.Notificaciones
                WHERE id_config = 1
            """)
            row = cursor.fetchone()
            if not row:
                logging.warning("[SMTP] Sin registro en OB.Notificaciones (id_config=1) — correo desactivado.")
                return

            servidor, puerto, usuario_enc, contrasena_enc, usar_tls, correo_origen, nombre_rem, correos_raw = row

            def descifrar(valor):
                if not valor:
                    return None
                try:
                    return fernet.decrypt(valor.strip().encode()).decode()
                except Exception:
                    logging.warning("[SMTP] No se pudo descifrar credencial — ¿clave Fernet incorrecta?")
                    return None

            SMTP_SERVIDOR         = servidor or None
            SMTP_PUERTO           = int(puerto) if puerto else 587
            SMTP_USAR_TLS         = bool(usar_tls)
            SMTP_USUARIO          = descifrar(usuario_enc)
            SMTP_CONTRASENA       = descifrar(contrasena_enc)
            SMTP_CORREO_ORIGEN    = correo_origen or None
            SMTP_NOMBRE_REMITENTE = nombre_rem or 'Sistema Omegas'
            CORREOS_ALERTAS       = [
                e.strip()
                for e in (correos_raw or '').replace(',', ';').split(';')
                if e.strip()
            ]

            logging.info(
                f"[SMTP] Config cargada — servidor: {SMTP_SERVIDOR}, "
                f"origen: {SMTP_CORREO_ORIGEN}, destinatarios: {len(CORREOS_ALERTAS)}"
            )
    except Exception as e:
        logging.error(f"[SMTP] Error cargando OB.Notificaciones: {e}")

# NOTA: cargar_config_smtp() se llama desde __main__ (ConexionODBCCZ se define más adelante)


def sync_pending_orders(lookback_days=1, log_prefix='[SYNC]'):
    """Sincroniza en DataLake los pedidos pendientes de MAPEX dentro de la ventana indicada."""
    with PEDIDOS_DB_LOCK:
        cutoff_time = datetime.now() - timedelta(days=lookback_days)
        print(f"{log_prefix} Sincronizando pendientes desde: {cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}")

        def is_pending_status(row):
            return row['EstadoERP'] == 0 and row['Id_wam_estado_pedido_cliente'] == 1

        # Obtener catálogo local para derivar CWT/DS/EX/TB/CWI desde las líneas.
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
            if conn_main is None:
                raise Exception('No se pudo conectar a DataLakeSCCZ para cargar OB.Omegas')

            cursor_main = conn_main.cursor()
            cursor_main.execute("SELECT Assy, [W/C] FROM OB.Omegas")
            omegas_map = {row.Assy: row[1] for row in cursor_main.fetchall()}

        latest_orders = []
        latest_pending_order_ids = []
        terminal_order_numbers = []
        datos_externos = []
        with ConexionODBCCZ(database='mapexbp') as conn_cz:
            if conn_cz is None:
                raise Exception('No se pudo conectar a MAPEXBP para sincronizar pedidos')

            cursor_cz = conn_cz.cursor()
            latest_orders_query = """
                WITH LatestPedidos AS (
                    SELECT 
                        A.id_his_wam_pedido_cliente,
                        A.NumeroPedido,
                        A.FechaEntrega,
                        A.Bsark,
                        A.EstadoERP,
                        A.Id_wam_estado_pedido_cliente,
                        A.FechaPedido,
                        ROW_NUMBER() OVER (
                            PARTITION BY A.NumeroPedido
                            ORDER BY A.id_his_wam_pedido_cliente DESC
                        ) AS rn
                    FROM his_wam_pedido_cliente A
                    WHERE A.FechaEntrega >= ?
                )
                SELECT 
                    id_his_wam_pedido_cliente,
                    NumeroPedido,
                    FechaEntrega,
                    Bsark,
                    EstadoERP,
                    Id_wam_estado_pedido_cliente,
                    FechaPedido
                FROM LatestPedidos
                WHERE rn = 1;
            """
            cursor_cz.execute(latest_orders_query, cutoff_time.strftime('%Y-%m-%d %H:%M:%S'))
            latest_columns = [desc[0] for desc in cursor_cz.description]
            latest_orders = [dict(zip(latest_columns, row)) for row in cursor_cz.fetchall()]

            for order in latest_orders:
                if is_pending_status(order):
                    latest_pending_order_ids.append(order['id_his_wam_pedido_cliente'])
                else:
                    terminal_order_numbers.append(order['NumeroPedido'])

            if latest_pending_order_ids:
                placeholders = ','.join(['?' for _ in latest_pending_order_ids])
                query = f"""
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
                    A.id_his_wam_pedido_cliente IN ({placeholders});
                """
                cursor_cz.execute(query, latest_pending_order_ids)
                columns = [desc[0] for desc in cursor_cz.description]
                datos_externos = [dict(zip(columns, row)) for row in cursor_cz.fetchall()]

        affected_order_numbers = [order['NumeroPedido'] for order in latest_orders]

        if not affected_order_numbers:
            print(f"{log_prefix} No hay datos para procesar en el período especificado")
            return {
                'cabeceras_procesadas': 0,
                'lineas_procesadas': 0,
                'pedidos_terminales_invalidados': 0,
                'periodo_desde': cutoff_time.strftime('%Y-%m-%d %H:%M:%S')
            }

        pedidos_agrupados = defaultdict(list)
        for linea in datos_externos:
            pedidos_agrupados[linea['id_his_wam_pedido_cliente']].append(linea)

        cabeceras_a_procesar, lineas_a_insertar = {}, []
        for pedido_id, lineas in pedidos_agrupados.items():
            cwt, ds, ex, tb, cwi = None, None, None, None, None
            primera_linea = lineas[0]

            for linea in lineas:
                wc_type = omegas_map.get(linea['Cod_producto'])
                if wc_type == 'CWT' and not cwt:
                    cwt = linea['Cod_producto']
                elif wc_type == 'DS' and not ds:
                    ds = linea['Cod_producto']
                elif wc_type == 'EX' and not ex:
                    ex = linea['Cod_producto']
                elif wc_type == 'TB' and not tb:
                    tb = linea['Cod_producto']
                elif wc_type == 'CWI' and not cwi:
                    cwi = linea['Cod_producto']

            cabecera_values = [
                pedido_id,
                primera_linea['NumeroPedido'],
                primera_linea['FechaEntrega'],
                primera_linea['Bsark'],
                primera_linea['EstadoERP'],
                primera_linea['Id_wam_estado_pedido_cliente'],
                cwt,
                ds,
                ex,
                tb,
            ]
            if pedidos_cabecera_has_column('CWI'):
                cabecera_values.append(cwi)

            cabeceras_a_procesar[pedido_id] = tuple(cabecera_values)

            for linea in lineas:
                lineas_a_insertar.append((
                    linea['id_his_wam_linea_pedido_cliente'], linea['id_his_wam_pedido_cliente'],
                    linea['Id_producto'], linea['Cod_producto'],
                    linea['UnidadesPedidas'], linea['UniValMapex']
                ))
        lista_cabeceras = list(cabeceras_a_procesar.values())

        with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
            if conn_main is None:
                raise Exception('No se pudo conectar a DataLakeSCCZ para actualizar PedidosCabecera')

            cursor_main = conn_main.cursor()
            try:
                conn_main.autocommit = False

                if terminal_order_numbers:
                    placeholders_terminales = ','.join(['?' for _ in terminal_order_numbers])
                    cursor_main.execute(
                        f"DELETE FROM OB.PedidosSecuenciados WHERE NumeroPedido IN ({placeholders_terminales})",
                        terminal_order_numbers
                    )

                if affected_order_numbers:
                    placeholders = ','.join(['?' for _ in affected_order_numbers])
                    cursor_main.execute(
                        f"""
                        DELETE pl
                        FROM OB.PedidosLineas pl
                        INNER JOIN OB.PedidosCabecera pc ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
                        WHERE pc.NumeroPedido IN ({placeholders})
                        """,
                        affected_order_numbers
                    )
                    cursor_main.execute(
                        f"DELETE FROM OB.PedidosCabecera WHERE NumeroPedido IN ({placeholders})",
                        affected_order_numbers
                    )

                if lista_cabeceras:
                    pedidos_cabecera_columns = [
                        'ID_PedidoCabecera_Externa',
                        'NumeroPedido',
                        'FechaEntrega',
                        'Bsark',
                        'EstadoERP',
                        'Id_wam_estado_pedido_cliente',
                        'CWT',
                        'DS',
                        'EX',
                        'TB',
                    ]
                    if pedidos_cabecera_has_column('CWI'):
                        pedidos_cabecera_columns.append('CWI')
                    placeholders_cabecera = ', '.join(['?' for _ in pedidos_cabecera_columns])
                    sql_cabecera = f"INSERT INTO OB.PedidosCabecera ({', '.join(pedidos_cabecera_columns)}) VALUES ({placeholders_cabecera});"
                    cursor_main.executemany(sql_cabecera, lista_cabeceras)

                if lineas_a_insertar:
                    sql_lineas = "INSERT INTO OB.PedidosLineas (ID_PedidoLinea_Externa, ID_PedidoCabecera_Externa, ID_Producto_Externo, Cod_Producto_Externo, UnidadesPedidas, UniValMapex) VALUES (?, ?, ?, ?, ?, ?);"
                    cursor_main.executemany(sql_lineas, lineas_a_insertar)

                conn_main.commit()
            except Exception:
                conn_main.rollback()
                raise
            finally:
                conn_main.autocommit = True

        print(
            f"{log_prefix} Procesados: {len(lista_cabeceras)} cabeceras y {len(lineas_a_insertar)} líneas | "
            f"Pedidos terminales invalidados: {len(terminal_order_numbers)}"
        )
        return {
            'cabeceras_procesadas': len(lista_cabeceras),
            'lineas_procesadas': len(lineas_a_insertar),
            'pedidos_terminales_invalidados': len(terminal_order_numbers),
            'periodo_desde': cutoff_time.strftime('%Y-%m-%d %H:%M:%S')
        }


def run_startup_sync():
    try:
        print("[MAIN] Sincronizando pedidos pendientes al arranque...")
        startup_sync = sync_pending_orders(lookback_days=1, log_prefix='[STARTUP SYNC]')
        print(
            f"[MAIN] -> Sync inicial completado: "
            f"{startup_sync['cabeceras_procesadas']} cabeceras y {startup_sync['lineas_procesadas']} líneas."
        )
    except Exception as e:
        logging.exception("[MAIN] Fallo en la sync inicial de pedidos")
        print(f"[MAIN] ADVERTENCIA: no se pudo ejecutar la sync inicial de pedidos: {e}")


def _manual_sync_state_response():
    with MANUAL_SYNC_STATE_LOCK:
        return {
            'running': MANUAL_SYNC_STATE['running'],
            'started_at': MANUAL_SYNC_STATE['started_at'],
            'finished_at': MANUAL_SYNC_STATE['finished_at'],
            'result': MANUAL_SYNC_STATE['result'],
            'error': MANUAL_SYNC_STATE['error'],
        }


def run_manual_full_sync_background():
    try:
        resultado_sync = sync_pending_orders(lookback_days=1, log_prefix='[MANUAL SYNC]')
        resultado_sync['stock_assignment'] = recalculate_assigned_stock_once()
        with MANUAL_SYNC_STATE_LOCK:
            MANUAL_SYNC_STATE['running'] = False
            MANUAL_SYNC_STATE['finished_at'] = datetime.now().isoformat(timespec='seconds')
            MANUAL_SYNC_STATE['result'] = resultado_sync
    except Exception as e:
        logging.exception('[MANUAL SYNC] ERROR GENERAL en segundo plano')
        with MANUAL_SYNC_STATE_LOCK:
            MANUAL_SYNC_STATE['running'] = False
            MANUAL_SYNC_STATE['finished_at'] = datetime.now().isoformat(timespec='seconds')
            MANUAL_SYNC_STATE['error'] = str(e)

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
        sync_pending_orders(lookback_days=1, log_prefix='[SCHEDULER]')
            
    except Exception as e:
        print(f"[SCHEDULER] ERROR GENERAL en sincronización diaria: {str(e)}")

def run_scheduler():
    """
    Worker que ejecuta el scheduler en segundo plano
    """
    print("[SCHEDULER] Iniciando scheduler para sincronización diaria a las 00:00:00")

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

# --- FUNCIÓN DE ASIGNACIÓN DE STOCK DE PEDIDOS SECUENCIADOS ---
def _update_sequenced_sync_status(**values):
    with SEQUENCED_SYNC_STATUS_LOCK:
        SEQUENCED_SYNC_STATUS.update(values)


def recalculate_assigned_stock_once():
    """Recalcula AssignedStock/AssignedStockBeam usando conexiones activas.

    La función es deliberadamente síncrona para que el worker, el arranque y
    las sincronizaciones manuales compartan exactamente el mismo cálculo.
    Todas las operaciones que usan un cursor permanecen dentro de su ``with``;
    esto evita reutilizar un cursor después de cerrar la conexión ODBC.
    """
    started_at = time.time()

    with PEDIDOS_DB_LOCK:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
            if conn_main is None:
                raise RuntimeError('No se pudo conectar a DataLakeSCCZ para leer pedidos secuenciados')

            cursor_main = conn_main.cursor()
            cursor_main.execute("""
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
                    ps.PriorityOrder
                FROM OB.PedidosSecuenciados ps
                INNER JOIN OB.PedidosCabecera pc
                    ON ps.NumeroPedido = pc.NumeroPedido
                INNER JOIN OB.PedidosLineas pl
                    ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
                   AND ps.Assy = pl.Cod_Producto_Externo
                ORDER BY
                    CASE WHEN ps.PriorityOrder IS NULL THEN 1 ELSE 0 END,
                    ps.PriorityOrder ASC,
                    TRY_CONVERT(int, SUBSTRING(
                        ps.SequenceValue,
                        CHARINDEX('-', ps.SequenceValue) + 1,
                        100
                    )) ASC,
                    ps.SequenceValue ASC
            """)
            pedidos_actuales = cursor_main.fetchall()

        # MAPEX se consulta con otra conexión; nunca se mantiene abierto el
        # cursor de DataLake mientras se recorren las líneas de MAPEX.
        updates_univalmapex = []
        mapex_values = {}
        pedidos_terminales = set()
        with ConexionODBCCZ(database='mapexbp') as conn_cz:
            if conn_cz is None:
                raise RuntimeError('No se pudo conectar a mapexbp para actualizar UniValMapex')

            cursor_cz = conn_cz.cursor()
            for pedido in pedidos_actuales:
                numero_pedido = pedido.NumeroPedido
                assy = pedido.Assy
                cursor_cz.execute("""
                    WITH UltimaCabecera AS (
                        SELECT TOP 1
                            A.id_his_wam_pedido_cliente,
                            A.EstadoERP,
                            A.Id_wam_estado_pedido_cliente
                        FROM his_wam_pedido_cliente A
                        WHERE A.NumeroPedido = ?
                        ORDER BY A.id_his_wam_pedido_cliente DESC
                    )
                    SELECT TOP 1
                        uc.EstadoERP,
                        uc.Id_wam_estado_pedido_cliente,
                        SUM(ISNULL(B.UniValMapex, 0)) AS UniValMapex,
                        SUM(ISNULL(B.UnidadesPedidas, 0)) AS UnidadesPedidas,
                        SUM(ISNULL(B.UnidadesServidas, 0)) AS UnidadesServidas
                    FROM UltimaCabecera uc
                    JOIN his_wam_linea_pedido_cliente B
                        ON B.id_his_wam_pedido_cliente = uc.id_his_wam_pedido_cliente
                    JOIN V_Cfg_producto C ON C.Id_producto = B.Id_producto
                    WHERE C.Cod_producto = ?
                    GROUP BY uc.EstadoERP, uc.Id_wam_estado_pedido_cliente
                """, (numero_pedido, assy))
                row = cursor_cz.fetchone()
                if not row:
                    continue

                mapex_key = (str(numero_pedido).strip(), str(assy).strip())
                estado_erp = row.EstadoERP
                estado_wam = row.Id_wam_estado_pedido_cliente
                uni_val_mapex = row.UniValMapex or 0
                unidades_pedidas_mapex = row.UnidadesPedidas or 0
                unidades_servidas = row.UnidadesServidas or 0
                mapex_values[mapex_key] = uni_val_mapex

                if is_terminal_mapex_order(
                    estado_erp,
                    estado_wam,
                    unidades_pedidas_mapex,
                    unidades_servidas,
                ):
                    pedidos_terminales.add((numero_pedido, assy))
                    continue

                if pedido.UniValMapex != uni_val_mapex:
                    updates_univalmapex.append((uni_val_mapex, pedido.ID_PedidoLinea_Externa))

        pedidos_actuales = [
            pedido for pedido in pedidos_actuales
            if (pedido.NumeroPedido, pedido.Assy) not in pedidos_terminales
        ]

        updates_necesarios = []
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
            if conn_main is None:
                raise RuntimeError('No se pudo conectar a DataLakeSCCZ para actualizar stock asignado')

            cursor_main = conn_main.cursor()

            if pedidos_terminales:
                cursor_main.executemany(
                    "DELETE FROM OB.PedidosSecuenciados WHERE NumeroPedido = ? AND Assy = ?",
                    list(pedidos_terminales),
                )

            if updates_univalmapex:
                cursor_main.executemany(
                    "UPDATE OB.PedidosLineas SET UniValMapex = ? WHERE ID_PedidoLinea_Externa = ?",
                    updates_univalmapex,
                )

            cursor_main.execute("SELECT Cod_producto, StockActual FROM OB.Stock_Omegas_New")
            stock_disponible = {
                str(row.Cod_producto).strip(): (row.StockActual or 0)
                for row in cursor_main.fetchall()
            }

            cursor_main.execute("SELECT Cod_producto, StockActual FROM OB.Stock_Beams_New")
            stock_beams = {
                str(row.Cod_producto).strip(): (row.StockActual or 0)
                for row in cursor_main.fetchall()
            }

            for pedido in pedidos_actuales:
                assy_key = str(pedido.Assy).strip()
                beam_key = str(pedido.Beam).strip() if pedido.Beam else ''
                uni_val_mapex = mapex_values.get(
                    (str(pedido.NumeroPedido).strip(), assy_key),
                    pedido.UniValMapex or 0,
                )
                stock_actual_para_assy = stock_disponible.get(assy_key, 0)
                stock_actual_para_beam = stock_beams.get(beam_key, 0) if beam_key else 0
                cantidad_necesaria = (pedido.UnidadesPedidas or 0) - uni_val_mapex
                cantidad_necesaria_beam = pedido.UnidadesPedidas or 0

                nuevo_stock_asignado_assy = 0
                if cantidad_necesaria > 0 and stock_actual_para_assy > 0:
                    nuevo_stock_asignado_assy = min(cantidad_necesaria, stock_actual_para_assy)
                    stock_disponible[assy_key] = max(0, stock_actual_para_assy - nuevo_stock_asignado_assy)

                nuevo_stock_asignado_beam = 0
                if beam_key and cantidad_necesaria_beam > 0 and stock_actual_para_beam > 0:
                    nuevo_stock_asignado_beam = min(cantidad_necesaria_beam, stock_actual_para_beam)
                    stock_beams[beam_key] = max(0, stock_actual_para_beam - nuevo_stock_asignado_beam)

                viejo_assy = pedido.AssignedStock if pedido.AssignedStock is not None else 0
                viejo_beam = pedido.AssignedStockBeam if pedido.AssignedStockBeam is not None else 0
                if nuevo_stock_asignado_assy != viejo_assy or nuevo_stock_asignado_beam != viejo_beam:
                    updates_necesarios.append((
                        nuevo_stock_asignado_assy,
                        nuevo_stock_asignado_beam,
                        pedido.NumeroPedido,
                        pedido.Assy,
                    ))

            if updates_necesarios:
                cursor_main.executemany(
                    """UPDATE OB.PedidosSecuenciados
                       SET AssignedStock = ?, AssignedStockBeam = ?
                       WHERE NumeroPedido = ? AND Assy = ?""",
                    updates_necesarios,
                )

    if pedidos_terminales or updates_univalmapex or updates_necesarios:
        clear_endpoint_response_cache(
            'pedidos_secuenciados_c',
            'pedidos_secuenciados_c_trazabilidad',
            'pedidos_secuenciados_w',
            'pedidos_picking',
            'pedidos_tb',
        )

    result = {
        'processed_lines': len(pedidos_actuales),
        'updated_lines': len(updates_necesarios),
        'terminal_lines': len(pedidos_terminales),
        'mapex_updates': len(updates_univalmapex),
        'duration_seconds': round(time.time() - started_at, 3),
    }
    logging.info(
        '[AUTO-SYNC] Stock asignado: procesadas=%s actualizadas=%s terminales=%s mapex=%s duración=%.3fs',
        result['processed_lines'], result['updated_lines'], result['terminal_lines'],
        result['mapex_updates'], result['duration_seconds'],
    )
    return result


def auto_sync_sequenced():
    print('[AUTO-SYNC] Servicio de actualización incremental de pedidos secuenciados iniciado.')
    while True:
        started_at = time.time()
        _update_sequenced_sync_status(running=True, last_started_at=started_at, last_error=None)
        try:
            result = recalculate_assigned_stock_once()
            _update_sequenced_sync_status(
                running=False,
                last_completed_at=time.time(),
                **{key: result[key] for key in (
                    'processed_lines', 'updated_lines', 'terminal_lines', 'mapex_updates'
                )},
            )
        except Exception as error:
            _update_sequenced_sync_status(
                running=False,
                last_completed_at=time.time(),
                last_error=type(error).__name__,
            )
            logging.exception('[AUTO-SYNC] Error en el recálculo de stock asignado.')

        time.sleep(AUTO_SYNC_SEQUENCED_INTERVAL_SECONDS)


@app.route('/api/diagnostics/sequenced-sync', methods=['GET'])
@cross_origin()
def sequenced_sync_diagnostics():
    """Estado no sensible del worker de asignación de stock."""
    with SEQUENCED_SYNC_STATUS_LOCK:
        return jsonify(dict(SEQUENCED_SYNC_STATUS)), 200

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
def auto_sync_beams_stock():
    """
    Lanza periódicamente el procedimiento SQL de sincronización de Beams.
    La lógica incremental vive en SQL Server para mantener el mismo patrón que Omegas.
    """
    intervalo_segundos = 15
    print('[AUTO-SYNC BEAMS] Servicio de sincronización SQL de stock de Beams iniciado.')

    while True:
        try:
            # Serializar la sincronización de movimientos de Beam con el
            # recálculo de AssignedStock para evitar leer un stock intermedio.
            with PEDIDOS_DB_LOCK:
                with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                    if conn_main is None:
                        raise Exception('No se pudo conectar a DataLakeSCCZ')

                    cursor_main = conn_main.cursor()
                    cursor_main.execute("{CALL OB.sp_Sync_Beams_RawData}")

            print(f"[AUTO-SYNC BEAMS] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: sincronización SQL completada.")
        except Exception as e:
            logging.exception('[AUTO-SYNC BEAMS] Falló la ejecución de OB.sp_Sync_Beams_RawData.')

        time.sleep(intervalo_segundos)


# ====================================================================================
# NUEVA FUNCIÓN: STOCK WATCHDOG — Detecta stock negativo en tiempo real
# ====================================================================================
def stock_watchdog_loop():
    """
    Hilo de vigilancia que inspecciona periódicamente las vistas de stock.
    Si detecta stock negativo, registra un snapshot completo del contexto
    (últimas producciones, últimos consumos, marcas de agua) para diagnóstico.
    """
    intervalo_segundos = 30
    stock_logger.info("Iniciando Watchdog de Stock...")
    print("[STOCK-WATCHDOG] Servicio de vigilancia de stock iniciado (intervalo: 30s).")

    while True:
        try:
            with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                if conn_main is None:
                    time.sleep(intervalo_segundos)
                    continue

                cursor = conn_main.cursor()

                # ─── 1. Comprobar Beams negativos ───
                cursor.execute("""
                    SELECT Cod_producto, StockActual, Entradas, Salidas
                    FROM OB.Stock_Beams_New
                    WHERE StockActual < 0
                """)
                beams_negativos = cursor.fetchall()

                for row in beams_negativos:
                    cod_producto = row.Cod_producto
                    stock_actual = row.StockActual
                    entradas = row.Entradas
                    salidas = row.Salidas

                    # Extraer el contexto de este Beam específico
                    cursor.execute("""
                        SELECT TOP 3 WorkGroup, Fecha_inicio, Fecha_fin, Unidades_OK
                        FROM OB.Beams_Produccion
                        WHERE Cod_producto = ? ORDER BY Fecha_fin DESC
                    """, (cod_producto,))
                    ultimas_prods = cursor.fetchall()

                    cursor.execute("""
                        SELECT TOP 3 WorkGroup, Fecha_inicio, Fecha_fin, Unidades_OK
                        FROM OB.Beams_Consumos
                        WHERE Cod_producto = ? ORDER BY Fecha_fin DESC
                    """, (cod_producto,))
                    ultimos_cons = cursor.fetchall()

                    cursor.execute("""
                        SELECT Fuente, Last_Sync_Date
                        FROM OB.Last_Sync_Beams
                        WHERE Cod_producto = ?
                    """, (cod_producto,))
                    last_syncs = cursor.fetchall()

                    stock_logger.error(
                        f"ANOMALÍA DETECTADA (BEAM): '{cod_producto}' tiene stock {stock_actual} "
                        f"(Entradas: {entradas} | Salidas: {salidas}).\n"
                        f"    Últimas producciones: {[(p.WorkGroup, p.Fecha_inicio, p.Fecha_fin, p.Unidades_OK) for p in ultimas_prods]}\n"
                        f"    Últimos consumos:     {[(c.WorkGroup, c.Fecha_inicio, c.Fecha_fin, c.Unidades_OK) for c in ultimos_cons]}\n"
                        f"    Marcas Last_Sync:     {[(s.Fuente, s.Last_Sync_Date) for s in last_syncs]}"
                    )

                # ─── 2. Comprobar Omegas negativos ───
                cursor.execute("""
                    SELECT Cod_producto, StockActual
                    FROM OB.Stock_Omegas_New
                    WHERE StockActual < 0
                """)
                omegas_negativos = cursor.fetchall()

                for row in omegas_negativos:
                    cod_producto = row.Cod_producto
                    stock_actual = row.StockActual

                    # Investigar si la lectura ocurrió antes que la producción
                    cursor.execute("""
                        SELECT TOP 3 fecha, numero_serie, id_operario
                        FROM OB.Omegas_Lecturas
                        WHERE producto = ? ORDER BY fecha DESC
                    """, (cod_producto,))
                    ultimas_lec = cursor.fetchall()

                    cursor.execute("""
                        SELECT TOP 3 WorkGroup, Fecha_inicio, Fecha_fin, Unidades_OK
                        FROM OB.Omegas_Produccion
                        WHERE Cod_producto = ? ORDER BY Fecha_fin DESC
                    """, (cod_producto,))
                    ultimas_prod = cursor.fetchall()

                    cursor.execute("""
                        SELECT Fuente, Last_Sync_Date
                        FROM OB.Last_Sync_omegas
                        WHERE Cod_producto = ?
                    """, (cod_producto,))
                    last_syncs = cursor.fetchall()

                    # Detectar patrón: consumo antes que producción
                    fecha_ultima_lec = ultimas_lec[0].fecha if ultimas_lec else None
                    fecha_ultima_prod = ultimas_prod[0].Fecha_fin if ultimas_prod else None
                    desfase = ""
                    if fecha_ultima_lec and fecha_ultima_prod and fecha_ultima_lec > fecha_ultima_prod:
                        desfase = f" (LECTURA {fecha_ultima_lec} POSTERIOR a PRODUCCIÓN {fecha_ultima_prod} — posible consumo antes de reportar producción)"

                    stock_logger.error(
                        f"ANOMALÍA DETECTADA (OMEGA): '{cod_producto}' tiene stock {stock_actual}.\n"
                        f"    Últimas lecturas:   {[(l.fecha, l.numero_serie) for l in ultimas_lec]}\n"
                        f"    Últimas producciones: {[(p.WorkGroup, p.Fecha_inicio, p.Fecha_fin, p.Unidades_OK) for p in ultimas_prod]}\n"
                        f"    Marcas Last_Sync:    {[(s.Fuente, s.Last_Sync_Date) for s in last_syncs]}"
                        f"{desfase}"
                    )

        except Exception as e:
            stock_logger.exception(f"Error en la ejecución del bucle Watchdog: {str(e)}")

        time.sleep(intervalo_segundos)


# ====================================================================================
# NUEVA FUNCIÓN: LIMPIAR PEDIDOS SECUENCIADOS QUE YA NO CUMPLEN CRITERIOS
# ====================================================================================
def cleanup_sequenced_orders_legacy():
    """
    Función que elimina de PedidosSecuenciados los registros cuyo estado ha cambiado
    en MAPEX (ya no son pendientes o han sido completados).
    Se ejecuta cada 30 segundos.
    """
    print('[CLEANUP] Servicio de limpieza de pedidos secuenciados iniciado.')
    
    while True:
        try:
            with PEDIDOS_DB_LOCK:
                with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                    cursor_main = conn_main.cursor()
                
                # 1. Obtener todos los pedidos secuenciados
                cursor_main.execute("""
                    SELECT 
                        ps.NumeroPedido, 
                        ps.Assy
                    FROM OB.PedidosSecuenciados ps
                """)
                pedidos_secuenciados = cursor_main.fetchall()
                
                if not pedidos_secuenciados:
                    print("[CLEANUP] No hay pedidos secuenciados para verificar.")
                    time.sleep(CLEANUP_SEQUENCED_INTERVAL_SECONDS)
                    continue
                
                # 2. Verificar cada uno directamente en MAPEX
                pedidos_a_eliminar = []
                
                with ConexionODBCCZ(database='mapexbp') as conn_cz:
                    cursor_cz = conn_cz.cursor()
                    
                    for pedido in pedidos_secuenciados:
                        numero_pedido = pedido[0]
                        assy = pedido[1]

                        cursor_cz.execute("""
                            WITH UltimaCabecera AS (
                                SELECT TOP 1
                                    A.id_his_wam_pedido_cliente,
                                    A.EstadoERP,
                                    A.Id_wam_estado_pedido_cliente
                                FROM his_wam_pedido_cliente A
                                WHERE A.NumeroPedido = ?
                                ORDER BY A.id_his_wam_pedido_cliente DESC
                            )
                            SELECT TOP 1
                                uc.EstadoERP,
                                uc.Id_wam_estado_pedido_cliente,
                                SUM(ISNULL(B.UnidadesPedidas, 0)) AS UnidadesPedidas,
                                SUM(ISNULL(B.UnidadesServidas, 0)) AS UnidadesServidas
                            FROM UltimaCabecera uc
                            JOIN his_wam_linea_pedido_cliente B ON B.id_his_wam_pedido_cliente = uc.id_his_wam_pedido_cliente
                            JOIN V_Cfg_producto C ON C.Id_producto = B.Id_producto
                            WHERE C.Cod_producto = ?
                            GROUP BY uc.EstadoERP, uc.Id_wam_estado_pedido_cliente
                        """, (numero_pedido, assy))
                        row = cursor_cz.fetchone()
                        
                        if not row:
                            # No encontrado en MAPEX: NO eliminar, puede ser un fallo de JOIN o de conexión
                            print(f"[CLEANUP] Pedido {numero_pedido}/{assy} no encontrado en MAPEX - Se omite (no se elimina)")
                            continue

                        estado_erp = row[0] if row[0] is not None else 0
                        estado_wam = row[1] if row[1] is not None else 0
                        unidades_pedidas_mapex = row[2] if row[2] is not None else 0
                        unidades_servidas = row[3] if row[3] is not None else 0

                        # Si la última cabecera ya no está pendiente en MAPEX, debemos retirar la secuencia.
                        if is_terminal_mapex_order(
                            estado_erp,
                            estado_wam,
                            unidades_pedidas_mapex,
                            unidades_servidas,
                        ):
                            print(
                                f"[CLEANUP] ⚠ Pedido {numero_pedido}/{assy} con estado final en MAPEX "
                                f"(EstadoERP={estado_erp}, WAM={estado_wam}) - Se eliminará"
                            )
                            pedidos_a_eliminar.append((numero_pedido, assy))
                            continue
                
                # 3. Eliminar los pedidos que ya no cumplen criterios
                if pedidos_a_eliminar:
                    for numero_pedido, assy in pedidos_a_eliminar:
                        try:
                            cursor_main.execute(
                                "DELETE FROM OB.PedidosSecuenciados WHERE NumeroPedido = ? AND Assy = ?",
                                (numero_pedido, assy)
                            )
                            print(f"[CLEANUP] ✓ Eliminado: {numero_pedido} / {assy}")
                        except Exception as e:
                            print(f"[CLEANUP] ERROR al eliminar {numero_pedido}/{assy}: {e}")
                    
                    print(f"[CLEANUP] Total eliminados: {len(pedidos_a_eliminar)} pedidos")
                else:
                    print("[CLEANUP] No hay pedidos para limpiar en este ciclo")
                    
        except Exception as e:
            print(f"[CLEANUP] ERROR GENERAL: {str(e)}")
        
        time.sleep(CLEANUP_SEQUENCED_INTERVAL_SECONDS)


# ====================================================================================
# NUEVO WORKER: LIMPIAR PEDIDOS VIEJOS NO SECUENCIADOS (>7 días y EstadoERP != 0)
# ====================================================================================
_sequenced_cleanup_status_lock = threading.Lock()
_sequenced_cleanup_status = {
    'running': False,
    'last_started_at': None,
    'last_completed_at': None,
    'last_error': None,
    'checked_lines': 0,
    'terminal_lines_found': 0,
    'deleted_lines': 0,
}


def _update_sequenced_cleanup_status(**values):
    """Store a non-sensitive health snapshot for the cleanup worker."""
    with _sequenced_cleanup_status_lock:
        _sequenced_cleanup_status.update(values)


def _get_latest_mapex_line_states(cursor, order_numbers, batch_size=250):
    """Fetch current MAPEX order/product states in batches instead of per line."""
    states = {}
    for start in range(0, len(order_numbers), batch_size):
        batch = order_numbers[start:start + batch_size]
        placeholders = ','.join('?' for _ in batch)
        cursor.execute(f"""
            WITH LatestOrder AS (
                SELECT A.NumeroPedido, A.id_his_wam_pedido_cliente, A.EstadoERP,
                       A.Id_wam_estado_pedido_cliente,
                       ROW_NUMBER() OVER (
                           PARTITION BY A.NumeroPedido
                           ORDER BY A.id_his_wam_pedido_cliente DESC
                       ) AS RowNumber
                FROM his_wam_pedido_cliente A
                WHERE A.NumeroPedido IN ({placeholders})
            )
            SELECT LTRIM(RTRIM(lo.NumeroPedido)) AS NumeroPedido,
                   LTRIM(RTRIM(product.Cod_producto)) AS Assy,
                   lo.EstadoERP, lo.Id_wam_estado_pedido_cliente,
                   SUM(ISNULL(line.UnidadesPedidas, 0)) AS UnidadesPedidas,
                   SUM(ISNULL(line.UnidadesServidas, 0)) AS UnidadesServidas
            FROM LatestOrder lo
            INNER JOIN his_wam_linea_pedido_cliente line
                ON line.id_his_wam_pedido_cliente = lo.id_his_wam_pedido_cliente
            INNER JOIN V_Cfg_producto product ON product.Id_producto = line.Id_producto
            WHERE lo.RowNumber = 1
            GROUP BY LTRIM(RTRIM(lo.NumeroPedido)),
                     LTRIM(RTRIM(product.Cod_producto)),
                     lo.EstadoERP, lo.Id_wam_estado_pedido_cliente
        """, batch)
        for row in cursor.fetchall():
            key = (str(row.NumeroPedido).strip(), str(row.Assy).strip())
            current = (row.EstadoERP, row.Id_wam_estado_pedido_cliente,
                       row.UnidadesPedidas, row.UnidadesServidas)
            previous = states.get(key)
            # After aggregation, keep only the first row defensively.
            if previous is None:
                states[key] = current
    return states


def audit_sequenced_orders_against_mapex(detail_limit=0):
    """Classify the current sequencer contents using the same MAPEX logic.

    This is deliberately read-only: it is suitable for local verification
    against real databases and shares the production cleanup decision path.
    """
    with PEDIDOS_DB_LOCK:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
            cursor_main = conn_main.cursor()
            cursor_main.execute("""
                SELECT LTRIM(RTRIM(NumeroPedido)) AS NumeroPedido,
                       LTRIM(RTRIM(Assy)) AS Assy
                FROM OB.PedidosSecuenciados
            """)
            sequenced_lines = cursor_main.fetchall()

        order_numbers = sorted({str(row.NumeroPedido).strip() for row in sequenced_lines})
        mapex_states = {}
        if order_numbers:
            with ConexionODBCCZ(database='mapexbp') as conn_mapex:
                mapex_states = _get_latest_mapex_line_states(
                    conn_mapex.cursor(), order_numbers
                )

    terminal_lines = []
    pending_lines = []
    missing_lines = []
    for line in sequenced_lines:
        key = (str(line.NumeroPedido).strip(), str(line.Assy).strip())
        state = mapex_states.get(key)
        if state is None:
            missing_lines.append(key)
        elif is_terminal_mapex_order(*state):
            terminal_lines.append(key)
        else:
            pending_lines.append(key)

    result = {
        'mode': 'read_only',
        'checked_lines': len(sequenced_lines),
        'checked_orders': len(order_numbers),
        'terminal_lines_would_delete': len(terminal_lines),
        'pending_lines': len(pending_lines),
        'missing_in_mapex_lines': len(missing_lines),
    }
    if detail_limit:
        limit = max(1, min(int(detail_limit), 100))
        result['terminal_line_samples'] = [
            {'sales_order': order_number, 'assy': assy}
            for order_number, assy in terminal_lines[:limit]
        ]
        result['pending_line_samples'] = [
            {'sales_order': order_number, 'assy': assy}
            for order_number, assy in pending_lines[:limit]
        ]
    return result


def cleanup_sequenced_orders():
    """Remove MAPEX-terminal sequenced lines with observable batch processing."""
    logging.info('[CLEANUP] Sequenced-order cleanup worker started.')
    while True:
        # El lector de la pantalla, las sincronizaciones y el limpiador antiguo
        # pueden mantener PEDIDOS_DB_LOCK durante bastante tiempo. La limpieza
        # solo borra por clave exacta líneas ya terminales en MAPEX, por lo que no
        # debe quedar bloqueada detrás de esos procesos durante todo su ciclo.
        if not SEQUENCED_CLEANUP_LOCK.acquire(blocking=False):
            logging.info('[CLEANUP] Previous cleanup cycle is still active; skipping overlap.')
            time.sleep(CLEANUP_SEQUENCED_INTERVAL_SECONDS)
            continue

        started_at = time.time()
        _update_sequenced_cleanup_status(running=True, last_started_at=started_at,
                                         last_error=None)
        try:
            with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                cursor_main = conn_main.cursor()
                cursor_main.execute("""
                    SELECT LTRIM(RTRIM(NumeroPedido)) AS NumeroPedido,
                           LTRIM(RTRIM(Assy)) AS Assy
                    FROM OB.PedidosSecuenciados WITH (NOLOCK)
                """)
                sequenced_lines = cursor_main.fetchall()

            terminal_lines = []
            missing_lines = 0
            if sequenced_lines:
                order_numbers = sorted({str(row.NumeroPedido).strip() for row in sequenced_lines})
                with ConexionODBCCZ(database='mapexbp') as conn_mapex:
                    mapex_states = _get_latest_mapex_line_states(
                        conn_mapex.cursor(), order_numbers
                    )
                for line in sequenced_lines:
                    key = (str(line.NumeroPedido).strip(), str(line.Assy).strip())
                    state = mapex_states.get(key)
                    if state is None:
                        missing_lines += 1
                    elif is_terminal_mapex_order(*state):
                        terminal_lines.append(key)

            deleted_lines = 0
            if terminal_lines:
                # La PK es (NumeroPedido, Assy). executemany limita el tramo de
                # escritura a una operación corta y no bloquea la consulta MAPEX.
                with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                    cursor_main = conn_main.cursor()
                    cursor_main.executemany(
                        'DELETE FROM OB.PedidosSecuenciados WHERE NumeroPedido = ? AND Assy = ?',
                        terminal_lines,
                    )
                    deleted_lines = len(terminal_lines)
                clear_endpoint_response_cache()

            completed_at = time.time()
            _update_sequenced_cleanup_status(
                running=False, last_completed_at=completed_at,
                checked_lines=len(sequenced_lines),
                terminal_lines_found=len(terminal_lines),
                deleted_lines=deleted_lines,
            )
            logging.info(
                '[CLEANUP] Cycle complete: checked=%s terminal=%s deleted=%s missing_in_mapex=%s duration=%.2fs',
                len(sequenced_lines), len(terminal_lines), deleted_lines,
                missing_lines, completed_at - started_at,
            )
        except Exception as error:
            _update_sequenced_cleanup_status(
                running=False, last_completed_at=time.time(), last_error=type(error).__name__,
            )
            logging.exception('[CLEANUP] Cycle failed before completion.')
        finally:
            SEQUENCED_CLEANUP_LOCK.release()
        time.sleep(CLEANUP_SEQUENCED_INTERVAL_SECONDS)


@app.route('/api/diagnostics/sequenced-cleanup', methods=['GET'])
@cross_origin()
def sequenced_cleanup_diagnostics():
    """Expose a non-sensitive cleanup health snapshot for monitoring."""
    with _sequenced_cleanup_status_lock:
        return jsonify(dict(_sequenced_cleanup_status)), 200


@app.route('/api/diagnostics/sequenced-cleanup/audit', methods=['GET'])
@cross_origin()
def sequenced_cleanup_audit():
    """Run the MAPEX cleanup decision path without deleting any line."""
    try:
        detail_limit = request.args.get('detail_limit', default=0, type=int)
        result = audit_sequenced_orders_against_mapex(detail_limit=detail_limit)
        logging.info(
            '[CLEANUP-AUDIT] checked=%s terminal=%s pending=%s missing=%s',
            result['checked_lines'], result['terminal_lines_would_delete'],
            result['pending_lines'], result['missing_in_mapex_lines'],
        )
        return jsonify(result), 200
    except Exception as error:
        logging.exception('[CLEANUP-AUDIT] Read-only audit failed.')
        return jsonify({'error': 'sequenced_cleanup_audit_failed', 'type': type(error).__name__}), 503


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
            with PEDIDOS_DB_LOCK:
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

                # NUEVO: Verificar en MAPEX el estado ACTUAL de TODOS los pedidos locales,
                # independientemente de su FechaEntrega. Detecta pedidos completados/entregados
                # (EstadoERP != 0 o Id_wam_estado_pedido_cliente IN (2,3,4)) que aún permanecen
                # en nuestra base de datos porque no cumplían el criterio de >7 días.
                cursor_main.execute("""
                    SELECT pc.ID_PedidoCabecera_Externa, pc.NumeroPedido
                    FROM OB.PedidosCabecera pc
                """)
                todos_pedidos_locales = cursor_main.fetchall()

                if todos_pedidos_locales:
                    ids_para_verificar = [row[0] for row in todos_pedidos_locales]

                    with ConexionODBCCZ(database='mapexbp') as conn_cz2:
                        cursor_cz2 = conn_cz2.cursor()
                        placeholders_ids = ','.join(['?' for _ in ids_para_verificar])
                        cursor_cz2.execute(f"""
                            SELECT id_his_wam_pedido_cliente, EstadoERP, Id_wam_estado_pedido_cliente
                            FROM his_wam_pedido_cliente
                            WHERE id_his_wam_pedido_cliente IN ({placeholders_ids})
                        """, ids_para_verificar)
                        estados_en_mapex = {row[0]: (row[1], row[2]) for row in cursor_cz2.fetchall()}

                    for id_cabecera_externa, numero_pedido in todos_pedidos_locales:
                        # Evitar procesar los ya marcados para eliminar
                        if (id_cabecera_externa, numero_pedido) in cabeceras_a_eliminar:
                            continue
                        estado = estados_en_mapex.get(id_cabecera_externa)
                        if not estado:
                            continue
                        estado_erp, estado_wam = estado
                        # ERP: 3=COMPLETADO, 4=CANCELADO. WAM: 3=FINALIZADA,
                        # 4=CANCELADO. El estado 2 es EN CURSO y sigue activo.
                        if estado_erp in (3, 4) or estado_wam in (3, 4):
                            if numero_pedido not in pedidos_secuenciados:
                                print(f"[CLEANUP-OLD] Pedido {numero_pedido} completado en MAPEX "
                                      f"(EstadoERP={estado_erp}, WAM={estado_wam}) - Se eliminará")
                                cabeceras_a_eliminar.append((id_cabecera_externa, numero_pedido))
                            else:
                                print(f"[CLEANUP-OLD] Pedido {numero_pedido} completado en MAPEX "
                                      f"(EstadoERP={estado_erp}, WAM={estado_wam}) pero ESTÁ SECUENCIADO - Se conserva")

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
        
        time.sleep(CLEANUP_OLD_UNSEQUENCED_INTERVAL_SECONDS)


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
            cursor.execute("SELECT * FROM OB.V_PedidosSummary_Pendientes_EX")
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
    inicio = time.time()
    VIEW_LOGGER.info("=== INICIO: GET /api/summary/sequenced ===")
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            
            # Usar la vista wrapper que ya incluye EX y TB
            query = """
                SELECT * 
                FROM OB.V_PedidosSummary_Secuenciados_Full WITH (NOLOCK)
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
            
            duracion = time.time() - inicio
            cantidad = len(result)
            
            if cantidad == 0:
                VIEW_LOGGER.warning(f"⚠️ ADVERTENCIA: Vista retornó 0 registros | Duración: {duracion:.3f}s")
            else:
                VIEW_LOGGER.info(f"✓ Vista retornó {cantidad} registros | Duración: {duracion:.3f}s")
            
            VIEW_LOGGER.info("=== FIN: GET /api/summary/sequenced ===\n")
            
            return jsonify(result)

    except pyodbc.Error as db_err:
        duracion = time.time() - inicio
        VIEW_LOGGER.error(f"❌ ERROR SQL: {str(db_err)} | Duración: {duracion:.3f}s")
        logging.error(f"Error de base de datos en /api/summary/sequenced: {db_err}")
        return jsonify({'error': "Error de base de datos", "details": str(db_err)}), 500
    except Exception as e:
        duracion = time.time() - inicio
        VIEW_LOGGER.error(f"❌ ERROR INESPERADO: {str(e)} | Duración: {duracion:.3f}s")
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

def normalize_wc_value(raw_value):
    if raw_value is None:
        return None
    normalized_value = str(raw_value).strip()
    if not normalized_value:
        return None
    if normalized_value.upper() == 'MS':
        return 'DS'
    if normalized_value.upper() == 'WIC':
        return 'CWI'
    return normalized_value


PEDIDOS_CABECERA_OPTIONAL_COLUMNS_CACHE = {}


def pedidos_cabecera_has_column(column_name):
    normalized_column = str(column_name).strip().upper()
    if not normalized_column:
        return False

    if PEDIDOS_CABECERA_OPTIONAL_COLUMNS_CACHE.get(normalized_column) is True:
        return True

    exists = False
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is not None:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT 1
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = 'OB'
                      AND TABLE_NAME = 'PedidosCabecera'
                      AND UPPER(COLUMN_NAME) = ?
                    """,
                    normalized_column,
                )
                exists = cursor.fetchone() is not None
    except Exception as exc:
        logging.error(f"Error comprobando columna {normalized_column} en OB.PedidosCabecera: {exc}")

    if exists:
        PEDIDOS_CABECERA_OPTIONAL_COLUMNS_CACHE[normalized_column] = True
    else:
        PEDIDOS_CABECERA_OPTIONAL_COLUMNS_CACHE.pop(normalized_column, None)
    return exists


def build_pedidos_cabecera_optional_select_sql(column_name, alias=None):
    safe_column = str(column_name).strip()
    safe_alias = alias or safe_column
    if pedidos_cabecera_has_column(safe_column):
        return f"ISNULL(pc.[{safe_column}], '') AS {safe_alias}"
    return f"'' AS {safe_alias}"


def normalize_component_quantity(raw_value):
    if raw_value is None:
        return 0
    if isinstance(raw_value, Decimal):
        return int(raw_value) if raw_value == raw_value.to_integral_value() else float(raw_value)
    if isinstance(raw_value, float):
        return int(raw_value) if raw_value.is_integer() else raw_value
    return raw_value


def scale_component_quantity(component_qty, order_qty):
    component_qty = normalize_component_quantity(component_qty)
    order_qty = normalize_component_quantity(order_qty)

    if component_qty in (None, '') or order_qty in (None, ''):
        return 0

    return normalize_component_quantity(component_qty * order_qty)


def scale_component_quantity_from_beam(component_qty, beam_component_qty, beam_order_qty):
    component_qty = normalize_component_quantity(component_qty)
    beam_component_qty = normalize_component_quantity(beam_component_qty)
    beam_order_qty = normalize_component_quantity(beam_order_qty)

    if component_qty in (None, '') or beam_component_qty in (None, '', 0) or beam_order_qty in (None, ''):
        return 0

    return normalize_component_quantity((component_qty / beam_component_qty) * beam_order_qty)


def format_if_quantity_display(if1, if2, if1_qty, if2_qty):
    if1_qty = normalize_component_quantity(if1_qty)
    if2_qty = normalize_component_quantity(if2_qty)

    if if1 and if2 and str(if1).strip() and str(if2).strip() and str(if1).strip() != str(if2).strip():
        return f"{if1_qty}/{if2_qty}"
    return if1_qty


def get_mapex_component_quantities_by_assy(assy_codes):
    cleaned_codes = sorted({str(code).strip() for code in (assy_codes or []) if code and str(code).strip()})
    if not cleaned_codes:
        return {}

    cached_quantities, missing_codes = get_cached_mapex_component_quantities(cleaned_codes)
    if not missing_codes:
        return cached_quantities

    placeholders = ','.join('?' for _ in missing_codes)
    query = f'''
        WITH target_assy AS (
            SELECT v.Id_producto, v.Cod_producto AS Assy
            FROM dbo.V_Cfg_producto v WITH (NOLOCK)
            WHERE v.Cod_producto IN ({placeholders})
        )
        SELECT
            target.Assy,
            component.Cod_producto AS ComponentCode,
            SUM(ISNULL(fp.Unidades, 0)) AS ComponentQty
        FROM target_assy target
        INNER JOIN dbo.cfg_fase fase WITH (NOLOCK)
            ON fase.Id_producto_final = target.Id_producto
        INNER JOIN dbo.cfg_fase_producto fp WITH (NOLOCK)
            ON fp.Id_fase = fase.Id_fase
        LEFT JOIN dbo.V_Cfg_producto component WITH (NOLOCK)
            ON component.Id_producto = fp.Id_producto
        WHERE fp.EntradaSalida = 0
          AND component.Cod_producto IS NOT NULL
          AND LTRIM(RTRIM(component.Cod_producto)) <> ''
        GROUP BY target.Assy, component.Cod_producto
    '''

    quantities_by_assy = defaultdict(dict)
    for assy_code, component_quantities in cached_quantities.items():
        quantities_by_assy[assy_code].update(component_quantities)

    fetched_quantities = defaultdict(dict)

    try:
        with ConexionODBCCZ(database='mapexbp') as conn:
            if conn is None:
                logging.error('No se pudo conectar a MAPEX para resolver BeamQty/IFQty')
                return quantities_by_assy

            cursor = conn.cursor()
            cursor.execute(query, missing_codes)
            for assy, component_code, component_qty in cursor.fetchall():
                normalized_assy = str(assy).strip() if assy is not None else ''
                normalized_component = str(component_code).strip() if component_code is not None else ''
                if not normalized_assy or not normalized_component:
                    continue
                normalized_qty = normalize_component_quantity(component_qty)
                quantities_by_assy[normalized_assy][normalized_component] = normalized_qty
                fetched_quantities[normalized_assy][normalized_component] = normalized_qty

            for assy_code in missing_codes:
                fetched_quantities.setdefault(assy_code, {})

            set_cached_mapex_component_quantities(fetched_quantities)
    except Exception as exc:
        logging.error(f'Error obteniendo cantidades Beam/IF desde MAPEX: {exc}')

    return quantities_by_assy


def load_clinching_subomega_master_mapping():
    """Carga y cachea el mapeo Sub-Omega -> Beam + Guide Interface desde SQL Server."""
    now = time.time()
    with CLINCHING_MASTER_CACHE_LOCK:
        cached_timestamp = CLINCHING_MASTER_CACHE.get('timestamp', 0)
        cached_mapping = CLINCHING_MASTER_CACHE.get('mapping') or {}
        if cached_mapping and (now - cached_timestamp) <= CLINCHING_MASTER_CACHE_TTL_SECONDS:
            return cached_mapping

    mapping = {}
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                logging.error('No se pudo conectar a DataLakeSCCZ para cargar el master de clinching')
                return {}

            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT SubOmega, Beam, GuideInterface
                FROM OB.ClinchingSubOmegaMaster WITH (NOLOCK)
                WHERE IsActive = 1
                ORDER BY SubOmega ASC
                """
            )

            for subomega, beam, guide_interface in cursor.fetchall():
                subomega_code = str(subomega).strip() if subomega is not None else ''
                beam_code = str(beam).strip() if beam is not None else ''
                guide_code = str(guide_interface).strip() if guide_interface is not None else ''
                if not subomega_code or not beam_code or not guide_code:
                    continue
                mapping[subomega_code] = {
                    'Beam': beam_code,
                    'GuideInterface': guide_code,
                }
    except Exception as exc:
        logging.error(f'Error cargando master de clinching desde SQL: {exc}')
        return {}

    with CLINCHING_MASTER_CACHE_LOCK:
        CLINCHING_MASTER_CACHE['timestamp'] = now
        CLINCHING_MASTER_CACHE['mapping'] = mapping

    logging.info(f'[CLINCHING MASTER] Cargados {len(mapping)} Sub-Omegas desde SQL')
    return mapping


def enrich_clinching_orders_with_master_components(items):
    """Enriquece pedidos de clinching usando Sub-Omega master + cantidades desde MAPEX."""
    if not items:
        return items

    master_mapping = load_clinching_subomega_master_mapping()
    if not master_mapping:
        for item in items:
            item['SubOmega'] = str(item.get('Beam') or '').strip()
            item['SubOmegaQty'] = normalize_component_quantity(item.get('Qty', 0))
            item['ClinchingBeam'] = ''
            item['ClinchingBeamQty'] = 0
            item['GuideInterface'] = ''
            item['GuideInterfaceQty'] = 0
        return items

    subomega_codes = [str(item.get('Beam') or '').strip() for item in items]
    quantities_by_subomega = get_mapex_component_quantities_by_assy(subomega_codes)

    for item in items:
        subomega_code = str(item.get('Beam') or '').strip()
        item['SubOmega'] = subomega_code
        item['SubOmegaQty'] = normalize_component_quantity(item.get('Qty', 0))

        mapping = master_mapping.get(subomega_code, {})
        clinching_beam = mapping.get('Beam', '')
        guide_interface = mapping.get('GuideInterface', '')
        component_quantities = quantities_by_subomega.get(subomega_code, {})

        beam_component_qty = normalize_component_quantity(component_quantities.get(clinching_beam, 0)) if clinching_beam else 0
        guide_component_qty = normalize_component_quantity(component_quantities.get(guide_interface, 0)) if guide_interface else 0

        subomega_master_qty = beam_component_qty if beam_component_qty else 0
        subomega_order_qty = item['SubOmegaQty']

        item['ClinchingBeam'] = clinching_beam
        item['GuideInterface'] = guide_interface
        item['ClinchingBeamQty'] = scale_component_quantity_from_beam(beam_component_qty, subomega_master_qty, subomega_order_qty) if clinching_beam else 0
        item['GuideInterfaceQty'] = scale_component_quantity_from_beam(guide_component_qty, subomega_master_qty, subomega_order_qty) if guide_interface else 0

    return items


def enrich_orders_with_mapex_quantities(items):
    if not items:
        return items

    quantities_by_assy = get_mapex_component_quantities_by_assy(item.get('Assy') for item in items)

    for item in items:
        assy = str(item.get('Assy') or '').strip()
        component_quantities = quantities_by_assy.get(assy, {})
        order_qty = normalize_component_quantity(item.get('Qty', 0))

        beam_code = str(item.get('Beam') or '').strip()
        if1_code = str(item.get('IF1') or '').strip()
        if2_code = str(item.get('IF2') or '').strip()
        beam_component_qty = normalize_component_quantity(component_quantities.get(beam_code, 0)) if beam_code else 0

        beam_qty = order_qty if beam_code else 0
        if1_qty = scale_component_quantity_from_beam(component_quantities.get(if1_code, 0), beam_component_qty, beam_qty) if if1_code else 0
        if2_qty = scale_component_quantity_from_beam(component_quantities.get(if2_code, 0), beam_component_qty, beam_qty) if if2_code else 0

        item['BeamQty'] = beam_qty
        item['IF1Qty'] = if1_qty
        item['IF2Qty'] = if2_qty
        item['IFQty'] = format_if_quantity_display(if1_code, if2_code, if1_qty, if2_qty)

    return items


def get_mapex_served_quantities_by_order_assy(items):
    """Devuelve las unidades servidas en MAPEX por pedido y producto Omega.

    UnidadesServidas es el avance de picking/servicio; UniValMapex representa
    producción y no debe usarse para retirar filas de la pantalla de Picking.
    """
    order_numbers = sorted({
        str(item.get('SalesOrder') or '').strip()
        for item in (items or [])
        if str(item.get('SalesOrder') or '').strip()
    })
    if not order_numbers:
        return {}

    served_by_order_assy = {}
    with ConexionODBCCZ(database='mapexbp') as conn:
        if conn is None:
            raise RuntimeError('No se pudo conectar a MAPEX para consultar unidades servidas')
        cursor = conn.cursor()
        for start in range(0, len(order_numbers), 250):
            batch = order_numbers[start:start + 250]
            placeholders = ','.join('?' for _ in batch)
            cursor.execute(f"""
                WITH LatestOrder AS (
                    SELECT A.NumeroPedido, A.id_his_wam_pedido_cliente,
                           ROW_NUMBER() OVER (
                               PARTITION BY A.NumeroPedido
                               ORDER BY A.id_his_wam_pedido_cliente DESC
                           ) AS RowNumber
                    FROM his_wam_pedido_cliente A
                    WHERE A.NumeroPedido IN ({placeholders})
                )
                SELECT LTRIM(RTRIM(lo.NumeroPedido)) AS SalesOrder,
                       LTRIM(RTRIM(product.Cod_producto)) AS Assy,
                       SUM(ISNULL(line.UnidadesServidas, 0)) AS UnidadesServidas
                FROM LatestOrder lo
                INNER JOIN his_wam_linea_pedido_cliente line
                    ON line.id_his_wam_pedido_cliente = lo.id_his_wam_pedido_cliente
                INNER JOIN V_Cfg_producto product ON product.Id_producto = line.Id_producto
                WHERE lo.RowNumber = 1
                GROUP BY LTRIM(RTRIM(lo.NumeroPedido)), LTRIM(RTRIM(product.Cod_producto))
            """, batch)
            for row in cursor.fetchall():
                key = (str(row.SalesOrder).strip(), str(row.Assy).strip())
                served_by_order_assy[key] = max(0, int(row.UnidadesServidas or 0))
    return served_by_order_assy


@app.route('/api/pedidos_secuenciados_c', methods=['GET'])
@cross_origin()
def get_pedidos_secuenciados_c():
    """
    Devuelve los pedidos secuenciados tipo C (Assembly = 'Yes C').
    Usa la vista OB.V_PedidosSummary_Secuenciados_Full como fuente única.
    Excluye pedidos con TB para evitar solape con la tarjeta Tie Brackets.
    Ordenados por PriorityOrder primero (manual) y luego por Sequence (automático).
    """
    inicio = time.time()
    VIEW_LOGGER.info("=== INICIO: GET /api/pedidos_secuenciados_c ===")
    cache_key = 'pedidos_secuenciados_c'

    cached_result = get_cached_endpoint_response(cache_key)
    if cached_result is not None:
        VIEW_LOGGER.info(f"✓ Cache hit: {cache_key} | Registros: {len(cached_result)}")
        VIEW_LOGGER.info("=== FIN: GET /api/pedidos_secuenciados_c ===\n")
        return jsonify(cached_result)
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                VIEW_LOGGER.error("No se pudo conectar a la base de datos")
                return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
            cursor = conn.cursor()
            cursor.execute(build_sequenced_orders_cards_prepare_query(
                'YES C',
                "ISNULL(ps.UniValMapex,0)",
                include_c_fields=True,
            ))
            query = build_sequenced_orders_cards_query(
                'YES C',
                "ISNULL(ps.UniValMapex,0)",
                include_c_fields=True,
            )
            query_inicio = time.time()
            cursor.execute(query)
            rows = cursor.fetchall()
            query_duracion = time.time() - query_inicio
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

            enrich_inicio = time.time()
            enrich_orders_with_mapex_quantities(result)
            enrich_duracion = time.time() - enrich_inicio
            set_cached_endpoint_response(cache_key, result)
            
            duracion = time.time() - inicio
            cantidad = len(result)
            VIEW_LOGGER.info(f"DB: {query_duracion:.3f}s | MAPEX: {enrich_duracion:.3f}s")
            
            if cantidad == 0:
                VIEW_LOGGER.warning(f"⚠️ ADVERTENCIA: Vista retornó 0 registros | Duración: {duracion:.3f}s")
            else:
                VIEW_LOGGER.info(f"✓ Vista retornó {cantidad} registros | Duración: {duracion:.3f}s")
            
            VIEW_LOGGER.info("=== FIN: GET /api/pedidos_secuenciados_c ===\n")
            return jsonify(result)
    except Exception as e:
        duracion = time.time() - inicio
        VIEW_LOGGER.error(f"❌ ERROR: {str(e)} | Duración: {duracion:.3f}s")
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
    Incluye Extender (EX) y ExtenderQty.
    """
    inicio = time.time()
    VIEW_LOGGER.info("=== INICIO: GET /api/pedidos_secuenciados_c_trazabilidad ===")
    cache_key = 'pedidos_secuenciados_c_trazabilidad'

    cached_result = get_cached_endpoint_response(cache_key)
    if cached_result is not None:
        VIEW_LOGGER.info(f"✓ Cache hit: {cache_key} | Registros: {len(cached_result)}")
        VIEW_LOGGER.info("=== FIN: GET /api/pedidos_secuenciados_c_trazabilidad ===\n")
        return jsonify(cached_result)
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                VIEW_LOGGER.error("No se pudo conectar a la base de datos")
                return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
            cursor = conn.cursor()
            query = '''
                SELECT 
                    ps.Sequence AS Sequence,
                    ps.NumeroPedido AS SalesOrder,
                    CASE
                        WHEN ISNULL(ps.UnidadesPedidas, 0) - ISNULL(ps.UniValMapex, 0) > 0
                            THEN ISNULL(ps.UnidadesPedidas, 0) - ISNULL(ps.UniValMapex, 0)
                        ELSE 0
                    END AS Qty,
                    ISNULL(ps.UniValMapex, 0) AS ProducedQty,
                    ISNULL(ps.AssignedStockBeam,0) AS DoneQty,
                    ps.Assy,
                    ps.Beam,
                    pc.FechaEntrega AS DeliveryDate
                FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
                LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON pc.NumeroPedido = ps.NumeroPedido
                WHERE UPPER(LTRIM(RTRIM(ps.[C/W]))) = 'C'
                  AND ISNULL(ps.UnidadesPedidas, 0) > ISNULL(ps.UniValMapex, 0)
                ORDER BY 
                    CASE WHEN ps.PriorityOrder IS NULL THEN 1 ELSE 0 END,
                    ps.PriorityOrder ASC,
                    ps.Sequence ASC
            '''
            query_inicio = time.time()
            cursor.execute(query)
            rows = cursor.fetchall()
            query_duracion = time.time() - query_inicio
            columns = [desc[0] for desc in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]

            enrich_inicio = time.time()
            enrich_clinching_orders_with_master_components(result)
            enrich_duracion = time.time() - enrich_inicio
            set_cached_endpoint_response(cache_key, result)
            
            duracion = time.time() - inicio
            cantidad = len(result)
            VIEW_LOGGER.info(f"DB: {query_duracion:.3f}s | MAPEX: {enrich_duracion:.3f}s")
            
            if cantidad == 0:
                VIEW_LOGGER.warning(f"⚠️ ADVERTENCIA: Vista retornó 0 registros | Duración: {duracion:.3f}s")
            else:
                VIEW_LOGGER.info(f"✓ Vista retornó {cantidad} registros | Duración: {duracion:.3f}s")
            
            VIEW_LOGGER.info("=== FIN: GET /api/pedidos_secuenciados_c_trazabilidad ===\n")
            return jsonify(result)
    except Exception as e:
        duracion = time.time() - inicio
        VIEW_LOGGER.error(f"❌ ERROR: {str(e)} | Duración: {duracion:.3f}s")
        print(f"Error en /api/pedidos_secuenciados_c_trazabilidad: {e}")
        return jsonify({"error": "Error interno", "details": str(e)}), 500

# ====================================================================================
# ENDPOINT PARA PEDIDOS SECUENCIADOS W (para pantalla OB_W)
# ====================================================================================
@app.route('/api/pedidos_secuenciados_w', methods=['GET'])
@cross_origin()
def get_pedidos_secuenciados_w():
    """
    Devuelve los pedidos secuenciados tipo W (Assembly = 'Yes W') usando la vista OB.V_PedidosSummary_Secuenciados_Full,
    con IF1 e IF2 de OB.Omegas. Excluye pedidos con TB para evitar solape con Tie Brackets.
    Ordenados por PriorityOrder primero (manual) y luego por Sequence (automático).
    """
    inicio = time.time()
    VIEW_LOGGER.info("=== INICIO: GET /api/pedidos_secuenciados_w ===")
    cache_key = 'pedidos_secuenciados_w'

    cached_result = get_cached_endpoint_response(cache_key)
    if cached_result is not None:
        VIEW_LOGGER.info(f"✓ Cache hit: {cache_key} | Registros: {len(cached_result)}")
        VIEW_LOGGER.info("=== FIN: GET /api/pedidos_secuenciados_w ===\n")
        return jsonify(cached_result)
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                VIEW_LOGGER.error("No se pudo conectar a la base de datos")
                return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
            cursor = conn.cursor()
            cursor.execute(build_sequenced_orders_cards_prepare_query(
                'YES W',
                "ISNULL(ps.UniValMapex,0)",
            ))
            query = build_sequenced_orders_cards_query(
                'YES W',
                "ISNULL(ps.UniValMapex,0)",
            )
            query_inicio = time.time()
            cursor.execute(query)
            rows = cursor.fetchall()
            query_duracion = time.time() - query_inicio
            columns = [desc[0] for desc in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]

            enrich_inicio = time.time()
            enrich_orders_with_mapex_quantities(result)
            enrich_duracion = time.time() - enrich_inicio
            set_cached_endpoint_response(cache_key, result)
            
            duracion = time.time() - inicio
            cantidad = len(result)
            VIEW_LOGGER.info(f"DB: {query_duracion:.3f}s | MAPEX: {enrich_duracion:.3f}s")
            
            if cantidad == 0:
                VIEW_LOGGER.warning(f"⚠️ ADVERTENCIA: Vista retornó 0 registros | Duración: {duracion:.3f}s")
            else:
                VIEW_LOGGER.info(f"✓ Vista retornó {cantidad} registros | Duración: {duracion:.3f}s")
            
            VIEW_LOGGER.info("=== FIN: GET /api/pedidos_secuenciados_w ===\n")
            return jsonify(result)
    except Exception as e:
        duracion = time.time() - inicio
        VIEW_LOGGER.error(f"❌ ERROR: {str(e)} | Duración: {duracion:.3f}s")
        print(f"Error en /api/pedidos_secuenciados_w: {e}")
        return jsonify({"error": "Error interno", "details": str(e)}), 500

# ====================================================================================
# ENDPOINT PARA PEDIDOS CON TIE BRACKET (TB)
# ====================================================================================
@app.route('/api/pedidos_tb', methods=['GET'])
@cross_origin()
def get_pedidos_tb():
    """
    Devuelve los pedidos secuenciados que tengan TB (Tie Bracket) asignado.
    Usa la vista wrapper OB.V_PedidosSummary_Secuenciados_Full que ya incluye EX y TB.
    Esta tarjeta es exclusiva para pedidos con TB para que no se solapen con OB_C/OB_W.
    Muestra: Sequence, SalesOrder, Qty, TieBracket, Extender, ExtenderQuantity.
    Devuelve solo las filas objetivo: por lógica de TB y/o por lógica de extensor.
    Ordenados por PriorityOrder primero y luego por Sequence.
    """
    inicio = time.time()
    VIEW_LOGGER.info("=== INICIO: GET /api/pedidos_tb ===")
    cache_key = 'pedidos_tb'

    cached_result = get_cached_endpoint_response(cache_key)
    if cached_result is not None:
        VIEW_LOGGER.info(f"✓ Cache hit: {cache_key} | Registros: {len(cached_result)}")
        VIEW_LOGGER.info("=== FIN: GET /api/pedidos_tb ===\n")
        return jsonify(cached_result)
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                VIEW_LOGGER.error("No se pudo conectar a la base de datos")
                return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
            cursor = conn.cursor()
            query = '''
                SELECT 
                    ps.Sequence AS Sequence,
                    ps.NumeroPedido AS SalesOrder,
''' + build_tb_cards_quantity_case_sql('ps', False) + ''',
                    ps.Assy AS Assy,
                    ISNULL(ps.TB, '') AS TieBracket,
                                        pc.FechaEntrega AS DeliveryDate,
''' + build_extender_value_case_sql('ps') + ''' AS Extender,
                    ps.PriorityOrder,
''' + build_tb_cards_quantity_case_sql('ps', True) + '''
                FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
                                LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON pc.NumeroPedido = ps.NumeroPedido
''' + build_wc_line_apply_sql('ps', 'tbext', 'TB') + '''
                WHERE ps.TB IS NOT NULL AND LTRIM(RTRIM(ps.TB)) != ''
                  AND (
''' + build_tb_cards_quantity_predicate_sql('ps') + '''
                  )
                ORDER BY 
                    CASE WHEN ps.PriorityOrder IS NULL THEN 1 ELSE 0 END,
                    ps.PriorityOrder ASC,
                    ps.Sequence ASC
            '''
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
            set_cached_endpoint_response(cache_key, result)
            
            duracion = time.time() - inicio
            cantidad = len(result)
            
            if cantidad == 0:
                VIEW_LOGGER.warning(f"⚠️ ADVERTENCIA: Vista retornó 0 registros | Duración: {duracion:.3f}s")
            else:
                VIEW_LOGGER.info(f"✓ Vista retornó {cantidad} registros | Duración: {duracion:.3f}s")
            
            VIEW_LOGGER.info("=== FIN: GET /api/pedidos_tb ===\n")
            return jsonify(result)
    except Exception as e:
        duracion = time.time() - inicio
        VIEW_LOGGER.error(f"❌ ERROR: {str(e)} | Duración: {duracion:.3f}s")
        print(f"Error en /api/pedidos_tb: {e}")
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
    inicio = time.time()
    VIEW_LOGGER.info("=== INICIO: GET /api/pedidos_picking ===")
    cache_key = 'pedidos_picking'

    cached_result = get_cached_endpoint_response(cache_key, max_age_seconds=15)
    if cached_result is not None:
        VIEW_LOGGER.info(f"✓ Cache hit: {cache_key} | Registros: {len(cached_result)}")
        VIEW_LOGGER.info("=== FIN: GET /api/pedidos_picking ===\n")
        return jsonify(cached_result)
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                VIEW_LOGGER.error("No se pudo conectar a la base de datos")
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
                    ps.Picking,
                    ps.UniValMapex,
                    ISNULL(ps.AssignedStock, 0) AS AssignedStock,
                    ISNULL(pc.CWT, '') AS CWT,
                    ISNULL(pc.DS, '') AS MS,
                    ''' + build_pedidos_cabecera_optional_select_sql('CWI') + ''',
                    ISNULL(o.[W/C], '') AS WCType,
                    ''' + build_pit_bracket_quantity_value_sql('ps', 'o') + ''' AS LabelQty
                FROM OB.V_PedidosSummary_Secuenciados ps WITH (NOLOCK)
                LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON pc.NumeroPedido = ps.NumeroPedido
                LEFT JOIN OB.Omegas o WITH (NOLOCK) ON o.Assy = ps.Assy
                WHERE UPPER(LTRIM(RTRIM(ps.[C/W]))) IN ('C', 'W')
                  AND ISNULL(ps.UnidadesPedidas, 0) > 0
            '''
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            candidates = [dict(zip(columns, row)) for row in rows]
            served_by_order_assy = get_mapex_served_quantities_by_order_assy(candidates)
            result = []
            for item in candidates:
                ordered_qty = max(0, int(item.get('Qty') or 0))
                produced_qty = max(0, int(item.get('UniValMapex') or 0))
                assigned_stock = max(0, int(item.get('AssignedStock') or 0))
                served_qty = served_by_order_assy.get((
                    str(item.get('SalesOrder') or '').strip(),
                    str(item.get('Assy') or '').strip(),
                ), 0)
                # La vista decide qué líneas están listas para Picking. No volver
                # a incluir líneas con Picking='No' solo porque ya estén producidas.
                # Se conserva una recogida parcial mientras MAPEX registre avance.
                picking_value = str(item.get('Picking') or '').strip().upper()
                is_pickable = picking_value in ('SI', 'SÍ', 'YES', '1', 'TRUE')
                remaining_to_pick = max(0, ordered_qty - served_qty)
                if not remaining_to_pick or (served_qty <= 0 and not is_pickable):
                    continue
                item['OrderedQty'] = ordered_qty
                item['PickedQty'] = served_qty
                item['Qty'] = remaining_to_pick
                result.append(item)
            set_cached_endpoint_response(cache_key, result)
            
            duracion = time.time() - inicio
            cantidad = len(result)
            
            if cantidad == 0:
                VIEW_LOGGER.warning(f"⚠️ ADVERTENCIA: Vista retornó 0 registros | Duración: {duracion:.3f}s")
            else:
                VIEW_LOGGER.info(f"✓ Vista retornó {cantidad} registros | Duración: {duracion:.3f}s")
            
            VIEW_LOGGER.info("=== FIN: GET /api/pedidos_picking ===\n")
            return jsonify(result)
    except Exception as e:
        duracion = time.time() - inicio
        VIEW_LOGGER.error(f"❌ ERROR: {str(e)} | Duración: {duracion:.3f}s")
        print(f"Error en /api/pedidos_picking: {e}")
        return jsonify({"error": "Error interno", "details": str(e)}), 500

# ====================================================================================
# HELPER PARA POC DE MATERIAL 1035 (EXTENSORES)
# ====================================================================================
def get_extender_values_for_material_1035(cod_producto):
    """
    POC: Si el material es 1035, retorna valores fabricados para extensores.
    Esto permite validar el pipeline completo sin datos reales de SAP.
    """
    if not cod_producto:
        return None
    
    material_str = str(cod_producto).strip().upper()
    if '1035' in material_str or 'SCOS59001035' in material_str:
        print(f"[EXTENDER POC] Material 1035 detectado: {cod_producto}")
        return {
            'GRP_HSK_TYPE': 'LH',
            'GRP_NUM_OMEGA': 4,
            'GRP_OMEGA_BRACKET_TYPE_TSD': 'TSD21_O_A2_1002'
        }
    return None

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

    with MANUAL_SYNC_STATE_LOCK:
        if MANUAL_SYNC_STATE['running']:
            return jsonify({
                'message': 'La actualización manual ya está en curso',
                **_manual_sync_state_response(),
            }), 202

        MANUAL_SYNC_STATE['running'] = True
        MANUAL_SYNC_STATE['started_at'] = datetime.now().isoformat(timespec='seconds')
        MANUAL_SYNC_STATE['finished_at'] = None
        MANUAL_SYNC_STATE['result'] = None
        MANUAL_SYNC_STATE['error'] = None

        worker = threading.Thread(
            target=run_manual_full_sync_background,
            daemon=True,
            name='ManualFullSync',
        )
        worker.start()

    return jsonify({
        'message': 'Actualización manual iniciada en segundo plano',
        **_manual_sync_state_response(),
    }), 202


@app.route('/api/sync/manual-full/status', methods=['GET'])
@cross_origin()
def manual_full_sync_status():
    return jsonify(_manual_sync_state_response()), 200

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
        with PEDIDOS_DB_LOCK:
            # Reponer cabeceras/líneas pendientes ausentes para evitar pedidos futuros sin importar.
            try:
                sync_pending_orders(lookback_days=1, log_prefix='[INCREMENTAL SYNC]')
            except Exception as e:
                print(f"[INCREMENTAL SYNC] ADVERTENCIA reponiendo cabeceras pendientes: {e}")

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
            except Exception:
                logging.exception('[INCREMENTAL SYNC] Error actualizando UniValMapex desde MAPEX.')

            # Recalcular AssignedStock para TODOS los pedidos secuenciados con
            # la misma función que usa el worker periódico.
            try:
                stock_assignment = recalculate_assigned_stock_once()
            except Exception as error:
                logging.exception('[INCREMENTAL SYNC] Error recalculando stock asignado.')
                stock_assignment = {'error': type(error).__name__}

        return jsonify({
            "message": "Actualización incremental completada exitosamente",
            "periodo": "Todos los pedidos secuenciados recalculados",
            "stock_assignment": stock_assignment,
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
                            (NumeroPedido, Assy, Beam, SequenceValue, OFs, FechaSecuenciacion, AssignedStock, AssignedStockBeam)
                            VALUES (?, ?, ?, ?, ?, GETDATE(), 0, 0)
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
    def __init__(self, database=None, servidor=None):
        self.server = servidor
        self.database = database
        self.conn = None

    def __enter__(self):
        try:
            if not DB_USER or not DB_PASSWORD:
                raise Exception('Faltan credenciales de base de datos')

            servers, drivers = build_connection_candidates(
                DB_CONNECTION_CONFIG.get('main_servers', []),
                self.server
            )
            last_error = None

            for driver in drivers:
                for server in servers:
                    conn_str = (
                        f"DRIVER={{{driver}}};"
                        f"SERVER={server};"
                        f"DATABASE={self.database};"
                        f"UID={DB_USER};PWD={DB_PASSWORD};"
                        "Encrypt=yes;"
                        "TrustServerCertificate=yes;"
                        "Connection Timeout=10;"
                    )

                    try:
                        self.conn = pyodbc.connect(conn_str, timeout=10, autocommit=True)
                        self.server = server
                        logging.info(f"[DB MAIN] Conectado a {self.database} con server={server}, driver={driver}")
                        return self.conn
                    except Exception as conn_error:
                        last_error = conn_error
                        logging.warning(f"[DB MAIN] Fallo de conexión con server={server}, driver={driver}: {conn_error}")

            raise last_error or Exception('No se encontró una combinación válida de servidor/driver')
        except Exception as e:
            logging.error(f"Error CRÍTICO al conectar con la base de datos: {e}")
            return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.close()

# ====================================================================================
# CLASE DE CONEXIÓN ODBC PARA CZ
# ====================================================================================
class ConexionODBCCZ:
    def __init__(self, database='mapexbp', servidor=None):
        self.server = servidor
        self.database = database
        self.conn = None

    def __enter__(self):
        try:
            if not DB_USERCZ or not DB_PASSWORDCZ:
                raise Exception('Faltan credenciales de base de datos CZ')

            servers, drivers = build_connection_candidates(
                DB_CONNECTION_CONFIG.get('cz_servers', []),
                self.server
            )
            last_error = None

            for driver in drivers:
                for server in servers:
                    conn_str = (
                        f"DRIVER={{{driver}}};"
                        f"SERVER={server};"
                        f"DATABASE={self.database};"
                        f"UID={DB_USERCZ};PWD={DB_PASSWORDCZ};"
                        "Encrypt=yes;"
                        "TrustServerCertificate=yes;"
                        "Connection Timeout=10;"
                    )

                    try:
                        self.conn = pyodbc.connect(conn_str, timeout=10, autocommit=True)
                        self.server = server
                        logging.info(f"[DB CZ] Conectado a {self.database} con server={server}, driver={driver}")
                        return self.conn
                    except Exception as conn_error:
                        last_error = conn_error
                        logging.warning(f"[DB CZ] Fallo de conexión con server={server}, driver={driver}: {conn_error}")

            raise last_error or Exception('No se encontró una combinación válida de servidor/driver para CZ')
        except Exception as e:
            logging.error(f"Error CRÍTICO al conectar con la base de datos CZ: {e}")
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
    response = send_from_directory(RUTA_PANTALLAS, nombre_archivo)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


def buscar_usuario_cz(cursor, columnas_sql, usuario):
    usuario = str(usuario).strip()

    if usuario.isdigit():
        cursor.execute(
            f"""
                SELECT {columnas_sql}
                FROM OB.Usuarios_CZ_hash
                WHERE Num_Operario = ? OR Nombre = ?
            """,
            (int(usuario), usuario)
        )
    else:
        cursor.execute(
            f"""
                SELECT {columnas_sql}
                FROM OB.Usuarios_CZ_hash
                WHERE Nombre = ?
            """,
            (usuario,)
        )

    return cursor.fetchone()


def verificar_password_usuario(stored_password, plain_password):
    if stored_password is None or plain_password is None:
        return False

    if isinstance(stored_password, bytes):
        stored_password = stored_password.decode('utf-8', errors='ignore')

    stored_text = str(stored_password).strip()
    plain_text = str(plain_password).strip()

    if not stored_text or not plain_text:
        return False

    if stored_text == plain_text:
        return True

    if len(stored_text) == 64 and all(char in '0123456789abcdefABCDEF' for char in stored_text):
        return hashlib.sha256(plain_text.encode('utf-8')).hexdigest().lower() == stored_text.lower()

    try:
        return check_password_hash(stored_text, plain_text)
    except Exception:
        return False


# ====================================================================================
# ENDPOINTS DE LA API
# ====================================================================================
def build_wc_line_apply_sql(order_alias='ps', apply_alias='wcline', wc_value='EX'):
    """OUTER APPLY genérico: resuelve cualquier W/C desde PedidosLineas + OB.Omegas.
    Esto evita depender de PedidosCabecera (que solo se actualiza al importar).
    Si un producto se añade al catálogo OB.Omegas después de importar el pedido,
    este OUTER APPLY lo encontrará igualmente en la siguiente consulta."""
    safe_wc = str(wc_value).strip().replace("'", "''")
    return f"""
                OUTER APPLY (
                    SELECT TOP 1
                        LTRIM(RTRIM(pl.Cod_Producto_Externo)) AS WCLine
                    FROM OB.PedidosCabecera pc WITH (NOLOCK)
                    INNER JOIN OB.PedidosLineas pl WITH (NOLOCK)
                        ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
                    INNER JOIN OB.Omegas o_line WITH (NOLOCK)
                        ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
                    WHERE LTRIM(RTRIM(pc.NumeroPedido)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                      AND LTRIM(RTRIM(o_line.[W/C])) = '{safe_wc}'
                    ORDER BY pl.UnidadesPedidas DESC, pl.Cod_Producto_Externo ASC
                ) {apply_alias}
    """


def build_extender_line_apply_sql(order_alias='ps', apply_alias='extline'):
    """Recupera el EX real desde las líneas del pedido cuando la cabecera no lo materializó."""
    return build_wc_line_apply_sql(order_alias, apply_alias, 'EX')


def build_extender_derived_apply_sql(order_alias='ps', apply_alias='extderived'):
    """Calcula una sola vez el extensor derivado desde LH/TSD para reutilizarlo en la query."""
    return f"""
                OUTER APPLY (
                    SELECT TOP 1
                        LTRIM(RTRIM(o_tsd.Assy)) AS DerivedExtender
                    FROM OB.pedidos_exportados pe_lh WITH (NOLOCK)
                    INNER JOIN OB.pedidos_exportados pe_tsd WITH (NOLOCK)
                        ON LTRIM(RTRIM(pe_tsd.sales_document)) = LTRIM(RTRIM(pe_lh.sales_document))
                    INNER JOIN OB.Omegas o_tsd WITH (NOLOCK)
                        ON LTRIM(RTRIM(o_tsd.Assy)) = LTRIM(RTRIM({order_alias}.Assy))
                       AND LTRIM(RTRIM(o_tsd.ExtenderVariable)) = LTRIM(RTRIM(pe_tsd.characteristic_value))
                                        WHERE LTRIM(RTRIM(pe_lh.sales_document)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                      AND pe_lh.characteristic_name = 'GRP_HSK_TYPE'
                      AND UPPER(LTRIM(RTRIM(pe_lh.characteristic_value))) = 'LH'
                      AND pe_tsd.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
                      AND pe_tsd.characteristic_value IS NOT NULL
                      AND LTRIM(RTRIM(pe_tsd.characteristic_value)) <> ''
                                            AND NOT EXISTS (
                                                    SELECT 1
                                                    FROM OB.PedidosCabecera pc WITH (NOLOCK)
                                                    INNER JOIN OB.PedidosLineas pl WITH (NOLOCK)
                                                            ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
                                                    INNER JOIN OB.Omegas o_line WITH (NOLOCK)
                                                            ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
                                                    WHERE LTRIM(RTRIM(pc.NumeroPedido)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                                                        AND LTRIM(RTRIM(o_line.[W/C])) = 'EX'
                                            )
                ) {apply_alias}
    """


def build_extender_target_apply_sql(order_alias='ps', apply_alias='exttarget'):
    """Identifica una sola vez si la fila actual es la fila objetivo para ExtenderQty."""
    return f"""
                OUTER APPLY (
                    SELECT TOP 1 1 AS IsTargetAssy
                    FROM OB.pedidos_exportados pe_lh WITH (NOLOCK)
                    INNER JOIN OB.pedidos_exportados pe WITH (NOLOCK)
                        ON LTRIM(RTRIM(pe.sales_document)) = LTRIM(RTRIM(pe_lh.sales_document))
                    INNER JOIN OB.Omegas o_target WITH (NOLOCK)
                        ON (
                            pe.characteristic_name IN ('GRP_OMEGA_BRACKET_TYPE_HEAD', 'GRP_OMEGA_BRACKET_TYPE_TRAV')
                            AND LTRIM(RTRIM(o_target.OmegaType)) = LTRIM(RTRIM(pe.characteristic_value))
                        )
                        OR (
                            pe.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
                            AND LTRIM(RTRIM(o_target.ExtenderVariable)) = LTRIM(RTRIM(pe.characteristic_value))
                        )
                    WHERE LTRIM(RTRIM(pe_lh.sales_document)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                      AND pe_lh.characteristic_name = 'GRP_HSK_TYPE'
                      AND UPPER(LTRIM(RTRIM(pe_lh.characteristic_value))) = 'LH'
                      AND pe.characteristic_value IS NOT NULL
                      AND LTRIM(RTRIM(pe.characteristic_value)) <> ''
                      AND LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM({order_alias}.Assy))
                ) {apply_alias}
    """


def build_extender_resolved_value_sql(order_alias='ps', line_alias='extline', derived_alias='extderived'):
    """Devuelve EX persistido, EX real en líneas o el extensor derivado ya calculado por OUTER APPLY."""
    return f"COALESCE(NULLIF(LTRIM(RTRIM({order_alias}.EX)), ''), {line_alias}.WCLine, {derived_alias}.DerivedExtender)"


def build_extender_resolved_quantity_sql(order_alias='ps', line_alias='extline', derived_alias='extderived', target_alias='exttarget', alias_name='ExtenderQuantity'):
    """Devuelve la cantidad de extensor reutilizando el extensor derivado y la fila objetivo."""
    resolved_value = build_extender_resolved_value_sql(order_alias, line_alias, derived_alias)
    return f"""
                    CASE
                        WHEN {resolved_value} IS NULL THEN NULL
                        WHEN {target_alias}.IsTargetAssy = 1 THEN CASE
                            WHEN {order_alias}.UnidadesPedidas > 2 THEN {order_alias}.UnidadesPedidas - 2
                            ELSE 0
                        END
                        ELSE NULL
                    END AS {alias_name}
    """


def build_sequenced_orders_cards_prepare_query(assembly_value, done_qty_sql, include_c_fields=False):
    """Materializa el conjunto pequeño de la tarjeta y sus datos auxiliares.

    Los CTE de SQL Server no se materializan: al reutilizar ``base`` muchas veces,
    el optimizador podía volver a expandir la vista pesada. Estas tablas temporales
    viven solo durante la petición ODBC y evitan ese trabajo repetido.
    """
    if assembly_value not in ('YES C', 'YES W'):
        raise ValueError('Tipo de assembly no permitido para la tarjeta secuenciada')

    c_base_fields = ''
    if include_c_fields:
        c_base_fields = """
                    ISNULL(pc.CWT, '') AS CWT,
                    ISNULL(pc.DS, '') AS MS,
                    """ + build_pedidos_cabecera_optional_select_sql('CWI') + ","

    return f'''
                SELECT
                    ps.Sequence AS Sequence,
                    ps.NumeroPedido AS SalesOrder,
                    LTRIM(RTRIM(ps.NumeroPedido)) AS NumeroPedido,
                    CASE
                        WHEN ISNULL(ps.UnidadesPedidas, 0) - ISNULL(ps.UniValMapex, 0) > 0
                            THEN ISNULL(ps.UnidadesPedidas, 0) - ISNULL(ps.UniValMapex, 0)
                        ELSE 0
                    END AS Qty,
                    ps.UnidadesPedidas AS OrderedQty,
                    ISNULL(ps.UniValMapex, 0) AS ProducedQty,
                    ps.UnidadesPedidas AS UnidadesPedidas,
                    {done_qty_sql} AS DoneQty,
                    ps.Assy,
                    ps.Beam,
                    o.IF1,
                    o.IF2,
                    pc.FechaEntrega AS DeliveryDate,
{c_base_fields}
                    ps.OFs AS WO,
                    ps.EX AS RawEX,
                    ps.TB AS RawTB,
                    ps.PriorityOrder
                INTO #seq_cards_base
                FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
                LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK)
                    ON pc.NumeroPedido = ps.NumeroPedido
                LEFT JOIN OB.Omegas o WITH (NOLOCK)
                    ON ps.Assy = o.Assy
                WHERE UPPER(LTRIM(RTRIM(ps.[C/W]))) = '{assembly_value[-1]}'
                  AND ISNULL(ps.UniValMapex, 0) < ISNULL(ps.UnidadesPedidas, 0);

                CREATE CLUSTERED INDEX IX_seq_cards_base
                    ON #seq_cards_base (NumeroPedido, Assy);

                ;WITH ranked_chars AS (
                    SELECT
                        LTRIM(RTRIM(pe.sales_document)) AS doc,
                        pe.characteristic_name,
                        LTRIM(RTRIM(pe.characteristic_value)) AS val,
                        ROW_NUMBER() OVER (
                            PARTITION BY LTRIM(RTRIM(pe.sales_document)), pe.characteristic_name
                            ORDER BY pe.fecha_importacion DESC, pe.id_importacion DESC
                        ) AS row_num
                    FROM OB.pedidos_exportados pe WITH (NOLOCK)
                    INNER JOIN (SELECT DISTINCT NumeroPedido FROM #seq_cards_base) b
                        ON b.NumeroPedido = LTRIM(RTRIM(pe.sales_document))
                    WHERE pe.characteristic_name IN (
                        'GRP_HSK_TYPE',
                        'GRP_OMEGA_BRACKET_TYPE_TSD',
                        'GRP_OMEGA_BRACKET_TYPE_HEAD',
                        'GRP_OMEGA_BRACKET_TYPE_TRAV',
                        'GRP_OMEGA_BRACKET_TYPE_PIT',
                        'GRP_OMEGA_BRACKET_QTY_PIT',
                        'GRP_TIE_BRACKET_OPT',
                        'GRP_TIE_BRACKET_TYPE',
                        'GRP_TIE_BRACKET_QTY'
                    )
                )
                SELECT doc, characteristic_name, val
                INTO #seq_cards_chars
                FROM ranked_chars
                WHERE row_num = 1;

                CREATE INDEX IX_seq_cards_chars
                    ON #seq_cards_chars (doc, characteristic_name)
                    INCLUDE (val);

                SELECT
                    LTRIM(RTRIM(pc.NumeroPedido)) AS doc,
                    LTRIM(RTRIM(pl.Cod_Producto_Externo)) AS WCLine,
                    pl.UnidadesPedidas AS Qty,
                    LTRIM(RTRIM(o_line.[W/C])) AS WorkCenter
                INTO #seq_cards_lines
                FROM (SELECT DISTINCT NumeroPedido FROM #seq_cards_base) b
                INNER JOIN OB.PedidosCabecera pc WITH (NOLOCK)
                    ON b.NumeroPedido = LTRIM(RTRIM(pc.NumeroPedido))
                INNER JOIN OB.PedidosLineas pl WITH (NOLOCK)
                    ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
                INNER JOIN OB.Omegas o_line WITH (NOLOCK)
                    ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
                WHERE LTRIM(RTRIM(o_line.[W/C])) IN ('TB', 'EX');

                CREATE INDEX IX_seq_cards_lines
                    ON #seq_cards_lines (doc, WorkCenter, Qty DESC);
    '''


def build_sequenced_orders_cards_query(assembly_value, done_qty_sql, include_c_fields=False):
    """Consulta set-based para las tarjetas C/W.

    La consulta anterior ejecutaba varios OUTER APPLY y subconsultas correlacionadas
    por cada fila de la vista.  Con varios cientos de pedidos eso multiplicaba las
    lecturas de PedidosLineas y pedidos_exportados.  Esta variante calcula cada
    relación una única vez y solo para los pedidos visibles en la tarjeta.
    """
    if assembly_value not in ('YES C', 'YES W'):
        raise ValueError('Tipo de assembly no permitido para la tarjeta secuenciada')

    c_base_fields = ''
    c_result_fields = ''
    c_result_after_delivery = ''
    if include_c_fields:
        c_base_fields = """
                        ISNULL(pc.CWT, '') AS CWT,
                        ISNULL(pc.DS, '') AS MS,
                        """ + build_pedidos_cabecera_optional_select_sql('CWI') + ","
        c_result_fields = """
                    b.CWT,
                    b.MS,"""
        c_result_after_delivery = """
                    b.CWI,"""

    return f'''
                WITH base AS (
                    SELECT * FROM #seq_cards_base
                ),
                lh_docs AS (
                    SELECT DISTINCT pe.doc
                    FROM #seq_cards_chars pe
                    WHERE pe.characteristic_name = 'GRP_HSK_TYPE'
                      AND UPPER(pe.val) = 'LH'
                ),
                tsd_map AS (
                    SELECT pe.doc, pe.val
                    FROM #seq_cards_chars pe
                    WHERE pe.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
                      AND pe.val IS NOT NULL AND pe.val <> ''
                ),
                head_trav_map AS (
                    SELECT pe.doc, pe.val
                    FROM #seq_cards_chars pe
                    WHERE pe.characteristic_name IN ('GRP_OMEGA_BRACKET_TYPE_HEAD', 'GRP_OMEGA_BRACKET_TYPE_TRAV')
                      AND pe.val IS NOT NULL AND pe.val <> ''
                ),
                pit_map AS (
                    SELECT pe.doc, pe.val
                    FROM #seq_cards_chars pe
                    WHERE pe.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_PIT'
                      AND pe.val IS NOT NULL AND pe.val <> ''
                ),
                pit_qty_map AS (
                    SELECT pe.doc, TRY_CAST(pe.val AS INT) AS qty
                    FROM #seq_cards_chars pe
                    WHERE pe.characteristic_name = 'GRP_OMEGA_BRACKET_QTY_PIT'
                      AND pe.val IS NOT NULL AND pe.val <> ''
                ),
                pit_qty_value AS (
                    SELECT doc, MIN(qty) AS qty
                    FROM pit_qty_map
                    WHERE qty IS NOT NULL
                    GROUP BY doc
                ),
                tb_opt_y_docs AS (
                    SELECT DISTINCT pe.doc
                    FROM #seq_cards_chars pe
                    WHERE pe.characteristic_name = 'GRP_TIE_BRACKET_OPT'
                      AND UPPER(pe.val) = 'Y'
                ),
                tb_type_map AS (
                    SELECT pe.doc, pe.val
                    FROM #seq_cards_chars pe
                    WHERE pe.characteristic_name = 'GRP_TIE_BRACKET_TYPE'
                      AND pe.val IS NOT NULL AND pe.val <> ''
                ),
                tb_qty_map AS (
                    SELECT pe.doc, TRY_CAST(pe.val AS INT) AS qty
                    FROM #seq_cards_chars pe
                    WHERE pe.characteristic_name = 'GRP_TIE_BRACKET_QTY'
                      AND pe.val IS NOT NULL AND pe.val <> ''
                ),
                wc_tb AS (
                    SELECT line.doc,
                           line.WCLine,
                           line.Qty,
                           ROW_NUMBER() OVER (
                               PARTITION BY line.doc
                               ORDER BY line.Qty DESC, line.WCLine ASC
                           ) AS rn
                    FROM #seq_cards_lines line
                    WHERE line.WorkCenter = 'TB'
                ),
                wc_ex AS (
                    SELECT line.doc,
                           line.WCLine,
                           ROW_NUMBER() OVER (
                               PARTITION BY line.doc
                               ORDER BY line.Qty DESC, line.WCLine ASC
                           ) AS rn
                    FROM #seq_cards_lines line
                    WHERE line.WorkCenter = 'EX'
                ),
                has_ex_line AS (
                    SELECT DISTINCT doc FROM wc_ex
                ),
                ext_derived AS (
                    SELECT DISTINCT b.NumeroPedido, b.Assy, b.Assy AS DerivedExtender
                    FROM base b
                    INNER JOIN lh_docs lh ON lh.doc = b.NumeroPedido
                    INNER JOIN tsd_map t ON t.doc = b.NumeroPedido
                    INNER JOIN OB.Omegas o_tsd WITH (NOLOCK)
                        ON LTRIM(RTRIM(o_tsd.Assy)) = LTRIM(RTRIM(b.Assy))
                       AND LTRIM(RTRIM(o_tsd.ExtenderVariable)) = t.val
                    WHERE NOT EXISTS (
                        SELECT 1 FROM has_ex_line hx WHERE hx.doc = b.NumeroPedido
                    )
                ),
                ext_target AS (
                    SELECT DISTINCT b.NumeroPedido, b.Assy, 1 AS IsTargetAssy
                    FROM base b
                    INNER JOIN lh_docs lh ON lh.doc = b.NumeroPedido
                    INNER JOIN OB.Omegas o_target WITH (NOLOCK)
                        ON LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM(b.Assy))
                    WHERE EXISTS (
                        SELECT 1 FROM head_trav_map ht
                        WHERE ht.doc = b.NumeroPedido
                          AND LTRIM(RTRIM(o_target.OmegaType)) = ht.val
                    ) OR EXISTS (
                        SELECT 1 FROM tsd_map t
                        WHERE t.doc = b.NumeroPedido
                          AND LTRIM(RTRIM(o_target.ExtenderVariable)) = t.val
                    )
                ),
                pit_target_exists AS (
                    SELECT DISTINCT b.NumeroPedido, b.Assy
                    FROM base b
                    INNER JOIN pit_map pm ON pm.doc = b.NumeroPedido
                    INNER JOIN OB.Omegas o_target WITH (NOLOCK)
                        ON REPLACE(UPPER(LTRIM(RTRIM(o_target.OmegaType))), ' LH', '')
                         = REPLACE(UPPER(LTRIM(RTRIM(pm.val))), ' LH', '')
                       AND LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM(b.Assy))
                    WHERE EXISTS (
                        SELECT 1 FROM lh_docs lh
                        WHERE lh.doc = b.NumeroPedido
                    ) OR EXISTS (
                        SELECT 1 FROM head_trav_map ht
                        WHERE ht.doc = b.NumeroPedido
                          AND REPLACE(UPPER(LTRIM(RTRIM(ht.val))), ' LH', '')
                              <> REPLACE(UPPER(LTRIM(RTRIM(pm.val))), ' LH', '')
                    )
                ),
                tb_target_exists AS (
                    SELECT DISTINCT b.NumeroPedido, b.Assy
                    FROM base b
                    INNER JOIN tb_opt_y_docs toy ON toy.doc = b.NumeroPedido
                    INNER JOIN tb_type_map ttm ON ttm.doc = b.NumeroPedido
                    INNER JOIN OB.Omegas o_target WITH (NOLOCK)
                        ON LTRIM(RTRIM(o_target.OmegaType)) = ttm.val
                       AND LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM(b.Assy))
                ),
                ext_value AS (
                    SELECT b.NumeroPedido, b.Assy,
                           COALESCE(NULLIF(LTRIM(RTRIM(b.RawEX)), ''), we.WCLine, ed.DerivedExtender) AS Extender
                    FROM base b
                    LEFT JOIN (SELECT doc, WCLine FROM wc_ex WHERE rn = 1) we
                        ON we.doc = b.NumeroPedido
                    LEFT JOIN ext_derived ed
                        ON ed.NumeroPedido = b.NumeroPedido AND ed.Assy = b.Assy
                ),
                ext_qty AS (
                    SELECT b.NumeroPedido, b.Assy,
                           CASE
                               WHEN ev.Extender IS NULL THEN NULL
                               WHEN lh.doc IS NOT NULL
                                    AND pte.NumeroPedido IS NOT NULL
                                    AND pit_qty.qty IS NOT NULL
                                    AND UPPER(LTRIM(RTRIM(o_ext_qty.[W/C]))) = 'W'
                                   THEN b.UnidadesPedidas
                               WHEN et.IsTargetAssy = 1 THEN CASE
                                   -- En el objetivo de extensor se separan las etiquetas
                                   -- PIT del total para que ambos valores sumen el Assy.
                                   -- Mantener 2 para importaciones antiguas sin QTY_PIT.
                                   WHEN b.UnidadesPedidas > COALESCE(pit_qty.qty, 2)
                                       THEN b.UnidadesPedidas - COALESCE(pit_qty.qty, 2)
                                   ELSE 0
                               END
                               ELSE NULL
                           END AS ExtenderQuantity
                    FROM base b
                    LEFT JOIN ext_value ev
                        ON ev.NumeroPedido = b.NumeroPedido AND ev.Assy = b.Assy
                    LEFT JOIN ext_target et
                        ON et.NumeroPedido = b.NumeroPedido AND et.Assy = b.Assy
                    LEFT JOIN lh_docs lh
                        ON lh.doc = b.NumeroPedido
                    LEFT JOIN pit_target_exists pte
                        ON pte.NumeroPedido = b.NumeroPedido AND pte.Assy = b.Assy
                    LEFT JOIN OB.Omegas o_ext_qty WITH (NOLOCK)
                        ON LTRIM(RTRIM(o_ext_qty.Assy)) = LTRIM(RTRIM(b.Assy))
                    LEFT JOIN pit_qty_value pit_qty
                        ON pit_qty.doc = b.NumeroPedido
                )
                SELECT
                    b.Sequence,
                    b.SalesOrder,
                    b.Qty,
                    b.DoneQty,
                    b.Assy,
                    b.Beam,
                    b.IF1,
                    b.IF2,
                    COALESCE(NULLIF(LTRIM(RTRIM(b.RawTB)), ''), wtb.WCLine) AS TieBracket,
{c_result_fields}
                    b.DeliveryDate,
{c_result_after_delivery}
                    b.WO,
                    ev.Extender,
                    {"b.PriorityOrder," if include_c_fields else ""}
                    pv.PitBracket,
                    CASE WHEN pte.NumeroPedido IS NULL THEN NULL ELSE pq.qty END AS PitBracketQty,
                    COALESCE(
                        CASE
                            WHEN COALESCE(NULLIF(LTRIM(RTRIM(b.RawTB)), ''), wtb.WCLine) IS NULL THEN NULL
                            WHEN tte.NumeroPedido IS NULL THEN NULL
                            ELSE tq.qty
                        END,
                        CASE
                            WHEN COALESCE(NULLIF(LTRIM(RTRIM(b.RawTB)), ''), wtb.WCLine) IS NULL THEN NULL
                            WHEN toy.doc IS NOT NULL THEN NULL
                            WHEN eq.ExtenderQuantity IS NOT NULL THEN 1
                            ELSE NULL
                        END,
                        tlq.Qty
                    ) AS TieBracketQty,
                    COALESCE(
                        CASE
                            WHEN COALESCE(NULLIF(LTRIM(RTRIM(b.RawTB)), ''), wtb.WCLine) IS NULL THEN NULL
                            WHEN tte.NumeroPedido IS NULL THEN NULL
                            ELSE tq.qty
                        END,
                        CASE
                            WHEN COALESCE(NULLIF(LTRIM(RTRIM(b.RawTB)), ''), wtb.WCLine) IS NULL THEN NULL
                            WHEN toy.doc IS NOT NULL THEN NULL
                            WHEN eq.ExtenderQuantity IS NOT NULL THEN 1
                            ELSE NULL
                        END
                    ) AS TieExtenderQty,
                    eq.ExtenderQuantity
                FROM base b
                LEFT JOIN (SELECT doc, WCLine FROM wc_tb WHERE rn = 1) wtb ON wtb.doc = b.NumeroPedido
                LEFT JOIN ext_value ev ON ev.NumeroPedido = b.NumeroPedido AND ev.Assy = b.Assy
                LEFT JOIN ext_qty eq ON eq.NumeroPedido = b.NumeroPedido AND eq.Assy = b.Assy
                LEFT JOIN (SELECT doc, MIN(val) AS PitBracket FROM pit_map GROUP BY doc) pv ON pv.doc = b.NumeroPedido
                LEFT JOIN pit_target_exists pte ON pte.NumeroPedido = b.NumeroPedido AND pte.Assy = b.Assy
                LEFT JOIN pit_qty_value pq ON pq.doc = b.NumeroPedido
                LEFT JOIN tb_opt_y_docs toy ON toy.doc = b.NumeroPedido
                LEFT JOIN tb_target_exists tte ON tte.NumeroPedido = b.NumeroPedido AND tte.Assy = b.Assy
                LEFT JOIN (SELECT doc, MIN(qty) AS qty FROM tb_qty_map GROUP BY doc) tq ON tq.doc = b.NumeroPedido
                LEFT JOIN (SELECT doc, Qty FROM wc_tb WHERE rn = 1) tlq ON tlq.doc = b.NumeroPedido
                ORDER BY
                    CASE WHEN b.PriorityOrder IS NULL THEN 1 ELSE 0 END,
                    b.PriorityOrder ASC,
                    b.Sequence ASC
    '''


def build_sequenced_orders_extender_query(assembly_value, done_qty_sql, extra_where_sql=''):
    """Consulta set-based para tarjetas C/W evitando subconsultas correlacionadas repetidas."""
    extra_where_clause = ''
    if extra_where_sql and extra_where_sql.strip():
        extra_where_clause = f"\n                  AND {extra_where_sql.strip()}"

    cwi_select_sql = build_pedidos_cabecera_optional_select_sql('CWI')

    return f'''
                WITH base AS (
                    SELECT
                        ps.Sequence AS Sequence,
                        ps.NumeroPedido AS SalesOrder,
                        ps.NumeroPedido AS NumeroPedido,
                        ps.UnidadesPedidas AS Qty,
                        ps.UnidadesPedidas AS UnidadesPedidas,
                        {done_qty_sql} AS DoneQty,
                        ps.Assy,
                        ps.Beam,
                        o.IF1,
                        o.IF2,
                        ISNULL(pc.CWT, '') AS CWT,
                        ISNULL(pc.DS, '') AS MS,
                        {cwi_select_sql},
                        ps.OFs AS WO,
                        ps.EX AS RawEX,
                        ps.PriorityOrder
                    FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
                    LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON pc.NumeroPedido = ps.NumeroPedido
                    LEFT JOIN OB.Omegas o WITH (NOLOCK) ON ps.Assy = o.Assy
                    WHERE UPPER(LTRIM(RTRIM(ps.Assembly))) = '{assembly_value}'{extra_where_clause}
                ),
                extender_value AS (
                    SELECT DISTINCT
                        b.NumeroPedido,
                        b.Assy,
                        o_tsd.Assy AS DerivedExtender
                    FROM base b
                    INNER JOIN OB.pedidos_exportados pe_lh WITH (NOLOCK)
                        ON pe_lh.sales_document = b.NumeroPedido
                    INNER JOIN OB.pedidos_exportados pe_tsd WITH (NOLOCK)
                        ON pe_tsd.sales_document = pe_lh.sales_document
                    INNER JOIN OB.Omegas o_tsd WITH (NOLOCK)
                        ON o_tsd.Assy = b.Assy
                       AND o_tsd.ExtenderVariable = pe_tsd.characteristic_value
                    WHERE pe_lh.characteristic_name = 'GRP_HSK_TYPE'
                      AND pe_lh.characteristic_value = 'LH'
                      AND pe_tsd.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
                      AND pe_tsd.characteristic_value IS NOT NULL
                      AND pe_tsd.characteristic_value <> ''
                ),
                extender_target AS (
                    SELECT DISTINCT
                        b.NumeroPedido,
                        b.Assy,
                        1 AS IsTargetAssy
                    FROM base b
                    INNER JOIN OB.pedidos_exportados pe_lh WITH (NOLOCK)
                        ON pe_lh.sales_document = b.NumeroPedido
                    INNER JOIN OB.pedidos_exportados pe WITH (NOLOCK)
                        ON pe.sales_document = pe_lh.sales_document
                    INNER JOIN OB.Omegas o_target WITH (NOLOCK)
                        ON (
                            pe.characteristic_name IN ('GRP_OMEGA_BRACKET_TYPE_HEAD', 'GRP_OMEGA_BRACKET_TYPE_TRAV')
                            AND o_target.OmegaType = pe.characteristic_value
                        )
                        OR (
                            pe.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
                            AND o_target.ExtenderVariable = pe.characteristic_value
                        )
                    WHERE pe_lh.characteristic_name = 'GRP_HSK_TYPE'
                      AND pe_lh.characteristic_value = 'LH'
                      AND pe.characteristic_value IS NOT NULL
                      AND pe.characteristic_value <> ''
                      AND o_target.Assy = b.Assy
                )
                SELECT
                    b.Sequence,
                    b.SalesOrder,
                    b.Qty,
                    b.DoneQty,
                    b.Assy,
                    b.Beam,
                    b.IF1,
                    b.IF2,
                    b.CWT,
                    b.MS,
                    b.CWI,
                    b.WO,
                    COALESCE(NULLIF(b.RawEX, ''), ev.DerivedExtender) AS Extender,
                    b.PriorityOrder,
                    CASE
                        WHEN COALESCE(NULLIF(b.RawEX, ''), ev.DerivedExtender) IS NULL THEN NULL
                        WHEN et.IsTargetAssy = 1 THEN CASE
                            WHEN b.UnidadesPedidas > 2 THEN b.UnidadesPedidas - 2
                            ELSE 0
                        END
                        ELSE NULL
                    END AS ExtenderQuantity
                FROM base b
                LEFT JOIN extender_value ev
                    ON ev.NumeroPedido = b.NumeroPedido
                   AND ev.Assy = b.Assy
                LEFT JOIN extender_target et
                    ON et.NumeroPedido = b.NumeroPedido
                   AND et.Assy = b.Assy
                ORDER BY
                    CASE WHEN b.PriorityOrder IS NULL THEN 1 ELSE 0 END,
                    b.PriorityOrder ASC,
                    b.Sequence ASC
    '''


def build_extender_value_case_sql(order_alias='ps'):
    """Construye la expresión SQL de extensor usando EX persistido, EX en líneas o derivándolo desde LH/TSD."""
    return f"""
                    COALESCE(
                        NULLIF(LTRIM(RTRIM({order_alias}.EX)), ''),
                        (
                            SELECT TOP 1 LTRIM(RTRIM(pl.Cod_Producto_Externo))
                            FROM OB.PedidosCabecera pc WITH (NOLOCK)
                            INNER JOIN OB.PedidosLineas pl WITH (NOLOCK)
                                ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
                            INNER JOIN OB.Omegas o_line WITH (NOLOCK)
                                ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
                            WHERE LTRIM(RTRIM(pc.NumeroPedido)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                              AND LTRIM(RTRIM(o_line.[W/C])) = 'EX'
                            ORDER BY pl.UnidadesPedidas DESC, pl.Cod_Producto_Externo ASC
                        ),
                        (
                            SELECT TOP 1 LTRIM(RTRIM(o_target.Assy))
                            FROM OB.pedidos_exportados pe_lh WITH (NOLOCK)
                            INNER JOIN OB.pedidos_exportados pe_tsd WITH (NOLOCK)
                                ON LTRIM(RTRIM(pe_tsd.sales_document)) = LTRIM(RTRIM(pe_lh.sales_document))
                            INNER JOIN OB.Omegas o_target WITH (NOLOCK)
                                ON LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM({order_alias}.Assy))
                               AND LTRIM(RTRIM(o_target.ExtenderVariable)) = LTRIM(RTRIM(pe_tsd.characteristic_value))
                            WHERE LTRIM(RTRIM(pe_lh.sales_document)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                              AND pe_lh.characteristic_name = 'GRP_HSK_TYPE'
                              AND UPPER(LTRIM(RTRIM(pe_lh.characteristic_value))) = 'LH'
                              AND pe_tsd.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
                              AND pe_tsd.characteristic_value IS NOT NULL
                              AND LTRIM(RTRIM(pe_tsd.characteristic_value)) <> ''
                                                            AND NOT EXISTS (
                                                                    SELECT 1
                                                                    FROM OB.PedidosCabecera pc WITH (NOLOCK)
                                                                    INNER JOIN OB.PedidosLineas pl WITH (NOLOCK)
                                                                            ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
                                                                    INNER JOIN OB.Omegas o_line WITH (NOLOCK)
                                                                            ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
                                                                    WHERE LTRIM(RTRIM(pc.NumeroPedido)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                                                                        AND LTRIM(RTRIM(o_line.[W/C])) = 'EX'
                                                            )
                        )
                    )
    """


def build_extender_quantity_case_sql(order_alias='ps'):
    """Construye la expresión SQL que identifica el Assy correcto para descontar 2 unidades."""
    return f"""
                    CASE
                        WHEN {build_extender_value_case_sql(order_alias).strip()} IS NULL THEN NULL
                        WHEN EXISTS (
                            SELECT 1
                            FROM OB.pedidos_exportados pe_lh WITH (NOLOCK)
                            INNER JOIN OB.pedidos_exportados pe WITH (NOLOCK)
                                ON LTRIM(RTRIM(pe.sales_document)) = LTRIM(RTRIM(pe_lh.sales_document))
                            INNER JOIN OB.Omegas o_target WITH (NOLOCK)
                                ON (
                                    pe.characteristic_name IN ('GRP_OMEGA_BRACKET_TYPE_HEAD', 'GRP_OMEGA_BRACKET_TYPE_TRAV')
                                    AND LTRIM(RTRIM(o_target.OmegaType)) = LTRIM(RTRIM(pe.characteristic_value))
                                )
                                OR (
                                    pe.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
                                    AND LTRIM(RTRIM(o_target.ExtenderVariable)) = LTRIM(RTRIM(pe.characteristic_value))
                                )
                                                        WHERE LTRIM(RTRIM(pe_lh.sales_document)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                                                            AND pe_lh.characteristic_name = 'GRP_HSK_TYPE'
                                                            AND UPPER(LTRIM(RTRIM(pe_lh.characteristic_value))) = 'LH'
                              AND pe.characteristic_value IS NOT NULL
                              AND LTRIM(RTRIM(pe.characteristic_value)) <> ''
                              AND LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM({order_alias}.Assy))
                        )
                        THEN CASE
                            WHEN {order_alias}.UnidadesPedidas > 2 THEN {order_alias}.UnidadesPedidas - 2
                            ELSE 0
                        END
                        ELSE NULL
                    END AS ExtenderQuantity
    """


def build_extender_quantity_value_case_sql(order_alias='ps'):
    """Construye la expresión SQL de cantidad de extensor sin alias para reutilizarla."""
    return f"""
                    CASE
                        WHEN {build_extender_value_case_sql(order_alias).strip()} IS NULL THEN NULL
                        WHEN EXISTS (
                            SELECT 1
                            FROM OB.pedidos_exportados pe_lh WITH (NOLOCK)
                            INNER JOIN OB.pedidos_exportados pe WITH (NOLOCK)
                                ON LTRIM(RTRIM(pe.sales_document)) = LTRIM(RTRIM(pe_lh.sales_document))
                            INNER JOIN OB.Omegas o_target WITH (NOLOCK)
                                ON (
                                    pe.characteristic_name IN ('GRP_OMEGA_BRACKET_TYPE_HEAD', 'GRP_OMEGA_BRACKET_TYPE_TRAV')
                                    AND LTRIM(RTRIM(o_target.OmegaType)) = LTRIM(RTRIM(pe.characteristic_value))
                                )
                                OR (
                                    pe.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_TSD'
                                    AND LTRIM(RTRIM(o_target.ExtenderVariable)) = LTRIM(RTRIM(pe.characteristic_value))
                                )
                                                        WHERE LTRIM(RTRIM(pe_lh.sales_document)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                                                            AND pe_lh.characteristic_name = 'GRP_HSK_TYPE'
                                                            AND UPPER(LTRIM(RTRIM(pe_lh.characteristic_value))) = 'LH'
                              AND pe.characteristic_value IS NOT NULL
                              AND LTRIM(RTRIM(pe.characteristic_value)) <> ''
                              AND LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM({order_alias}.Assy))
                        )
                        THEN CASE
                            WHEN {order_alias}.UnidadesPedidas > 2 THEN {order_alias}.UnidadesPedidas - 2
                            ELSE 0
                        END
                        ELSE NULL
                    END
    """


def build_tie_bracket_target_quantity_value_sql(order_alias='ps'):
    """Construye la expresión SQL de cantidad TB sin alias para reutilizarla."""
    return f"""
                    CASE
                        WHEN COALESCE(NULLIF(LTRIM(RTRIM({order_alias}.TB)), ''), tbext.WCLine) IS NULL THEN NULL
                        WHEN EXISTS (
                            SELECT 1
                            FROM OB.pedidos_exportados pe_opt WITH (NOLOCK)
                            INNER JOIN OB.pedidos_exportados pe_type WITH (NOLOCK)
                                ON LTRIM(RTRIM(pe_type.sales_document)) = LTRIM(RTRIM(pe_opt.sales_document))
                            INNER JOIN OB.Omegas o_target WITH (NOLOCK)
                                ON REPLACE(UPPER(LTRIM(RTRIM(o_target.OmegaType))), ' LH', '')
                                 = REPLACE(UPPER(LTRIM(RTRIM(pe_type.characteristic_value))), ' LH', '')
                            WHERE LTRIM(RTRIM(pe_opt.sales_document)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                              AND pe_opt.characteristic_name = 'GRP_TIE_BRACKET_OPT'
                              AND UPPER(LTRIM(RTRIM(pe_opt.characteristic_value))) = 'Y'
                              AND pe_type.characteristic_name = 'GRP_TIE_BRACKET_TYPE'
                              AND pe_type.characteristic_value IS NOT NULL
                              AND LTRIM(RTRIM(pe_type.characteristic_value)) <> ''
                              AND LTRIM(RTRIM(o_target.Assy)) = LTRIM(RTRIM({order_alias}.Assy))
                        )
                        THEN (
                            SELECT TOP 1 TRY_CAST(LTRIM(RTRIM(pe_qty.characteristic_value)) AS INT)
                            FROM OB.pedidos_exportados pe_qty WITH (NOLOCK)
                            WHERE LTRIM(RTRIM(pe_qty.sales_document)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                              AND pe_qty.characteristic_name = 'GRP_TIE_BRACKET_QTY'
                              AND pe_qty.characteristic_value IS NOT NULL
                              AND LTRIM(RTRIM(pe_qty.characteristic_value)) <> ''
                        )
                        ELSE NULL
                    END
    """


def build_tie_bracket_fallback_quantity_value_sql(order_alias='ps'):
    """Construye el fallback 1/1 para TB cuando no existan variables o OPT sea N."""
    return f"""
                    CASE
                        WHEN COALESCE(NULLIF(LTRIM(RTRIM({order_alias}.TB)), ''), tbext.WCLine) IS NULL THEN NULL
                        WHEN EXISTS (
                            SELECT 1
                            FROM OB.pedidos_exportados pe_opt_y WITH (NOLOCK)
                            WHERE LTRIM(RTRIM(pe_opt_y.sales_document)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                              AND pe_opt_y.characteristic_name = 'GRP_TIE_BRACKET_OPT'
                              AND UPPER(LTRIM(RTRIM(pe_opt_y.characteristic_value))) = 'Y'
                        ) THEN NULL
                        WHEN {build_extender_quantity_value_case_sql(order_alias).strip()} IS NOT NULL THEN 1
                        ELSE NULL
                    END
    """


def build_tie_bracket_line_quantity_value_sql(order_alias='ps'):
    """Obtiene la cantidad real de la línea TB del pedido.

    Los pedidos que no son LH no siempre incluyen las variables
    GRP_TIE_BRACKET_*. En esos casos la fuente fiable es la línea del pedido
    identificada como W/C = TB en el maestro de Omegas.
    """
    return f"""
                    (
                        SELECT TOP 1 pl.UnidadesPedidas
                        FROM OB.PedidosCabecera pc WITH (NOLOCK)
                        INNER JOIN OB.PedidosLineas pl WITH (NOLOCK)
                            ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
                        INNER JOIN OB.Omegas o_line WITH (NOLOCK)
                            ON LTRIM(RTRIM(o_line.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
                        WHERE LTRIM(RTRIM(pc.NumeroPedido)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                          AND LTRIM(RTRIM(o_line.[W/C])) = 'TB'
                        ORDER BY pl.UnidadesPedidas DESC, pl.Cod_Producto_Externo ASC
                    )
    """


def build_pit_bracket_value_sql(order_alias='ps'):
    """Devuelve el valor del bracket PIT desde la característica GRP_OMEGA_BRACKET_TYPE_PIT."""
    return f"""
                (
                    SELECT TOP 1 LTRIM(RTRIM(pe_pit.characteristic_value))
                    FROM OB.pedidos_exportados pe_pit WITH (NOLOCK)
                    WHERE LTRIM(RTRIM(pe_pit.sales_document)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                      AND pe_pit.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_PIT'
                      AND pe_pit.characteristic_value IS NOT NULL
                      AND LTRIM(RTRIM(pe_pit.characteristic_value)) <> ''
                )
    """


def build_pit_bracket_quantity_value_sql(order_alias='ps', omega_alias='o'):
    """Devuelve la cantidad de etiquetas PIT solo para el Assy cuyo OmegaType
    coincide con el último tipo PIT importado para el pedido."""
    return f"""
                    CASE
                        WHEN REPLACE(UPPER(LTRIM(RTRIM({omega_alias}.OmegaType))), ' LH', '') = REPLACE(UPPER(LTRIM(RTRIM((
                            SELECT TOP 1 pe_type.characteristic_value
                            FROM OB.pedidos_exportados pe_type WITH (NOLOCK)
                            WHERE LTRIM(RTRIM(pe_type.sales_document)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                              AND pe_type.characteristic_name = 'GRP_OMEGA_BRACKET_TYPE_PIT'
                              AND pe_type.characteristic_value IS NOT NULL
                              AND LTRIM(RTRIM(pe_type.characteristic_value)) <> ''
                            ORDER BY pe_type.fecha_importacion DESC, pe_type.id_importacion DESC
                        )))), ' LH', '')
                        THEN (
                            SELECT TOP 1 TRY_CAST(LTRIM(RTRIM(pe_qty.characteristic_value)) AS INT)
                            FROM OB.pedidos_exportados pe_qty WITH (NOLOCK)
                            WHERE LTRIM(RTRIM(pe_qty.sales_document)) = LTRIM(RTRIM({order_alias}.NumeroPedido))
                              AND pe_qty.characteristic_name = 'GRP_OMEGA_BRACKET_QTY_PIT'
                              AND pe_qty.characteristic_value IS NOT NULL
                              AND LTRIM(RTRIM(pe_qty.characteristic_value)) <> ''
                            ORDER BY pe_qty.fecha_importacion DESC, pe_qty.id_importacion DESC
                        )
                        ELSE NULL
                    END
    """


def build_tb_cards_quantity_case_sql(order_alias='ps', require_extender=False, alias_name=None):
    """Construye la cantidad a mostrar en tarjetas TB combinando objetivo TB y objetivo de extensor."""
    alias_name = alias_name or ('ExtenderQuantity' if require_extender else 'Qty')
    line_quantity_fallback = '' if require_extender else f''',
                        {build_tie_bracket_line_quantity_value_sql(order_alias).strip()}'''
    return f"""
                    COALESCE(
                        {build_tie_bracket_target_quantity_value_sql(order_alias).strip()},
                        {build_tie_bracket_fallback_quantity_value_sql(order_alias).strip()}{line_quantity_fallback}
                    ) AS {alias_name}
    """


def build_tb_cards_quantity_predicate_sql(order_alias='ps'):
    """Devuelve el predicado SQL para quedarnos solo con filas objetivo en tarjetas TB."""
    return f"""
                        {build_tie_bracket_target_quantity_value_sql(order_alias).strip()} IS NOT NULL
                        OR {build_tie_bracket_fallback_quantity_value_sql(order_alias).strip()} IS NOT NULL
                        OR {build_tie_bracket_line_quantity_value_sql(order_alias).strip()} IS NOT NULL
    """


@app.route('/api/login', methods=['POST'])
def login():
    """
    Endpoint de autenticación.
    Soporta contraseñas en texto plano (legacy) y hash pbkdf2 (si se migra).
    """
    data = request.get_json(silent=True) or {}
    usuario = str(data.get('usuario', '')).strip()
    password = str(data.get('password', '')).strip()
    
    if not usuario or not password:
        return jsonify({'success': False, 'message': 'Usuario y contraseña son requeridos'}), 400
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                raise Exception('No se pudo conectar con DataLakeSCCZ')
            cursor = conn.cursor()
            row = buscar_usuario_cz(
                cursor,
                'Id_Usuario, Num_Operario, Nombre, Contrasena, Nivel_Permisos, Roles',
                usuario
            )
            
            if not row:
                logging.warning(f"[LOGIN] Usuario no encontrado: {usuario}")
                return jsonify({'success': False, 'message': 'Usuario no encontrado'}), 401
            
            stored_password = row[3]
            password_valid = verificar_password_usuario(stored_password, password)
            
            if password_valid:
                logging.info(f"[LOGIN] Login correcto para usuario={usuario} nombre={row[2]}")
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
                logging.warning(f"[LOGIN] Contraseña incorrecta para usuario={usuario}")
                return jsonify({'success': False, 'message': 'Contraseña incorrecta'}), 401
                
    except Exception as e:
        logging.error(f"Error en /api/login: {str(e)}", exc_info=True)
        response = {'success': False, 'message': 'Error interno del servidor'}
        if DEV_MODE:
            response['error'] = str(e)
        return jsonify(response), 500
    
@app.route('/api/cambiar_password', methods=['POST'])
def cambiar_password():
    """
    Endpoint para cambiar contraseña.
    La nueva contraseña se guarda con hash pbkdf2.
    """
    data = request.get_json(silent=True) or {}
    usuario = str(data.get('usuario', '')).strip()
    actual = str(data.get('actual', '')).strip()
    nueva = str(data.get('nueva', '')).strip()
    
    if not usuario or not actual or not nueva:
        return jsonify({'success': False, 'message': 'Todos los campos son requeridos'}), 400
    
    if len(nueva) < 6:
        return jsonify({'success': False, 'message': 'La contraseña debe tener al menos 6 caracteres'}), 400
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                raise Exception('No se pudo conectar con DataLakeSCCZ')
            cursor = conn.cursor()
            row = buscar_usuario_cz(cursor, 'Id_Usuario, Contrasena', usuario)
            
            if not row:
                return jsonify({'success': False, 'message': 'Usuario no encontrado'}), 401
            
            id_usuario = row[0]
            stored_password = row[1]
            
            # Verificar contraseña actual
            password_valid = verificar_password_usuario(stored_password, actual)
            
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
        logging.error(f"Error en /api/cambiar_password: {str(e)}", exc_info=True)
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
            if conn is None:
                raise Exception('No se pudo conectar con DataLakeSCCZ')
            cursor = conn.cursor()

            if num_operario is not None and str(num_operario).strip().isdigit():
                cursor.execute("""
                    SELECT Id_Usuario, Nombre, Nivel_Permisos, Roles 
                    FROM OB.Usuarios_CZ_hash 
                    WHERE Id_Usuario = ? OR Num_Operario = ?
                """, (user_id, int(str(num_operario).strip())))
            else:
                cursor.execute("""
                    SELECT Id_Usuario, Nombre, Nivel_Permisos, Roles 
                    FROM OB.Usuarios_CZ_hash 
                    WHERE Id_Usuario = ?
                """, (user_id,))
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
# ENDPOINT PARA CONSULTAR STOCK DE OMEGAS EN SAP
# ====================================================================================
@app.route('/api/stock_sap_omegas', methods=['GET'])
@cross_origin()
def get_stock_sap_omegas():
    """
    Consulta el stock de todas las Omegas en SAP (tabla MARD, centro 2000, sin almacén 2055).
    Guarda el resultado en stock_sap_omegas.json y lo devuelve como JSON.
    """
    # Consulta SAP temporalmente desactivada para evitar llamadas externas.
    # La interfaz seguirá cargando el último stock disponible mediante
    # /api/stock_sap_cached al abrir la pantalla.
    return jsonify({
        "error": "La consulta de stock SAP está temporalmente desactivada."
    }), 503

    """Bloque conservado para reactivar la consulta SAP.
    try:
        # 1. Obtener todos los códigos de Omega de nuestra base de datos
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
            cursor = conn.cursor()
            cursor.execute("SELECT Assy FROM OB.Omegas")
            omegas = [row[0] for row in cursor.fetchall()]

        if not omegas:
            return jsonify([]), 200

        print(f"[SAP STOCK] Consultando {len(omegas)} omegas en SAP...")

        # 2. Enviar lista de materiales a SAP como JSON en el body
        response = requests.post(
            SAP_STOCK_URL,
            json=omegas,
            auth=(SAP_USER, SAP_PASSWORD),
            headers={'sap-client': SAP_CLIENT},
            timeout=30
        )
        response.raise_for_status()
        sap_data = response.json()

        # 3. Guardar en stock_sap_omegas.json en la raíz del proyecto
        json_path = os.path.join(BASE_DIR, 'stock_sap_omegas.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
                'total': len(sap_data),
                'data': sap_data
            }, f, ensure_ascii=False, indent=2)

        print(f"[SAP STOCK] Consulta completada: {len(sap_data)} registros. Guardado en {json_path}")
        return jsonify(sap_data), 200

    except requests.exceptions.ConnectionError:
        logging.error("[SAP STOCK] No se pudo conectar al servidor SAP")
        return jsonify({"error": "No se pudo conectar al servidor SAP"}), 503
    except requests.exceptions.Timeout:
        logging.error("[SAP STOCK] Timeout al consultar SAP")
        return jsonify({"error": "Timeout al consultar SAP (>30s)"}), 504
    except requests.exceptions.HTTPError as e:
        logging.error(f"[SAP STOCK] Error HTTP de SAP: {e}")
        return jsonify({"error": f"SAP respondió con error: {str(e)}"}), 502
    except Exception as e:
        logging.error(f"[SAP STOCK] Error inesperado: {e}")
        return jsonify({"error": str(e)}), 500
    """


# ====================================================================================
# ENDPOINT PARA SERVIR EL CACHÉ LOCAL DE STOCK SAP (sin llamar a SAP)
# ====================================================================================
@app.route('/api/stock_sap_cached', methods=['GET'])
@cross_origin()
def get_stock_sap_cached():
    """
    Devuelve el último resultado de SAP guardado en stock_sap_omegas.json.
    No llama a SAP - sirve el caché local.
    """
    json_path = os.path.join(BASE_DIR, 'stock_sap_omegas.json')
    if not os.path.exists(json_path):
        return jsonify({"data": [], "timestamp": None}), 200
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            cached = json.load(f)
        return jsonify(cached), 200
    except Exception as e:
        logging.error(f"[SAP CACHE] Error leyendo caché: {e}")
        return jsonify({"data": [], "timestamp": None}), 200


# ====================================================================================
# ENDPOINTS PARA GESTIONAR CORREOS DE AVISOS SAP STOCK (BD: OB.Notificaciones)
# ====================================================================================

def _leer_emails_bd():
    """Lee correos_alertas de OB.Notificaciones y devuelve una lista de strings."""
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                print("[SAP EMAILS DEBUG] Sin conexión a DataLakeSCCZ")
                return []
            cursor = conn.cursor()
            cursor.execute("SELECT correos_alertas FROM OB.Notificaciones WHERE id_config = 1")
            row = cursor.fetchone()
            if not row or not row[0]:
                print("[SAP EMAILS DEBUG] Sin fila o correos_alertas vacío")
                return []
            raw = row[0]
            print(f"[SAP EMAILS DEBUG] Valor raw de BD: {repr(raw)}")
            result = [e.strip() for e in raw.replace(',', ';').split(';') if e.strip()]
            print(f"[SAP EMAILS DEBUG] Lista parseada: {result}")
            return result
    except Exception as e:
        print(f"[SAP EMAILS DEBUG] Excepción: {e}")
        logging.error(f"[SAP EMAILS] Error leyendo BD: {e}")
        return []


def _guardar_emails_bd(emails):
    """Persiste la lista de emails en OB.Notificaciones.correos_alertas y recarga CORREOS_ALERTAS."""
    global CORREOS_ALERTAS
    valor = '; '.join(emails)
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                raise Exception('Sin conexión a DataLakeSCCZ')
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE OB.Notificaciones SET correos_alertas = ?, ultima_actualizacion = GETDATE() WHERE id_config = 1",
                valor
            )
        CORREOS_ALERTAS = list(emails)
        return True
    except Exception as e:
        logging.error(f"[SAP EMAILS] Error guardando en BD: {e}")
        return False


@app.route('/api/sap/emails', methods=['GET'])
@cross_origin()
def get_sap_emails():
    """Devuelve la lista de correos guardados en OB.Notificaciones."""
    return jsonify({'emails': _leer_emails_bd()})


@app.route('/api/sap/emails', methods=['POST'])
@cross_origin()
def manage_sap_emails():
    """Añade o elimina un correo en OB.Notificaciones.correos_alertas."""
    data   = request.get_json() or {}
    action = data.get('action')
    email  = (data.get('email') or '').strip()

    if not email or '@' not in email:
        return jsonify({'error': 'Email inválido'}), 400

    emails = _leer_emails_bd()

    if action == 'add':
        if email not in emails:
            emails.append(email)
    elif action == 'remove':
        emails = [e for e in emails if e != email]
    else:
        return jsonify({'error': 'Acción no válida'}), 400

    if not _guardar_emails_bd(emails):
        return jsonify({'error': 'Error al guardar en base de datos'}), 500

    return jsonify({'emails': emails})


# ====================================================================================
# FUNCIÓN Y ENDPOINT PARA ENVÍO DE CORREO DE DIFERENCIAS SAP vs APP
# ====================================================================================
def enviar_correo_sap_diff(diferencias, idioma='es'):
    """Envía un correo HTML con las diferencias de stock entre la app y SAP."""
    # Recargar config de BD por si fue actualizada en caliente
    cargar_config_smtp()

    if not SMTP_SERVIDOR or not SMTP_CORREO_ORIGEN:
        logging.warning("[SAP EMAIL] SMTP no configurado — correo no enviado.")
        return False

    # Destinatarios: vienen de CORREOS_ALERTAS (cargados desde OB.Notificaciones)
    emails = list(CORREOS_ALERTAS)

    if not emails:
        logging.warning("[SAP EMAIL] Sin destinatarios en OB.Notificaciones — correo no enviado.")
        return False

    textos = {
        'es': {
            'asunto':    'Diferencias Stock SAP vs Aplicación',
            'titulo':    'Diferencias detectadas entre Stock SAP y Aplicación',
            'col_omega': 'Omega',
            'col_app':   'Stock App',
            'col_sap':   'Stock SAP',
            'col_dif':   'Diferencia',
            'mensaje':   f'Se han detectado {len(diferencias)} omega(s) con diferencia de stock entre la aplicación y SAP.',
            'pie':       'Sistema de Gestión Omegas',
        },
        'en': {
            'asunto':    'SAP vs Application Stock Differences',
            'titulo':    'Stock differences detected between SAP and Application',
            'col_omega': 'Omega',
            'col_app':   'App Stock',
            'col_sap':   'SAP Stock',
            'col_dif':   'Difference',
            'mensaje':   f'{len(diferencias)} omega(s) with stock differences detected between application and SAP.',
            'pie':       'Omegas Management System',
        },
        'cz': {
            'asunto':    'Rozdíly skladu SAP vs Aplikace',
            'titulo':    'Zjištěny rozdíly skladu mezi SAP a aplikací',
            'col_omega': 'Omega',
            'col_app':   'Sklad App',
            'col_sap':   'Sklad SAP',
            'col_dif':   'Rozdíl',
            'mensaje':   f'Bylo zjištěno {len(diferencias)} omega(s) s rozdílem skladu mezi aplikací a SAP.',
            'pie':       'Systém správy Omega',
        },
    }
    t = textos.get(idioma, textos['es'])

    filas_html = ''
    for d in diferencias:
        dif   = d['stock_sap'] - d['stock_app']
        color = '#d9534f' if dif < 0 else '#5cb85c'
        signo = '+' if dif > 0 else ''
        filas_html += f"""
        <tr>
          <td style="padding:8px;border:1px solid #ddd;">{d['omega']}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:center;">{d['stock_app']}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:center;">{d['stock_sap']}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:center;color:{color};font-weight:bold;">{signo}{dif}</td>
        </tr>"""

    cuerpo_html = f"""<html>
<body style="font-family:Arial,sans-serif;margin:0;padding:0;">
  <div style="background:#2c3e50;color:white;padding:20px;">
    <h2 style="margin:0;">⚠️ {t['titulo']}</h2>
  </div>
  <div style="padding:20px;border:1px solid #ddd;">
    <p><strong>Fecha:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
    <p>{t['mensaje']}</p>
    <table style="border-collapse:collapse;width:100%;margin-top:10px;">
      <thead>
        <tr style="background:#34495e;color:white;">
          <th style="padding:10px;border:1px solid #ddd;">{t['col_omega']}</th>
          <th style="padding:10px;border:1px solid #ddd;">{t['col_app']}</th>
          <th style="padding:10px;border:1px solid #ddd;">{t['col_sap']}</th>
          <th style="padding:10px;border:1px solid #ddd;">{t['col_dif']}</th>
        </tr>
      </thead>
      <tbody>{filas_html}</tbody>
    </table>
  </div>
  <div style="background:#f5f5f5;padding:10px;font-size:12px;color:#777;">{t['pie']}</div>
</body>
</html>"""

    try:
        msg = MIMEMultipart()
        msg['From']    = f"{SMTP_NOMBRE_REMITENTE} <{SMTP_CORREO_ORIGEN}>"
        msg['To']      = ', '.join(emails)
        msg['Subject'] = f"[OMEGAS] {t['asunto']}"
        msg.attach(MIMEText(cuerpo_html, 'html'))

        server = smtplib.SMTP(SMTP_SERVIDOR, SMTP_PUERTO, timeout=10)
        if SMTP_USAR_TLS:
            server.starttls()
        if SMTP_USUARIO and SMTP_CONTRASENA:
            server.login(SMTP_USUARIO, SMTP_CONTRASENA)
        server.send_message(msg)
        server.quit()
        logging.info(f"[SAP EMAIL] Correo enviado a {len(emails)} destinatarios ({len(diferencias)} diferencias)")
        return True
    except Exception as e:
        logging.error(f"[SAP EMAIL] Error enviando correo: {e}")
        return False


@app.route('/api/sap/send-diff-email', methods=['POST'])
@cross_origin()
def send_sap_diff_email():
    """Recibe una lista de diferencias y envía un correo HTML a los destinatarios configurados."""
    data        = request.get_json() or {}
    diferencias = data.get('diferencias', [])
    idioma      = data.get('idioma', 'es')

    if not diferencias:
        return jsonify({'error': 'Sin diferencias que reportar'}), 400

    ok = enviar_correo_sap_diff(diferencias, idioma)
    if ok:
        return jsonify({'success': True, 'enviados': len(diferencias)}), 200
    else:
        return jsonify({'error': 'Error enviando correo. Verifica la configuración SMTP o los destinatarios.'}), 500


# ====================================================================================
# ENDPOINT PARA LISTAR TODOS LOS OMEGAS
# ====================================================================================
SAP_SCHEDULER_CONFIG_FILE = os.path.join(BASE_DIR, 'sap_scheduler_config.json')

@app.route('/api/sap/scheduler-config', methods=['GET'])
@cross_origin()
def get_sap_scheduler_config():
    """Devuelve la configuración del scheduler SAP desde sap_scheduler_config.json."""
    if not os.path.exists(SAP_SCHEDULER_CONFIG_FILE):
        return jsonify({'enabled': False, 'time': '00:00', 'emailLang': 'es', 'lastRun': None})
    try:
        with open(SAP_SCHEDULER_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    except Exception as e:
        logging.error(f"[SCHED CONFIG] Error leyendo: {e}")
        return jsonify({'enabled': False, 'time': '00:00', 'emailLang': 'es', 'lastRun': None})


@app.route('/api/sap/scheduler-config', methods=['POST'])
@cross_origin()
def save_sap_scheduler_config():
    """Guarda la configuración del scheduler SAP en sap_scheduler_config.json."""
    data = request.get_json() or {}
    cfg = {
        'enabled':   bool(data.get('enabled', False)),
        'time':      (data.get('time') or '00:00').strip(),
        'emailLang': (data.get('emailLang') or 'es').strip(),
        'lastRun':   data.get('lastRun', None),
    }
    try:
        with open(SAP_SCHEDULER_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return jsonify({'success': True})
    except Exception as e:
        logging.error(f"[SCHED CONFIG] Error guardando: {e}")
        return jsonify({'error': str(e)}), 500
@app.route('/api/omegas/all', methods=['GET'])
@cross_origin()
def get_all_omegas():
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({"error": "No se pudo conectar a la base de datos Digitalizacion"}), 500
            cursor = conn.cursor()
            query = "SELECT OmegaID, Assy, Beam, IF1, IF2, [W/C], ExtenderVariable, OmegaType FROM OB.Omegas ORDER BY Assy;"
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

    campos_validos = ['Beam', 'IF1', 'IF2', 'W/C', 'ExtenderVariable', 'OmegaType']
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
            value = normalize_wc_value(data[campo]) if campo == 'W/C' else data[campo]
            params.append(value)

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
    print(f"[BULK INSERT] Datos recibidos: {data}")
    if not data or not isinstance(data, list) or not data:
        return jsonify({'success': False, 'error': 'No se recibieron datos válidos.'}), 400

    # Solo columnas válidas
    columns = ['Assy', 'Beam', 'IF1', 'IF2', 'W/C', 'ExtenderVariable', 'OmegaType']
    values = []
    for i, row in enumerate(data):
        print(f"[BULK INSERT] Fila {i}: {row}")
        # Construir tupla con valores en el orden correcto
        # Convertir strings vacíos a None para campos opcionales
        values_list = []
        for col in columns:
            val = row.get(col)
            if col == 'W/C':
                val = normalize_wc_value(val)
            # Si es string vacío y no es Assy (requerido), convertir a None
            if val == '' and col != 'Assy':
                val = None
            values_list.append(val)
        values_tuple = tuple(values_list)
        print(f"[BULK INSERT] Tupla {i}: {values_tuple}")
        values.append(values_tuple)

    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'success': False, 'error': 'No se pudo conectar a la base de datos'}), 500
            cursor = conn.cursor()
            insert_columns = ['Assy', 'Beam', 'IF1', 'IF2', '[W/C]', 'ExtenderVariable', 'OmegaType']
            placeholders = ', '.join(['?' for _ in columns])
            sql = f"INSERT INTO OB.Omegas ({', '.join(insert_columns)}) VALUES ({placeholders})"
            print(f"[BULK INSERT] SQL: {sql}")
            print(f"[BULK INSERT] Values: {values}")
            cursor.executemany(sql, values)
            print(f"[BULK INSERT] ✅ Insertadas {cursor.rowcount} filas")
        return jsonify({'success': True, 'inserted': len(values)})
    except Exception as e:
        print(f"[BULK INSERT] ❌ Error: {e}")
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


@app.route('/api/clinching-master/all', methods=['GET'])
@cross_origin()
def get_all_clinching_master_rows():
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'error': 'No se pudo conectar a la base de datos Digitalizacion'}), 500

            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT Id_ClinchingSubOmegaMaster, SubOmega, Beam, GuideInterface, IsActive, SourceNote
                FROM OB.ClinchingSubOmegaMaster
                ORDER BY SubOmega ASC;
                """
            )
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
            return jsonify(result), 200
    except Exception as e:
        logging.error(f'Error al obtener Clinching master: {e}')
        return jsonify({'error': 'Error interno del servidor'}), 500


@app.route('/api/clinching-master/update', methods=['PATCH'])
@cross_origin()
def update_clinching_master_row():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No se recibieron datos.'}), 400

    campos_validos = ['Beam', 'GuideInterface', 'IsActive', 'SourceNote']
    set_clauses = []
    params = []

    if 'newSubOmega' in data and data['newSubOmega']:
        set_clauses.append('[SubOmega] = ?')
        params.append(data['newSubOmega'])

    for campo in campos_validos:
        if campo in data:
            set_clauses.append(f'[{campo}] = ?')
            params.append(data[campo])

    if not set_clauses:
        return jsonify({'success': False, 'error': 'No hay campos para actualizar.'}), 400

    if 'Beam' in data and not str(data.get('Beam') or '').strip():
        return jsonify({'success': False, 'error': 'Beam es obligatorio.'}), 400
    if 'GuideInterface' in data and not str(data.get('GuideInterface') or '').strip():
        return jsonify({'success': False, 'error': 'Guide Interface es obligatorio.'}), 400
    if 'newSubOmega' in data and not str(data.get('newSubOmega') or '').strip():
        return jsonify({'success': False, 'error': 'Sub-Omega es obligatorio.'}), 400

    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            if 'Id_ClinchingSubOmegaMaster' in data and data['Id_ClinchingSubOmegaMaster'] is not None:
                sql = f"UPDATE OB.ClinchingSubOmegaMaster SET {', '.join(set_clauses)}, [UpdatedAt] = GETDATE() WHERE Id_ClinchingSubOmegaMaster = ?"
                params.append(data['Id_ClinchingSubOmegaMaster'])
            elif 'SubOmega' in data and data['SubOmega']:
                sql = f"UPDATE OB.ClinchingSubOmegaMaster SET {', '.join(set_clauses)}, [UpdatedAt] = GETDATE() WHERE SubOmega = ?"
                params.append(data['SubOmega'])
            else:
                return jsonify({'success': False, 'error': 'No se proporcionó Id_ClinchingSubOmegaMaster ni SubOmega.'}), 400

            cursor.execute(sql, params)
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'error': 'No se encontró la fila a actualizar.'}), 404

            clear_clinching_master_cache()
            return jsonify({'success': True})
    except Exception as e:
        logging.error(f'Error al actualizar Clinching master: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/clinching-master/bulk-insert', methods=['POST'])
@cross_origin()
def bulk_insert_clinching_master_rows():
    data = request.get_json()
    if not data or not isinstance(data, list) or not data:
        return jsonify({'success': False, 'error': 'No se recibieron datos válidos.'}), 400

    rows_to_insert = []
    for row in data:
        subomega = str(row.get('SubOmega') or '').strip()
        beam = str(row.get('Beam') or '').strip()
        guide_interface = str(row.get('GuideInterface') or '').strip()
        if not subomega or not beam or not guide_interface:
            return jsonify({'success': False, 'error': 'SubOmega, Beam y GuideInterface son obligatorios.'}), 400
        rows_to_insert.append((subomega, beam, guide_interface, 1, row.get('SourceNote') or 'Manual maintenance'))

    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'success': False, 'error': 'No se pudo conectar a la base de datos'}), 500

            cursor = conn.cursor()
            sql = """
                INSERT INTO OB.ClinchingSubOmegaMaster (SubOmega, Beam, GuideInterface, IsActive, SourceNote)
                VALUES (?, ?, ?, ?, ?)
            """
            cursor.executemany(sql, rows_to_insert)
            clear_clinching_master_cache()
        return jsonify({'success': True, 'inserted': len(rows_to_insert)})
    except Exception as e:
        logging.error(f'Error al insertar Clinching master: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/clinching-master/delete', methods=['POST'])
@cross_origin()
def delete_clinching_master_row():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No se recibieron datos.'}), 400

    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            if 'Id_ClinchingSubOmegaMaster' in data and data['Id_ClinchingSubOmegaMaster'] is not None:
                cursor.execute(
                    'DELETE FROM OB.ClinchingSubOmegaMaster WHERE Id_ClinchingSubOmegaMaster = ?',
                    (data['Id_ClinchingSubOmegaMaster'],)
                )
            elif 'SubOmega' in data and data['SubOmega']:
                cursor.execute(
                    'DELETE FROM OB.ClinchingSubOmegaMaster WHERE SubOmega = ?',
                    (data['SubOmega'],)
                )
            else:
                return jsonify({'success': False, 'error': 'No se proporcionó Id_ClinchingSubOmegaMaster ni SubOmega.'}), 400

            if cursor.rowcount == 0:
                return jsonify({'success': False, 'error': 'No se encontró la fila a eliminar.'}), 404

            clear_clinching_master_cache()
            return jsonify({'success': True})
    except Exception as e:
        logging.error(f'Error al eliminar Clinching master: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
    
# ====================================================================================
# ENDPOINT PARA CONSULTAR UN RESUMEN DE PEDIDOS PENDIENTES
# ====================================================================================
@app.route('/api/summary', methods=['GET'])
@cross_origin()
def get_summary_omegas():
    """
    Endpoint optimizado que usa la vista OB.V_PedidosSummary_Pendientes_EX
    para obtener todos los pedidos pendientes de secuenciar con detección automática de EX y TB.
    """
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({"error": "No se pudo conectar a la base de datos Digitalizacion"}), 500

            cursor = conn.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;")

            # Esta vista alimenta una pantalla de consulta; aceptamos lectura no bloqueante
            # para evitar deadlocks cuando otras tareas refrescan pedidos en paralelo.
            query = """
                SELECT 
                    vp.*
                FROM OB.V_PedidosSummary_Pendientes_EX vp
            """

            deadlock_error = None
            rows = []
            columns = []
            for attempt in range(3):
                try:
                    cursor.execute(query)
                    rows = cursor.fetchall()
                    columns = [desc[0] for desc in cursor.description]
                    deadlock_error = None
                    break
                except pyodbc.Error as ex:
                    if '1205' not in str(ex):
                        raise

                    deadlock_error = ex
                    logging.warning(f"[/api/summary] Deadlock detectado en intento {attempt + 1}/3: {ex}")
                    if attempt == 2:
                        raise
                    time.sleep(0.2)

            if deadlock_error is not None:
                raise deadlock_error

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
            "INSERT INTO OB.PedidosSecuenciados (NumeroPedido, Assy, SequenceValue, OFs, AssignedStock, AssignedStockBeam) VALUES (?, ?, ?, ?, 0, 0)",
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
    Devuelve el stock actual de todos los Beams desde la vista OB.Stock_Beams_New.
    """
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            query = """
                SELECT BeamID, Cod_producto AS BeamCode, Entradas, Salidas, StockActual AS CurrentStock
                FROM OB.Stock_Beams_New
                ORDER BY Cod_producto;
            """
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
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            sql = "{CALL OB.sp_Reset_Beam_Stock(?, ?, ?, ?)}"
            params = (beam_id, int(real_stock_count), usuario_id, 'AJUSTE_MANUAL')
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


@app.route('/api/beam_wos', methods=['POST'])
@cross_origin()
def get_wos_for_beams_batch():
    """
    Devuelve las WO activas para múltiples Beams en una sola consulta a MAPEX.
    Espera JSON: { "beamCodes": ["BEAM1", "BEAM2"] }
    """
    payload = request.get_json(silent=True) or {}
    beam_codes = payload.get('beamCodes') or []
    normalized_codes = sorted({str(code).strip() for code in beam_codes if code and str(code).strip()})

    if not normalized_codes:
        return jsonify({})

    cache_key = f"beam_wos_batch:{'|'.join(normalized_codes)}"
    cached_result = get_cached_endpoint_response(cache_key)
    if cached_result is not None:
        return jsonify(cached_result)

    placeholders = ','.join('?' for _ in normalized_codes)
    query = f"""
        SELECT Cod_producto, Cod_of
        FROM dbo.V_OFs WITH (NOLOCK)
        WHERE Cod_producto IN ({placeholders})
          AND Desc_estadoof IN ('IN PROGRESS', 'PLANNED')
        ORDER BY Cod_producto ASC, Fecha_ini ASC
    """

    try:
        results = {beam_code: [] for beam_code in normalized_codes}

        with ConexionODBCCZ(database='mapexbp') as conn_cz:
            if conn_cz is None:
                error_message = "No se pudo establecer conexión con la base de datos 'mapexbp'."
                logging.error(f"[API GET WOS BATCH] ERROR: {error_message}")
                return jsonify({'error': error_message}), 500

            cursor_cz = conn_cz.cursor()
            cursor_cz.execute(query, normalized_codes)

            for beam_code, wo_code in cursor_cz.fetchall():
                normalized_beam = str(beam_code).strip() if beam_code is not None else ''
                normalized_wo = str(wo_code).strip() if wo_code is not None else ''
                if not normalized_beam or not normalized_wo:
                    continue
                results.setdefault(normalized_beam, []).append(normalized_wo)

        set_cached_endpoint_response(cache_key, results)
        return jsonify(results)

    except pyodbc.Error as db_err:
        logging.error(f"Error de BD en get_wos_for_beams_batch: {db_err}")
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
# ENDPOINT DE IMPORTACIÓN DE PEDIDOS DESDE ARCHIVOS
# ====================================================================================
@app.route('/api/importar-pedidos', methods=['POST'])
@cross_origin()
def importar_pedidos():
    """
    Endpoint para importar pedidos desde archivos CSV o Excel.
    SOLO guarda líneas relevantes:
    - GRP_HSK_TYPE con su valor actual (para distinguir LH de no-LH)
    - GRP_OMEGA_BRACKET_TYPE_TSD con su valor (línea del bracket type)
    
    El resto de características se ignoran.
    """
    try:
        logging.info("[IMPORTAR-PEDIDOS] === INICIANDO IMPORTACIÓN v2 ===")
        
        # Validar que hay archivo
        if 'archivo' not in request.files:
            logging.error("[IMPORTAR-PEDIDOS] No se envió archivo")
            return jsonify({'success': False, 'mensaje': 'No se envió archivo'}), 400
        
        archivo = request.files['archivo']
        logging.info(f"[IMPORTAR-PEDIDOS] Archivo recibido: {archivo.filename}")
        
        if archivo.filename == '':
            logging.error("[IMPORTAR-PEDIDOS] Archivo vacío")
            return jsonify({'success': False, 'mensaje': 'Archivo vacío'}), 400
        
        # Detectar tipo de archivo
        filename_lower = archivo.filename.lower()
        es_excel = filename_lower.endswith(('.xlsx', '.xls'))
        es_csv = filename_lower.endswith('.csv')
        
        logging.info(f"[IMPORTAR-PEDIDOS] Es Excel: {es_excel}, Es CSV: {es_csv}")
        
        if not (es_excel or es_csv):
            logging.error(f"[IMPORTAR-PEDIDOS] Formato no soportado: {filename_lower}")
            return jsonify({'success': False, 'mensaje': 'Formato no soportado. Use Excel (.xlsx) o CSV'}), 400
        
        encabezados_requeridos = ['Sales document', 'Material', 'Characteristic Name', 'Characteristic Value']
        aliases_columnas = {
            'Sales document': ['sales document', 'salesdocument', 'doc.vtas', 'doc vtas', 'docventas', 'documento venta', 'documento de venta', 'pedido', 'numero pedido', 'numero de pedido', 'numeropedido'],
            'Material': ['material', 'codigo material', 'cod material', 'codigo', 'cod_producto', 'cod producto', 'assy'],
            'Characteristic Name': ['characteristic name', 'characteristicname', 'nombre caracteristica', 'nombre de caracteristica', 'caracteristica', 'characteristic', 'nombre característica', 'nombre de característica'],
            'Characteristic Value': ['characteristic value', 'characteristicvalue', 'valor caracteristica', 'valor de caracteristica', 'valor', 'valor característica', 'valor de característica']
        }
        registros_insertados = 0
        errores = []
        resumen_por_pedido = {}  # Para contabilizar

        def normalizar_valor(valor):
            if valor is None:
                return ''
            if isinstance(valor, float) and valor.is_integer():
                return str(int(valor))
            if isinstance(valor, int):
                return str(valor)
            return str(valor).strip()

        def simplificar_encabezado(valor):
            texto = normalizar_valor(valor).lower()
            reemplazos = {
                'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ü': 'u', 'ñ': 'n'
            }
            for origen, destino in reemplazos.items():
                texto = texto.replace(origen, destino)
            for caracter in (' ', '.', '_', '-', '/', '\\', ':', ';', ',', '(', ')'):
                texto = texto.replace(caracter, '')
            return texto

        def encontrar_columna(encabezados, columna_canonica):
            aliases_columnas = {
                'Sales document': ['sales document', 'salesdocument', 'doc.vtas', 'doc vtas', 'docventas', 'documento venta', 'documento de venta', 'pedido', 'numero pedido', 'numero de pedido', 'numeropedido'],
                'Material': ['material', 'codigo material', 'cod material', 'codigo', 'cod_producto', 'cod producto', 'assy'],
                'Characteristic Name': ['characteristic name', 'characteristicname', 'nombre caracteristica', 'nombre de caracteristica', 'caracteristica', 'characteristic', 'nombre característica', 'nombre de característica'],
                'Characteristic Value': ['characteristic value', 'characteristicvalue', 'valor caracteristica', 'valor de caracteristica', 'valor', 'valor característica', 'valor de característica']
            }
            
            candidatos = [simplificar_encabezado(columna_canonica)]
            candidatos.extend(simplificar_encabezado(alias) for alias in aliases_columnas.get(columna_canonica, []))

            for idx, encabezado in enumerate(encabezados):
                encabezado_simple = simplificar_encabezado(encabezado)
                if not encabezado_simple:
                    continue
                if encabezado_simple in candidatos or any(candidato in encabezado_simple or encabezado_simple in candidato for candidato in candidatos):
                    return idx
            return None

        def obtener_indices_columnas(encabezados):
            encabezados_normalizados = [normalizar_valor(h) for h in encabezados]
            idx_sales = encontrar_columna(encabezados_normalizados, 'Sales document')
            idx_material = encontrar_columna(encabezados_normalizados, 'Material')
            idx_characteristic = encontrar_columna(encabezados_normalizados, 'Characteristic Name')
            idx_value = encontrar_columna(encabezados_normalizados, 'Characteristic Value')

            faltantes = []
            if idx_sales is None:
                faltantes.append('Sales document')
            if idx_material is None:
                faltantes.append('Material')
            if idx_characteristic is None:
                faltantes.append('Characteristic Name')
            if idx_value is None:
                faltantes.append('Characteristic Value')

            if faltantes:
                raise ValueError(
                    'Columnas incorrectas o incompletas. Faltan: '
                    + ', '.join(faltantes)
                    + '. Se aceptan nombres equivalentes en ingles o espanol.'
                )

            return (idx_sales, idx_material, idx_characteristic, idx_value)

        def es_caracteristica_relevante(characteristic_name, characteristic_value):
            """
            Determina si una característica es relevante para guardar.
            GUARDA:
            - GRP_HSK_TYPE con valor (para conservar el estado LH/no-LH más reciente)
            - GRP_OMEGA_BRACKET_TYPE_TSD con cualquier valor
            - GRP_OMEGA_BRACKET_TYPE_HEAD con cualquier valor
            - GRP_OMEGA_BRACKET_TYPE_TRAV con cualquier valor
            - GRP_OMEGA_BRACKET_TYPE_PIT con cualquier valor
            - GRP_OMEGA_BRACKET_QTY_PIT con valor
            - GRP_TIE_BRACKET_OPT con valor Y/N
            - GRP_TIE_BRACKET_QTY con valor
            - GRP_TIE_BRACKET_TYPE con valor
            """
            char_upper = normalizar_valor(characteristic_name).upper()
            
            # Guardar todos los valores HSK para que una reimportación no-LH
            # pueda reemplazar un LH antiguo en el histórico.
            if char_upper == 'GRP_HSK_TYPE' and normalizar_valor(characteristic_value):
                if normalizar_valor(characteristic_value).upper() == 'LH':
                    return True, 'GRP_HSK_TYPE=LH'
                return True, 'GRP_HSK_TYPE'
            
            # Relevante 2: GRP_OMEGA_BRACKET_TYPE_TSD con valor
            if char_upper == 'GRP_OMEGA_BRACKET_TYPE_TSD' and normalizar_valor(characteristic_value):
                return True, 'GRP_OMEGA_BRACKET_TYPE_TSD'
            
            # Relevante 3: GRP_OMEGA_BRACKET_TYPE_HEAD con valor
            if char_upper == 'GRP_OMEGA_BRACKET_TYPE_HEAD' and normalizar_valor(characteristic_value):
                return True, 'GRP_OMEGA_BRACKET_TYPE_HEAD'
            
            # Relevante 4: GRP_OMEGA_BRACKET_TYPE_TRAV con valor
            if char_upper == 'GRP_OMEGA_BRACKET_TYPE_TRAV' and normalizar_valor(characteristic_value):
                return True, 'GRP_OMEGA_BRACKET_TYPE_TRAV'

            # Relevante 5: GRP_TIE_BRACKET_OPT con Y/N
            if char_upper == 'GRP_TIE_BRACKET_OPT' and normalizar_valor(characteristic_value).upper() in ('Y', 'N'):
                return True, 'GRP_TIE_BRACKET_OPT'

            # Relevante 6: GRP_TIE_BRACKET_QTY con valor
            if char_upper == 'GRP_TIE_BRACKET_QTY' and normalizar_valor(characteristic_value):
                return True, 'GRP_TIE_BRACKET_QTY'

            # Relevante 7: GRP_TIE_BRACKET_TYPE con valor
            if char_upper == 'GRP_TIE_BRACKET_TYPE' and normalizar_valor(characteristic_value):
                return True, 'GRP_TIE_BRACKET_TYPE'

            # Relevante 8: GRP_OMEGA_BRACKET_TYPE_PIT con valor
            if char_upper == 'GRP_OMEGA_BRACKET_TYPE_PIT' and normalizar_valor(characteristic_value):
                return True, 'GRP_OMEGA_BRACKET_TYPE_PIT'

            # Relevante 9: GRP_OMEGA_BRACKET_QTY_PIT con valor
            if char_upper == 'GRP_OMEGA_BRACKET_QTY_PIT' and normalizar_valor(characteristic_value):
                return True, 'GRP_OMEGA_BRACKET_QTY_PIT'
            
            # No relevante
            return False, None

        def insertar_registro(cursor, sales_doc, material, characteristic, value):
            cursor.execute("""
                INSERT INTO [OB].[pedidos_exportados] (
                    sales_document,
                    material,
                    characteristic_name,
                    characteristic_value
                ) VALUES (?, ?, ?, ?)
            """, (sales_doc, material, characteristic, value))

        def procesar_filas(cursor, filas, indices, origen):
            nonlocal registros_insertados

            idx_sales, idx_material, idx_characteristic, idx_value = indices

            for idx_fila, fila in enumerate(filas, start=2):
                fila_lista = list(fila) if fila is not None else []

                if not fila_lista or not any(normalizar_valor(cell) for cell in fila_lista):
                    logging.debug(f"[IMPORTAR-PEDIDOS] {origen} fila {idx_fila} vacía, saltando")
                    continue

                try:
                    if len(fila_lista) < max(idx_sales, idx_material, idx_characteristic, idx_value) + 1:
                        msg = f"Fila {idx_fila}: Estructura incompleta"
                        logging.warning(f"[IMPORTAR-PEDIDOS] {msg}")
                        errores.append(msg)
                        continue

                    sales_doc = normalizar_valor(fila_lista[idx_sales])
                    material = normalizar_valor(fila_lista[idx_material])
                    characteristic = normalizar_valor(fila_lista[idx_characteristic])
                    value = normalizar_valor(fila_lista[idx_value])

                    if not sales_doc or not material or not characteristic:
                        msg = f"Fila {idx_fila}: Faltan campos obligatorios"
                        logging.warning(f"[IMPORTAR-PEDIDOS] {msg}")
                        errores.append(msg)
                        continue

                    # ANÁLISIS: ¿Es esta característica relevante?
                    es_relevante, tipo_relevancia = es_caracteristica_relevante(characteristic, value)

                    if not es_relevante:
                        logging.debug(
                            f"[IMPORTAR-PEDIDOS] {origen} fila {idx_fila} IGNORADA (no es relevante): "
                            f"{sales_doc} | {material} | {characteristic} | {value}"
                        )
                        continue

                    # GUARDADO: Solo guarda si es relevante
                    insertar_registro(cursor, sales_doc, material, characteristic, value)
                    registros_insertados += 1

                    # Contabilizar por pedido
                    clave_pedido = (sales_doc, material)
                    if clave_pedido not in resumen_por_pedido:
                        resumen_por_pedido[clave_pedido] = {
                            'lh': False,
                            'bracket': False,
                            'tb_opt': False,
                            'tb_qty': False,
                            'tb_type': False,
                            'pit_type': False,
                            'pit_qty': False,
                        }
                    
                    if tipo_relevancia == 'GRP_HSK_TYPE=LH':
                        resumen_por_pedido[clave_pedido]['lh'] = True
                    elif tipo_relevancia == 'GRP_OMEGA_BRACKET_TYPE_TSD':
                        resumen_por_pedido[clave_pedido]['bracket'] = True
                    elif tipo_relevancia == 'GRP_TIE_BRACKET_OPT':
                        resumen_por_pedido[clave_pedido]['tb_opt'] = True
                    elif tipo_relevancia == 'GRP_TIE_BRACKET_QTY':
                        resumen_por_pedido[clave_pedido]['tb_qty'] = True
                    elif tipo_relevancia == 'GRP_TIE_BRACKET_TYPE':
                        resumen_por_pedido[clave_pedido]['tb_type'] = True
                    elif tipo_relevancia == 'GRP_OMEGA_BRACKET_TYPE_PIT':
                        resumen_por_pedido[clave_pedido]['pit_type'] = True
                    elif tipo_relevancia == 'GRP_OMEGA_BRACKET_QTY_PIT':
                        resumen_por_pedido[clave_pedido]['pit_qty'] = True

                    logging.info(
                        f"[IMPORTAR-PEDIDOS] {origen} fila {idx_fila} GUARDADA ({tipo_relevancia}): "
                        f"{sales_doc} | {material} | {characteristic} = {value}"
                    )

                except Exception as e:
                    msg = f"Fila {idx_fila}: {str(e)}"
                    logging.error(f"[IMPORTAR-PEDIDOS] {msg}")
                    errores.append(msg)

        try:
            with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
                cursor = conn.cursor()

                if es_excel:
                    logging.info("[IMPORTAR-PEDIDOS] Procesando archivo Excel...")
                    try:
                        from openpyxl import load_workbook
                        import tempfile
                        import os

                        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                            archivo.save(tmp.name)
                            temp_path = tmp.name

                        logging.info(f"[IMPORTAR-PEDIDOS] Archivo temporal guardado en: {temp_path}")

                        try:
                            wb = load_workbook(temp_path, data_only=True)
                            ws = wb.active
                            encabezados = [cell.value for cell in ws[1]]
                            logging.info(f"[IMPORTAR-PEDIDOS] Encabezados Excel: {encabezados}")

                            indices = obtener_indices_columnas(encabezados)
                            procesar_filas(cursor, ws.iter_rows(min_row=2, values_only=True), indices, 'Excel')

                        finally:
                            try:
                                os.unlink(temp_path)
                                logging.info("[IMPORTAR-PEDIDOS] Archivo temporal eliminado")
                            except Exception as e:
                                logging.error(f"[IMPORTAR-PEDIDOS] Error al eliminar archivo temporal: {str(e)}")

                    except ImportError as e:
                        logging.error(f"[IMPORTAR-PEDIDOS] openpyxl no instalado: {str(e)}")
                        return jsonify({
                            'success': False,
                            'mensaje': 'Librería openpyxl no instalada. Instale con: pip install openpyxl'
                        }), 500

                else:
                    logging.info("[IMPORTAR-PEDIDOS] Procesando archivo CSV...")
                    import csv
                    import io

                    contenido_bytes = archivo.read()
                    contenido = None
                    for encoding in ('utf-8-sig', 'utf-8', 'latin-1'):
                        try:
                            contenido = contenido_bytes.decode(encoding)
                            logging.info(f"[IMPORTAR-PEDIDOS] CSV decodificado con {encoding}")
                            break
                        except UnicodeDecodeError:
                            continue

                    if contenido is None:
                        raise ValueError('No se pudo decodificar el archivo CSV')

                    sample = contenido[:2048]
                    try:
                        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
                    except csv.Error:
                        dialect = csv.excel

                    reader = csv.reader(io.StringIO(contenido), dialect)

                    try:
                        encabezados = next(reader)
                    except StopIteration:
                        return jsonify({
                            'success': False,
                            'mensaje': 'El archivo CSV está vacío.'
                        }), 400

                    logging.info(f"[IMPORTAR-PEDIDOS] Encabezados CSV: {encabezados}")
                    indices = obtener_indices_columnas(encabezados)
                    procesar_filas(cursor, reader, indices, 'CSV')

                # Confirmar transacción
                logging.info(
                    f"[IMPORTAR-PEDIDOS] Confirmando transacción... Registros guardados: {registros_insertados}"
                )
                conn.commit()
                clear_endpoint_response_cache()
                logging.info("[IMPORTAR-PEDIDOS] Transacción confirmada exitosamente")

        except ValueError as e:
            logging.error(f"[IMPORTAR-PEDIDOS] Validación fallida: {str(e)}")
            return jsonify({
                'success': False,
                'mensaje': str(e)
            }), 400
        except Exception as e:
            logging.error(f"[IMPORTAR-PEDIDOS] Error en BD: {str(e)}", exc_info=True)
            return jsonify({
                'success': False,
                'mensaje': f'Error en la base de datos: {str(e)}'
            }), 500
        
        # Validar que se insertó algo
        if registros_insertados == 0:
            logging.warning("[IMPORTAR-PEDIDOS] No se insertaron registros relevantes")
            return jsonify({
                'success': False,
                'mensaje': 'No se insertaron registros. Verifica que el archivo contenga características GRP_HSK_TYPE=LH, GRP_OMEGA_BRACKET_TYPE_* o GRP_TIE_BRACKET_*.',
                'errores': errores
            }), 400
        
        # Contar resumen
        pedidos_lh = sum(1 for datos in resumen_por_pedido.values() if datos['lh'])
        pedidos_bracket = sum(1 for datos in resumen_por_pedido.values() if datos['bracket'])
        pedidos_tb_opt = sum(1 for datos in resumen_por_pedido.values() if datos['tb_opt'])
        pedidos_tb_qty = sum(1 for datos in resumen_por_pedido.values() if datos['tb_qty'])
        pedidos_tb_type = sum(1 for datos in resumen_por_pedido.values() if datos['tb_type'])
        pedidos_pit_type = sum(1 for datos in resumen_por_pedido.values() if datos['pit_type'])
        pedidos_pit_qty = sum(1 for datos in resumen_por_pedido.values() if datos['pit_qty'])

        # Respuesta exitosa
        respuesta = {
            'success': True,
            'mensaje': (
                f'Importación completada: {registros_insertados} registros guardados. '
                f'Pedidos con GRP_HSK_TYPE=LH: {pedidos_lh}. '
                f'Pedidos con GRP_OMEGA_BRACKET_TYPE_TSD: {pedidos_bracket}. '
                f'Pedidos con TB OPT: {pedidos_tb_opt}. '
                f'Pedidos con TB QTY: {pedidos_tb_qty}. '
                f'Pedidos con TB TYPE: {pedidos_tb_type}. '
                f'Pedidos con PIT TYPE: {pedidos_pit_type}. '
                f'Pedidos con PIT QTY: {pedidos_pit_qty}.'
            ),
            'registros_insertados': registros_insertados,
            'pedidos_lh': pedidos_lh,
            'pedidos_bracket': pedidos_bracket,
            'pedidos_tb_opt': pedidos_tb_opt,
            'pedidos_tb_qty': pedidos_tb_qty,
            'pedidos_tb_type': pedidos_tb_type,
            'pedidos_pit_type': pedidos_pit_type,
            'pedidos_pit_qty': pedidos_pit_qty,
            'errores': errores if errores else None
        }
        
        logging.info(f"[IMPORTAR-PEDIDOS] === IMPORTACIÓN v2 COMPLETADA === Registros: {registros_insertados}, Errores: {len(errores)}")
        
        return jsonify(respuesta), 200
    
    except Exception as e:
        logging.error(f"[IMPORTAR-PEDIDOS] Error inesperado: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'mensaje': f'Error inesperado: {str(e)}'
        }), 500


@app.route('/api/pedidos-importados', methods=['GET'])
@cross_origin()
def obtener_pedidos_importados():
    """Devuelve pedidos únicos ya guardados en OB.pedidos_exportados."""
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT TOP (1000)
                    LTRIM(RTRIM([sales_document])) AS sales_document,
                    MAX([fecha_importacion]) AS fecha_importacion
                FROM [DataLakeSCCZ].[OB].[pedidos_exportados] WITH (NOLOCK)
                WHERE [sales_document] IS NOT NULL
                  AND LTRIM(RTRIM([sales_document])) <> ''
                GROUP BY LTRIM(RTRIM([sales_document]))
                ORDER BY MAX([fecha_importacion]) DESC, LTRIM(RTRIM([sales_document])) DESC
            """)

            rows = []
            for row in cursor.fetchall():
                rows.append({
                    'order': row.sales_document,
                })

        return jsonify({
            'success': True,
            'total': len(rows),
            'rows': rows,
        }), 200
    except Exception as e:
        logging.error(f"[PEDIDOS-IMPORTADOS] Error obteniendo pedidos importados: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'mensaje': f'Error obteniendo pedidos importados: {e}'
        }), 500


@app.route('/api/exportar-ex', methods=['POST'])
@cross_origin()
def exportar_ex():
    """
    Endpoint para procesar extensores (EX y TB) desde archivos CSV o Excel.
    Lee Material column, busca en OB.Omegas con W/C='EX' o W/C='TB', y actualiza PedidosCabecera.
    Columnas esperadas:
    - Doc.vtas (NumeroPedido)
    - Material (Código a buscar como EX o TB)
    - Resto de columnas son opcionales (solo referencia)
    """
    try:
        logging.info("[EXPORTAR-EX-TB] === INICIANDO EXPORTACIÓN DE EXTENSORES (EX/TB) ===")
        
        # Validar archivo
        if 'archivo' not in request.files:
            logging.error("[EXPORTAR-EX-TB] No se envió archivo")
            return jsonify({'success': False, 'mensaje': 'No se envió archivo'}), 400
        
        archivo = request.files['archivo']
        logging.info(f"[EXPORTAR-EX-TB] Archivo recibido: {archivo.filename}")
        
        if archivo.filename == '':
            logging.error("[EXPORTAR-EX-TB] Archivo vacío")
            return jsonify({'success': False, 'mensaje': 'Archivo vacío'}), 400
        
        # Detectar tipo de archivo
        filename_lower = archivo.filename.lower()
        es_excel = filename_lower.endswith(('.xlsx', '.xls'))
        es_csv = filename_lower.endswith('.csv')
        
        logging.info(f"[EXPORTAR-EX-TB] Es Excel: {es_excel}, Es CSV: {es_csv}")
        
        if not (es_excel or es_csv):
            logging.error(f"[EXPORTAR-EX-TB] Formato no soportado: {filename_lower}")
            return jsonify({'success': False, 'mensaje': 'Formato no soportado. Use Excel (.xlsx) o CSV'}), 400
        
        procesadas = 0
        actualizado_ex = 0
        actualizado_tb = 0
        errores = []
        
        try:
            # Leer archivo
            if es_excel:
                logging.info("[EXPORTAR-EX-TB] Procesando archivo Excel...")
                try:
                    from openpyxl import load_workbook
                    import tempfile
                    import os
                    
                    # Guardar archivo temporal
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                        archivo.save(tmp.name)
                        temp_path = tmp.name
                    
                    logging.info(f"[EXPORTAR-EX-TB] Archivo temporal guardado en: {temp_path}")
                    
                    try:
                        # Cargar Excel
                        wb = load_workbook(temp_path)
                        ws = wb.active
                        logging.info(f"[EXPORTAR-EX-TB] Excel cargado. Hoja activa: {ws.title}")
                        
                        # Leer encabezados
                        encabezados = [cell.value for cell in ws[1]]
                        logging.info(f"[EXPORTAR-EX-TB] Encabezados leídos RAW: {encabezados}")
                        
                        encabezados_normalizados = [str(h).strip() if h else '' for h in encabezados]
                        logging.info(f"[EXPORTAR-EX-TB] Encabezados normalizados: {encabezados_normalizados}")
                        
                        # Función para encontrar columna flexible
                        def encontrar_columna(encabezados, patrones):
                            """Busca una columna con flexibilidad de nombres"""
                            for idx, encab in enumerate(encabezados):
                                encab_lower = str(encab).lower().replace(' ', '').replace('.', '').replace('_', '')
                                for patron in patrones:
                                    patron_lower = patron.lower().replace(' ', '').replace('.', '').replace('_', '')
                                    if patron_lower in encab_lower or encab_lower in patron_lower:
                                        return idx
                            return None
                        
                        # Buscar columnas con flexibilidad
                        idx_doc_vtas = encontrar_columna(encabezados_normalizados, ['Doc.vtas', 'Doc vtas', 'Docventas', 'Documento venta', 'Sales document', 'Numeropedido'])
                        idx_material = encontrar_columna(encabezados_normalizados, ['Material', 'Assy', 'Codigo', 'Code'])
                        
                        logging.info(f"[EXPORTAR-EX-TB] Índices detectados: Doc.vtas={idx_doc_vtas}, Material={idx_material}")
                        
                        # Si no encuentra, intentar posiciones por defecto (primera y segunda columna)
                        if idx_doc_vtas is None:
                            idx_doc_vtas = 0
                            logging.warning(f"[EXPORTAR-EX-TB] Doc.vtas no encontrado, usando columna 0 (primera columna)")
                        if idx_material is None:
                            idx_material = 1
                            logging.warning(f"[EXPORTAR-EX-TB] Material no encontrado, usando columna 1 (segunda columna)")
                        
                        logging.info(f"[EXPORTAR-EX-TB] Usando índices finales: Doc.vtas={idx_doc_vtas} ({encabezados_normalizados[idx_doc_vtas] if idx_doc_vtas < len(encabezados_normalizados) else 'N/A'}), Material={idx_material} ({encabezados_normalizados[idx_material] if idx_material < len(encabezados_normalizados) else 'N/A'})")
                        
                        # Conectar a BD
                        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
                            cursor = conn.cursor()
                            cursor_check = conn.cursor()
                            logging.info("[EXPORTAR-EX-TB] Conexión a BD establecida")
                            
                            # Procesar filas desde la 2 en adelante
                            for idx_fila, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                                # Saltar filas vacías
                                if not row or not any(cell for cell in row):
                                    logging.debug(f"[EXPORTAR-EX-TB] Fila {idx_fila} vacía, saltando")
                                    continue
                                
                                try:
                                    # Validar estructura mínima
                                    if len(row) < max(idx_doc_vtas, idx_material) + 1:
                                        msg = f"Fila {idx_fila}: Estructura incompleta (tiene {len(row)} columnas, se necesitan {max(idx_doc_vtas, idx_material) + 1})"
                                        logging.warning(f"[EXPORTAR-EX-TB] {msg}")
                                        errores.append(msg)
                                        procesadas += 1
                                        continue
                                    
                                    # Extraer datos
                                    doc_vtas_raw = row[idx_doc_vtas]
                                    material_raw = row[idx_material]
                                    
                                    # Conversión segura: manejar números que vienen como float
                                    if isinstance(doc_vtas_raw, (int, float)):
                                        doc_vtas = str(int(doc_vtas_raw)).strip()
                                    else:
                                        doc_vtas = str(doc_vtas_raw).strip() if doc_vtas_raw else ''
                                    
                                    if isinstance(material_raw, (int, float)):
                                        material = str(int(material_raw)).strip()
                                    else:
                                        material = str(material_raw).strip() if material_raw else ''
                                    
                                    # Log detallado para DEBUG: mostrar longitud y caracteres
                                    logging.debug(f"[EXPORTAR-EX-TB] Fila {idx_fila}: Doc.vtas={doc_vtas}, Material={material}")
                                    logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila}: Material RAW - length={len(material)}, repr={repr(material)}, tipo={type(material_raw).__name__}")
                                    
                                    # VALIDACIÓN PREVIA: Verificar que el NumeroPedido existe en PedidosCabecera
                                    cursor_check.execute("""
                                        SELECT NumeroPedido FROM [OB].[PedidosCabecera]
                                        WHERE NumeroPedido = ?
                                    """, (doc_vtas,))
                                    
                                    pedido_existe = cursor_check.fetchone()
                                    if not pedido_existe:
                                        msg = f"Fila {idx_fila}: NumeroPedido='{doc_vtas}' NO existe en PedidosCabecera"
                                        logging.error(f"[EXPORTAR-EX-TB] {msg}")
                                        errores.append(msg)
                                        procesadas += 1
                                        continue
                                    
                                    logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila}: ✅ NumeroPedido='{doc_vtas}' EXISTE en PedidosCabecera")
                                    
                                    # Validar obligatorios
                                    if not doc_vtas or not material:
                                        msg = f"Fila {idx_fila}: Faltan Doc.vtas ({doc_vtas}) o Material ({material})"
                                        logging.warning(f"[EXPORTAR-EX-TB] {msg}")
                                        errores.append(msg)
                                        procesadas += 1
                                        continue
                                    
                                    # BÚSQUEDA 1: Verificar si existe como EX
                                    logging.debug(f"[EXPORTAR-EX-TB] Fila {idx_fila}: Buscando Material='{material}' con W/C='EX'")
                                    logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila}: BÚSQUEDA EX - Parámetro: repr={repr(material)}, length={len(material)}")
                                    cursor_check.execute("""
                                        SELECT Assy FROM [OB].[Omegas]
                                        WHERE Assy = ? AND LTRIM(RTRIM([W/C])) = 'EX'
                                    """, (material,))
                                    
                                    result_ex = cursor_check.fetchone()
                                    logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila}: Búsqueda EX - Material='{material}' -> Encontrado: {result_ex is not None}")
                                    
                                    if result_ex:
                                        logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila}: 🔍 Material '{material}' encontrado en OB.Omegas con W/C='EX'")
                                        cursor.execute("""
                                            UPDATE [OB].[PedidosCabecera]
                                            SET EX = ?
                                            WHERE NumeroPedido = ?
                                        """, (material, doc_vtas))
                                        
                                        if cursor.rowcount > 0:
                                            actualizado_ex += 1
                                            logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila}: ✅ ÉXITO - PedidosCabecera.{doc_vtas} actualizado con EX='{material}'")
                                        else:
                                            logging.warning(f"[EXPORTAR-EX-TB] Fila {idx_fila}: ⚠️  UPDATE no afectó filas para EX (¿NumeroPedido={doc_vtas} existe en PedidosCabecera?)")
                                    else:
                                        logging.warning(f"[EXPORTAR-EX-TB] Fila {idx_fila}: Material '{material}' NO encontrado como EX en OB.Omegas")
                                    
                                    # BÚSQUEDA 2: Verificar si existe como TB
                                    cursor_check.execute("""
                                        SELECT Assy FROM [OB].[Omegas]
                                        WHERE Assy = ? AND LTRIM(RTRIM([W/C])) = 'TB'
                                    """, (material,))
                                    
                                    result_tb = cursor_check.fetchone()
                                    
                                    if result_tb:
                                        cursor.execute("""
                                            UPDATE [OB].[PedidosCabecera]
                                            SET TB = ?
                                            WHERE NumeroPedido = ?
                                        """, (material, doc_vtas))
                                        
                                        if cursor.rowcount > 0:
                                            actualizado_tb += 1
                                            logging.info(f"[TB] Encontrado: {material}")
                                            logging.info(f"[TB] Pedido {doc_vtas} actualizado")
                                    
                                    # Si no encontró ni EX ni TB
                                    if not result_ex and not result_tb:
                                        msg = f"Fila {idx_fila}: Material '{material}' no encontrado en OB.Omegas como EX ni TB"
                                        logging.warning(f"[EXPORTAR-EX-TB] {msg}")
                                        errores.append(msg)
                                    else:
                                        logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila}: ✅ Material '{material}' procesado correctamente")
                                    
                                    procesadas += 1
                                    
                                except Exception as e:
                                    msg = f"Fila {idx_fila}: {str(e)}"
                                    logging.error(f"[EXPORTAR-EX-TB] {msg}", exc_info=True)
                                    errores.append(msg)
                                    procesadas += 1
                                    continue
                            
                            logging.info(f"[EXPORTAR-EX-TB] Confirmando transacción... Procesadas: {procesadas}, Actualizadas EX: {actualizado_ex}, Actualizadas TB: {actualizado_tb}")
                            conn.commit()
                            clear_endpoint_response_cache()
                            logging.info("[EXPORTAR-EX-TB] Transacción confirmada exitosamente")
                    
                    finally:
                        # Limpiar archivo temporal
                        try:
                            os.unlink(temp_path)
                            logging.info("[EXPORTAR-EX-TB] Archivo temporal eliminado")
                        except Exception as e:
                            logging.error(f"[EXPORTAR-EX-TB] Error al eliminar archivo temporal: {str(e)}")
                
                except ImportError as e:
                    logging.error(f"[EXPORTAR-EX-TB] openpyxl no instalado: {str(e)}")
                    return jsonify({
                        'success': False,
                        'mensaje': 'Librería openpyxl no instalada'
                    }), 500
            
            else:
                # Procesar CSV
                logging.info("[EXPORTAR-EX-TB] Procesando archivo CSV...")
                import csv
                import io
                
                contenido = archivo.read().decode('utf-8')
                logging.info(f"[EXPORTAR-EX-TB] Contenido CSV leído, primeros 200 caracteres: {contenido[:200]}")
                
                reader = csv.reader(io.StringIO(contenido))
                
                # Leer encabezados
                encabezados = next(reader)
                encabezados_normalizados = [h.strip() for h in encabezados]
                
                logging.info(f"[EXPORTAR-EX-TB] Encabezados CSV RAW: {encabezados}")
                logging.info(f"[EXPORTAR-EX-TB] Encabezados CSV normalizados: {encabezados_normalizados}")
                
                # Función para encontrar columna flexible
                def encontrar_columna(encabezados, patrones):
                    """Busca una columna con flexibilidad de nombres"""
                    for idx, encab in enumerate(encabezados):
                        encab_lower = str(encab).lower().replace(' ', '').replace('.', '').replace('_', '')
                        for patron in patrones:
                            patron_lower = patron.lower().replace(' ', '').replace('.', '').replace('_', '')
                            if patron_lower in encab_lower or encab_lower in patron_lower:
                                return idx
                    return None
                
                # Buscar columnas
                idx_doc_vtas = encontrar_columna(encabezados_normalizados, ['Doc.vtas', 'Doc vtas', 'Docventas', 'Documento venta', 'Sales document', 'Numeropedido'])
                idx_material = encontrar_columna(encabezados_normalizados, ['Material', 'Assy', 'Codigo', 'Code'])
                
                logging.info(f"[EXPORTAR-EX-TB] Índices CSV detectados: Doc.vtas={idx_doc_vtas}, Material={idx_material}")
                
                # Si no encuentra, intentar posiciones por defecto
                if idx_doc_vtas is None:
                    idx_doc_vtas = 0
                    logging.warning(f"[EXPORTAR-EX-TB] Doc.vtas no encontrado en CSV, usando columna 0")
                if idx_material is None:
                    idx_material = 1
                    logging.warning(f"[EXPORTAR-EX-TB] Material no encontrado en CSV, usando columna 1")
                
                logging.info(f"[EXPORTAR-EX-TB] Usando índices finales CSV: Doc.vtas={idx_doc_vtas} ({encabezados_normalizados[idx_doc_vtas] if idx_doc_vtas < len(encabezados_normalizados) else 'N/A'}), Material={idx_material} ({encabezados_normalizados[idx_material] if idx_material < len(encabezados_normalizados) else 'N/A'})")
                
                # Conectar a BD
                with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
                    cursor = conn.cursor()
                    cursor_check = conn.cursor()
                    logging.info("[EXPORTAR-EX-TB] Conexión a BD establecida (CSV)")
                    
                    for idx_fila, fila in enumerate(reader, start=2):
                        if not fila or not any(cell.strip() for cell in fila):
                            logging.debug(f"[EXPORTAR-EX-TB] Fila {idx_fila} vacía, saltando")
                            continue
                        
                        try:
                            # Validar estructura mínima
                            if len(fila) < max(idx_doc_vtas, idx_material) + 1:
                                msg = f"Fila {idx_fila}: Estructura incompleta"
                                logging.warning(f"[EXPORTAR-EX-TB] {msg}")
                                errores.append(msg)
                                procesadas += 1
                                continue
                            
                            doc_vtas = fila[idx_doc_vtas].strip()
                            material = fila[idx_material].strip()
                            
                            # Conversión segura para CSV también (aunque CSV siempre viene como string)
                            doc_vtas = str(doc_vtas).strip() if doc_vtas else ''
                            material = str(material).strip() if material else ''
                            
                            logging.debug(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: Doc.vtas={doc_vtas}, Material={material}")
                            logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: Material RAW - length={len(material)}, repr={repr(material)}")
                            
                            # VALIDACIÓN PREVIA: Verificar que el NumeroPedido existe en PedidosCabecera
                            cursor_check.execute("""
                                SELECT NumeroPedido FROM [OB].[PedidosCabecera]
                                WHERE NumeroPedido = ?
                            """, (doc_vtas,))
                            
                            pedido_existe = cursor_check.fetchone()
                            if not pedido_existe:
                                msg = f"Fila {idx_fila} CSV: NumeroPedido='{doc_vtas}' NO existe en PedidosCabecera"
                                logging.error(f"[EXPORTAR-EX-TB] {msg}")
                                errores.append(msg)
                                procesadas += 1
                                continue
                            
                            logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: ✅ NumeroPedido='{doc_vtas}' EXISTE en PedidosCabecera")
                            
                            if not doc_vtas or not material:
                                msg = f"Fila {idx_fila}: Faltan Doc.vtas o Material"
                                logging.warning(f"[EXPORTAR-EX-TB] {msg}")
                                errores.append(msg)
                                procesadas += 1
                                continue
                            
                            # BÚSQUEDA 1: Verificar si existe como EX
                            logging.debug(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: Buscando Material='{material}' con W/C='EX'")
                            logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: BÚSQUEDA EX - Parámetro: repr={repr(material)}, length={len(material)}")
                            cursor_check.execute("""
                                SELECT Assy FROM [OB].[Omegas]
                                WHERE Assy = ? AND LTRIM(RTRIM([W/C])) = 'EX'
                            """, (material,))
                            
                            result_ex = cursor_check.fetchone()
                            logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: Búsqueda EX - Material='{material}' -> Encontrado: {result_ex is not None}")
                            
                            if result_ex:
                                logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: 🔍 Material '{material}' encontrado con W/C='EX'")
                                cursor.execute("""
                                    UPDATE [OB].[PedidosCabecera]
                                    SET EX = ?
                                    WHERE NumeroPedido = ?
                                """, (material, doc_vtas))
                                
                                if cursor.rowcount > 0:
                                    actualizado_ex += 1
                                    logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: ✅ ÉXITO - Actualizado EX='{material}'")
                                else:
                                    logging.warning(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: ⚠️  UPDATE no afectó filas para EX (¿NumeroPedido={doc_vtas} existe en PedidosCabecera?)")
                            else:
                                logging.warning(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: Material '{material}' NO encontrado como EX en OB.Omegas")
                            
                            # BÚSQUEDA 2: Verificar si existe como TB
                            logging.debug(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: Buscando Material='{material}' con W/C='TB'")
                            logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: BÚSQUEDA TB - Parámetro: repr={repr(material)}, length={len(material)}")
                            cursor_check.execute("""
                                SELECT Assy FROM [OB].[Omegas]
                                WHERE Assy = ? AND LTRIM(RTRIM([W/C])) = 'TB'
                            """, (material,))
                            
                            result_tb = cursor_check.fetchone()
                            logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: Búsqueda TB - Material='{material}' -> Encontrado: {result_tb is not None}")
                            
                            if result_tb:
                                logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: 🔍 Material '{material}' encontrado con W/C='TB'")
                                cursor.execute("""
                                    UPDATE [OB].[PedidosCabecera]
                                    SET TB = ?
                                    WHERE NumeroPedido = ?
                                """, (material, doc_vtas))
                                
                                if cursor.rowcount > 0:
                                    actualizado_tb += 1
                                    logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: ✅ ÉXITO - Actualizado TB='{material}'")
                                else:
                                    logging.warning(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: ⚠️  UPDATE no afectó filas para TB (¿NumeroPedido={doc_vtas} existe en PedidosCabecera?)")
                            else:
                                logging.warning(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: Material '{material}' NO encontrado como TB en OB.Omegas")
                            
                            # Si no encontró ni EX ni TB
                            if not result_ex and not result_tb:
                                msg = f"Fila {idx_fila}: Material '{material}' no encontrado como EX ni TB"
                                logging.warning(f"[EXPORTAR-EX-TB] {msg}")
                                errores.append(msg)
                            else:
                                logging.info(f"[EXPORTAR-EX-TB] Fila {idx_fila} CSV: ✅ Material '{material}' procesado correctamente")
                            
                            procesadas += 1
                        
                        except Exception as e:
                            msg = f"Fila {idx_fila}: {str(e)}"
                            logging.error(f"[EXPORTAR-EX-TB] {msg}", exc_info=True)
                            errores.append(msg)
                            procesadas += 1
                            continue
                    
                    logging.info(f"[EXPORTAR-EX-TB] Confirmando transacción CSV... Procesadas: {procesadas}, EX: {actualizado_ex}, TB: {actualizado_tb}")
                    conn.commit()
                    clear_endpoint_response_cache()
                    logging.info("[EXPORTAR-EX-TB] Transacción CSV confirmada")
        
        except Exception as e:
            logging.error(f"[EXPORTAR-EX-TB] Error en BD: {str(e)}", exc_info=True)
            return jsonify({
                'success': False,
                'mensaje': f'Error en la base de datos: {str(e)}'
            }), 500
        
        # Respuesta
        respuesta = {
            'success': True,
            'procesadas': procesadas,
            'actualizado_ex': actualizado_ex,
            'actualizado_tb': actualizado_tb,
            'errores': errores if errores else []
        }
        
        logging.info(f"[EXPORTAR-EX-TB] === EXPORTACIÓN COMPLETADA === Procesadas: {procesadas}, EX: {actualizado_ex}, TB: {actualizado_tb}, Errores: {len(errores)}")
        
        return jsonify(respuesta), 200
    
    except Exception as e:
        logging.error(f"[EXPORTAR-EX-TB] Error inesperado: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'mensaje': f'Error inesperado: {str(e)}'
        }), 500
    """
    Endpoint para procesar extensores (EX) desde archivos CSV o Excel.
    Lee Material column, busca en OB.Omegas con W/C='EX', y actualiza PedidosCabecera.
    Columnas esperadas:
    - Doc.vtas (NumeroPedido)
    - Material (Código a buscar como EX)
    - Resto de columnas son opcionales (solo referencia)
    """
    try:
        logging.info("[EXPORTAR-EX] === INICIANDO EXPORTACIÓN DE EXTENSORES ===")
        
        # Validar archivo
        if 'archivo' not in request.files:
            logging.error("[EXPORTAR-EX] No se envió archivo")
            return jsonify({'success': False, 'mensaje': 'No se envió archivo'}), 400
        
        archivo = request.files['archivo']
        logging.info(f"[EXPORTAR-EX] Archivo recibido: {archivo.filename}")
        
        if archivo.filename == '':
            logging.error("[EXPORTAR-EX] Archivo vacío")
            return jsonify({'success': False, 'mensaje': 'Archivo vacío'}), 400
        
        # Detectar tipo de archivo
        filename_lower = archivo.filename.lower()
        es_excel = filename_lower.endswith(('.xlsx', '.xls'))
        es_csv = filename_lower.endswith('.csv')
        
        logging.info(f"[EXPORTAR-EX] Es Excel: {es_excel}, Es CSV: {es_csv}")
        
        if not (es_excel or es_csv):
            logging.error(f"[EXPORTAR-EX] Formato no soportado: {filename_lower}")
            return jsonify({'success': False, 'mensaje': 'Formato no soportado. Use Excel (.xlsx) o CSV'}), 400
        
        procesadas = 0
        actualizado = 0
        errores = []
        
        try:
            # Leer archivo
            if es_excel:
                logging.info("[EXPORTAR-EX] Procesando archivo Excel...")
                try:
                    from openpyxl import load_workbook
                    import tempfile
                    import os
                    
                    # Guardar archivo temporal
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                        archivo.save(tmp.name)
                        temp_path = tmp.name
                    
                    logging.info(f"[EXPORTAR-EX] Archivo temporal guardado en: {temp_path}")
                    
                    try:
                        # Cargar Excel
                        wb = load_workbook(temp_path)
                        ws = wb.active
                        logging.info(f"[EXPORTAR-EX] Excel cargado. Hoja activa: {ws.title}")
                        
                        # Leer encabezados
                        encabezados = [cell.value for cell in ws[1]]
                        logging.info(f"[EXPORTAR-EX] Encabezados leídos RAW: {encabezados}")
                        
                        encabezados_normalizados = [str(h).strip() if h else '' for h in encabezados]
                        logging.info(f"[EXPORTAR-EX] Encabezados normalizados: {encabezados_normalizados}")
                        
                        # Función para encontrar columna flexible
                        def encontrar_columna(encabezados, patrones):
                            """Busca una columna con flexibilidad de nombres"""
                            for idx, encab in enumerate(encabezados):
                                encab_lower = str(encab).lower().replace(' ', '').replace('.', '').replace('_', '')
                                for patron in patrones:
                                    patron_lower = patron.lower().replace(' ', '').replace('.', '').replace('_', '')
                                    if patron_lower in encab_lower or encab_lower in patron_lower:
                                        return idx
                            return None
                        
                        # Buscar columnas con flexibilidad
                        idx_doc_vtas = encontrar_columna(encabezados_normalizados, ['Doc.vtas', 'Doc vtas', 'Docventas', 'Documento venta', 'Sales document', 'Numeropedido'])
                        idx_material = encontrar_columna(encabezados_normalizados, ['Material', 'Assy', 'Codigo', 'Code'])
                        
                        logging.info(f"[EXPORTAR-EX] Índices detectados: Doc.vtas={idx_doc_vtas}, Material={idx_material}")
                        
                        # Si no encuentra, intentar posiciones por defecto (primera y segunda columna)
                        if idx_doc_vtas is None:
                            idx_doc_vtas = 0
                            logging.warning(f"[EXPORTAR-EX] Doc.vtas no encontrado, usando columna 0 (primera columna)")
                        if idx_material is None:
                            idx_material = 1
                            logging.warning(f"[EXPORTAR-EX] Material no encontrado, usando columna 1 (segunda columna)")
                        
                        logging.info(f"[EXPORTAR-EX] Usando índices finales: Doc.vtas={idx_doc_vtas} ({encabezados_normalizados[idx_doc_vtas] if idx_doc_vtas < len(encabezados_normalizados) else 'N/A'}), Material={idx_material} ({encabezados_normalizados[idx_material] if idx_material < len(encabezados_normalizados) else 'N/A'})")
                        
                        logging.info(f"[EXPORTAR-EX] Índices mapeados: Doc.vtas={idx_doc_vtas}, Material={idx_material}")
                        
                        # Conectar a BD
                        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
                            cursor = conn.cursor()
                            cursor_check = conn.cursor()
                            logging.info("[EXPORTAR-EX] Conexión a BD establecida")
                            
                            # Procesar filas desde la 2 en adelante
                            for idx_fila, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                                # Saltar filas vacías
                                if not row or not any(cell for cell in row):
                                    logging.debug(f"[EXPORTAR-EX] Fila {idx_fila} vacía, saltando")
                                    continue
                                
                                try:
                                    # Validar estructura mínima
                                    if len(row) < max(idx_doc_vtas, idx_material) + 1:
                                        msg = f"Fila {idx_fila}: Estructura incompleta (tiene {len(row)} columnas, se necesitan {max(idx_doc_vtas, idx_material) + 1})"
                                        logging.warning(f"[EXPORTAR-EX] {msg}")
                                        errores.append(msg)
                                        procesadas += 1
                                        continue
                                    
                                    # Extraer datos
                                    doc_vtas_raw = row[idx_doc_vtas]
                                    material_raw = row[idx_material]
                                    
                                    doc_vtas = str(doc_vtas_raw).strip() if doc_vtas_raw else ''
                                    material = str(material_raw).strip() if material_raw else ''
                                    
                                    logging.debug(f"[EXPORTAR-EX] Fila {idx_fila}: Doc.vtas_raw={doc_vtas_raw} ({type(doc_vtas_raw).__name__}), Material_raw={material_raw} ({type(material_raw).__name__})")
                                    logging.debug(f"[EXPORTAR-EX] Fila {idx_fila}: Doc.vtas={doc_vtas}, Material={material}")
                                    
                                    # Validar obligatorios
                                    if not doc_vtas or not material:
                                        msg = f"Fila {idx_fila}: Faltan Doc.vtas ({doc_vtas}) o Material ({material})"
                                        logging.warning(f"[EXPORTAR-EX] {msg}")
                                        errores.append(msg)
                                        procesadas += 1
                                        continue
                                    
                                    # Verificar si el Material existe en OB.Omegas con W/C='EX'
                                    logging.debug(f"[EXPORTAR-EX] Fila {idx_fila}: Buscando Material='{material}' en OB.Omegas con W/C='EX'")
                                    cursor_check.execute("""
                                        SELECT Assy FROM [OB].[Omegas]
                                        WHERE Assy = ? AND [W/C] = 'EX'
                                    """, (material,))
                                    
                                    result = cursor_check.fetchone()
                                    logging.debug(f"[EXPORTAR-EX] Fila {idx_fila}: Resultado búsqueda: {result}")
                                    
                                    if result:
                                        # Material encontrado, actualizar PedidosCabecera
                                        logging.info(f"[EXPORTAR-EX] Fila {idx_fila}: 🔍 Material '{material}' encontrado en OB.Omegas con W/C='EX'")
                                        logging.debug(f"[EXPORTAR-EX] Fila {idx_fila}: Ejecutando UPDATE: SET EX='{material}' WHERE NumeroPedido='{doc_vtas}'")
                                        
                                        cursor.execute("""
                                            UPDATE [OB].[PedidosCabecera]
                                            SET EX = ?
                                            WHERE NumeroPedido = ?
                                        """, (material, doc_vtas))
                                        
                                        rows_affected = cursor.rowcount
                                        logging.info(f"[EXPORTAR-EX] Fila {idx_fila}: UPDATE ejecutado, filas afectadas: {rows_affected}")
                                        
                                        if rows_affected > 0:
                                            actualizado += 1
                                            logging.info(f"[EXPORTAR-EX] Fila {idx_fila}: ✅ ÉXITO - PedidosCabecera.{doc_vtas} actualizado con EX='{material}'")
                                        else:
                                            msg = f"Fila {idx_fila}: NumeroPedido '{doc_vtas}' no encontrado en PedidosCabecera"
                                            logging.warning(f"[EXPORTAR-EX] {msg}")
                                            errores.append(msg)
                                    else:
                                        # Material no encontrado
                                        msg = f"Fila {idx_fila}: Material '{material}' no encontrado en OB.Omegas con W/C='EX'"
                                        logging.warning(f"[EXPORTAR-EX] {msg}")
                                        errores.append(msg)
                                    
                                    procesadas += 1
                                    
                                except Exception as e:
                                    msg = f"Fila {idx_fila}: {str(e)}"
                                    logging.error(f"[EXPORTAR-EX] {msg}", exc_info=True)
                                    errores.append(msg)
                                    procesadas += 1
                                    continue
                            
                            logging.info(f"[EXPORTAR-EX] Confirmando transacción... Procesadas: {procesadas}, Actualizadas: {actualizado}")
                            conn.commit()
                            logging.info("[EXPORTAR-EX] Transacción confirmada exitosamente")
                    
                    finally:
                        # Limpiar archivo temporal
                        try:
                            os.unlink(temp_path)
                            logging.info("[EXPORTAR-EX] Archivo temporal eliminado")
                        except Exception as e:
                            logging.error(f"[EXPORTAR-EX] Error al eliminar archivo temporal: {str(e)}")
                
                except ImportError as e:
                    logging.error(f"[EXPORTAR-EX] openpyxl no instalado: {str(e)}")
                    return jsonify({
                        'success': False,
                        'mensaje': 'Librería openpyxl no instalada'
                    }), 500
            
            else:
                # Procesar CSV
                logging.info("[EXPORTAR-EX] Procesando archivo CSV...")
                import csv
                import io
                
                contenido = archivo.read().decode('utf-8')
                logging.info(f"[EXPORTAR-EX] Contenido CSV leído, primeros 200 caracteres: {contenido[:200]}")
                
                reader = csv.reader(io.StringIO(contenido))
                
                # Leer encabezados
                encabezados = next(reader)
                encabezados_normalizados = [h.strip() for h in encabezados]
                
                logging.info(f"[EXPORTAR-EX] Encabezados CSV RAW: {encabezados}")
                logging.info(f"[EXPORTAR-EX] Encabezados CSV normalizados: {encabezados_normalizados}")
                
                # Función para encontrar columna flexible
                def encontrar_columna(encabezados, patrones):
                    """Busca una columna con flexibilidad de nombres"""
                    for idx, encab in enumerate(encabezados):
                        encab_lower = str(encab).lower().replace(' ', '').replace('.', '').replace('_', '')
                        for patron in patrones:
                            patron_lower = patron.lower().replace(' ', '').replace('.', '').replace('_', '')
                            if patron_lower in encab_lower or encab_lower in patron_lower:
                                return idx
                    return None
                
                # Buscar columnas
                idx_doc_vtas = encontrar_columna(encabezados_normalizados, ['Doc.vtas', 'Doc vtas', 'Docventas', 'Documento venta', 'Sales document', 'Numeropedido'])
                idx_material = encontrar_columna(encabezados_normalizados, ['Material', 'Assy', 'Codigo', 'Code'])
                
                logging.info(f"[EXPORTAR-EX] Índices CSV detectados: Doc.vtas={idx_doc_vtas}, Material={idx_material}")
                
                # Si no encuentra, intentar posiciones por defecto
                if idx_doc_vtas is None:
                    idx_doc_vtas = 0
                    logging.warning(f"[EXPORTAR-EX] Doc.vtas no encontrado en CSV, usando columna 0")
                if idx_material is None:
                    idx_material = 1
                    logging.warning(f"[EXPORTAR-EX] Material no encontrado en CSV, usando columna 1")
                
                logging.info(f"[EXPORTAR-EX] Usando índices finales CSV: Doc.vtas={idx_doc_vtas} ({encabezados_normalizados[idx_doc_vtas] if idx_doc_vtas < len(encabezados_normalizados) else 'N/A'}), Material={idx_material} ({encabezados_normalizados[idx_material] if idx_material < len(encabezados_normalizados) else 'N/A'})")
                
                # Conectar a BD
                with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
                    cursor = conn.cursor()
                    cursor_check = conn.cursor()
                    logging.info("[EXPORTAR-EX] Conexión a BD establecida (CSV)")
                    
                    for idx_fila, fila in enumerate(reader, start=2):
                        if not fila or not any(cell.strip() for cell in fila):
                            logging.debug(f"[EXPORTAR-EX] Fila {idx_fila} vacía, saltando")
                            continue
                        
                        try:
                            # Validar estructura mínima
                            if len(fila) < max(idx_doc_vtas, idx_material) + 1:
                                msg = f"Fila {idx_fila}: Estructura incompleta (tiene {len(fila)} columnas, se necesitan {max(idx_doc_vtas, idx_material) + 1})"
                                logging.warning(f"[EXPORTAR-EX] {msg}")
                                errores.append(msg)
                                procesadas += 1
                                continue
                            
                            doc_vtas = fila[idx_doc_vtas].strip()
                            material = fila[idx_material].strip()
                            
                            logging.debug(f"[EXPORTAR-EX] Fila {idx_fila} CSV: Doc.vtas={doc_vtas}, Material={material}")
                            
                            if not doc_vtas or not material:
                                msg = f"Fila {idx_fila}: Faltan Doc.vtas ({doc_vtas}) o Material ({material})"
                                logging.warning(f"[EXPORTAR-EX] {msg}")
                                errores.append(msg)
                                procesadas += 1
                                continue
                            
                            # Verificar si el Material existe en OB.Omegas con W/C='EX'
                            logging.debug(f"[EXPORTAR-EX] Fila {idx_fila} CSV: Buscando Material='{material}' en OB.Omegas")
                            cursor_check.execute("""
                                SELECT Assy FROM [OB].[Omegas]
                                WHERE Assy = ? AND [W/C] = 'EX'
                            """, (material,))
                            
                            result = cursor_check.fetchone()
                            logging.debug(f"[EXPORTAR-EX] Fila {idx_fila} CSV: Resultado búsqueda: {result}")
                            
                            if result:
                                # Material encontrado, actualizar
                                logging.info(f"[EXPORTAR-EX] Fila {idx_fila} CSV: 🔍 Material '{material}' encontrado en OB.Omegas con W/C='EX'")
                                logging.debug(f"[EXPORTAR-EX] Fila {idx_fila} CSV: Ejecutando UPDATE")
                                
                                cursor.execute("""
                                    UPDATE [OB].[PedidosCabecera]
                                    SET EX = ?
                                    WHERE NumeroPedido = ?
                                """, (material, doc_vtas))
                                
                                rows_affected = cursor.rowcount
                                logging.info(f"[EXPORTAR-EX] Fila {idx_fila} CSV: UPDATE ejecutado, filas afectadas: {rows_affected}")
                                
                                if rows_affected > 0:
                                    actualizado += 1
                                    logging.info(f"[EXPORTAR-EX] Fila {idx_fila} CSV: ✅ ÉXITO - PedidosCabecera.{doc_vtas} actualizado con EX='{material}'")
                                else:
                                    msg = f"Fila {idx_fila}: NumeroPedido '{doc_vtas}' no encontrado"
                                    logging.warning(f"[EXPORTAR-EX] {msg}")
                                    errores.append(msg)
                            else:
                                msg = f"Fila {idx_fila}: Material '{material}' no encontrado en OB.Omegas con W/C='EX'"
                                logging.warning(f"[EXPORTAR-EX] {msg}")
                                errores.append(msg)
                            
                            procesadas += 1
                        
                        except Exception as e:
                            msg = f"Fila {idx_fila}: {str(e)}"
                            logging.error(f"[EXPORTAR-EX] {msg}", exc_info=True)
                            errores.append(msg)
                            procesadas += 1
                            continue
                    
                    logging.info(f"[EXPORTAR-EX] Confirmando transacción CSV... Procesadas: {procesadas}, Actualizadas: {actualizado}")
                    conn.commit()
                    logging.info("[EXPORTAR-EX] Transacción CSV confirmada")
        
        except Exception as e:
            logging.error(f"[EXPORTAR-EX] Error en BD: {str(e)}", exc_info=True)
            return jsonify({
                'success': False,
                'mensaje': f'Error en la base de datos: {str(e)}'
            }), 500
        
        # Respuesta (aunque procesadas sea 0)
        respuesta = {
            'success': True,
            'procesadas': procesadas,
            'actualizado': actualizado,
            'errores': errores if errores else []
        }
        
        logging.info(f"[EXPORTAR-EX] === EXPORTACIÓN COMPLETADA === Procesadas: {procesadas}, Actualizadas: {actualizado}, Errores: {len(errores)}")
        
        return jsonify(respuesta), 200
    
    except Exception as e:
        logging.error(f"[EXPORTAR-EX] Error inesperado: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'mensaje': f'Error inesperado: {str(e)}'
        }), 500


# ====================================================================================
# EJECUCIÓN DE LA APLICACIÓN E INICIO DE WORKERS (VERSIÓN CORREGIDA)
# ====================================================================================
def is_app_port_available(port):
    """Return whether this process can own the HTTP port before starting workers."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(('0.0.0.0', port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


if __name__ == '__main__':
    print("="*50)
    print("INICIALIZANDO API OMEGAS...")
    print("="*50)

    # app.run() ocurre al final, pero los workers se crean antes. Comprobar el
    # puerto aquí evita que una segunda instancia sin servidor deje workers
    # duplicados ejecutándose en segundo plano.
    if not is_app_port_available(APP_PORT):
        logging.error('[MAIN] El puerto %s ya está ocupado. Instancia no iniciada.', APP_PORT)
        print(f'[MAIN] El puerto {APP_PORT} ya está ocupado. Cierra la instancia anterior antes de abrir otra.')
        raise SystemExit(1)

    # Cargar configuración SMTP desde BD (ahora ConexionODBCCZ ya está definida)
    cargar_config_smtp()

    # Local audit mode exposes diagnostics without starting any worker that can
    # change orders, reservations or stock. It is intentionally opt-in.
    if os.environ.get('OMEGAS_AUDIT_ONLY', '').strip().lower() in ('1', 'true', 'yes'):
        print('[MAIN] Modo auditoría: workers de escritura deshabilitados.')
        app.run(host='0.0.0.0', port=APP_PORT, debug=DEV_MODE, use_reloader=False)
        raise SystemExit(0)

    startup_sync_thread = threading.Thread(target=run_startup_sync, daemon=True, name="StartupSync")
    startup_sync_thread.start()
    print("[MAIN] -> Sync inicial lanzada en segundo plano.")

    # --- INICIAR EL SERVIDOR FLASK ---
    print("="*50)
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = '127.0.0.1'
    print(f"Servidor Flask iniciándose en: http://{local_ip}:{APP_PORT}")
    print("="*50)

    # --- INICIAR EL WORKER DE PEDIDOS ---
    # print("[MAIN] Creando hilo para la sincronización de pedidos (auto_sync_sequenced...)")
    # Asume que la función se llama auto_sync_sequenced
    pedidos_thread = threading.Thread(target=auto_sync_sequenced, name="PedidosSync")
    pedidos_thread.daemon = True
    pedidos_thread.start()
    print("[MAIN] -> Hilo de pedidos iniciado.")

    # --- INICIAR EL WORKER QUE DISPARA LA SINCRONIZACIÓN SQL DE STOCK DE BEAMS ---
    print("[MAIN] Creando hilo para el stock de Beams (OB.sp_Sync_Beams_RawData)...")
    beams_stock_thread = threading.Thread(target=auto_sync_beams_stock, name="BeamStockSync")
    beams_stock_thread.daemon = True
    beams_stock_thread.start()
    print("[MAIN] -> Hilo de stock de Beams iniciado (lógica en SQL).")

    # --- INICIAR EL WATCHDOG DE DIAGNÓSTICO DE STOCK ---
    print("[MAIN] Creando hilo para el Watchdog de stock...")
    watchdog_thread = threading.Thread(target=stock_watchdog_loop, name="StockWatchdogSync")
    watchdog_thread.daemon = True
    watchdog_thread.start()
    print("[MAIN] -> Hilo Watchdog de stock iniciado (logs en logs/stock_watchdog.log).")
    
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
    app.run(host='0.0.0.0', port=APP_PORT, debug=DEV_MODE, use_reloader=False)

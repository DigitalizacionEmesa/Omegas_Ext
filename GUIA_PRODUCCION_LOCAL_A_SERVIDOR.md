# 🚀 Guía Definitiva: De Local a Producción - Patrón Stock_Soldadura

## Versión: 1.0 | Fecha: Abril 2026

---

## 1. ESTRUCTURA DEL PROYECTO CORRECTO

```
proyecto/
├── api/
│   ├── app.py                    ← PUNTO DE ENTRADA PRINCIPAL
│   ├── requirements.txt          ← DEPENDENCIAS CRÍTICAS
│   ├── utils/
│   │   ├── __init__.py
│   │   └── db.py                ← UTILIDADES DE BD (opcional)
│   └── __pycache__/             ← GENERADO AUTOMÁTICAMENTE
├── Templates/                    ← HTML/UI
│   ├── Welding.html
│   └── FabricaVisual.html
├── assets/                       ← CSS/JS
│   ├── styles.css
│   ├── css/
│   └── js/
├── IMAGENES/                     ← Recursos visuales
├── data/                         ← PERSISTENCIA LOCAL (config, snapshots)
│   ├── scheduler_config.json
│   └── last_stock_sync.json
├── build/                        ← SALIDA DE PYINSTALLER
├── dist/                         ← EJECUTABLE FINAL (.exe)
├── requirements.txt              ← A nivel raíz también
├── monitorsoldadura.spec         ← SPEC DE PYINSTALLER
└── .env                          ← VARIABLES DE ENTORNO (NO COMMITEAR)
```

---

## 2. DEPENDENCIAS OBLIGATORIAS (requirements.txt)

```txt
flask==2.3.3
flask-cors==4.0.0
apscheduler
pyodbc
requests
werkzeug
python-dotenv
```

**⚠️ CRÍTICO:**
- **NO usar** versiones diferentes de Flask (hay breaking changes)
- **pyodbc** DEBE estar instalado en el servidor de producción
- **Werkzeug** para hashing de contraseñas (seguridad)
- **python-dotenv** para variables de entorno

---

## 3. CONFIGURACIÓN BASE DEL APP.PY (INICIO)

### 3.1 Encoding UTF-8 en Windows (OBLIGATORIO)

```python
import sys
import io
import os

# Forzar UTF-8 en stdout para Windows - SIN ESTO CRASHEA CON CARACTERES ESPECIALES
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
```

### 3.2 Inicialización de Flask

```python
from flask import Flask, request, jsonify, session
from flask_cors import CORS
import logging

# LOGGING - Esencial para debugging en producción
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(asctime)s - %(name)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# APLICACIÓN
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'emesa_sga_secret_key_2025_dev_only')
CORS(app, supports_credentials=True)

# VARIABLES DE ENTORNO (SEGURIDAD)
DEV_MODE = os.getenv('DEV_MODE', 'False').lower() == 'true'
if DEV_MODE:
    logger.warning("⚠️ DEV_MODE ACTIVO - SEGURIDAD DESHABILITADA")
```

---

## 4. MANEJO DE RUTAS ABSOLUTAS (PyInstaller Compatible)

**ESTO ES CRÍTICO** - permite que funcione tanto en `.py` como en `.exe`:

```python
def resource_path(relative_path):
    """Obtiene la ruta absoluta al recurso (PyInstaller compatible)"""
    try:
        # Si está empaquetado en .exe
        base_path = sys._MEIPASS
    except AttributeError:
        # Si está corriendo como script .py
        base_path = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.dirname(base_path)  # Subir un nivel (al raíz del proyecto)
    return os.path.join(base_path, relative_path)

# Usar SIEMPRE resource_path() para acceder a Templates, Assets, etc
TEMPLATES_DIR = resource_path('Templates')
ASSETS_DIR = resource_path('assets')
IMAGENES_DIR = resource_path('IMAGENES')
DATA_DIR = resource_path('data')

# En rutas, usar send_from_directory:
@app.route('/Templates/<path:filename>')
def serve_templates(filename):
    return send_from_directory(TEMPLATES_DIR, filename)

@app.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory(ASSETS_DIR, filename)
```

---

## 5. CONTEXTO MANAGER: CONEXIÓN A BASE DE DATOS

**NUNCA abrir conexiones directas** - siempre usar context manager:

```python
import pyodbc

class ConexionODBC:
    """Maneja conexiones ODBC con SQL Server - PATRÓN CRÍTICO"""
    
    def __init__(self, servidor='172.16.10.10', base_datos='DataLakeSCCZ', 
                 usuario='sccz', clave='S@vera,CZ,2024'):
        self.servidor = servidor
        self.base_datos = base_datos
        self.usuario = usuario
        self.clave = clave
        self.connection = None
        self.driver_usado = None
    
    def __enter__(self):
        """Context manager entry - CONECTAR"""
        if self.conectar():
            return self.connection
        return None  # ← IMPORTANTE: devolver None si falla
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - DESCONECTAR Y ROLLBACK"""
        self.cerrar()
    
    def conectar(self):
        """Probar múltiples drivers (Windows tiene de todo)"""
        drivers_to_try = [
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "ODBC Driver 13 for SQL Server",
            "SQL Server Native Client 11.0",
            "SQL Server"
        ]
        
        for driver in drivers_to_try:
            try:
                connection_string = (
                    f"DRIVER={{{driver}}};"
                    f"Server={self.servidor};"
                    f"Database={self.base_datos};"
                    f"UID={self.usuario};"
                    f"PWD={self.clave};"
                    f"TrustServerCertificate=yes;"
                    f"Encrypt=yes;"
                    f"Connection Timeout=30;"
                )
                self.connection = pyodbc.connect(connection_string)
                self.connection.autocommit = False
                self.driver_usado = driver
                logger.info(f"✅ Connected with {driver}")
                return True
            except Exception as e:
                logger.debug(f"Driver {driver} failed: {e}")
                continue
        
        logger.error("❌ No drivers available")
        return False
    
    def cerrar(self):
        """Cerrar y limpiar"""
        if self.connection:
            try:
                self.connection.close()
            except Exception as e:
                logger.warning(f"Error closing: {e}")

# USAR SIEMPRE ASÍ:
with ConexionODBC() as conn:
    if not conn:
        return jsonify({"error": "DB connection failed"}), 500
    
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tabla")
    rows = cursor.fetchall()
    conn.commit()  # ← NO OLVIDAR COMMIT
```

---

## 6. INTEGRACIÓN CON SAP (API REST)

```python
import requests
from requests.auth import HTTPBasicAuth

class ConexionSAP:
    """Maneja llamadas a SAP REST API"""
    
    def __init__(self, url='http://emesapprdapp:8000/sap/bc/z_ordenes',
                 client='100', user='EMESA.MM', password='EMESA1234'):
        self.url = url
        self.client = client
        self.user = user
        self.password = password
    
    def obtener_datos(self, fecha_ini=None, fecha_fin=None):
        """Llamada con timeout y manejo de errores"""
        try:
            params = {
                'sap-client': self.client,
                'fecha_ini': fecha_ini,
                'fecha_fin': fecha_fin,
            }
            
            response = requests.get(
                self.url,
                params=params,
                auth=HTTPBasicAuth(self.user, self.password),
                timeout=30  # ← CRÍTICO: Timeout para no colgar
            )
            
            if response.status_code == 200:
                data = response.json()
                # SAP puede devolver {DATA: [...]} o array directo
                return {
                    "success": True,
                    "data": data.get('DATA', data) if isinstance(data, dict) else data,
                    "status_code": 200
                }
            else:
                logger.warning(f"SAP returned {response.status_code}")
                return {"success": False, "status_code": response.status_code}
        
        except requests.exceptions.Timeout:
            logger.error("SAP timeout - expected in production")
            return {"success": False, "message": "SAP Timeout", "status_code": 504}
        except Exception as e:
            logger.error(f"SAP error: {e}")
            return {"success": False, "message": str(e), "status_code": 500}
```

---

## 7. AUTENTICACIÓN Y SESIONES

```python
from werkzeug.security import generate_password_hash, check_password_hash

def verify_password(hashed, plain):
    """Verificar contraseña - SOPORTA LEGADO (SHA256) Y MODERNO (Werkzeug)"""
    hashed_str = str(hashed).strip()
    plain_str = str(plain).strip()
    
    # Caso 1: Texto plano (desarrollo local, NO usar en producción)
    if hashed_str == plain_str:
        return True
    
    # Caso 2: SHA256 legacy (64 hex chars)
    if len(hashed_str) == 64 and all(c in '0123456789abcdef' for c in hashed_str.lower()):
        import hashlib
        return hashlib.sha256(plain_str.encode()).hexdigest() == hashed_str
    
    # Caso 3: Werkzeug (bcrypt/pbkdf2) - RECOMENDADO
    try:
        return check_password_hash(hashed_str, plain_str)
    except:
        return False

@app.route('/api/login', methods=['POST'])
def login():
    """Endpoint de autenticación"""
    if 'username' in session:
        return jsonify({"success": False, "message": "Already logged in"}), 400
    
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return jsonify({"success": False, "message": "Missing credentials"}), 400
    
    try:
        with ConexionODBC() as conn:
            if not conn:
                return jsonify({"success": False, "message": "DB Error"}), 500
            
            cursor = conn.cursor()
            cursor.execute(
                "SELECT Num_Operario, Nombre, Nivel_Permisos, Contrasena FROM [OB].[Usuarios_CZ] WHERE Num_Operario = ?",
                (username,)
            )
            row = cursor.fetchone()
            
            if not row or not verify_password(row[3], password):
                logger.warning(f"❌ Login failed for {username}")
                return jsonify({"success": False, "message": "Invalid credentials"}), 401
            
            # Crear sesión
            session['username'] = row[0]
            session['nombre'] = row[1]
            session['nivel_permisos'] = row[2]
            session['login_time'] = datetime.now().isoformat()
            
            logger.info(f"✅ User {username} logged in")
            return jsonify({"success": True, "user": row[1]}), 200
    
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    """Cerrar sesión"""
    session.clear()
    return jsonify({"success": True}), 200

# PROTEGER ENDPOINTS - EN CADA RUTA:
@app.route('/api/datos', methods=['GET'])
def get_datos():
    """Endpoint protegido"""
    if 'username' not in session:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    # ... lógica del endpoint
```

---

## 8. MANEJO DE JSON Y FORMATO DE RESPUESTAS

```python
# ALWAYS JSONIFY RESPONSES
@app.route('/api/datos', methods=['GET'])
def get_datos():
    try:
        # ... lógica
        return jsonify({
            "success": True,
            "data": datos,
            "total": len(datos)
        }), 200
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

# PARSEAR JSON ENTRANTE SEGURAMENTE
@app.route('/api/guardar', methods=['POST'])
def guardar():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False}), 400
        
        valor = data.get('valor', '').strip()
        # ... procesar
        
    except Exception as e:
        logger.error(f"Parse error: {e}")
        return jsonify({"success": False, "message": str(e)}), 400
```

---

## 9. VARIABLES DE ENTORNO (.env)

**NUNCA commitear credenciales en el código** - usar `.env`:

```bash
# .env (NO INCLUIR EN GIT)
SECRET_KEY=tu_clave_super_secreta_cambiar
DEV_MODE=False
DB_SERVER=172.16.10.10
DB_USER=sccz
DB_PASSWORD=S@vera,CZ,2024
DB_DATABASE=DataLakeSCCZ
SAP_URL=http://emesapprdapp:8000/sap/bc/z_ordenes
SAP_CLIENT=100
SAP_USER=EMESA.MM
SAP_PASSWORD=EMESA1234
```

```python
# En app.py
from dotenv import load_dotenv

load_dotenv()

DB_SERVER = os.getenv('DB_SERVER', '172.16.10.10')
DB_USER = os.getenv('DB_USER', 'sccz')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'default')
# etc
```

**.gitignore:**
```
.env
*.pyc
__pycache__/
.venv/
dist/
build/
*.egg-info/
```

---

## 10. PYINSTALLER CONFIGURATION (monitorsoldadura.spec)

```python
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

BASE_DIR = os.getcwd()

a = Analysis(
    [os.path.join('api', 'app.py')],  # ← PUNTO DE ENTRADA
    pathex=[BASE_DIR],
    binaries=[],
    datas=[
        (os.path.join('Templates'), 'Templates'),      # Incluir templates
        (os.path.join('assets'), 'assets'),            # Incluir assets
        (os.path.join('IMAGENES'), 'IMAGENES'),        # Incluir imágenes
        (os.path.join('api', 'utils'), 'api/utils'),   # Módulos utils
    ],
    hiddenimports=collect_submodules('pkg_resources') + [
        'flask',
        'flask_cors',
        'pyodbc',
        'requests',
        'werkzeug',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=['apscheduler'],  # Excluir si no es necesario
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='monitorsoldadura',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Importante para ver logs
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

**Compilar:**
```powershell
pyinstaller monitorsoldadura.spec
# Salida: dist/monitorsoldadura.exe
```

---

## 11. INICIAR EL SERVIDOR EN PRODUCCIÓN

### Opción A: Script Python directo

```bash
# Terminal 1: Activar venv
cd C:\Proyectos\tu_proyecto
.venv\Scripts\activate

# Terminal 2: Ejecutar app
python api/app.py
```

### Opción B: Ejecutable compilado

```bash
dist/monitorsoldadura.exe
# Automáticamente inicia en http://localhost:3042
```

### Opción C: Windows Service (Recomendado para producción)

Usar `NSSM` (Non-Sucking Service Manager):

```powershell
# Descargar NSSM: https://nssm.cc/download
# Extraer en C:\NSSM

cd C:\NSSM\win64

# Instalar servicio
.\nssm.exe install "Stock_Soldadura" "C:\Proyectos\Stock_Soldadura\dist\monitorsoldadura.exe"

# Configurar para iniciar automáticamente
.\nssm.exe set "Stock_Soldadura" Start SERVICE_AUTO_START

# Iniciar servicio
.\nssm.exe start "Stock_Soldadura"

# Ver estado
.\nssm.exe status "Stock_Soldadura"

# Ver logs
C:\Proyectos\Stock_Soldadura\logs\  # Configurar en app.py
```

---

## 12. DEBUGGING: ERRORES COMUNES EN PRODUCCIÓN

### Error: "Module not found"

```
❌ ModuleNotFoundError: No module named 'pyodbc'
```

**Solución:**
```bash
pip install -r requirements.txt
# Verificar: python -c "import pyodbc; print('OK')"
```

### Error: "Cannot connect to database"

```
❌ pyodbc.OperationalError: [28000] Login failed
```

**Checklist:**
- [ ] Credenciales correctas (sccz / S@vera,CZ,2024)
- [ ] SQL Server alcanzable desde el servidor (ping 172.16.10.10)
- [ ] Driver ODBC instalado (`odbcad32.exe` en Windows)
- [ ] TrustServerCertificate=yes configurado
- [ ] Puerto 1433 abierto en firewall

```python
# Testear directamente
with ConexionODBC() as conn:
    if conn:
        print("✅ Database OK")
    else:
        print("❌ Database connection failed")
```

### Error: "UTF-8 encoding error"

```
❌ UnicodeEncodeError: 'ascii' codec can't encode
```

**Solución:** Agregar al inicio de app.py (ya incluido)

```python
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
```

### Error: "Template not found"

```
❌ FileNotFoundError: /Templates/Welding.html
```

**Causa:** Usar rutas hardcoded en vez de `resource_path()`

**Solución:**
```python
# ❌ MALO
return send_from_directory('Templates', 'Welding.html')

# ✅ BUENO
return send_from_directory(TEMPLATES_DIR, 'Welding.html')
```

### Error: "SAP timeout"

```
❌ requests.exceptions.Timeout: HTTPConnectionPool timeout
```

**Esto es NORMAL en producción.** Implementar reintentos:

```python
def obtener_datos_con_reintentos(url, max_intentos=3):
    """SAP puede fallar - reintentar 3 veces"""
    for intento in range(max_intentos):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                return response.json()
        except requests.exceptions.Timeout:
            logger.warning(f"SAP timeout, intento {intento+1}/{max_intentos}")
            if intento < max_intentos - 1:
                time.sleep(2)  # Esperar 2 segundos antes de reintentar
    
    logger.error("SAP unreachable after 3 attempts")
    return None
```

---

## 13. MONITORING Y LOGS

```python
# Guardar logs a archivo (para producción)
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),  # Guardar en disco
        logging.StreamHandler()                # También en consola
    ]
)

# En el código:
logger.info("✅ Evento bueno")
logger.warning("⚠️ Advertencia")
logger.error("❌ Error crítico")

# Usar emojis para ser visible en gigabytes de logs
# ✅ = ok, ❌ = error, ⚠️ = warning, 🔌 = conexión, 📡 = SAP, 💾 = BD
```

**Revisar logs:**
```bash
tail -f logs/app.log
# O en Windows
Get-Content logs/app.log -Tail 20 -Wait
```

---

## 14. CHECKLIST FINAL: LOCAL → PRODUCCIÓN

- [ ] **Dependencias:** `pip install -r requirements.txt`
- [ ] **Base de datos:** Conectividad probada con ConexionODBC
- [ ] **SAP:** Endpoint funcional, timeout configurado
- [ ] **Estructura:** Templates/, assets/, IMAGENES/ incluidos
- [ ] **Rutas:** TODAS usan `resource_path()` NO hardcoded
- [ ] **Sessions:** Todos los endpoints protegidos tiene `if 'username' not in session`
- [ ] **Variables entorno:** `.env` NO está en Git, credenciales seguras
- [ ] **Logs:** Sistema de logging funcional, visible en producción
- [ ] **Encoding:** Windows UTF-8 setup en la parte superior de app.py
- [ ] **PyInstaller:** Spec configurado correctamente si usas .exe
- [ ] **Error handling:** Todos los endpoints tienen try/except con logging
- [ ] **Context managers:** Todas las conexiones usan `with ConexionODBC()`
- [ ] **Commits:** NUNCA olvida `conn.commit()` en operaciones de escritura
- [ ] **CORS:** `CORS(app, supports_credentials=True)` configurado
- [ ] **Puerto:** Confirm Flask corre en puerto correcto (3042)

---

## 15. EJEMPLO ENDPOINT COMPLETO (PRODUCCIÓN-READY)

```python
@app.route('/api/materiales', methods=['GET'])
def get_materiales():
    """
    Obtener lista de materiales - PUNTO DE ENTRADA COMPLETO
    Requerimientos: autenticado, BD conectada, timeout manejado
    """
    # 1. VALIDAR AUTENTICACIÓN
    if 'username' not in session:
        logger.warning("❌ Acceso sin autenticación a /api/materiales")
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    # 2. PARÁMETROS OPCIONALES
    limite = request.args.get('limit', 100, type=int)
    filtro = request.args.get('filter', '', str).strip()
    
    try:
        # 3. CONECTAR A BD
        with ConexionODBC() as conn:
            if not conn:
                logger.error("❌ DB connection failed in /api/materiales")
                return jsonify({"success": False, "message": "DB Error"}), 500
            
            cursor = conn.cursor()
            
            # 4. EJECUTAR QUERY CON PARÁMETROS
            query = "SELECT id, codigo, nombre, stock FROM maestro_materiales WHERE activo = 1"
            params = []
            
            if filtro:
                query += " AND nombre LIKE ?"
                params.append(f"%{filtro}%")
            
            query += f" ORDER BY nombre LIMIT {limite}"
            
            logger.debug(f"Executing query: {query} with params: {params}")
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # 5. TRANSFORMAR RESULTADOS
            materiales = [
                {
                    'id': row[0],
                    'codigo': row[1],
                    'nombre': row[2],
                    'stock': float(row[3]) if row[3] else 0
                }
                for row in rows
            ]
            
            logger.info(f"✅ Retrieved {len(materiales)} materials")
            
            # 6. RETORNAR RESPONSE
            return jsonify({
                "success": True,
                "data": materiales,
                "total": len(materiales),
                "filtered": bool(filtro)
            }), 200
    
    except Exception as e:
        logger.error(f"❌ Error in /api/materiales: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "message": "Internal server error",
            "error": str(e) if DEV_MODE else "Server error"
        }), 500
```

---

## 📞 SOPORTE Y CONTACTO

Si algo no funciona:

1. **Revisar logs** - 90% de los problemas están en los logs
2. **Verificar conexiones** - BD, SAP, Network
3. **Probar localmente** - `python api/app.py`
4. **Check firewall** - Puerto 1433 (SQL), puerto de SAP
5. **Revisar credenciales** - `.env`, permisos de BD

---

**Generated from Stock_Soldadura - Production-Proven Patterns 🎯**

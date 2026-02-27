# -*- coding: utf-8 -*-
"""
Sistema de Gestión de Usuarios - API Independiente
===================================================
Autor: Sistema EMESA
Fecha: 2025
Descripción: API Flask para gestión de usuarios con contraseñas encriptadas (Werkzeug/Scrypt)
"""

from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from pathlib import Path
import pyodbc
import os

# ====================================================================================
# CONFIGURACIÓN DE LA APLICACIÓN
# ====================================================================================

# Ruta absoluta a la carpeta compartida (pantallas HTML)
RUTA_PANTALLAS = r"\\EMEBIDWH\Digitalizacion\Gestion_Usuarios_CZ\templates"
# Ruta absoluta a la carpeta de assets
RUTA_ASSETS = r"\\EMEBIDWH\Digitalizacion\Gestion_Usuarios_CZ\static"
# Ruta absoluta a la carpeta de imágenes
RUTA_IMAGENES = r"\\EMEBIDWH\Digitalizacion\Gestion_Usuarios_CZ\static\images"
# Inicializar Flask con las rutas personalizadas
app = Flask(
    __name__,
    static_folder=RUTA_ASSETS,      # ✅ Carpeta static
    static_url_path='/static',       # ✅ URL base para archivos static
    template_folder=RUTA_PANTALLAS   # ✅ Carpeta templates
)
CORS(app, supports_credentials=True, resources={r"/*": {"origins": "*"}}, methods=["GET", "POST", "PUT", "OPTIONS"], allow_headers=["Content-Type"])

# Credenciales de base de datos CZ
DB_USERCZ = 'sccz'
DB_PASSWORDCZ = 'S@vera,CZ,2024'

print(f"📁 Templates: {RUTA_PANTALLAS}")
print(f"📁 Static: {RUTA_ASSETS}")
print(f"📁 Images: {RUTA_IMAGENES}")

# ====================================================================================
# FUNCIONES DE ENCRIPTACIÓN WERKZEUG
# ====================================================================================

def hash_password(password):
    """Encripta una contraseña usando Werkzeug (Scrypt)"""
    return generate_password_hash(password)

def verify_password(password, hashed_password):
    """Verifica una contraseña contra su hash"""
    if not hashed_password:
        return False
    
    try:
        # Verificar si es hash werkzeug
        if hashed_password.startswith('scrypt:') or hashed_password.startswith('pbkdf2:'):
            return check_password_hash(hashed_password, password)
        
        # Fallback: texto plano (legacy)
        return password == hashed_password
        
    except Exception as e:
        print(f"❌ Error verificando contraseña: {e}")
        return False

def is_password_hashed(password):
    """Determina si una contraseña ya está encriptada"""
    if not password:
        return False
    return password.startswith('scrypt:') or password.startswith('pbkdf2:')

# ====================================================================================
# CLASE DE CONEXIÓN ODBC PARA CZ
# ====================================================================================

class ConexionODBCCZ:
    """
    Clase para gestionar conexiones ODBC a SQL Server de Chequia.
    """
    
    def __init__(self, database='mapexbp', servidor='172.16.10.10'):
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
            
            self.conn = pyodbc.connect(conn_str, timeout=5, autocommit=True)
            return self.conn
            
        except Exception as e:
            print(f"❌ Error conectando a la base de datos CZ: {e}")
            return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.close()

# ====================================================================================
# RUTAS ESTÁTICAS Y TEMPLATES
# ====================================================================================

@app.route('/')
def index():
    return redirect('/templates/Configurar_Usuario.html')

@app.route('/test')
def test():
    return "✅ Servidor funcionando correctamente!"

@app.route('/test_db')
def test_db():
    """Endpoint de prueba para verificar conexión a BD de CZ"""
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'success': False, 'message': 'Error de conexión a BD CZ'}), 500
            
            cursor = conn.cursor()
            
            # Contar usuarios
            cursor.execute("SELECT COUNT(*) FROM General.Usuarios")
            total = cursor.fetchone()[0]
            
            # Obtener algunos usuarios de ejemplo
            cursor.execute("""
                SELECT TOP 5 Id_Usuario, Num_Operario, Nombre, Nivel_Permisos
                FROM General.Usuarios
                ORDER BY Id_Usuario
            """)
            usuarios = []
            for row in cursor.fetchall():
                usuarios.append({
                    'id': row[0],
                    'num_operario': row[1],
                    'nombre': row[2],
                    'nivel': row[3]
                })
            
            return jsonify({
                'success': True,
                'message': 'Conexión exitosa a DataLakeSCCZ',
                'total_usuarios': total,
                'usuarios_ejemplo': usuarios
            })
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/templates/<path:filename>')
def servir_template(filename):
    print(f"🔍 DEBUG: Petición a /templates/{filename}")
    print(f"🔍 DEBUG: RUTA_PANTALLAS = {RUTA_PANTALLAS}")
    return send_from_directory(RUTA_PANTALLAS, filename)

# Flask ya maneja automáticamente /static/ con la configuración static_folder
# Pero agregamos esta ruta de respaldo por si acaso
@app.route('/static/<path:filename>')
def servir_static_backup(filename):
    print(f"🔍 DEBUG: Petición a /static/{filename} (ruta de respaldo)")
    return send_from_directory(RUTA_ASSETS, filename)

@app.route('/IMAGENES/<path:filename>')
def servir_imagenes(filename):
    """Ruta de compatibilidad para imágenes"""
    print(f"🔍 DEBUG: Petición a /IMAGENES/{filename}")
    return send_from_directory(RUTA_IMAGENES, filename)

# ====================================================================================
# ENDPOINTS DE AUTENTICACIÓN
# ====================================================================================

@app.route('/api/login', methods=['POST'])
def login():
    """Login con verificación de contraseña encriptada"""
    data = request.json
    usuario = data.get('usuario')
    password = data.get('password')
    
    if not usuario or not password:
        return jsonify({'success': False, 'message': 'Usuario y contraseña requeridos'}), 400
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'success': False, 'message': 'Error de conexión'}), 500
            
            cursor = conn.cursor()
            cursor.execute(
                "SELECT Id_Usuario, Num_Operario, Nombre, Nivel_Permisos, Roles, Contrasena "
                "FROM General.Usuarios WHERE Num_Operario=?",
                (usuario,)
            )
            row = cursor.fetchone()
            
            if row:
                stored_password = row[5]
                
                if verify_password(password, stored_password):
                    # Migrar a werkzeug si está en texto plano
                    if not is_password_hashed(stored_password):
                        new_hash = hash_password(password)
                        cursor.execute(
                            "UPDATE General.Usuarios SET Contrasena=? WHERE Id_Usuario=?",
                            (new_hash, row[0])
                        )
                        conn.commit()
                        print(f"✅ Contraseña migrada a werkzeug para usuario {usuario}")
                    
                    return jsonify({
                        'success': True,
                        'id': row[0],
                        'num_operario': row[1],
                        'nombre': row[2],
                        'nivel': row[3],
                        'rol': row[4]
                    })
                else:
                    return jsonify({'success': False, 'message': 'Contraseña incorrecta'}), 401
            else:
                return jsonify({'success': False, 'message': 'Usuario no encontrado'}), 401
                
    except Exception as e:
        print(f"❌ Error en login: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/cambiar_password', methods=['POST'])
def cambiar_password():
    """Cambiar contraseña de usuario (encriptada con werkzeug)"""
    data = request.json
    usuario = data.get('usuario')
    actual = data.get('actual')
    nueva = data.get('nueva')
    
    if not usuario or not actual or not nueva:
        return jsonify({'success': False, 'message': 'Faltan datos'}), 400
    
    if len(nueva) < 4:
        return jsonify({'success': False, 'message': 'Contraseña debe tener al menos 4 caracteres'}), 400
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'success': False, 'message': 'Error de conexión'}), 500
            
            cursor = conn.cursor()
            cursor.execute(
                "SELECT Contrasena FROM General.Usuarios WHERE Num_Operario=?",
                (usuario,)
            )
            row = cursor.fetchone()
            
            if not row:
                return jsonify({'success': False, 'message': 'Usuario no encontrado'}), 404
            
            stored_password = row[0]
            
            if not verify_password(actual, stored_password):
                return jsonify({'success': False, 'message': 'Contraseña actual incorrecta'}), 401
            
            nueva_encriptada = hash_password(nueva)
            
            cursor.execute(
                "UPDATE General.Usuarios SET Contrasena=? WHERE Num_Operario=?",
                (nueva_encriptada, usuario)
            )
            conn.commit()
            
            print(f"✅ Contraseña cambiada para usuario: {usuario}")
            
            return jsonify({'success': True, 'message': 'Contraseña actualizada correctamente'})
            
    except Exception as e:
        print(f"❌ Error cambiando contraseña: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ====================================================================================
# ENDPOINTS DE GESTIÓN DE USUARIOS
# ====================================================================================

@app.route('/api/usuarios', methods=['GET'])
def get_usuarios():
    """Obtener lista de usuarios filtrados por nivel de permisos"""
    id_usuario_actual = request.args.get('id_usuario', type=int)
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'success': False, 'message': 'Error de conexión'}), 500
            
            cursor = conn.cursor()
            
            # Obtener nivel del usuario actual
            nivel_actual = 0
            if id_usuario_actual:
                cursor.execute(
                    "SELECT Nivel_Permisos FROM General.Usuarios WHERE Id_Usuario=?",
                    (id_usuario_actual,)
                )
                row = cursor.fetchone()
                nivel_actual = row[0] if row else 0

            # Obtener todos los usuarios
            cursor.execute("""
                SELECT Id_Usuario, Num_Operario, Nombre, Nivel_Permisos, Roles
                FROM General.Usuarios
                ORDER BY Num_Operario
            """)
            
            usuarios = []
            for u in cursor.fetchall():
                # Filtrar según nivel (supervisores no ven admins)
                if nivel_actual < 9 and u[3] in (9, 10):
                    continue
                
                usuarios.append({
                    'id': u[0],
                    'num_operario': u[1],
                    'nombre': u[2],
                    'nivel': u[3],
                    'rol': u[4]
                })
            
            return jsonify({'success': True, 'usuarios': usuarios})
            
    except Exception as e:
        print(f"❌ Error obteniendo usuarios: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/usuarios/crear', methods=['POST'])
def crear_usuario():
    """Crear nuevo usuario con contraseña encriptada"""
    data = request.json
    num_operario = data.get('num_operario')
    nombre = data.get('nombre')
    contrasena = data.get('contrasena')
    nivel = data.get('nivel', 1)
    rol = data.get('rol', '')
    
    if not num_operario or not nombre or not contrasena:
        return jsonify({'success': False, 'message': 'Faltan datos requeridos'}), 400
    
    if len(contrasena) < 4:
        return jsonify({'success': False, 'message': 'Contraseña debe tener al menos 4 caracteres'}), 400
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'success': False, 'message': 'Error de conexión'}), 500
            
            cursor = conn.cursor()
            
            # Verificar si el operario ya existe
            cursor.execute(
                "SELECT COUNT(*) FROM General.Usuarios WHERE Num_Operario=?",
                (num_operario,)
            )
            if cursor.fetchone()[0] > 0:
                return jsonify({'success': False, 'message': 'El número de operario ya existe'}), 400
            
            # Encriptar contraseña
            contrasena_encriptada = hash_password(contrasena)
            
            # Insertar usuario
            cursor.execute(
                "INSERT INTO General.Usuarios (Num_Operario, Nombre, Contrasena, Nivel_Permisos, Roles) "
                "VALUES (?, ?, ?, ?, ?)",
                (num_operario, nombre, contrasena_encriptada, nivel, rol)
            )
            conn.commit()
            
            print(f"✅ Usuario creado: {num_operario}")
            
            return jsonify({'success': True, 'message': 'Usuario creado correctamente'})
            
    except Exception as e:
        print(f"❌ Error creando usuario: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/usuarios/actualizar_operario', methods=['POST'])
def actualizar_operario():
    """Actualizar número de operario"""
    data = request.json
    user_id = data.get('id')
    nuevo_operario = data.get('num_operario')
    
    if not user_id or not nuevo_operario:
        return jsonify({'success': False, 'message': 'Faltan datos'}), 400
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'success': False, 'message': 'Error de conexión'}), 500
            
            cursor = conn.cursor()
            
            # Verificar que no exista otro usuario con ese operario
            cursor.execute(
                "SELECT COUNT(*) FROM General.Usuarios WHERE Num_Operario=? AND Id_Usuario!=?",
                (nuevo_operario, user_id)
            )
            if cursor.fetchone()[0] > 0:
                return jsonify({'success': False, 'message': 'El número de operario ya existe'}), 400
            
            cursor.execute(
                "UPDATE General.Usuarios SET Num_Operario=? WHERE Id_Usuario=?",
                (nuevo_operario, user_id)
            )
            conn.commit()
            
            return jsonify({'success': True})
            
    except Exception as e:
        print(f"❌ Error actualizando operario: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/usuarios/actualizar_nombre', methods=['POST'])
def actualizar_nombre():
    """Actualizar nombre de usuario"""
    data = request.json
    user_id = data.get('id')
    nuevo_nombre = data.get('nombre')
    
    if not user_id or not nuevo_nombre:
        return jsonify({'success': False, 'message': 'Faltan datos'}), 400
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'success': False, 'message': 'Error de conexión'}), 500
            
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE General.Usuarios SET Nombre=? WHERE Id_Usuario=?",
                (nuevo_nombre, user_id)
            )
            conn.commit()
            
            return jsonify({'success': True})
            
    except Exception as e:
        print(f"❌ Error actualizando nombre: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/usuarios/actualizar_nivel', methods=['POST'])
def actualizar_nivel():
    """Actualizar nivel de permisos"""
    data = request.json
    user_id = data.get('id')
    nuevo_nivel = data.get('nivel')
    
    if not user_id or nuevo_nivel is None:
        return jsonify({'success': False, 'message': 'Faltan datos'}), 400
    
    if nuevo_nivel < 1 or nuevo_nivel > 10:
        return jsonify({'success': False, 'message': 'Nivel debe estar entre 1 y 10'}), 400
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'success': False, 'message': 'Error de conexión'}), 500
            
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE General.Usuarios SET Nivel_Permisos=? WHERE Id_Usuario=?",
                (nuevo_nivel, user_id)
            )
            conn.commit()
            
            return jsonify({'success': True})
            
    except Exception as e:
        print(f"❌ Error actualizando nivel: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/usuarios/actualizar_rol', methods=['POST'])
def actualizar_rol():
    """Actualizar rol de usuario"""
    data = request.json
    user_id = data.get('id')
    nuevo_rol = data.get('rol')
    
    if not user_id:
        return jsonify({'success': False, 'message': 'Falta ID de usuario'}), 400
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'success': False, 'message': 'Error de conexión'}), 500
            
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE General.Usuarios SET Roles=? WHERE Id_Usuario=?",
                (nuevo_rol, user_id)
            )
            conn.commit()
            
            return jsonify({'success': True})
            
    except Exception as e:
        print(f"❌ Error actualizando rol: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/usuarios/actualizar_contrasena', methods=['POST'])
def actualizar_contrasena():
    """Actualizar contraseña de usuario (encriptada)"""
    data = request.json
    user_id = data.get('id')
    nueva_contrasena = data.get('contrasena')
    
    if not user_id or not nueva_contrasena:
        return jsonify({'success': False, 'message': 'Faltan datos'}), 400
    
    if len(nueva_contrasena) < 4:
        return jsonify({'success': False, 'message': 'Contraseña debe tener al menos 4 caracteres'}), 400
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'success': False, 'message': 'Error de conexión'}), 500
            
            cursor = conn.cursor()
            
            # Encriptar nueva contraseña
            contrasena_encriptada = hash_password(nueva_contrasena)
            
            cursor.execute(
                "UPDATE General.Usuarios SET Contrasena=? WHERE Id_Usuario=?",
                (contrasena_encriptada, user_id)
            )
            conn.commit()
            
            print(f"✅ Contraseña actualizada para usuario ID: {user_id}")
            
            return jsonify({'success': True})
            
    except Exception as e:
        print(f"❌ Error actualizando contraseña: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/usuarios/eliminar', methods=['POST'])
def eliminar_usuario():
    """Eliminar usuario (protege usuario ID 1)"""
    data = request.json
    user_id = data.get('id')
    
    if not user_id:
        return jsonify({'success': False, 'message': 'Falta ID de usuario'}), 400
    
    if user_id == 1:
        return jsonify({'success': False, 'message': 'No se puede eliminar el administrador principal'}), 403
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'success': False, 'message': 'Error de conexión'}), 500
            
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM General.Usuarios WHERE Id_Usuario=?",
                (user_id,)
            )
            conn.commit()
            
            print(f"✅ Usuario ID {user_id} eliminado")
            
            return jsonify({'success': True})
            
    except Exception as e:
        print(f"❌ Error eliminando usuario: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/resetear_contrasena', methods=['POST'])
def resetear_contrasena():
    """Resetear contraseña a '1234' (solo admin ID 1)"""
    data = request.json
    admin_id = data.get('admin_id')
    target_user_id = data.get('id')
    
    if not admin_id or not target_user_id:
        return jsonify({'success': False, 'message': 'Faltan datos'}), 400
    
    if admin_id != 1:
        return jsonify({'success': False, 'message': 'Solo el administrador principal puede resetear contraseñas'}), 403
    
    if target_user_id == 1:
        return jsonify({'success': False, 'message': 'No se puede resetear la contraseña del administrador principal'}), 403
    
    try:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
            if conn is None:
                return jsonify({'success': False, 'message': 'Error de conexión'}), 500
            
            cursor = conn.cursor()
            
            # Encriptar "1234"
            nueva_contrasena = hash_password("1234")
            
            cursor.execute(
                "UPDATE General.Usuarios SET Contrasena=? WHERE Id_Usuario=?",
                (nueva_contrasena, target_user_id)
            )
            conn.commit()
            
            print(f"✅ Contraseña reseteada a '1234' para usuario ID: {target_user_id}")
            
            return jsonify({'success': True, 'message': 'Contraseña reseteada a 1234'})
            
    except Exception as e:
        print(f"❌ Error reseteando contraseña: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ====================================================================================
# EJECUCIÓN DEL SERVIDOR
# ====================================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3527))
    
    print("=" * 60)
    print("🚀 API DE GESTIÓN DE USUARIOS - CHEQUIA")
    print("=" * 60)
    print(f"📡 Servidor: http://localhost:{port}")
    print(f"🗂️  Base de datos: DataLakeSCCZ.General.Usuarios (172.16.10.10)")
    print(f"🔐 Encriptación: Werkzeug (Scrypt)")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=True)
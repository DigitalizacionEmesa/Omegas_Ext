/**
 * =====================================================
 * AUTH HELPER - Funciones de ayuda para autenticación
 * EMESA Omegas Application
 * =====================================================
 * 
 * Este archivo proporciona funciones de ayuda para verificar
 * sesión y permisos en todas las páginas de la aplicación.
 * 
 * Uso:
 *   <script src="/assets/authHelper.js"></script>
 *   <script>
 *     AuthHelper.requireAuth(); // Requiere autenticación
 *     AuthHelper.requireLevel(5); // Requiere nivel mínimo 5
 *   </script>
 */

(function() {
    'use strict';

    // Configuración
    const CONFIG = {
        loginPage: '/Pantallas/Pantallas_Generales/Pantalla_login.html',
        homePage: '/Pantallas/Pantallas_Generales/Pantalla_INICIO.html',
        sessionKeys: ['usuarioActual', 'usuarioSGA', 'omegas_user_session']
    };

    /**
     * Obtiene el usuario actual de localStorage
     * Busca en múltiples claves por compatibilidad
     */
    function getCurrentUser() {
        for (const key of CONFIG.sessionKeys) {
            try {
                const data = localStorage.getItem(key);
                if (data) {
                    const user = JSON.parse(data);
                    if (user && user.id) {
                        return user;
                    }
                }
            } catch (e) {
                console.warn(`Error parsing ${key}:`, e);
            }
        }
        return null;
    }

    /**
     * Verifica si hay sesión activa
     */
    function isAuthenticated() {
        return getCurrentUser() !== null;
    }

    /**
     * Obtiene el nivel de permisos del usuario actual
     */
    function getUserLevel() {
        const user = getCurrentUser();
        return user ? (user.nivel_permisos || user.nivel || 0) : 0;
    }

    /**
     * Requiere autenticación - redirige al login si no hay sesión
     * @param {Function} callback - Función a ejecutar si está autenticado
     */
    function requireAuth(callback) {
        const user = getCurrentUser();
        
        if (!user) {
            console.log('🔒 No hay sesión activa, redirigiendo al login...');
            window.location.href = CONFIG.loginPage;
            return false;
        }
        
        console.log(`✅ Sesión activa: ${user.nombre} (Nivel ${user.nivel_permisos || user.nivel})`);
        
        if (typeof callback === 'function') {
            callback(user);
        }
        
        return true;
    }

    /**
     * Requiere nivel mínimo de permisos
     * @param {number} minLevel - Nivel mínimo requerido
     * @param {Function} callback - Función a ejecutar si tiene permisos
     */
    function requireLevel(minLevel, callback) {
        const user = getCurrentUser();
        
        if (!user) {
            console.log('🔒 No hay sesión activa, redirigiendo al login...');
            window.location.href = CONFIG.loginPage;
            return false;
        }
        
        const userLevel = user.nivel_permisos || user.nivel || 0;
        
        if (userLevel < minLevel) {
            const levelNames = {
                1: 'Básico',
                5: 'Intermedio',
                10: 'Administrador'
            };
            console.log(`❌ Acceso denegado. Requiere nivel ${minLevel}, usuario tiene ${userLevel}`);
            alert(`❌ Acceso denegado.\n\nNecesitas nivel ${minLevel} (${levelNames[minLevel] || 'Superior'}) para acceder a esta sección.\nTu nivel actual: ${userLevel}`);
            window.location.href = CONFIG.homePage;
            return false;
        }
        
        console.log(`✅ Acceso permitido: ${user.nombre} (Nivel ${userLevel})`);
        
        if (typeof callback === 'function') {
            callback(user);
        }
        
        return true;
    }

    /**
     * Cierra sesión y limpia localStorage
     */
    function logout() {
        for (const key of CONFIG.sessionKeys) {
            localStorage.removeItem(key);
        }
        localStorage.removeItem('loggedUser');
        window.location.href = CONFIG.loginPage;
    }

    /**
     * Sincroniza datos entre las diferentes claves de sesión
     * Útil para mantener compatibilidad con código legacy
     */
    function syncSession(userData) {
        const usuarioSGA = {
            id: userData.id,
            num_operario: userData.num_operario,
            nombre: userData.nombre,
            nivel: userData.nivel_permisos || userData.nivel,
            roles: userData.roles,
            nivel_permisos: userData.nivel_permisos || userData.nivel
        };
        localStorage.setItem('usuarioSGA', JSON.stringify(usuarioSGA));
        
        const usuarioActual = {
            id: userData.id,
            nombre: userData.nombre,
            nivel_permisos: userData.nivel_permisos || userData.nivel,
            num_operario: userData.num_operario,
            roles: userData.roles
        };
        localStorage.setItem('usuarioActual', JSON.stringify(usuarioActual));
    }

    /**
     * Crea un widget de usuario simple (sin dependencia de LoginModal)
     */
    function createSimpleUserWidget(containerId) {
        const user = getCurrentUser();
        if (!user) return null;
        
        const container = document.getElementById(containerId);
        if (!container) return null;
        
        const initials = user.nombre ? 
            user.nombre.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase() : 
            '??';
        
        const levelName = {
            1: 'Básico',
            5: 'Intermedio', 
            10: 'Administrador'
        }[user.nivel_permisos || user.nivel] || 'Usuario';
        
        container.innerHTML = `
            <div class="user-widget" style="display:flex;align-items:center;gap:10px;padding:8px 16px;background:#f8f9fa;border-radius:25px;cursor:pointer;position:relative;" id="simpleUserWidget">
                <div style="width:36px;height:36px;background:linear-gradient(135deg,#0066cc,#00a8ff);border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:600;font-size:14px;">${initials}</div>
                <div style="display:flex;flex-direction:column;">
                    <span style="font-size:14px;font-weight:600;color:#333;">${user.nombre || 'Usuario'}</span>
                    <span style="font-size:11px;color:#666;">${levelName}</span>
                </div>
                <div id="simpleUserDropdown" style="position:absolute;top:calc(100% + 8px);right:0;background:#fff;border-radius:8px;box-shadow:0 5px 20px rgba(0,0,0,0.15);min-width:180px;opacity:0;visibility:hidden;transform:translateY(-10px);transition:all 0.3s ease;z-index:100;">
                    <div style="padding:12px 16px;display:flex;align-items:center;gap:10px;color:#333;cursor:pointer;border-bottom:1px solid #eee;" onclick="window.location.href='/Pantallas/Pantallas_Configuración/scrCambiarPassword.html'">
                        🔑 Cambiar Contraseña
                    </div>
                    <div style="padding:12px 16px;display:flex;align-items:center;gap:10px;color:#dc3545;cursor:pointer;" onclick="AuthHelper.logout()">
                        🚪 Cerrar Sesión
                    </div>
                </div>
            </div>
        `;
        
        // Toggle dropdown
        const widget = document.getElementById('simpleUserWidget');
        const dropdown = document.getElementById('simpleUserDropdown');
        
        widget.addEventListener('click', (e) => {
            e.stopPropagation();
            const isVisible = dropdown.style.opacity === '1';
            dropdown.style.opacity = isVisible ? '0' : '1';
            dropdown.style.visibility = isVisible ? 'hidden' : 'visible';
            dropdown.style.transform = isVisible ? 'translateY(-10px)' : 'translateY(0)';
        });
        
        document.addEventListener('click', () => {
            dropdown.style.opacity = '0';
            dropdown.style.visibility = 'hidden';
            dropdown.style.transform = 'translateY(-10px)';
        });
        
        return widget;
    }

    // Exportar API global
    window.AuthHelper = {
        getCurrentUser,
        isAuthenticated,
        getUserLevel,
        requireAuth,
        requireLevel,
        logout,
        syncSession,
        createSimpleUserWidget,
        
        // Configuración
        setConfig: (newConfig) => {
            Object.assign(CONFIG, newConfig);
        }
    };

})();

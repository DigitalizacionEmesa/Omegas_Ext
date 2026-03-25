// sharedSession.js - Sistema de Gestión de Sesión Compartida
// =====================================================================
// Este módulo sincroniza automáticamente la sesión entre múltiples pestañas/ventanas

(function() {
  'use strict';

  // Configuración
  const SESSION_CONFIG = {
    STORAGE_KEY: 'usuarioSGA',
    CHECK_INTERVAL: 1000, // Verificar cada segundo si hay cambios
    SESSION_TIMEOUT: 8 * 60 * 60 * 1000, // 8 horas
    LAST_ACTIVITY_KEY: 'lastActivityTime'
  };

  let lastKnownSession = null;
  let checkInterval = null;

  // Función para obtener la sesión actual
  function getCurrentSession() {
    try {
      const sessionData = localStorage.getItem(SESSION_CONFIG.STORAGE_KEY);
      return sessionData ? JSON.parse(sessionData) : null;
    } catch (error) {
      console.error('[SharedSession] Error leyendo sesión:', error);
      return null;
    }
  }

  // Función para verificar si la sesión ha expirado
  function isSessionExpired() {
    try {
      const lastActivity = localStorage.getItem(SESSION_CONFIG.LAST_ACTIVITY_KEY);
      if (!lastActivity) return false;

      const timeSinceLastActivity = Date.now() - parseInt(lastActivity, 10);
      return timeSinceLastActivity > SESSION_CONFIG.SESSION_TIMEOUT;
    } catch (error) {
      return false;
    }
  }

  // Función para actualizar la última actividad
  function updateLastActivity() {
    try {
      localStorage.setItem(SESSION_CONFIG.LAST_ACTIVITY_KEY, Date.now().toString());
    } catch (error) {
      console.error('[SharedSession] Error actualizando actividad:', error);
    }
  }

  // Función para verificar cambios en la sesión
  function checkSessionChanges() {
    const currentSession = getCurrentSession();
    
    // Si la sesión expiró, cerrarla
    if (currentSession && isSessionExpired()) {
      console.log('[SharedSession] Sesión expirada, cerrando...');
      localStorage.removeItem(SESSION_CONFIG.STORAGE_KEY);
      localStorage.removeItem(SESSION_CONFIG.LAST_ACTIVITY_KEY);
      window.location.reload();
      return;
    }

    // Detectar cambios en la sesión
    const currentSessionStr = JSON.stringify(currentSession);
    const lastSessionStr = JSON.stringify(lastKnownSession);

    if (currentSessionStr !== lastSessionStr) {
      console.log('[SharedSession] Cambio de sesión detectado');
      
      // Si había sesión y ahora no, recargar página
      if (lastKnownSession && !currentSession) {
        console.log('[SharedSession] Sesión cerrada en otra pestaña');
        window.location.reload();
      }
      
      // Si no había sesión y ahora sí, recargar página
      if (!lastKnownSession && currentSession) {
        console.log('[SharedSession] Sesión iniciada en otra pestaña');
        window.location.reload();
      }
      
      // Si cambió el usuario, recargar página
      if (lastKnownSession && currentSession && 
          lastKnownSession.id !== currentSession.id) {
        console.log('[SharedSession] Usuario diferente detectado');
        window.location.reload();
      }

      lastKnownSession = currentSession;

      // Actualizar el widget si está disponible
      if (typeof updateUserWidget === 'function') {
        updateUserWidget();
      }
    }
  }

  // Función para inicializar el sistema de sesión compartida
  function initSharedSession() {
    // Guardar la sesión actual como referencia
    lastKnownSession = getCurrentSession();

    // Actualizar última actividad
    updateLastActivity();

    // Escuchar eventos de storage (cambios en otras pestañas)
    window.addEventListener('storage', (event) => {
      if (event.key === SESSION_CONFIG.STORAGE_KEY) {
        console.log('[SharedSession] Cambio de sesión desde otra pestaña');
        checkSessionChanges();
      }
    });

    // Verificar periódicamente cambios en la sesión
    if (!checkInterval) {
      checkInterval = setInterval(checkSessionChanges, SESSION_CONFIG.CHECK_INTERVAL);
    }

    // Actualizar última actividad en cada interacción del usuario
    const activityEvents = ['mousedown', 'keydown', 'scroll', 'touchstart'];
    activityEvents.forEach(event => {
      document.addEventListener(event, updateLastActivity, { passive: true });
    });

    console.log('[SharedSession] Sistema de sesión compartida iniciado');
  }

  // Función para destruir el sistema
  function destroySharedSession() {
    if (checkInterval) {
      clearInterval(checkInterval);
      checkInterval = null;
    }
  }

  // Función para forzar sincronización
  function forceSync() {
    checkSessionChanges();
  }

  // Función para extender la sesión actual
  function extendSession() {
    updateLastActivity();
    console.log('[SharedSession] Sesión extendida');
  }

  // API pública
  window.SharedSession = {
    init: initSharedSession,
    destroy: destroySharedSession,
    forceSync: forceSync,
    extendSession: extendSession,
    getCurrentSession: getCurrentSession,
    isExpired: isSessionExpired,
    config: SESSION_CONFIG
  };

  // Auto-inicialización cuando el DOM esté listo
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSharedSession);
  } else {
    initSharedSession();
  }

  // Limpiar al cerrar la página
  window.addEventListener('beforeunload', destroySharedSession);

  console.log('[SharedSession] Módulo cargado');

})();

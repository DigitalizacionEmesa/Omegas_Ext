// globalHeader.js - Sistema de Header Global Reutilizable
// =====================================================================
// Incluir este script en cualquier página para tener un header consistente
// Uso: <script src="/static/globalHeader.js" data-title="Mi Título"></script>
// O llamar: initGlobalHeader({ title: 'Mi Título' });

(function() {
  'use strict';

  // Configuración por defecto
  const HEADER_CONFIG = {
    logoSrc: '/static/images/Logo_EMESA.png',
    logoAlt: 'EMESA',
    homeUrl: '/templates/index.html',
    loginWidgetId: 'loginWidgetContainer'
  };

  // Función para obtener el título de la página
  function getPageTitle() {
    // 1. Buscar data-title en el script
    const scripts = document.querySelectorAll('script[src*="globalHeader.js"]');
    for (const script of scripts) {
      if (script.dataset.title) {
        return script.dataset.title;
      }
    }
    
    // 2. Usar el título del documento
    return document.title || 'SGA EMESA';
  }

  // Función para crear el HTML del header
  function createHeaderHTML(title) {
    return `
      <link rel="stylesheet" href="/static/loginModal.css">
      <div class="global-header">
        <div class="header-main-row">
          <div class="header-left-section">
            <a href="${HEADER_CONFIG.homeUrl}" class="logo-link" title="Ir a Inicio">
              <img class="EMESA-logo" src="${HEADER_CONFIG.logoSrc}" alt="${HEADER_CONFIG.logoAlt}">
            </a>
          </div>
          <span class="header-title">${title}</span>
          <div class="header-right-section">
            <div id="${HEADER_CONFIG.loginWidgetId}"></div>
          </div>
        </div>
      </div>
    `;
  }

  // Función para crear los estilos del header
  function createHeaderStyles() {
    if (document.getElementById('globalHeaderStyles')) return;

    const styles = document.createElement('style');
    styles.id = 'globalHeaderStyles';
    styles.textContent = `
      /* ========================================= */
      /* GLOBAL HEADER STYLES                      */
      /* ========================================= */
      
      .global-header {
        background: linear-gradient(135deg, #1976d2 0%, #0d47a1 100%);
        padding: 12px 0;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
        position: relative;
        z-index: 1000;
      }

      .global-header .header-main-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        padding: 0 20px;
        box-sizing: border-box;
      }

      .global-header .header-left-section {
        display: flex;
        align-items: center;
        gap: 15px;
      }

      .global-header .logo-link {
        display: flex;
        align-items: center;
        text-decoration: none;
        transition: transform 0.2s ease, opacity 0.2s ease;
      }

      .global-header .logo-link:hover {
        transform: scale(1.05);
        opacity: 0.9;
      }

      .global-header .EMESA-logo {
        height: 45px;
        width: auto;
        cursor: pointer;
      }

      .global-header .header-title {
        color: #fff;
        font-size: 1.5rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
        text-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
      }

      .global-header .header-right-section {
        display: flex;
        align-items: center;
        gap: 12px;
      }

      /* Contenedor para el widget de login */
      .global-header #${HEADER_CONFIG.loginWidgetId} {
        display: flex;
        align-items: center;
      }

      /* Responsive */
      @media (max-width: 768px) {
        .global-header .header-title {
          font-size: 1rem;
          letter-spacing: 0.5px;
        }

        .global-header .EMESA-logo {
          height: 35px;
        }

        .global-header .header-main-row {
          padding: 0 10px;
        }
      }

      @media (max-width: 480px) {
        .global-header .header-title {
          font-size: 0.85rem;
          max-width: 150px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
      }
    `;

    document.head.appendChild(styles);
  }

  // Función para cargar scripts externos
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      // Verificar si ya está cargado
      if (document.querySelector(`script[src="${src}"]`)) {
        resolve();
        return;
      }

      const script = document.createElement('script');
      script.src = src;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  // Función para inicializar el header
  async function initGlobalHeader(options = {}) {
    const title = options.title || getPageTitle();

    // Crear estilos
    createHeaderStyles();

    // Buscar o crear contenedor del header
    let headerContainer = document.querySelector('.header');
    
    if (headerContainer) {
      // Reemplazar header existente
      headerContainer.outerHTML = createHeaderHTML(title);
    } else {
      // Insertar al principio del body
      const headerDiv = document.createElement('div');
      headerDiv.innerHTML = createHeaderHTML(title);
      document.body.insertBefore(headerDiv.firstElementChild, document.body.firstChild);
    }

    // Cargar scripts necesarios
    try {
      await loadScript('/static/loginModal.js');
      await loadScript('/static/sharedSession.js');

      // Inicializar el widget de login manualmente después de cargar el script
      if (typeof LoginModal !== 'undefined' && LoginModal.init) {
        LoginModal.init();
      }

      // Inicializar sesión compartida
      if (typeof SharedSession !== 'undefined' && SharedSession.init) {
        SharedSession.init();
      }
    } catch (error) {
      console.error('[GlobalHeader] Error cargando scripts:', error);
    }

    console.log('[GlobalHeader] Header inicializado correctamente');
  }

  // Función para actualizar el título del header
  function updateHeaderTitle(newTitle) {
    const titleElement = document.querySelector('.global-header .header-title');
    if (titleElement) {
      titleElement.textContent = newTitle;
    }
  }

  // API pública
  window.GlobalHeader = {
    init: initGlobalHeader,
    updateTitle: updateHeaderTitle,
    config: HEADER_CONFIG
  };

  // Auto-inicialización cuando el DOM esté listo
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      // Solo auto-inicializar si el script tiene el atributo data-auto-init
      const script = document.querySelector('script[src*="globalHeader.js"]');
      if (script && script.dataset.autoInit !== 'false') {
        initGlobalHeader();
      }
    });
  } else {
    // DOM ya está listo
    const script = document.querySelector('script[src*="globalHeader.js"]');
    if (script && script.dataset.autoInit !== 'false') {
      initGlobalHeader();
    }
  }

})();

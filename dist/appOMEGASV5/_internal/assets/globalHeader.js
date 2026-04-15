// globalHeader.js - Sistema de Header Global Reutilizable
// =====================================================================
// Uso: <script src="/assets/globalHeader.js" data-title="Mi Título" data-title-key="clave_traduccion"></script>

(function() {
  'use strict';

  // Configuración por defecto
  const HEADER_CONFIG = {
    logoSrc: '/IMAGENES/Logo_EMESA.png',
    logoAlt: 'EMESA',
    homeUrl: '/Pantallas/Pantallas_Generales/Pantalla_INICIO.html',
    loginWidgetId: 'loginWidgetContainer',
    showLanguageSelector: true
  };

  // Función para obtener el título de la página y su clave de traducción
  function getPageTitle() {
    const scripts = document.querySelectorAll('script[src*="globalHeader.js"]');
    for (const script of scripts) {
      if (script.dataset.title) {
        return {
          text: script.dataset.title,
          key: script.dataset.titleKey || null
        };
      }
    }
    return { text: document.title || 'SGA EMESA', key: null };
  }

  // Función para crear el HTML del header CON selector de idioma
  function createHeaderHTML(titleData) {
    const languageSelector = HEADER_CONFIG.showLanguageSelector ? `
      <select id="header-language-selector" onchange="if(typeof changeLanguage==='function')changeLanguage(this.value)" 
              style="padding: 6px 12px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.3); 
                     cursor: pointer; background: rgba(255,255,255,0.2); color: white; font-weight: 500;
                     margin-left: 12px;">
        <option value="es" style="color: #333;">ES</option>
        <option value="en" style="color: #333;">EN</option>
        <option value="cz" style="color: #333;">CZ</option>
      </select>
    ` : '';

    // Si hay clave de traducción, usar data-translate-key
    const titleAttr = titleData.key ? `data-translate-key="${titleData.key}"` : '';
    const titleText = titleData.text;

    return `
      <div class="global-header">
        <div class="header-main-row">
          <div class="header-left-section">
            <a href="${HEADER_CONFIG.homeUrl}" class="logo-link" title="Ir a Inicio">
              <img class="emesa-logo" src="${HEADER_CONFIG.logoSrc}" alt="${HEADER_CONFIG.logoAlt}">
            </a>
          </div>
          <span class="header-title" ${titleAttr}>${titleText}</span>
          <div class="header-right-section">
            <div id="${HEADER_CONFIG.loginWidgetId}"></div>
            ${languageSelector}
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

      .global-header .emesa-logo {
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

      .global-header #loginWidgetContainer {
        display: flex;
        align-items: center;
      }

      #header-language-selector:focus {
        outline: 2px solid rgba(255,255,255,0.5);
      }

      @media (max-width: 768px) {
        .global-header .header-title {
          font-size: 1rem;
          letter-spacing: 0.5px;
        }

        .global-header .emesa-logo {
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
      if (document.querySelector(`script[src="${src}"]`)) {
        resolve();
        return;
      }

      const script = document.createElement('script');
      script.src = src;
      script.onload = resolve;
      script.onerror = () => {
        console.warn('[GlobalHeader] No se pudo cargar: ' + src);
        resolve();
      };
      document.head.appendChild(script);
    });
  }

  // Función para sincronizar el selector de idioma con localStorage
  function syncLanguageSelector() {
    const savedLang = localStorage.getItem('language') || 'es';
    const selector = document.getElementById('header-language-selector');
    if (selector) {
      selector.value = savedLang;
    }
    // También sincronizar el otro selector si existe
    const oldSelector = document.getElementById('language-selector');
    if (oldSelector) {
      oldSelector.value = savedLang;
    }
  }

  // Función principal para inicializar el header
  async function initGlobalHeader(options = {}) {
    console.log('[GlobalHeader] Iniciando...');
    
    // Obtener título (puede ser objeto con text y key, o string simple)
    let titleData = options.title || getPageTitle();
    if (typeof titleData === 'string') {
      titleData = { text: titleData, key: options.titleKey || null };
    }

    // Crear estilos primero
    createHeaderStyles();

    // Crear el HTML del header
    const headerHTML = createHeaderHTML(titleData);

    // Insertar al principio del body
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = headerHTML;
    const headerElement = tempDiv.firstElementChild;
    
    // Insertar como primer hijo del body
    if (document.body.firstChild) {
      document.body.insertBefore(headerElement, document.body.firstChild);
    } else {
      document.body.appendChild(headerElement);
    }

    console.log('[GlobalHeader] Header insertado en el DOM');

    // Cargar CSS del login modal
    if (!document.querySelector('link[href*="loginModal.css"]')) {
      const linkCSS = document.createElement('link');
      linkCSS.rel = 'stylesheet';
      linkCSS.href = '/assets/loginModal.css';
      document.head.appendChild(linkCSS);
    }

    // Cargar scripts necesarios
    try {
      await loadScript('/assets/loginModal.js');
      await loadScript('/assets/sharedSession.js');

      // Esperar un momento para que el DOM se actualice
      await new Promise(resolve => setTimeout(resolve, 100));

      // Inicializar el widget de login
      if (typeof LoginModal !== 'undefined' && LoginModal.init) {
        LoginModal.init();
        console.log('[GlobalHeader] LoginModal inicializado');
      }

      // Inicializar sesión compartida
      if (typeof SharedSession !== 'undefined' && SharedSession.init) {
        SharedSession.init();
        console.log('[GlobalHeader] SharedSession inicializado');
      }
    } catch (error) {
      console.error('[GlobalHeader] Error cargando scripts:', error);
    }

    // Sincronizar selector de idioma después de que todo esté listo
    syncLanguageSelector();

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
    syncLanguage: syncLanguageSelector,
    config: HEADER_CONFIG
  };

  // EJECUTAR INMEDIATAMENTE - El script está al final del body, el DOM ya está listo
  initGlobalHeader();

})();



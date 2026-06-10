# Guia Reutilizable De Login Modal Y Header Global

## Objetivo

Este documento describe la logica completa del sistema de autenticacion frontend usado en este proyecto para poder reutilizarlo en otro proyecto con el menor acoplamiento posible.

El sistema se apoya en tres piezas principales:

1. `assets/loginModal.js`
2. `assets/sharedSession.js`
3. `assets/globalHeader.js`

Y en un contrato backend minimo:

1. `POST /api/login`
2. Una tabla de usuarios con identificador, nombre, password y nivel de permisos


## Resumen De Arquitectura

### 1. `loginModal.js`

Se encarga de:

1. Detectar si existe una sesion en `localStorage`.
2. Mostrar un modal de login si no hay usuario autenticado.
3. Enviar credenciales al backend en `POST /api/login`.
4. Guardar la respuesta del usuario en `localStorage` bajo la clave `usuarioSGA`.
5. Renderizar el widget visual del usuario autenticado dentro del header.
6. Exponer una API global en `window.LoginModal`.

### 2. `sharedSession.js`

Se encarga de:

1. Sincronizar la sesion entre pestañas o ventanas.
2. Detectar login y logout realizados en otra pestaña.
3. Forzar recarga de la pagina cuando cambia el usuario o expira la sesion.
4. Mantener un timestamp de actividad para timeout de sesion.

### 3. `globalHeader.js`

Se encarga de:

1. Insertar un header global al principio del `body`.
2. Crear un contenedor para el widget de usuario: `loginWidgetContainer`.
3. Cargar dinamicamente `loginModal.js` y `sharedSession.js`.
4. Inicializar ambos modulos.
5. Mantener integrado el selector de idioma y el area del usuario.


## Flujo Funcional Completo

### Flujo De Carga De Pagina

1. La pagina incluye `globalHeader.js`.
2. `globalHeader.js` se autoejecuta e inserta el header en el DOM.
3. `globalHeader.js` carga `loginModal.js` y `sharedSession.js`.
4. `LoginModal.init()` crea estilos del widget, monta el widget y verifica si hay sesion.
5. Si no existe `localStorage.usuarioSGA`, se abre el modal de login.
6. Si existe, se muestra la tarjeta del usuario en el header.

### Flujo De Login

1. El usuario introduce `usuario` y `password` en el modal.
2. `loginModal.js` envia `POST /api/login` con este payload:

```json
{
  "usuario": "1234",
  "password": "clave"
}
```

3. Si el backend responde con exito, el frontend guarda el objeto completo en `localStorage.usuarioSGA`.
4. El modal se cierra.
5. Se emite el evento global `userLoggedIn`.
6. El widget del usuario se actualiza.

### Flujo De Logout

1. El usuario pulsa el boton `Salir` del widget.
2. Se elimina `localStorage.usuarioSGA`.
3. Se detiene la verificacion automatica local.
4. Se recarga la pagina.
5. `sharedSession.js` propaga el cambio al resto de pestañas por evento `storage`.

### Flujo De Sesion Compartida

1. `sharedSession.js` escucha el evento `storage` del navegador.
2. Si cambia `usuarioSGA` en otra pestaña, compara la sesion actual con la previa.
3. Si detecta login, logout o cambio de usuario, recarga la pagina.
4. Adicionalmente guarda `lastActivityTime` para controlar expiracion.


## Contrato Del Backend

El frontend actual espera que `POST /api/login` responda con esta forma:

### Respuesta Correcta

```json
{
  "success": true,
  "id": 1,
  "num_operario": "1234",
  "nombre": "Supervisor",
  "nivel": 10,
  "nivel_permisos": 10,
  "roles": "ADMIN"
}
```

### Respuesta De Error Controlado

```json
{
  "success": false,
  "message": "Contraseña incorrecta"
}
```

### Campos Minimos Recomendados

Para reutilizar el sistema sin tocar demasiado frontend, conviene mantener:

1. `success`
2. `id`
3. `num_operario`
4. `nombre`
5. `nivel`
6. `nivel_permisos`
7. `roles`

`loginModal.js` y las pantallas usan sobre todo estos:

1. `id`
2. `nombre`
3. `nivel`


## Logica Del Endpoint Actual

El endpoint actual esta en `api/appOMEGAS.py` y hace lo siguiente:

1. Lee `usuario` y `password` desde JSON.
2. Busca usuario en `OB.Usuarios_CZ_hash` usando `buscar_usuario_cz(...)`.
3. Recupera:
   1. `Id_Usuario`
   2. `Num_Operario`
   3. `Nombre`
   4. `Contrasena`
   5. `Nivel_Permisos`
   6. `Roles`
4. Valida el password con `verificar_password_usuario(...)`.
5. Devuelve un JSON de sesion si la validacion es correcta.

El endpoint soporta:

1. Password legacy en texto plano.
2. Password hash si ya fue migrado.


## Esquema De Sesion En Frontend

La sesion se guarda en:

1. `localStorage['usuarioSGA']`
2. `localStorage['lastActivityTime']`

### `usuarioSGA`

Contiene el JSON completo devuelto por `POST /api/login`.

Ejemplo:

```json
{
  "success": true,
  "id": 12,
  "num_operario": "4521",
  "nombre": "Supervisor",
  "nivel": 10,
  "nivel_permisos": 10,
  "roles": "ADMIN"
}
```

### `lastActivityTime`

Contiene un timestamp en milisegundos que se actualiza con actividad del usuario.


## API Global Del Frontend

### `window.LoginModal`

Metodos publicos disponibles:

1. `show()`
2. `hide()`
3. `checkUser()`
4. `requireUser(callback, errorMessage)`
5. `getCurrentUser()`
6. `logout()`
7. `init()`
8. `createUserWidget()`
9. `updateUserWidget()`
10. `startAutoCheck()`
11. `stopAutoCheck()`

Propiedades utiles:

1. `LoginModal.isOpen`
2. `LoginModal.hasUser`
3. `LoginModal.config`

### `window.SharedSession`

Metodos publicos:

1. `init()`
2. `destroy()`
3. `forceSync()`
4. `extendSession()`
5. `getCurrentSession()`
6. `isExpired()`

### `window.GlobalHeader`

Metodos publicos:

1. `init(options)`
2. `updateTitle(newTitle)`
3. `syncLanguage()`
4. `config`


## Eventos Relevantes

### `userLoggedIn`

Se emite desde `loginModal.js` cuando el login es correcto.

Uso esperado:

```javascript
window.addEventListener('userLoggedIn', (event) => {
  console.log('Usuario autenticado', event.detail);
});
```

Este evento es importante porque muchas pantallas no recargan tras login; simplemente reaccionan al evento.


## Comportamiento Del Header Relacionado Con Login

El header no autentica por si mismo. Su papel es estructural.

Hace estas funciones:

1. Inserta visualmente el area de usuario.
2. Garantiza que exista `#loginWidgetContainer`.
3. Carga los dos modulos relacionados con sesion.
4. Inicializa login y sesion compartida.

El orden real de carga es:

1. Crear estilos del header.
2. Insertar el HTML del header.
3. Cargar `loginModal.css`.
4. Cargar `loginModal.js`.
5. Cargar `sharedSession.js`.
6. Ejecutar `LoginModal.init()`.
7. Ejecutar `SharedSession.init()`.


## Dependencias Minimas Para Reutilizarlo En Otro Proyecto

### Frontend

Necesitas copiar:

1. `assets/loginModal.js`
2. `assets/loginModal.css`
3. `assets/sharedSession.js`
4. `assets/globalHeader.js`

Opcionalmente adaptar:

1. Logo
2. Ruta de inicio
3. Textos
4. Selector de idioma

### Backend

Necesitas implementar:

1. `POST /api/login`
2. Fuente de usuarios
3. Verificacion de contraseña

### DOM

No necesitas crear manualmente el contenedor del widget si usas `globalHeader.js`, porque el propio header inserta `loginWidgetContainer`.


## Pasos De Integracion En Otro Proyecto

### Opcion 1. Reutilizar Todo El Header

1. Copiar los cuatro archivos del bloque frontend.
2. Ajustar en `globalHeader.js`:
   1. `logoSrc`
   2. `logoAlt`
   3. `homeUrl`
3. Incluir el script:

```html
<script src="/assets/globalHeader.js" data-title="Mi Pantalla"></script>
```

4. Implementar `POST /api/login` con el mismo contrato JSON.

### Opcion 2. Reutilizar Solo El Login Sin Header

1. Copiar `loginModal.js`, `loginModal.css` y `sharedSession.js`.
2. Crear manualmente un contenedor con id `loginWidgetContainer` si quieres el widget visual.
3. Ejecutar:

```javascript
LoginModal.init();
SharedSession.init();
```


## Puntos De Configuracion Importantes

### En `loginModal.js`

`LOGIN_MODAL_CONFIG`:

1. `AUTO_CHECK_INTERVAL`
2. `REDIRECT_DELAY`
3. `STYLES_LOADED`

Nota importante: en el codigo actual ya no se usa el chequeo periodico cada 30 segundos para forzar el login, porque ese comportamiento provocaba cierres de sesion molestos. La verificacion fuerte de sincronizacion queda en `sharedSession.js`.

### En `sharedSession.js`

`SESSION_CONFIG`:

1. `STORAGE_KEY = 'usuarioSGA'`
2. `CHECK_INTERVAL = 1000`
3. `SESSION_TIMEOUT = 8 horas`
4. `LAST_ACTIVITY_KEY = 'lastActivityTime'`

### En `globalHeader.js`

`HEADER_CONFIG`:

1. `logoSrc`
2. `logoAlt`
3. `homeUrl`
4. `loginWidgetId`
5. `showLanguageSelector`


## Comportamiento De Seguridad Actual

### Lo Que Si Hace

1. No deja continuar sin sesion en pantallas que inicializan `LoginModal`.
2. Centraliza el usuario actual en `localStorage`.
3. Sincroniza login y logout entre pestañas.
4. Maneja expiracion por inactividad en frontend.
5. Permite reaccionar a `nivel` o `nivel_permisos` desde cada pagina.

### Lo Que No Hace

1. No usa JWT ni cookie de sesion HttpOnly.
2. No firma la sesion del lado frontend.
3. No protege por si solo los endpoints backend.
4. No sustituye autorizacion del lado servidor.

Para otro proyecto, esto es importante:

1. El modal de login es una capa UX.
2. La seguridad real debe seguir estando en backend.


## Recomendaciones Si Se Reutiliza En Otro Proyecto

### Recomendado Sin Cambiar Mucho

1. Mantener la clave `usuarioSGA`.
2. Mantener el evento `userLoggedIn`.
3. Mantener `loginWidgetContainer`.
4. Mantener el formato JSON del login.

### Recomendado Si Quieres Mejorarlo

1. Sustituir `localStorage` por token corto + refresh seguro.
2. Mover timeout de sesion al backend.
3. Añadir endpoint `/api/logout`.
4. Añadir endpoint `/api/session/me` para rehidratar la sesion.
5. Reducir logs de consola en produccion.


## Riesgos Y Acoplamientos Actuales

1. `globalHeader.js` asume que `changeLanguage()` puede existir globalmente.
2. `loginModal.js` asume que el backend devuelve `nombre`, `id` y `nivel`.
3. `sharedSession.js` recarga la pagina ante cualquier cambio relevante de sesion.
4. El widget de usuario depende del id `loginWidgetContainer`.

Si se va a portar a otro proyecto, estos son los puntos que normalmente hay que adaptar primero.


## Checklist De Portabilidad

### Backend

1. Crear `POST /api/login`.
2. Devolver el JSON con el contrato esperado.
3. Implementar verificacion de password.
4. Tener niveles o roles equivalentes.

### Frontend

1. Copiar `loginModal.js`.
2. Copiar `loginModal.css`.
3. Copiar `sharedSession.js`.
4. Copiar `globalHeader.js`.
5. Ajustar logo y rutas.
6. Verificar que exista `document.body` al autoarrancar.
7. Verificar que el proyecto permita `localStorage`.

### Integracion

1. Probar login correcto.
2. Probar password incorrecta.
3. Probar logout.
4. Probar apertura en dos pestañas.
5. Probar expiracion por inactividad.
6. Probar reaccion al evento `userLoggedIn`.


## Fragmento Minimo De Uso

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Mi Proyecto</title>
</head>
<body>
  <main>
    <h1>Contenido</h1>
  </main>

  <script src="/assets/globalHeader.js" data-title="Mi Proyecto"></script>
</body>
</html>
```


## Conclusion

El sistema esta pensado como una solucion ligera de autenticacion visual y sesion compartida para aplicaciones internas basadas en pantallas HTML servidas por Flask.

La pieza central no es el modal en si, sino la combinacion de estas tres responsabilidades:

1. `loginModal.js` autentica y renderiza usuario.
2. `sharedSession.js` sincroniza y expira sesion.
3. `globalHeader.js` integra todo de forma reutilizable.

Si en el proyecto destino mantienes el contrato JSON del login y la clave `usuarioSGA`, la portabilidad es directa.
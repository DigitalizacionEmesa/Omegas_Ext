Quiero que actúes como un desarrollador senior .NET especializado en análisis de incidencias de producción.

Contexto del proyecto:

- Esta aplicación (SEQ) recibe información de movimientos de stock desde Mapex.
- Ocasionalmente aparecen valores negativos de stock.
- El problema ya ocurrió anteriormente cuando se consumía material antes de que el operario reportara la producción en Mapex.
- Se implementaron correcciones y la frecuencia disminuyó, pero el problema sigue apareciendo.
- No sabemos exactamente cuándo ni cómo ocurre.
- Existe la sospecha de:
  - Condiciones de carrera (race conditions).
  - Procesamiento de mensajes fuera de orden.
  - Mensajes duplicados.
  - Mensajes perdidos.
  - Caídas temporales del servicio o servidor.
  - Errores en sincronización entre Mapex y SEQ.
  - Actualizaciones concurrentes sobre el stock.
  - Problemas en procedimientos almacenados o transacciones SQL.

Objetivo:

Haz una revisión completa del código y ayúdame a identificar todos los puntos donde podría producirse stock negativo.

Quiero que analices:

1. Todas las clases relacionadas con:
   - Stock
   - Inventario
   - Consumos
   - Producción
   - Mapex
   - Sincronización
   - Integraciones
   - Mensajería
   - Colas
   - Procesamiento en background

2. Todas las operaciones que:
   - Incrementen stock.
   - Decrementen stock.
   - Recalculen stock.
   - Sincronicen stock.
   - Corrijan stock.

3. Verifica:
   - Si existen transacciones SQL.
   - Si las transacciones son correctas.
   - Si hay lecturas sin bloqueo.
   - Si hay actualizaciones concurrentes.
   - Si existe riesgo de race condition.
   - Si existen operaciones async no controladas.
   - Si hay múltiples procesos modificando el mismo stock.

4. Revisa los Stored Procedures involucrados y busca:
   - UPDATE de stock.
   - INSERT de movimientos.
   - MERGE.
   - Triggers.
   - Recalculos automáticos.

5. Indica:
   - Archivo.
   - Método.
   - Riesgo encontrado.
   - Explicación técnica.
   - Nivel de criticidad (Alta, Media, Baja).

6. Diseña un sistema de auditoría para detectar el problema cuando vuelva a ocurrir:
   - Registrar material.
   - Fecha/hora.
   - Stock anterior.
   - Movimiento recibido.
   - Stock posterior.
   - Origen del movimiento.
   - Id de mensaje.
   - Usuario o proceso.
   - Stack trace si procede.

7. Busca cualquier lugar donde el stock pueda quedar:
   - Menor que cero.
   - Desincronizado respecto a Mapex.
   - Inconsistente tras un reinicio del servicio.

No hagas suposiciones. Primero crea un mapa completo del flujo de stock desde que llega un movimiento de Mapex hasta que el valor queda almacenado en base de datos.

Empieza identificando los archivos y componentes clave involucrados en la gestión de stock.
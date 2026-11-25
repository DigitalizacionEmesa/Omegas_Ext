Para encontrar la causa raíz con total precisión, la estrategia de implementar
un Watchdog (perro guardián) y un sistema de logs de diagnóstico es el enfoque
más profesional y efectivo [11.1]. Te permitirá registrar una especie de "caja
negra" cada vez que ocurra una anomalía.

A continuación, te presento una propuesta de diseño para implementar este
sistema de monitorización tanto en la Base de Datos (SQL) como en tu Aplicación
(Python).

Componente 1: La "Caja Negra" en Base de Datos (SQL)

La forma más rápida de saber por qué un stock baja de cero es registrar una
instantánea (un snapshot) de la situación en el momento exacto en que ocurre el
descuadre.

1. Crear una tabla de logs de diagnóstico (OB.Stock_Diagnostics_Log)

Esta tabla guardará el historial detallado de qué producto falló, qué valores
tenían sus tablas y qué proceso estaba corriendo.

CREATE TABLE OB.Stock_Diagnostics_Log (
    LogID               INT IDENTITY(1,1) PRIMARY KEY,
    LogTimestamp        DATETIME2 DEFAULT GETDATE(),
    Cod_producto        VARCHAR(50) NOT NULL,
    TipoProducto        VARCHAR(10), -- 'OMEGA' o 'BEAM'
    StockCalculado      INT NOT NULL,
    
    -- Diagnóstico del desajuste
    TotalProduccion     INT,
    TotalConsumos       INT,
    
    -- Trazabilidad del origen
    UltimaFechaProd     DATETIME2,
    UltimaFechaConsumo  DATETIME2,
    LastSyncDateMark    DATETIME2, -- Marca de agua en Last_Sync
    
    -- Contexto de ejecución
    ProcedimientoOrigen VARCHAR(100), -- SP que causó el cambio (si aplica)
    ContextoSQL         NVARCHAR(1000), -- Datos del sistema SQL (SPID, Host, etc.)
    Notas               NVARCHAR(MAX)
);

2. Crear un Trigger de Alerta Temprana en SQL

Para capturar el momento justo en que se inserta un consumo o una lectura que
provoca un stock negativo, podemos colocar un Trigger en las tablas de salidas
(Omegas_Lecturas y Beams_Consumos).

Ejemplo de Trigger para Beams_Consumos:

CREATE TRIGGER OB.TR_Watchdog_Beams_Consumos
ON OB.Beams_Consumos
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;

    -- Verificar si los productos recién insertados provocan stock negativo
    IF EXISTS (
        SELECT 1 
        FROM OB.Stock_Beams_New sb
        INNER JOIN inserted i ON sb.Cod_producto = i.Cod_producto
        WHERE sb.StockActual < 0
    )
    BEGIN
        -- Insertar el diagnóstico de los productos que quedaron en negativo
        INSERT INTO OB.Stock_Diagnostics_Log (
            Cod_producto, TipoProducto, StockCalculado, 
            TotalProduccion, TotalConsumos, 
            UltimaFechaProd, UltimaFechaConsumo, LastSyncDateMark,
            ProcedimientoOrigen, ContextoSQL, Notas
        )
        SELECT 
            sb.Cod_producto,
            'BEAM',
            sb.StockActual,
            sb.Entradas,
            sb.Salidas,
            (SELECT MAX(Fecha_fin) FROM OB.Beams_Produccion WHERE Cod_producto = sb.Cod_producto),
            (SELECT MAX(Fecha_fin) FROM OB.Beams_Consumos WHERE Cod_producto = sb.Cod_producto),
            (SELECT Last_Sync_Date FROM OB.Last_Sync_Beams WHERE Cod_producto = sb.Cod_producto AND Fuente = 'CONS'),
            'Trigger TR_Watchdog_Beams_Consumos',
            CONCAT('Host: ', HOST_NAME(), ' | App: ', APP_NAME(), ' | SPID: ', @@SPID),
            'Se detectó stock negativo tras una inserción en Beams_Consumos.'
        FROM OB.Stock_Beams_New sb
        INNER JOIN inserted i ON sb.Cod_producto = i.Cod_producto
        WHERE sb.StockActual < 0;
    END
END;

Componente 2: El Watchdog en la Aplicación (Python)

Podemos añadir un hilo dedicando exclusivamente a vigilar la base de datos de
manera silenciosa (un Watchdog Thread). Este hilo no interfiere con la
producción y se encarga de analizar desviaciones [10.3].

1. Configurar el Logger en api/appOMEGAS.py

Asegúrate de que Python escriba en un archivo de log rotativo dedicado a stock
para no mezclarlo con otros eventos del servidor web.

import logging
from logging.handlers import RotatingFileHandler

# Configurar un logger específico para el Stock Watchdog
stock_logger = logging.getLogger("StockWatchdog")
stock_logger.setLevel(logging.WARNING)

# Archivo de logs rotativo (10MB por archivo, guarda hasta 5 históricos)
handler = RotatingFileHandler("logs/stock_watchdog.log", maxBytes=10*1024*1024, backupCount=5)
formatter = logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s')
handler.setFormatter(formatter)
stock_logger.addHandler(handler)

2. Definir el bucle del Watchdog

Este bucle se ejecutará en background. Si detecta un stock negativo, no solo lo
registrará, sino que extraerá los datos necesarios para que sepas qué pasó de
inmediato [11.1].

import time
import threading

def stock_watchdog_loop():
    stock_logger.info("Iniciando Watchdog de Stock...")
    while True:
        try:
            with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
                cursor = conn_main.cursor()
                
                # 1. Comprobar Beams negativos
                cursor.execute("""
                    SELECT Cod_producto, StockActual, Entradas, Salidas 
                    FROM OB.Stock_Beams_New 
                    WHERE StockActual < 0
                """)
                beams_negativos = cursor.fetchall()
                for row in beams_negativos:
                    # Extraer el contexto de este Beam específico
                    cursor.execute("""
                        SELECT TOP 3 WorkGroup, Fecha_inicio, Fecha_fin, Unidades_OK 
                        FROM OB.Beams_Produccion 
                        WHERE Cod_producto = ? ORDER BY Fecha_fin DESC
                    """, (row.Cod_producto,))
                    ultimos_prods = cursor.fetchall()
                    
                    stock_logger.error(
                        f"ANOMALÍA DETECTADA: Beam '{row.Cod_producto}' tiene stock {row.StockActual} "
                        f"(Entradas: {row.Entradas} | Salidas: {row.Salidas}).\n"
                        f"Últimas producciones registradas: {ultimos_prods}"
                    )
                
                # 2. Comprobar Omegas negativos
                cursor.execute("""
                    SELECT Cod_producto, StockActual 
                    FROM OB.Stock_Omegas_New 
                    WHERE StockActual < 0
                """)
                omegas_negativos = cursor.fetchall()
                for row in omegas_negativos:
                    # Investigar si el problema es que la lectura ocurrió antes que la producción
                    cursor.execute("""
                        SELECT TOP 1 fecha FROM OB.Omegas_Lecturas 
                        WHERE producto = ? ORDER BY fecha DESC
                    """, (row.Cod_producto,))
                    u_lec = cursor.fetchone()
                    
                    cursor.execute("""
                        SELECT TOP 1 Fecha_fin FROM OB.Omegas_Produccion 
                        WHERE Cod_producto = ? ORDER BY Fecha_fin DESC
                    """, (row.Cod_producto,))
                    u_prod = cursor.fetchone()
                    
                    stock_logger.error(
                        f"ANOMALÍA DETECTADA: Omega '{row.Cod_producto}' tiene stock {row.StockActual}.\n"
                        f"Última lectura: {u_lec[0] if u_lec else 'NINGUNA'} | "
                        f"Última producción: {u_prod[0] if u_prod else 'NINGUNA'}"
                    )
                    
        except Exception as e:
            stock_logger.exception(f"Error en la ejecución del bucle Watchdog: {str(e)}")
            
        # Ejecutar inspección cada 30 segundos (configurable)
        time.sleep(30)

3. Lanzar el Watchdog al arrancar la App

En la sección donde inicializas tus hilos (cerca de la línea 5960 en
appOMEGAS.py), añade el nuevo hilo [10.1, 10.3]:

# Hilo del Watchdog de diagnóstico de stock
threading.Thread(target=stock_watchdog_loop, name="StockWatchdogSync", daemon=True).start()

¿Cómo te ayudará esto a resolver el problema de raíz?

Una vez que dejes corriendo este sistema, cuando ocurra un stock negativo podrás
abrir el archivo logs/stock_watchdog.log o revisar la tabla
OB.Stock_Diagnostics_Log en base de datos. Esto te permitirá responder con
precisión matemática a las siguientes preguntas:

1.  ¿El operador escaneó el material antes de que MAPEX registrara la
    producción?
      - Lo sabrás porque: El log mostrará una "Última lectura" con fecha (por
        ejemplo) 10:15:30 y la "Última producción" tendrá fecha 10:18:00.
        (Confirmado: Desfase temporal en planta).
2.  ¿Se duplicó la producción tras un reinicio debido al bug de la condición OR?
      - Lo sabrás porque: Verás en el historial de producción de la tabla de
        diagnóstico dos registros idénticos de unidades producidas con la misma
        fecha de inicio, pero insertados en momentos diferentes.
3.  ¿La asignación de Python está consumiendo de más debido a la falta de Locks?
      - Lo sabrás porque: El trigger en SQL capturará que el stock bajó de cero
        exactamente cuando se procesó una actualización desde la aplicación web
        (App: Python/pyodbc).

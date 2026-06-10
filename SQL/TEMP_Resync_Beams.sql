USE DataLakeSCCZ;
GO

PRINT '========================================';
PRINT '🔄 INICIANDO RESINCRONIZACIÓN FORZADA';
PRINT '========================================';
GO

-- 1️⃣ Resetear Last_Sync_Date a 7 días atrás
UPDATE OB.Last_Sync_Beams
SET Last_Sync_Date = DATEADD(DAY, -7, GETDATE())
WHERE Cod_producto IN (
    SELECT BeamCode 
    FROM OB.Beams 
    WHERE IsActive = 1
);

PRINT '✅ Paso 1: Last_Sync_Date reseteada a 7 días atrás';
PRINT '';
GO

-- 2️⃣ Ejecutar sincronización (5 veces para asegurar cobertura completa)
PRINT '⏳ Paso 2: Ejecutando sincronización (puede tardar 20-30 segundos)...';
GO

EXEC OB.sp_Sync_Beams_RawData;
GO
EXEC OB.sp_Sync_Beams_RawData;
GO
EXEC OB.sp_Sync_Beams_RawData;
GO
EXEC OB.sp_Sync_Beams_RawData;
GO
EXEC OB.sp_Sync_Beams_RawData;
GO

PRINT '✅ Paso 2: Sincronización completada';
PRINT '';
GO

-- 3️⃣ VERIFICACIÓN: Last_Sync_Date actualizada
PRINT '========================================';
PRINT '📊 VERIFICACIÓN 1: Estado de sincronización';
PRINT '========================================';
GO

SELECT TOP 10
    Cod_producto AS 'Beam',
    Fuente AS 'Tipo',
    FORMAT(Last_Sync_Date, 'yyyy-MM-dd HH:mm:ss') AS 'Última Sincronización',
    DATEDIFF(MINUTE, Last_Sync_Date, GETDATE()) AS 'Minutos de retraso'
FROM OB.Last_Sync_Beams
WHERE DATEDIFF(MINUTE, Last_Sync_Date, GETDATE()) > 20
ORDER BY DATEDIFF(MINUTE, Last_Sync_Date, GETDATE()) DESC;

-- Si no devuelve filas, está todo bien
IF @@ROWCOUNT = 0
BEGIN
    PRINT '✅ CORRECTO: Todas las sincronizaciones están actualizadas (menos de 20 minutos)';
END
ELSE
BEGIN
    PRINT '⚠️ ADVERTENCIA: Hay beams con retraso en sincronización';
END
PRINT '';
GO

-- 4️⃣ VERIFICACIÓN: Stock corregido
PRINT '========================================';
PRINT '📊 VERIFICACIÓN 2: Stock de beams problemáticos';
PRINT '========================================';
GO

SELECT 
    Cod_producto AS 'Beam',
    StockActual AS 'Stock',
    Entradas AS 'Producciones',
    Salidas AS 'Consumos'
FROM OB.Stock_Beams_New
WHERE Cod_producto IN (
    'S01SAA970778',
    'S01SAA973104', 
    'S01SAA970795',
    'S01SAA973108',
    'S01SAA973105',
    'S01SAB973106'
)
ORDER BY StockActual;
GO

-- 5️⃣ Resumen final
PRINT '';
PRINT '========================================';
PRINT '📋 RESUMEN';
PRINT '========================================';
GO

DECLARE @NegativeCount INT;
SELECT @NegativeCount = COUNT(*) FROM OB.Stock_Beams_New WHERE StockActual < 0;

IF @NegativeCount = 0
BEGIN
    PRINT '✅ ¡PERFECTO! No hay beams con stock negativo';
    PRINT '✅ La resincronización fue exitosa';
END
ELSE
BEGIN
    PRINT '⚠️ ATENCIÓN: Aún hay ' + CAST(@NegativeCount AS VARCHAR) + ' beams con stock negativo';
    PRINT '📌 Esto puede deberse a:';
    PRINT '   - Datos históricos perdidos en MAPEX (más de 7 días)';
    PRINT '   - Mapping incorrecto en tabla OB.Omegas';
    PRINT '   - Consumos sin producciones asociadas';
END
GO

PRINT '';
PRINT '========================================';
PRINT '✅ Script completado exitosamente';
PRINT '========================================';

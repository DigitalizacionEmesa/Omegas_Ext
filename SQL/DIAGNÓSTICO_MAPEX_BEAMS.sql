-- ========================================
-- DIAGNÓSTICO: ¿MAPEX TRAE DATOS O NO?
-- ========================================
-- Este script verifica si MAPEX tiene datos disponibles
-- y compara con lo que debería sincronizarse

USE DataLakeSCCZ;
GO

PRINT '========================================';
PRINT 'DIAGNÓSTICO 1: ÚLTIMAS SINCRONIZACIONES';
PRINT '========================================';
GO

-- Mostrar cuándo fue la última sincronización
SELECT TOP 20
    Cod_producto,
    Fuente,
    Last_Sync_Date,
    DATEDIFF(DAY, Last_Sync_Date, GETDATE()) AS 'Días de retraso',
    DATEDIFF(HOUR, Last_Sync_Date, GETDATE()) AS 'Horas de retraso'
FROM OB.Last_Sync_Beams
ORDER BY Last_Sync_Date ASC;

PRINT '';
PRINT '========================================';
PRINT 'DIAGNÓSTICO 2: DATOS EN MAPEX (Beams)';
PRINT '========================================';
PRINT '';
GO

-- Intentar acceder a MAPEX directamente
-- Buscar producciones de Beams desde el 28-MAY
BEGIN TRY
    PRINT '🔍 Buscando datos en MAPEX.dbo.F_HIS_CT...';
    PRINT '  • Rango: 28-MAY-2026 a HOY';
    PRINT '  • WorkGroup1: 50 Assembly';
    PRINT '';

    SELECT TOP 50
        f.Cod_producto,
        f.WorkGroup1 AS WorkGroup,
        f.Fecha_inicio,
        f.Fecha_fin,
        f.Unidades_OK,
        DATEDIFF(DAY, f.Fecha_fin, GETDATE()) AS 'Días desde este registro'
    FROM mapexbp.dbo.F_HIS_CT(
        'WORKCENTER', 'DETAIL', 'PRODUCT',
        '2026-05-28', GETDATE(), 2
    ) f
    WHERE f.WorkGroup1 = '50 Assembly'
      AND f.Unidades_OK > 0
    ORDER BY f.Fecha_fin DESC;

    IF @@ROWCOUNT = 0
    BEGIN
        PRINT '❌ NO SE ENCONTRARON DATOS EN MAPEX';
        PRINT '   Posibles razones:';
        PRINT '   1. MAPEX no tiene datos desde 28-MAY';
        PRINT '   2. La función F_HIS_CT está vacía';
        PRINT '   3. Los datos fueron borrados de MAPEX';
    END
    ELSE
    BEGIN
        PRINT '✅ DATOS ENCONTRADOS EN MAPEX';
    END

END TRY
BEGIN CATCH
    PRINT '❌ ERROR AL CONECTAR A MAPEX:';
    PRINT '   Error: ' + ERROR_MESSAGE();
    PRINT '   Número: ' + CAST(ERROR_NUMBER() AS VARCHAR);
END CATCH;

PRINT '';
PRINT '========================================';
PRINT 'DIAGNÓSTICO 3: DATOS LOCALES (BD)';
PRINT '========================================';
PRINT '';
GO

-- Verificar qué hay en la BD local
PRINT 'Producciones en OB.Beams_Produccion:';
SELECT TOP 20
    Cod_producto,
    WorkGroup,
    Fecha_inicio,
    Fecha_fin,
    Unidades_OK,
    SyncDate,
    DATEDIFF(DAY, Fecha_fin, GETDATE()) AS 'Días desde este registro'
FROM OB.Beams_Produccion
ORDER BY Fecha_fin DESC;

PRINT '';
PRINT 'Consumos en OB.Beams_Consumos:';
SELECT TOP 20
    Cod_producto,
    WorkGroup,
    Fecha_inicio,
    Fecha_fin,
    Unidades_OK,
    SyncDate,
    DATEDIFF(DAY, Fecha_fin, GETDATE()) AS 'Días desde este registro'
FROM OB.Beams_Consumos
ORDER BY Fecha_fin DESC;

PRINT '';
PRINT '========================================';
PRINT 'DIAGNÓSTICO 4: COMPARATIVA';
PRINT '========================================';
PRINT '';
GO

-- Contar registros
DECLARE @ProdLocal INT;
DECLARE @ConsLocal INT;
DECLARE @ProdMapex INT;

SELECT @ProdLocal = COUNT(*) FROM OB.Beams_Produccion;
SELECT @ConsLocal = COUNT(*) FROM OB.Beams_Consumos;

BEGIN TRY
    SELECT @ProdMapex = COUNT(*)
    FROM mapexbp.dbo.F_HIS_CT(
        'WORKCENTER', 'DETAIL', 'PRODUCT',
        '2026-05-28', GETDATE(), 2
    ) f
    WHERE f.WorkGroup1 = '50 Assembly'
      AND f.Unidades_OK > 0;
END TRY
BEGIN CATCH
    SET @ProdMapex = -1;
END CATCH;

PRINT 'Registros locales de Producción: ' + CAST(@ProdLocal AS VARCHAR(20));
PRINT 'Registros locales de Consumo: ' + CAST(@ConsLocal AS VARCHAR(20));
IF @ProdMapex >= 0
    PRINT 'Registros en MAPEX (desde 28-MAY): ' + CAST(@ProdMapex AS VARCHAR(20));
ELSE
    PRINT 'Registros en MAPEX: ❌ ERROR AL CONECTAR';

PRINT '';
PRINT '========================================';
PRINT 'DIAGNÓSTICO 5: ÚLTIMOS REGISTROS INSERTADOS';
PRINT '========================================';
PRINT '';
GO

-- Verificar cuándo fue la última inserción
SELECT
    'Beams_Produccion' AS Tabla,
    MAX(SyncDate) AS 'Última inserción',
    DATEDIFF(HOUR, MAX(SyncDate), GETDATE()) AS 'Hace X horas'
FROM OB.Beams_Produccion

UNION ALL

SELECT
    'Beams_Consumos',
    MAX(SyncDate),
    DATEDIFF(HOUR, MAX(SyncDate), GETDATE())
FROM OB.Beams_Consumos;

PRINT '';
PRINT '========================================';
PRINT 'DIAGNÓSTICO 6: BEAMS SIN DATOS NUEVOS';
PRINT '========================================';
PRINT '';
GO

-- Mostrar beams que no se actualizan desde hace días
SELECT TOP 20
    lsb.Cod_producto,
    lsb.Fuente,
    lsb.Last_Sync_Date,
    DATEDIFF(DAY, lsb.Last_Sync_Date, GETDATE()) AS 'Días sin actualizar',
    CASE
        WHEN DATEDIFF(DAY, lsb.Last_Sync_Date, GETDATE()) > 3 THEN '🔴 CRÍTICO'
        WHEN DATEDIFF(DAY, lsb.Last_Sync_Date, GETDATE()) > 1 THEN '🟡 ALERTA'
        ELSE '🟢 OK'
    END AS Estado
FROM OB.Last_Sync_Beams lsb
WHERE lsb.Last_Sync_Date < DATEADD(DAY, -1, GETDATE())
ORDER BY lsb.Last_Sync_Date ASC;

PRINT '';
PRINT '✅ DIAGNÓSTICO COMPLETADO';

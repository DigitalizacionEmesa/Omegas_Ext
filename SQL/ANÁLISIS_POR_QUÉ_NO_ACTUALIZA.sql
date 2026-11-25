-- ========================================
-- ANÁLISIS DETALLADO: ¿QUÉ DATOS TRAE MAPEX?
-- ========================================

USE DataLakeSCCZ;
GO

PRINT '========================================';
PRINT '📊 ANÁLISIS: DATOS MÁS RECIENTES EN MAPEX';
PRINT '========================================';
GO

-- ¿Cuál es la fecha MÁS RECIENTE en MAPEX?
DECLARE @MaxFechaMapex DATETIME;
DECLARE @MinFechaMapex DATETIME;

BEGIN TRY
    SELECT 
        @MinFechaMapex = MIN(f.Fecha_ini),
        @MaxFechaMapex = MAX(f.Fecha_fin)
    FROM mapexbp.dbo.V_His_Prod f
    WHERE f.Dia_productivo BETWEEN '2026-05-28' AND GETDATE()
      AND f.Cod_area = '50 Assembly'
      AND f.Unidades_OK > 0;
    
    PRINT 'Datos en MAPEX:';
    PRINT '  • Fecha MÁS ANTIGUA: ' + ISNULL(CONVERT(VARCHAR, @MinFechaMapex, 120), 'NO HAY DATOS');
    PRINT '  • Fecha MÁS RECIENTE: ' + ISNULL(CONVERT(VARCHAR, @MaxFechaMapex, 120), 'NO HAY DATOS');
    PRINT '';
    
    PRINT 'Last_Sync_Date actuales:';
    SELECT 
        Cod_producto,
        Fuente,
        Last_Sync_Date,
        CASE
            WHEN @MaxFechaMapex > Last_Sync_Date THEN '✅ Hay datos nuevos en MAPEX'
            WHEN @MaxFechaMapex = Last_Sync_Date THEN '⚠️ MAPEX está al mismo nivel'
            ELSE '❌ MAPEX está MÁS VIEJO'
        END AS Análisis
    FROM OB.Last_Sync_Beams
    WHERE Fuente = 'CONS'
    ORDER BY Last_Sync_Date DESC;
    
END TRY
BEGIN CATCH
    PRINT 'Error: ' + ERROR_MESSAGE();
END CATCH;

PRINT '';
PRINT '========================================';
PRINT '🔍 VERIFICACIÓN: ¿POR QUÉ NO SE ACTUALIZA?';
PRINT '========================================';
GO

-- Simulemos lo que hace el procedimiento
DECLARE @BootstrapSyncDate DATETIME = DATEADD(MINUTE, -5, GETDATE());

SELECT TOP 20
    f.Cod_producto,
    lsb.Fuente,
    lsb.Last_Sync_Date AS 'Last_Sync_Date ACTUAL',
    f.Fecha_fin AS 'Fecha_fin en MAPEX',
    CASE
        WHEN f.Fecha_fin > lsb.Last_Sync_Date THEN '✅ DEBERÍA actualizar'
        ELSE '❌ NO actualiza (fecha <= Last_Sync)'
    END AS 'Se actualiza?'
FROM mapexbp.dbo.V_His_Prod f
INNER JOIN OB.Beams b ON b.BeamCode = f.Cod_producto AND b.IsActive = 1
INNER JOIN OB.Last_Sync_Beams lsb ON lsb.Cod_producto = f.Cod_producto AND lsb.Fuente = 'CONS'
WHERE f.Dia_productivo BETWEEN DATEADD(DAY, DATEDIFF(DAY, 0, @BootstrapSyncDate), 0) AND GETDATE()
  AND f.Cod_area = '50 Assembly'
  AND f.Unidades_OK > 0
ORDER BY f.Fecha_fin DESC;

PRINT '';
PRINT '✅ Si ves "❌ NO actualiza" → Eso es el problema';
PRINT '✅ Si ves "✅ DEBERÍA actualizar" → El problema está en otra parte';

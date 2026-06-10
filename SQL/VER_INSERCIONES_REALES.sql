-- Ver exactamente QUÉ SE INSERTÓ en las tablas
USE DataLakeSCCZ;
GO

PRINT '════════════════════════════════════════════════════════════════';
PRINT '📊 ÚLTIMAS INSERCIONES EN Beams_Consumos (últimos 10 registros)';
PRINT '════════════════════════════════════════════════════════════════';
GO

SELECT TOP 10
    Cod_producto,
    WorkGroup,
    Fecha_inicio,
    Fecha_fin,
    Unidades_OK,
    SyncDate,
    DATEDIFF(MINUTE, Fecha_fin, GETDATE()) AS 'Minutos de retraso'
FROM OB.Beams_Consumos
ORDER BY Fecha_fin DESC;

PRINT '';
PRINT '════════════════════════════════════════════════════════════════';
PRINT '📊 ÚLTIMAS INSERCIONES EN Beams_Produccion (últimos 10 registros)';
PRINT '════════════════════════════════════════════════════════════════';
GO

SELECT TOP 10
    Cod_producto,
    WorkGroup,
    Fecha_inicio,
    Fecha_fin,
    Unidades_OK,
    SyncDate,
    DATEDIFF(MINUTE, Fecha_fin, GETDATE()) AS 'Minutos de retraso'
FROM OB.Beams_Produccion
ORDER BY Fecha_fin DESC;

PRINT '';
PRINT '════════════════════════════════════════════════════════════════';
PRINT '🎯 PARA CADA BEAM: ¿Cuál es el MAX(Fecha_fin) en la tabla local?';
PRINT '════════════════════════════════════════════════════════════════';
GO

SELECT TOP 20
    'CONS' AS Fuente,
    Cod_producto,
    MAX(Fecha_fin) AS 'MAX(Fecha_fin) en LOCAL',
    (SELECT Last_Sync_Date FROM OB.Last_Sync_Beams WHERE Cod_producto = bc.Cod_producto AND Fuente = 'CONS') AS 'Last_Sync_Date ACTUAL',
    CASE
        WHEN MAX(Fecha_fin) > (SELECT Last_Sync_Date FROM OB.Last_Sync_Beams WHERE Cod_producto = bc.Cod_producto AND Fuente = 'CONS')
        THEN '✅ DEBERÍA haberse actualizado'
        ELSE '❌ No se actualiza'
    END AS 'Estado'
FROM OB.Beams_Consumos bc
GROUP BY Cod_producto
ORDER BY MAX(Fecha_fin) DESC;

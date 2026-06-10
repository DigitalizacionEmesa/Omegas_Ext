-- ============================================================================
-- FIX: sp_Reset_Omega_Stock - Evita que el sync reimporte producción antigua
-- ============================================================================
-- BUG: sp_Sync_Omegas_RawData tiene una 2ª condición OR que captura producción
--      que empezó ANTES del reset pero terminó DESPUÉS.
--      Ej: producción 09:10→11:44, reset a 10:53 → Last_Sync=10:53
--          Condición: Fin(11:44) > Last_Sync(10:53) AND Ini(09:10) < Last_Sync(10:53)
--          → TRUE → se reimporta la producción antigua → stock inflado.
--
-- FIX: Guardar el Fecha_fin más reciente ANTES de borrar, y poner Last_Sync_Date
--      = Fecha_fin + 1 segundo. Así la condición OR ya no se cumple.
-- ============================================================================

USE [DataLakeSCCZ]
GO

ALTER PROCEDURE [OB].[sp_Reset_Omega_Stock]
    @Cod_producto VARCHAR(50),
    @NuevoStock INT = 0
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @CurrentTime DATETIME = GETDATE();
    DECLARE @LatestProdFinish DATETIME;
    DECLARE @LatestLecDate DATETIME;

    IF @Cod_producto IS NOT NULL
    BEGIN
        -- ═══ FIX: Guardar fechas de última producción/lectura ANTES de borrar ═══
        SELECT @LatestProdFinish = MAX(Fecha_fin) 
        FROM OB.Omegas_Produccion 
        WHERE Cod_producto = @Cod_producto;

        SELECT @LatestLecDate = MAX(fecha)
        FROM OB.Omegas_Lecturas
        WHERE producto = @Cod_producto;
        -- ═══════════════════════════════════════════════════════════════════════

        DELETE FROM OB.Omegas_Produccion WHERE Cod_producto = @Cod_producto;
        DELETE FROM OB.Omegas_Lecturas WHERE producto = @Cod_producto;
        
        -- ═══ FIX: Last_Sync = después de la última prod/lec conocida ═══
        -- Así sp_Sync_Omegas_RawData no reimportará producción que ya existía
        UPDATE OB.Last_Sync_omegas 
        SET Last_Sync_Date = ISNULL(DATEADD(SECOND, 1, @LatestProdFinish), @CurrentTime)
        WHERE Cod_producto = @Cod_producto AND Fuente = 'PROD';

        UPDATE OB.Last_Sync_omegas 
        SET Last_Sync_Date = ISNULL(DATEADD(SECOND, 1, @LatestLecDate), @CurrentTime)
        WHERE Cod_producto = @Cod_producto AND Fuente = 'LEC';
        -- ════════════════════════════════════════════════════════════════

        IF @NuevoStock <> 0
        BEGIN
            INSERT INTO OB.Omegas_Produccion (Cod_producto, WorkGroup, Fecha_inicio, Fecha_fin, Unidades_OK)
            VALUES (@Cod_producto, 'AJUSTE_MANUAL', @CurrentTime, @CurrentTime, @NuevoStock);
        END
    END
END;
GO

PRINT '✅ sp_Reset_Omega_Stock corregido: ya no reimporta producción antigua tras reset.';

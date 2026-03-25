USE [DataLakeSCCZ]
GO

/****** Object:  StoredProcedure [OB].[sp_Reset_Omega_Stock]    Script Date: 18/03/2026 7:50:18 ******/
SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO

ALTER   PROCEDURE [OB].[sp_Reset_Omega_Stock]
    @Cod_producto VARCHAR(50),
    @NuevoStock INT = 0
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @CurrentTime DATETIME = GETDATE();

    IF @Cod_producto IS NOT NULL
    BEGIN
        DELETE FROM OB.Omegas_Produccion WHERE Cod_producto = @Cod_producto;
        DELETE FROM OB.Omegas_Lecturas WHERE producto = @Cod_producto;
        
        UPDATE OB.Last_Sync_omegas 
        SET Last_Sync_Date = @CurrentTime 
        WHERE Cod_producto = @Cod_producto;

        IF @NuevoStock <> 0
        BEGIN
            INSERT INTO OB.Omegas_Produccion (Cod_producto, WorkGroup, Fecha_inicio, Fecha_fin, Unidades_OK)
            VALUES (@Cod_producto, 'AJUSTE_MANUAL', @CurrentTime, @CurrentTime, @NuevoStock);
        END
    END
END;
GO
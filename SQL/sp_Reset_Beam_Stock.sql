USE [DataLakeSCCZ]
GO

SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO

CREATE OR ALTER PROCEDURE [OB].[sp_Reset_Beam_Stock]
    @BeamID INT,
    @NuevoStock INT,
    @UsuarioID INT,
    @Notes NVARCHAR(500) = N'AJUSTE_MANUAL'
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @BeamCode VARCHAR(50);
    DECLARE @CurrentTime DATETIME = GETDATE();

    SELECT @BeamCode = BeamCode
    FROM OB.Beams
    WHERE BeamID = @BeamID;

    IF @BeamCode IS NULL
    BEGIN
        THROW 50003, 'Error: El BeamID especificado no existe en la tabla OB.Beams.', 1;
        RETURN;
    END

    BEGIN TRANSACTION;

    BEGIN TRY
        DELETE FROM OB.BeamStocks
        WHERE BeamID = @BeamID;

        DELETE FROM OB.Beams_Produccion
        WHERE Cod_producto = @BeamCode;

        DELETE FROM OB.Beams_Consumos
        WHERE Cod_producto = @BeamCode;

        DELETE FROM OB.BeamSync_PostedTotals
        WHERE BeamID = @BeamID;

        MERGE OB.Last_Sync_Beams AS target
        USING (
            VALUES
                (@BeamCode, 'PROD', @CurrentTime),
                (@BeamCode, 'CONS', @CurrentTime)
        ) AS source (Cod_producto, Fuente, Last_Sync_Date)
            ON target.Cod_producto = source.Cod_producto
           AND target.Fuente = source.Fuente
        WHEN MATCHED THEN
            UPDATE SET Last_Sync_Date = source.Last_Sync_Date
        WHEN NOT MATCHED BY TARGET THEN
            INSERT (Cod_producto, Fuente, Last_Sync_Date)
            VALUES (source.Cod_producto, source.Fuente, source.Last_Sync_Date);

        IF @NuevoStock <> 0
        BEGIN
            INSERT INTO OB.Beams_Produccion (Cod_producto, WorkGroup, Fecha_inicio, Fecha_fin, Unidades_OK)
            VALUES (@BeamCode, 'AJUSTE_MANUAL', @CurrentTime, @CurrentTime, @NuevoStock);

            INSERT INTO OB.BeamStocks (BeamID, MovementID, Quantity, ID_Usuario, Notes)
            VALUES (@BeamID, 3, @NuevoStock, @UsuarioID, 'AJUSTE_MANUAL');
        END

        MERGE OB.BeamSync_PostedTotals AS target
        USING (
            VALUES
                (@BeamID, 'PROD', CASE WHEN @NuevoStock <> 0 THEN @NuevoStock ELSE 0 END, @CurrentTime),
                (@BeamID, 'CONS', 0, @CurrentTime)
        ) AS source (BeamID, Fuente, PostedQuantity, LastPostDate)
            ON target.BeamID = source.BeamID
           AND target.Fuente = source.Fuente
        WHEN MATCHED THEN
            UPDATE SET
                PostedQuantity = source.PostedQuantity,
                LastPostDate = source.LastPostDate
        WHEN NOT MATCHED BY TARGET THEN
            INSERT (BeamID, Fuente, PostedQuantity, LastPostDate)
            VALUES (source.BeamID, source.Fuente, source.PostedQuantity, source.LastPostDate);

        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0
            ROLLBACK TRANSACTION;

        THROW;
    END CATCH
END;
GO
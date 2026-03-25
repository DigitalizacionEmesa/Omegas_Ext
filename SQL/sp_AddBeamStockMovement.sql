USE [DataLakeSCCZ]
GO

/****** Object:  StoredProcedure [OB].[sp_AddBeamStockMovement]    Script Date: 18/03/2026 7:50:56 ******/
SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO


-- Creación del nuevo procedimiento almacenado para Beams
ALTER   PROCEDURE [OB].[sp_AddBeamStockMovement]
    @BeamID INT,
    @MovementID INT,
    @Quantity INT,
    @UsuarioID INT,
    @Notes NVARCHAR(500)
AS
BEGIN
    -- Optimización para evitar mensajes de 'rows affected'
    SET NOCOUNT ON;

    -- Validación de la existencia del Beam y del Tipo de Movimiento
    IF NOT EXISTS (SELECT 1 FROM OB.Beams WHERE BeamID = @BeamID)
    BEGIN
        -- Lanza un error claro que la API puede capturar
        THROW 50001, 'Error: El BeamID especificado no existe en la tabla OB.Beams.', 1;
        RETURN;
    END

    IF NOT EXISTS (SELECT 1 FROM OB.Movement WHERE MovementID = @MovementID)
    BEGIN
        THROW 50002, 'Error: El MovementID especificado no existe en la tabla OB.Movement.', 1;
        RETURN;
    END

    -- Lógica para asegurar el signo correcto de la cantidad
    DECLARE @FinalQuantity INT = @Quantity;
    
    -- Movimientos que SIEMPRE deben ser negativos (salidas)
    -- Asumimos: Lectura(2), Venta(5), Baja(7), Salida por Trazabilidad(9)
    IF @MovementID IN (2, 5, 7, 9) AND @Quantity > 0
    BEGIN
        SET @FinalQuantity = @Quantity * -1;
    END
    -- Movimientos que SIEMPRE deben ser positivos (entradas)
    -- Asumimos: Producción(1), Compra(4), Devolución(6)
    ELSE IF @MovementID IN (1, 4, 6) AND @Quantity < 0
    BEGIN
        SET @FinalQuantity = @Quantity * -1;
    END

    -- Inserción final del movimiento en la tabla de stock de Beams
    INSERT INTO OB.BeamStocks (BeamID, MovementID, Quantity, ID_Usuario, Notes)
    VALUES (@BeamID, @MovementID, @FinalQuantity, @UsuarioID, @Notes);
END
GO


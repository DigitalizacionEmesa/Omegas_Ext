-- =============================================================================
-- Agregar columna CWI a la tabla OB.PedidosCabecera para guardar clinching/W/C=CWI
-- =============================================================================

USE [DataLakeSCCZ];
GO

IF NOT EXISTS (
    SELECT 1
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'OB'
      AND TABLE_NAME = 'PedidosCabecera'
      AND COLUMN_NAME = 'CWI'
)
BEGIN
    ALTER TABLE [OB].[PedidosCabecera]
    ADD [CWI] NVARCHAR(100) NULL;

    PRINT 'Columna CWI agregada exitosamente a OB.PedidosCabecera';
END
ELSE
BEGIN
    PRINT 'La columna CWI ya existe en OB.PedidosCabecera';
END;

GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_OB_PedidosCabecera_CWI'
      AND object_id = OBJECT_ID('[OB].[PedidosCabecera]')
)
BEGIN
    CREATE INDEX [IX_OB_PedidosCabecera_CWI]
    ON [OB].[PedidosCabecera] ([CWI]);

    PRINT 'Indice en CWI creado exitosamente';
END
ELSE
BEGIN
    PRINT 'Indice en CWI ya existe';
END;

GO

PRINT 'Script completado';

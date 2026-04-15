-- =============================================================================
-- Agregar columna EX a la tabla OB.PedidosCabecera para guardar Extensores
-- =============================================================================

USE [DataLakeSCCZ];
GO

-- Verificar si la columna ya existe
IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS 
               WHERE TABLE_SCHEMA = 'OB' 
               AND TABLE_NAME = 'PedidosCabecera' 
               AND COLUMN_NAME = 'EX')
BEGIN
    -- Agregar columna EX
    ALTER TABLE [OB].[PedidosCabecera]
    ADD [EX] NVARCHAR(100) NULL;
    
    PRINT 'Columna EX agregada exitosamente a OB.PedidosCabecera';
END
ELSE
BEGIN
    PRINT 'La columna EX ya existe en OB.PedidosCabecera';
END;

GO

-- Crear índice en EX para búsquedas rápidas (opcional pero recomendado)
IF NOT EXISTS (SELECT 1 FROM sys.indexes 
               WHERE name = 'IX_OB_PedidosCabecera_EX' 
               AND object_id = OBJECT_ID('[OB].[PedidosCabecera]'))
BEGIN
    CREATE INDEX [IX_OB_PedidosCabecera_EX] 
    ON [OB].[PedidosCabecera] ([EX]);
    
    PRINT 'Índice en EX creado exitosamente';
END
ELSE
BEGIN
    PRINT 'Índice en EX ya existe';
END;

GO

PRINT 'Script completado';

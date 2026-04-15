-- =============================================================================
-- Agregar columna TB a la tabla OB.PedidosCabecera para guardar Tubing/Bracket
-- =============================================================================

USE [DataLakeSCCZ];
GO

-- Verificar si la columna ya existe
IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS 
               WHERE TABLE_SCHEMA = 'OB' 
               AND TABLE_NAME = 'PedidosCabecera' 
               AND COLUMN_NAME = 'TB')
BEGIN
    -- Agregar columna TB
    ALTER TABLE [OB].[PedidosCabecera]
    ADD [TB] NVARCHAR(100) NULL;
    
    PRINT 'Columna TB agregada exitosamente a OB.PedidosCabecera';
END
ELSE
BEGIN
    PRINT 'La columna TB ya existe en OB.PedidosCabecera';
END;

GO

-- Crear índice en TB para búsquedas rápidas (opcional pero recomendado)
IF NOT EXISTS (SELECT 1 FROM sys.indexes 
               WHERE name = 'IX_OB_PedidosCabecera_TB' 
               AND object_id = OBJECT_ID('[OB].[PedidosCabecera]'))
BEGIN
    CREATE INDEX [IX_OB_PedidosCabecera_TB] 
    ON [OB].[PedidosCabecera] ([TB]);
    
    PRINT 'Índice en TB creado exitosamente';
END
ELSE
BEGIN
    PRINT 'Índice en TB ya existe';
END;

GO

PRINT 'Script completado';

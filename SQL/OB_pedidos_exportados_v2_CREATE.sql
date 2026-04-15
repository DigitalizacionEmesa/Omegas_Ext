-- =============================================================================
-- Tabla: OB.pedidos_exportados_v2
-- Descripción: Almacena características de pedidos importados desde archivos
--              Structure simple: Sales Document | Material | Characteristic Name | Characteristic Value
-- =============================================================================

USE [DataLakeSCCZ];
GO

-- Crear esquema OB si aún no existiera
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'OB')
    EXEC('CREATE SCHEMA OB');
GO

-- Dropear tabla si existe (para recrear limpiamente)
IF EXISTS (SELECT 1 FROM sys.objects WHERE object_id = OBJECT_ID(N'[OB].[pedidos_exportados]') AND type = 'U')
    DROP TABLE [OB].[pedidos_exportados];
GO

-- =============================================================================
-- TABLA PRINCIPAL
-- =============================================================================
CREATE TABLE [OB].[pedidos_exportados] (
    [id_importacion]            INT            NOT NULL IDENTITY(1,1),
    [sales_document]            NVARCHAR(50)   NOT NULL,
    [material]                  NVARCHAR(100)  NOT NULL,
    [characteristic_name]       NVARCHAR(255)  NOT NULL,
    [characteristic_value]      NVARCHAR(MAX)  NULL,
    [fecha_importacion]         DATETIME2      NOT NULL DEFAULT GETDATE(),
    
    CONSTRAINT [PK_OB_pedidos_exportados] PRIMARY KEY ([id_importacion])
);
GO

-- Índice para búsquedas por número de pedido
CREATE INDEX [IDX_pedidos_exportados_sales_doc] ON [OB].[pedidos_exportados]([sales_document]);
GO

-- Índice para búsquedas por material
CREATE INDEX [IDX_pedidos_exportados_material] ON [OB].[pedidos_exportados]([material]);
GO

-- Índice para búsquedas por característica
CREATE INDEX [IDX_pedidos_exportados_char_name] ON [OB].[pedidos_exportados]([characteristic_name]);
GO

PRINT 'Tabla OB.pedidos_exportados creada exitosamente';
GO

-- =============================================================================
-- Tabla: OB.pedidos_exportados
-- Descripción: Almacena los pedidos importados desde archivos Excel/CSV
-- =============================================================================

USE [DataLakeSCCZ];
GO

-- Crear esquema OB si aún no existiera
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'OB')
    EXEC('CREATE SCHEMA OB');
GO

CREATE TABLE [OB].[pedidos_exportados] (
    [id_exportacion]      INT            NOT NULL IDENTITY(1,1),
    [sales_document]      NVARCHAR(50)   NOT NULL,
    [material]            NVARCHAR(100)  NOT NULL,
    [characteristic_name] NVARCHAR(255)  NOT NULL,
    [characteristic_value] NVARCHAR(MAX) NULL,
    [has_extender]        BIT            NULL,
    [omega_bracket_type_tsd] NVARCHAR(255) NULL,
    [extender_assy_candidates] NVARCHAR(MAX) NULL,
    [extender_order_materials] NVARCHAR(MAX) NULL,
    CONSTRAINT [PK_OB_pedidos_exp] PRIMARY KEY ([id_exportacion])
);
GO

PRINT 'Tabla OB.pedidos_exportados creada exitosamente';

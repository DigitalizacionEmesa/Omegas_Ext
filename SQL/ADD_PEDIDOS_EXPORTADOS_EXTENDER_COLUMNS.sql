USE [DataLakeSCCZ];
GO

IF COL_LENGTH('OB.pedidos_exportados', 'has_extender') IS NULL
BEGIN
    ALTER TABLE [OB].[pedidos_exportados]
    ADD [has_extender] BIT NULL;
END;
GO

IF COL_LENGTH('OB.pedidos_exportados', 'omega_bracket_type_tsd') IS NULL
BEGIN
    ALTER TABLE [OB].[pedidos_exportados]
    ADD [omega_bracket_type_tsd] NVARCHAR(255) NULL;
END;
GO

IF COL_LENGTH('OB.pedidos_exportados', 'extender_assy_candidates') IS NULL
BEGIN
    ALTER TABLE [OB].[pedidos_exportados]
    ADD [extender_assy_candidates] NVARCHAR(MAX) NULL;
END;
GO

IF COL_LENGTH('OB.pedidos_exportados', 'extender_order_materials') IS NULL
BEGIN
    ALTER TABLE [OB].[pedidos_exportados]
    ADD [extender_order_materials] NVARCHAR(MAX) NULL;
END;
GO

PRINT 'Columnas derivadas de extensores verificadas en OB.pedidos_exportados';
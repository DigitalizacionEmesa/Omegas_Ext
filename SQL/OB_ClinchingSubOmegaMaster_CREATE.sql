-- =============================================================================
-- Tabla: OB.ClinchingSubOmegaMaster
-- Descripción: Master de Sub-Omega -> Beam + Guide Interface para la pantalla de Clinching
-- =============================================================================

USE [DataLakeSCCZ];
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'OB')
    EXEC('CREATE SCHEMA OB');
GO

IF OBJECT_ID('[OB].[ClinchingSubOmegaMaster]', 'U') IS NULL
BEGIN
    CREATE TABLE [OB].[ClinchingSubOmegaMaster] (
        [Id_ClinchingSubOmegaMaster] INT           NOT NULL IDENTITY(1,1),
        [SubOmega]                   NVARCHAR(50)  NOT NULL,
        [Beam]                       NVARCHAR(50)  NOT NULL,
        [GuideInterface]             NVARCHAR(50)  NOT NULL,
        [IsActive]                   BIT           NOT NULL CONSTRAINT [DF_OB_ClinchingSubOmegaMaster_IsActive] DEFAULT 1,
        [SourceNote]                 NVARCHAR(255) NULL,
        [CreatedAt]                  DATETIME2(3)  NOT NULL CONSTRAINT [DF_OB_ClinchingSubOmegaMaster_CreatedAt] DEFAULT GETDATE(),
        [UpdatedAt]                  DATETIME2(3)  NOT NULL CONSTRAINT [DF_OB_ClinchingSubOmegaMaster_UpdatedAt] DEFAULT GETDATE(),
        CONSTRAINT [PK_OB_ClinchingSubOmegaMaster] PRIMARY KEY ([Id_ClinchingSubOmegaMaster]),
        CONSTRAINT [UQ_OB_ClinchingSubOmegaMaster_SubOmega] UNIQUE ([SubOmega])
    );

    PRINT 'Tabla OB.ClinchingSubOmegaMaster creada exitosamente';
END
ELSE
BEGIN
    PRINT 'La tabla OB.ClinchingSubOmegaMaster ya existe';
END
GO
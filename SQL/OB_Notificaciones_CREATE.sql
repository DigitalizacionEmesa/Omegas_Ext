-- =============================================================================
-- Tabla: OB.Notificaciones  (DataLakeSCCZ)
-- Equivalente a [Digitalizacion].[DIG].[UPDATER_DIG_Configuracion_Global]
-- Solo columnas necesarias para el sistema de notificaciones de Omegas.
-- Las credenciales SMTP se almacenan cifradas con Fernet.
-- =============================================================================

USE [DataLakeSCCZ];
GO

-- Crear esquema OB si aún no existiera
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'OB')
    EXEC('CREATE SCHEMA OB');
GO

CREATE TABLE [OB].[Notificaciones] (
    [id_config]               INT            NOT NULL CONSTRAINT [DF_OB_Notificaciones_id] DEFAULT 1,
    [smtp_servidor]           NVARCHAR(255)  NULL,
    [smtp_puerto]             INT            NOT NULL CONSTRAINT [DF_OB_Notificaciones_puerto] DEFAULT 587,
    [smtp_usuario_cifrado]    NVARCHAR(500)  NULL,   -- Cifrado con Fernet
    [smtp_contrasena_cifrada] NVARCHAR(500)  NULL,   -- Cifrado con Fernet
    [smtp_usar_tls]           BIT            NOT NULL CONSTRAINT [DF_OB_Notificaciones_tls] DEFAULT 1,
    [correo_origen]           NVARCHAR(255)  NULL,
    [nombre_remitente]        NVARCHAR(255)  NULL CONSTRAINT [DF_OB_Notificaciones_remitente] DEFAULT 'Sistema Omegas',
    [correos_alertas]         NVARCHAR(MAX)  NULL,   -- Separados por punto y coma: a@x.com; b@x.com
    [ultima_actualizacion]    DATETIME2(3)   NULL CONSTRAINT [DF_OB_Notificaciones_ts] DEFAULT GETDATE(),
    [actualizado_por]         NVARCHAR(100)  NULL,
    CONSTRAINT [PK_OB_Notificaciones] PRIMARY KEY ([id_config])
);
GO

-- =============================================================================
-- INSERT inicial con los valores de la configuración existente
-- (credenciales ya cifradas con la misma clave Fernet que usa la aplicación)
-- =============================================================================
INSERT INTO [OB].[Notificaciones] (
    id_config, smtp_servidor, smtp_puerto,
    smtp_usuario_cifrado, smtp_contrasena_cifrada,
    smtp_usar_tls, correo_origen, nombre_remitente,
    correos_alertas, ultima_actualizacion, actualizado_por
) VALUES (
    1,
    'smtp.gmail.com',
    587,
    'gAAAAABpeI0iKTAXr6ynMxUI5sTjdu4tbdxe-VIwpeXzUfVr0-ikYAHemaEAJj-wuCOeDiGErTz2JIYBJBLf6jTHXUuVjtkWpNoenPdMUxyBj2WFd5onqAQ=',
    'gAAAAABpeI0iWMairBJv-yUFx_uKQNznD55KIUiJoGhJ7Mlx04r5ds0WXLVQqDu-UuUBNsy7r9Jjb65zeXFbBaKa8bPlTCwESolH61RjxdRK-GXyAgu2PmQ=',
    1,
    'digitalizacionemesa@gmail.com',
    'Sistema Omegas',
    'o.abad@saveragroup.com; j.cortes@saveragroup.com; pi.cortes@saveragroup.com',
    GETDATE(),
    NULL
);
GO

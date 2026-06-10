USE [DataLakeSCCZ]
GO

SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO

IF OBJECT_ID('OB.Last_Sync_Beams', 'U') IS NOT NULL
   AND COL_LENGTH('OB.Last_Sync_Beams', 'Cod_producto') IS NULL
BEGIN
    DROP TABLE OB.Last_Sync_Beams;
END;
GO

IF OBJECT_ID('OB.Last_Sync_Beams', 'U') IS NULL
BEGIN
    CREATE TABLE OB.Last_Sync_Beams (
        Cod_producto VARCHAR(50) NOT NULL,
        Fuente VARCHAR(10) NOT NULL,
        Last_Sync_Date DATETIME NULL,
        CONSTRAINT PK_Last_Sync_Beams PRIMARY KEY (Cod_producto, Fuente)
    );
END;
GO

IF OBJECT_ID('OB.Beams_Produccion', 'U') IS NOT NULL
   AND COL_LENGTH('OB.Beams_Produccion', 'ValidFrom') IS NULL
BEGIN
    DROP TABLE OB.Beams_Produccion;
END;
GO

IF OBJECT_ID('OB.Beams_Produccion_History', 'U') IS NOT NULL
   AND OBJECT_ID('OB.Beams_Produccion', 'U') IS NULL
BEGIN
    DROP TABLE OB.Beams_Produccion_History;
END;
GO

IF OBJECT_ID('OB.Beams_Produccion', 'U') IS NULL
BEGIN
    CREATE TABLE OB.Beams_Produccion (
        Id INT IDENTITY(1,1) NOT NULL,
        Cod_producto VARCHAR(50) NULL,
        WorkGroup VARCHAR(100) NULL,
        Fecha_inicio DATETIME NULL,
        Fecha_fin DATETIME NULL,
        Unidades_OK INT NULL,
        SyncDate DATETIME NULL CONSTRAINT DF_Beams_Produccion_SyncDate DEFAULT (GETDATE()),
        ValidFrom DATETIME2 GENERATED ALWAYS AS ROW START NOT NULL,
        ValidTo DATETIME2 GENERATED ALWAYS AS ROW END NOT NULL,
        PERIOD FOR SYSTEM_TIME (ValidFrom, ValidTo),
        CONSTRAINT PK_Beams_Produccion PRIMARY KEY (Id),
        CONSTRAINT UQ_Beams_Produccion_Natural UNIQUE (Cod_producto, WorkGroup, Fecha_inicio)
    )
    WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = OB.Beams_Produccion_History));
END;
GO

IF OBJECT_ID('OB.Beams_Consumos', 'U') IS NOT NULL
   AND COL_LENGTH('OB.Beams_Consumos', 'ValidFrom') IS NULL
BEGIN
    DROP TABLE OB.Beams_Consumos;
END;
GO

IF OBJECT_ID('OB.Beams_Consumos_History', 'U') IS NOT NULL
   AND OBJECT_ID('OB.Beams_Consumos', 'U') IS NULL
BEGIN
    DROP TABLE OB.Beams_Consumos_History;
END;
GO

IF OBJECT_ID('OB.Beams_Consumos', 'U') IS NULL
BEGIN
    CREATE TABLE OB.Beams_Consumos (
        Id INT IDENTITY(1,1) NOT NULL,
        Cod_producto VARCHAR(50) NULL,
        WorkGroup VARCHAR(100) NULL,
        Fecha_inicio DATETIME NULL,
        Fecha_fin DATETIME NULL,
        Unidades_OK INT NULL,
        SyncDate DATETIME NULL CONSTRAINT DF_Beams_Consumos_SyncDate DEFAULT (GETDATE()),
        ValidFrom DATETIME2 GENERATED ALWAYS AS ROW START NOT NULL,
        ValidTo DATETIME2 GENERATED ALWAYS AS ROW END NOT NULL,
        PERIOD FOR SYSTEM_TIME (ValidFrom, ValidTo),
        CONSTRAINT PK_Beams_Consumos PRIMARY KEY (Id),
        CONSTRAINT UQ_Beams_Consumos_Natural UNIQUE (Cod_producto, WorkGroup, Fecha_inicio)
    )
    WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = OB.Beams_Consumos_History));
END;
GO

IF OBJECT_ID('OB.BeamSync_PostedTotals', 'U') IS NULL
BEGIN
    CREATE TABLE OB.BeamSync_PostedTotals (
        BeamID INT NOT NULL,
        Fuente VARCHAR(10) NOT NULL,
        PostedQuantity INT NOT NULL CONSTRAINT DF_BeamSync_PostedTotals_Quantity DEFAULT (0),
        LastPostDate DATETIME NOT NULL CONSTRAINT DF_BeamSync_PostedTotals_LastPostDate DEFAULT (GETDATE()),
        CONSTRAINT PK_BeamSync_PostedTotals PRIMARY KEY (BeamID, Fuente),
        CONSTRAINT FK_BeamSync_PostedTotals_Beams FOREIGN KEY (BeamID) REFERENCES OB.Beams (BeamID)
    );
END;
GO

CREATE OR ALTER PROCEDURE [OB].[sp_Sync_Beams_RawData]
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @CurrentTime DATETIME = GETDATE();
    DECLARE @BootstrapSyncDate DATETIME = DATEADD(MINUTE, -5, @CurrentTime);

    INSERT INTO OB.Last_Sync_Beams (Cod_producto, Fuente, Last_Sync_Date)
    SELECT b.BeamCode, src.Fuente, @BootstrapSyncDate
    FROM OB.Beams b
    CROSS JOIN (VALUES ('PROD'), ('CONS')) src(Fuente)
    WHERE b.IsActive = 1
      AND NOT EXISTS (
          SELECT 1
          FROM OB.Last_Sync_Beams lsb
          WHERE lsb.Cod_producto = b.BeamCode
            AND lsb.Fuente = src.Fuente
      );

    MERGE OB.Beams_Produccion AS Target
    USING (
        SELECT
            f.Cod_producto,
            CAST(COALESCE(NULLIF(LTRIM(RTRIM(f.WorkGroup)), ''), '50 Assembly') AS VARCHAR(100)) AS WorkGroup,
            f.Fecha_inicio,
            f.Fecha_fin,
            CAST(f.Unidades_OK AS INT) AS Unidades_OK
        FROM mapexbp.dbo.F_HIS_CT(
            'WORKCENTER', 'DETAIL', 'PRODUCT',
            DATEADD(DAY, DATEDIFF(DAY, 0, @BootstrapSyncDate), 0), @CurrentTime, 2
        ) f
        INNER JOIN OB.Beams b
            ON b.BeamCode = f.Cod_producto
           AND b.IsActive = 1
        INNER JOIN OB.Last_Sync_Beams lsb
            ON lsb.Cod_producto = f.Cod_producto
           AND lsb.Fuente = 'PROD'
        WHERE f.WorkGroup1 = '50 Assembly'
          AND f.Unidades_OK > 0
          AND (
                f.Fecha_inicio >= lsb.Last_Sync_Date
                OR (
                    f.Fecha_fin > lsb.Last_Sync_Date
                    AND f.Fecha_inicio < lsb.Last_Sync_Date
                )
          )
    ) AS Source
    ON (
        Target.Cod_producto = Source.Cod_producto
        AND Target.WorkGroup = Source.WorkGroup
        AND Target.Fecha_inicio = Source.Fecha_inicio
    )
    WHEN MATCHED AND (
        Target.Fecha_fin <> Source.Fecha_fin OR
        Target.Unidades_OK <> Source.Unidades_OK
    ) THEN
        UPDATE SET
            Target.Fecha_fin = Source.Fecha_fin,
            Target.Unidades_OK = Source.Unidades_OK,
            Target.SyncDate = GETDATE()
    WHEN NOT MATCHED BY TARGET THEN
        INSERT (Cod_producto, WorkGroup, Fecha_inicio, Fecha_fin, Unidades_OK)
        VALUES (Source.Cod_producto, Source.WorkGroup, Source.Fecha_inicio, Source.Fecha_fin, Source.Unidades_OK);

    UPDATE lsb
    SET Last_Sync_Date = prod.MaxFecha
    FROM OB.Last_Sync_Beams lsb
    INNER JOIN (
        SELECT Cod_producto, MAX(Fecha_fin) AS MaxFecha
        FROM OB.Beams_Produccion
        WHERE Fecha_fin < DATEADD(MINUTE, -1, GETDATE())
        GROUP BY Cod_producto
    ) prod ON lsb.Cod_producto = prod.Cod_producto
    WHERE lsb.Fuente = 'PROD'
      AND prod.MaxFecha >= lsb.Last_Sync_Date;

    MERGE OB.Beams_Consumos AS Target
    USING (
        SELECT
            beam.BeamCode AS Cod_producto,
            CAST(omega.Assy AS VARCHAR(100)) AS WorkGroup,
            f.Fecha_inicio,
            f.Fecha_fin,
            CAST(f.Unidades_OK AS INT) AS Unidades_OK
        FROM mapexbp.dbo.F_HIS_CT(
            'WORKCENTER', 'DETAIL', 'PRODUCT',
            DATEADD(DAY, DATEDIFF(DAY, 0, @BootstrapSyncDate), 0), @CurrentTime, 2
        ) f
        INNER JOIN OB.Omegas omega
            ON omega.Assy = f.Cod_producto
           AND omega.[W/C] = 'C'
           AND omega.Beam IS NOT NULL
        INNER JOIN OB.Beams beam
            ON beam.BeamCode = omega.Beam
           AND beam.IsActive = 1
        INNER JOIN OB.Last_Sync_Beams lsb
            ON lsb.Cod_producto = beam.BeamCode
           AND lsb.Fuente = 'CONS'
        WHERE f.WorkGroup1 = '50 Assembly'
          AND f.Unidades_OK > 0
          AND (
                f.Fecha_inicio >= lsb.Last_Sync_Date
                OR (
                    f.Fecha_fin > lsb.Last_Sync_Date
                    AND f.Fecha_inicio < lsb.Last_Sync_Date
                )
          )
    ) AS Source
    ON (
        Target.Cod_producto = Source.Cod_producto
        AND Target.WorkGroup = Source.WorkGroup
        AND Target.Fecha_inicio = Source.Fecha_inicio
    )
    WHEN MATCHED AND (
        Target.Fecha_fin <> Source.Fecha_fin OR
        Target.Unidades_OK <> Source.Unidades_OK
    ) THEN
        UPDATE SET
            Target.Fecha_fin = Source.Fecha_fin,
            Target.Unidades_OK = Source.Unidades_OK,
            Target.SyncDate = GETDATE()
    WHEN NOT MATCHED BY TARGET THEN
        INSERT (Cod_producto, WorkGroup, Fecha_inicio, Fecha_fin, Unidades_OK)
        VALUES (Source.Cod_producto, Source.WorkGroup, Source.Fecha_inicio, Source.Fecha_fin, Source.Unidades_OK);

    UPDATE lsb
    SET Last_Sync_Date = cons.MaxFecha
    FROM OB.Last_Sync_Beams lsb
    INNER JOIN (
        SELECT Cod_producto, MAX(Fecha_fin) AS MaxFecha
        FROM OB.Beams_Consumos
        WHERE Fecha_fin < DATEADD(MINUTE, -1, GETDATE())
        GROUP BY Cod_producto
    ) cons ON lsb.Cod_producto = cons.Cod_producto
    WHERE lsb.Fuente = 'CONS'
      AND cons.MaxFecha >= lsb.Last_Sync_Date;

    MERGE OB.BeamSync_PostedTotals AS target
    USING (
        SELECT b.BeamID, src.Fuente
        FROM OB.Beams b
        CROSS JOIN (VALUES ('PROD'), ('CONS')) src(Fuente)
        WHERE b.IsActive = 1
    ) AS source
        ON target.BeamID = source.BeamID
       AND target.Fuente = source.Fuente
    WHEN NOT MATCHED BY TARGET THEN
        INSERT (BeamID, Fuente, PostedQuantity, LastPostDate)
        VALUES (source.BeamID, source.Fuente, 0, @CurrentTime);

    ;WITH RawTotals AS (
        SELECT b.BeamID, 'PROD' AS Fuente, SUM(bp.Unidades_OK) AS TotalQty
        FROM OB.Beams_Produccion bp
        INNER JOIN OB.Beams b ON b.BeamCode = bp.Cod_producto
        GROUP BY b.BeamID

        UNION ALL

        SELECT b.BeamID, 'CONS' AS Fuente, SUM(bc.Unidades_OK) AS TotalQty
        FROM OB.Beams_Consumos bc
        INNER JOIN OB.Beams b ON b.BeamCode = bc.Cod_producto
        GROUP BY b.BeamID
    ),
    CurrentTotals AS (
        SELECT
            pst.BeamID,
            pst.Fuente,
            ISNULL(rt.TotalQty, 0) AS TotalQty,
            pst.PostedQuantity
        FROM OB.BeamSync_PostedTotals pst
        LEFT JOIN RawTotals rt
            ON rt.BeamID = pst.BeamID
           AND rt.Fuente = pst.Fuente
    ),
    Diffs AS (
        SELECT
            BeamID,
            Fuente,
            TotalQty - PostedQuantity AS DeltaQty
        FROM CurrentTotals
        WHERE TotalQty <> PostedQuantity
    )
    INSERT INTO OB.BeamStocks (BeamID, MovementID, Quantity, ID_Usuario, Notes)
    SELECT
        d.BeamID,
        CASE WHEN d.Fuente = 'PROD' THEN 1 ELSE 9 END AS MovementID,
        CASE WHEN d.Fuente = 'PROD' THEN d.DeltaQty ELSE d.DeltaQty * -1 END AS Quantity,
        1 AS ID_Usuario,
        CONCAT('Sincronización automática Beams SQL [', d.Fuente, ']') AS Notes
    FROM Diffs d
    WHERE d.DeltaQty <> 0;

    ;WITH RawTotals AS (
        SELECT b.BeamID, 'PROD' AS Fuente, SUM(bp.Unidades_OK) AS TotalQty
        FROM OB.Beams_Produccion bp
        INNER JOIN OB.Beams b ON b.BeamCode = bp.Cod_producto
        GROUP BY b.BeamID

        UNION ALL

        SELECT b.BeamID, 'CONS' AS Fuente, SUM(bc.Unidades_OK) AS TotalQty
        FROM OB.Beams_Consumos bc
        INNER JOIN OB.Beams b ON b.BeamCode = bc.Cod_producto
        GROUP BY b.BeamID
    )
    UPDATE pst
    SET pst.PostedQuantity = ISNULL(rt.TotalQty, 0),
        pst.LastPostDate = @CurrentTime
    FROM OB.BeamSync_PostedTotals pst
    LEFT JOIN RawTotals rt
        ON rt.BeamID = pst.BeamID
       AND rt.Fuente = pst.Fuente
    WHERE pst.PostedQuantity <> ISNULL(rt.TotalQty, 0);
END;
GO

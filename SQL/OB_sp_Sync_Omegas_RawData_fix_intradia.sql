ALTER PROCEDURE [OB].[sp_Sync_Omegas_RawData]
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @CurrentTime DATETIME = GETDATE();

    INSERT INTO OB.Last_Sync_omegas (Cod_producto, Fuente)
    SELECT Assy, 'PROD' FROM OB.Omegas WHERE [W/C] IN ('C','W')
    AND NOT EXISTS (
        SELECT 1 FROM OB.Last_Sync_omegas
        WHERE Cod_producto = Assy AND Fuente = 'PROD'
    );

    INSERT INTO OB.Last_Sync_omegas (Cod_producto, Fuente)
    SELECT Assy, 'LEC' FROM OB.Omegas WHERE [W/C] IN ('C','W')
    AND NOT EXISTS (
        SELECT 1 FROM OB.Last_Sync_omegas
        WHERE Cod_producto = Assy AND Fuente = 'LEC'
    );

    DECLARE @MinProdDate DATETIME, @MinReadDate DATETIME, @MinProdDateFloor DATETIME;
    SELECT @MinProdDate = ISNULL(MIN(Last_Sync_Date), '2024-01-01')
    FROM OB.Last_Sync_omegas WHERE Fuente = 'PROD';
    SELECT @MinReadDate = ISNULL(MIN(Last_Sync_Date), '2024-01-01')
    FROM OB.Last_Sync_omegas WHERE Fuente = 'LEC';

    SET @MinProdDateFloor = DATEADD(DAY, DATEDIFF(DAY, 0, @MinProdDate), 0);

    ;WITH ProduccionMapexNeta AS (
        -- V_His_Prod expone las correcciones como filas independientes (también negativas).
        -- F_HIS_CT en modo DAY las compensa por producto, máquina y día productivo.
        SELECT
            f.Cod_producto,
            REPLACE(f.Cod_maquina, NCHAR(345), NCHAR(114)) AS WorkGroup,
            MIN(f.Fecha_ini) AS Fecha_inicio,
            MAX(f.Fecha_fin) AS Fecha_fin,
            CAST(SUM(CAST(f.Unidades_OK AS BIGINT)) AS INT) AS Unidades_OK
        FROM mapexbp.dbo.V_His_Prod f
        WHERE f.Cod_area = '50 Assembly'
          AND f.Dia_productivo BETWEEN @MinProdDateFloor AND @CurrentTime
        GROUP BY
            f.Cod_producto,
            REPLACE(f.Cod_maquina, NCHAR(345), NCHAR(114)),
            f.Dia_productivo
        HAVING SUM(CAST(f.Unidades_OK AS BIGINT)) > 0
    )
    MERGE OB.Omegas_Produccion AS Target
    USING (
        SELECT
            f.Cod_producto,
            f.WorkGroup,
            f.Fecha_inicio,
            f.Fecha_fin,
            f.Unidades_OK
        FROM ProduccionMapexNeta f
        INNER JOIN OB.Last_Sync_omegas lso
            ON f.Cod_producto = lso.Cod_producto
            AND lso.Fuente = 'PROD'
        WHERE (
            f.Fecha_inicio >= lso.Last_Sync_Date
            OR (
                f.Fecha_fin > lso.Last_Sync_Date
                AND f.Fecha_inicio < lso.Last_Sync_Date
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
        VALUES (Source.Cod_producto, Source.WorkGroup, Source.Fecha_inicio,
                Source.Fecha_fin, Source.Unidades_OK);

    UPDATE lso
    SET Last_Sync_Date = prod.MaxFecha
    FROM OB.Last_Sync_omegas lso
    INNER JOIN (
        SELECT Cod_producto, MAX(Fecha_fin) AS MaxFecha
        FROM OB.Omegas_Produccion
        WHERE Fecha_fin < DATEADD(MINUTE, -1, GETDATE())
        GROUP BY Cod_producto
    ) prod ON lso.Cod_producto = prod.Cod_producto
    WHERE lso.Fuente = 'PROD'
        AND prod.MaxFecha > lso.Last_Sync_Date;

    INSERT INTO OB.Omegas_Lecturas
        (id_his_lectura, producto, numero_serie, id_operario, fecha)
    SELECT
        h.id_his_lectura, h.producto, h.numero_serie,
        h.id_operario, h.fecha
    FROM mapexbp.dbo.his_lectura h
    INNER JOIN OB.Last_Sync_omegas lso
        ON h.producto = lso.Cod_producto
        AND lso.Fuente = 'LEC'
    WHERE h.fecha > lso.Last_Sync_Date
        AND NOT EXISTS (
            SELECT 1 FROM OB.Omegas_Lecturas ol
            WHERE ol.id_his_lectura = h.id_his_lectura
        );

    UPDATE lso
    SET Last_Sync_Date = lec.MaxFecha
    FROM OB.Last_Sync_omegas lso
    INNER JOIN (
        SELECT producto, MAX(fecha) AS MaxFecha
        FROM OB.Omegas_Lecturas
        GROUP BY producto
    ) lec ON lso.Cod_producto = lec.producto
    WHERE lso.Fuente = 'LEC'
        AND lec.MaxFecha > lso.Last_Sync_Date;
END;

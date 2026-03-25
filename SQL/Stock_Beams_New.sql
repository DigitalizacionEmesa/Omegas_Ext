USE [DataLakeSCCZ]
GO

SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO

CREATE OR ALTER VIEW [OB].[Stock_Beams_New]
AS
WITH Entradas AS (
    SELECT Cod_producto, SUM(Unidades_OK) AS TotalEntradas
    FROM OB.Beams_Produccion
    GROUP BY Cod_producto
),
Salidas AS (
    SELECT Cod_producto, SUM(Unidades_OK) AS TotalSalidas
    FROM OB.Beams_Consumos
    GROUP BY Cod_producto
)
SELECT
    b.BeamID,
    b.BeamCode AS Cod_producto,
    ISNULL(e.TotalEntradas, 0) AS Entradas,
    ISNULL(s.TotalSalidas, 0) AS Salidas,
    (ISNULL(e.TotalEntradas, 0) - ISNULL(s.TotalSalidas, 0)) AS StockActual
FROM OB.Beams b
LEFT JOIN Entradas e ON b.BeamCode = e.Cod_producto
LEFT JOIN Salidas s ON b.BeamCode = s.Cod_producto
WHERE b.IsActive = 1;
GO
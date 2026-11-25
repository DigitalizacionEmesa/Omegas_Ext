/*
    REPARACIÓN PUNTUAL DE STOCK ASIGNADO EN PEDIDOS SECUENCIADOS
    ============================================================

    Base de datos: DataLakeSCCZ
    Objetivo:
      1) Refrescar UniValMapex desde la última cabecera/línea de MAPEX.
      2) Recalcular AssignedStock por Assy respetando la secuencia.
      3) Recalcular AssignedStockBeam por Beam respetando la secuencia.
      4) Verificar el caso S0PF56225828 / pedido 44502.

    IMPORTANTE:
      - Parar la aplicación Omegas antes de ejecutar este script, o ejecutar
        inmediatamente después de desplegar el EXE corregido.
      - El script NO elimina pedidos secuenciados.
      - El stock negativo se trata como 0 para la asignación, igual que el
        comportamiento del worker Python.
      - Ejecutar con una cuenta que tenga permisos de lectura en mapexbp y
        escritura en las tablas OB de DataLakeSCCZ.
*/

USE [DataLakeSCCZ];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    PRINT 'Inicio de reparación de AssignedStock: ' + CONVERT(varchar(19), GETDATE(), 120);

    /* ---------------------------------------------------------------
       1. Refrescar UniValMapex desde el último estado de MAPEX.
       --------------------------------------------------------------- */
    UPDATE pl
       SET pl.UniValMapex = mapex.UniValMapex
    FROM OB.PedidosLineas pl
    INNER JOIN OB.PedidosCabecera pc
        ON pc.ID_PedidoCabecera_Externa = pl.ID_PedidoCabecera_Externa
    INNER JOIN (
        SELECT DISTINCT NumeroPedido, Assy
        FROM OB.PedidosSecuenciados
    ) seq
        ON LTRIM(RTRIM(seq.NumeroPedido)) = LTRIM(RTRIM(pc.NumeroPedido))
       AND LTRIM(RTRIM(seq.Assy)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
    CROSS APPLY (
        SELECT TOP 1
            ISNULL(B.UniValMapex, 0) AS UniValMapex
        FROM mapexbp.dbo.his_wam_pedido_cliente A
        INNER JOIN mapexbp.dbo.his_wam_linea_pedido_cliente B
            ON B.id_his_wam_pedido_cliente = A.id_his_wam_pedido_cliente
        INNER JOIN mapexbp.dbo.V_Cfg_producto C
            ON C.Id_producto = B.Id_producto
        WHERE LTRIM(RTRIM(A.NumeroPedido)) = LTRIM(RTRIM(pc.NumeroPedido))
          AND LTRIM(RTRIM(C.Cod_producto)) = LTRIM(RTRIM(pl.Cod_Producto_Externo))
        ORDER BY A.id_his_wam_pedido_cliente DESC
    ) mapex
    WHERE ISNULL(pl.UniValMapex, 0) <> mapex.UniValMapex;

    PRINT 'UniValMapex actualizado: ' + CONVERT(varchar(20), @@ROWCOUNT) + ' líneas.';

    /* ---------------------------------------------------------------
       2. Preparar el cálculo de asignación.

       La prioridad es la misma que en el worker:
         - PriorityOrder informado primero.
         - PriorityOrder ascendente.
         - SequenceValue ascendente.
         - Claves adicionales para desempate determinista.
       --------------------------------------------------------------- */
    ;WITH Base AS (
        SELECT
            ps.NumeroPedido,
            ps.Assy,
            ps.Beam,
            ps.AssignedStock AS AssignedStockAnterior,
            ps.AssignedStockBeam AS AssignedStockBeamAnterior,
            ps.PriorityOrder,
            ps.SequenceValue,
            ISNULL(pl.UnidadesPedidas, 0) AS UnidadesPedidas,
            ISNULL(pl.UniValMapex, 0) AS UniValMapex,
            CASE
                WHEN ISNULL(pl.UnidadesPedidas, 0) - ISNULL(pl.UniValMapex, 0) > 0
                    THEN ISNULL(pl.UnidadesPedidas, 0) - ISNULL(pl.UniValMapex, 0)
                ELSE 0
            END AS CantidadNecesariaAssy,
            CASE
                WHEN ps.Beam IS NOT NULL AND LTRIM(RTRIM(ps.Beam)) <> ''
                    THEN ISNULL(pl.UnidadesPedidas, 0)
                ELSE 0
            END AS CantidadNecesariaBeam,
            CASE
                WHEN ISNULL(so.StockActual, 0) > 0 THEN ISNULL(so.StockActual, 0)
                ELSE 0
            END AS StockAssy,
            CASE
                WHEN ISNULL(sb.StockActual, 0) > 0 THEN ISNULL(sb.StockActual, 0)
                ELSE 0
            END AS StockBeam,
            CASE WHEN ps.PriorityOrder IS NULL THEN 1 ELSE 0 END AS PriorityNull
        FROM OB.PedidosSecuenciados ps
        INNER JOIN OB.PedidosCabecera pc
            ON pc.NumeroPedido = ps.NumeroPedido
        INNER JOIN OB.PedidosLineas pl
            ON pl.ID_PedidoCabecera_Externa = pc.ID_PedidoCabecera_Externa
           AND pl.Cod_Producto_Externo = ps.Assy
        LEFT JOIN OB.Stock_Omegas_New so
            ON LTRIM(RTRIM(so.Cod_producto)) = LTRIM(RTRIM(ps.Assy))
        LEFT JOIN OB.Stock_Beams_New sb
            ON LTRIM(RTRIM(sb.Cod_producto)) = LTRIM(RTRIM(ps.Beam))
        WHERE ISNULL(pl.UniValMapex, 0) < ISNULL(pl.UnidadesPedidas, 0)
    ),
    Ventanas AS (
        SELECT
            b.*,
            SUM(b.CantidadNecesariaAssy) OVER (
                PARTITION BY b.Assy
                ORDER BY b.PriorityNull, b.PriorityOrder, b.SequenceValue,
                         b.NumeroPedido, b.Assy
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS CantidadAnteriorAssy,
            SUM(b.CantidadNecesariaBeam) OVER (
                PARTITION BY b.Beam
                ORDER BY b.PriorityNull, b.PriorityOrder, b.SequenceValue,
                         b.NumeroPedido, b.Assy
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS CantidadAnteriorBeam
        FROM Base b
    )
    SELECT
        v.NumeroPedido,
        v.Assy,
        CAST(CASE
            WHEN v.CantidadNecesariaAssy <= 0 THEN 0
            WHEN v.StockAssy - ISNULL(v.CantidadAnteriorAssy, 0) <= 0 THEN 0
            WHEN v.CantidadNecesariaAssy < v.StockAssy - ISNULL(v.CantidadAnteriorAssy, 0)
                THEN v.CantidadNecesariaAssy
            ELSE v.StockAssy - ISNULL(v.CantidadAnteriorAssy, 0)
        END AS int) AS AssignedStock,
        CAST(CASE
            WHEN v.CantidadNecesariaBeam <= 0 THEN 0
            WHEN v.StockBeam - ISNULL(v.CantidadAnteriorBeam, 0) <= 0 THEN 0
            WHEN v.CantidadNecesariaBeam < v.StockBeam - ISNULL(v.CantidadAnteriorBeam, 0)
                THEN v.CantidadNecesariaBeam
            ELSE v.StockBeam - ISNULL(v.CantidadAnteriorBeam, 0)
        END AS int) AS AssignedStockBeam
    INTO #Allocation
    FROM Ventanas v;

    CREATE INDEX IX_Allocation_OrderAssy
        ON #Allocation (NumeroPedido, Assy);

    /* ---------------------------------------------------------------
       3. Resetear y aplicar el cálculo completo.
       --------------------------------------------------------------- */
    UPDATE OB.PedidosSecuenciados
       SET AssignedStock = 0,
           AssignedStockBeam = 0;

    UPDATE ps
       SET ps.AssignedStock = a.AssignedStock,
           ps.AssignedStockBeam = a.AssignedStockBeam
    FROM OB.PedidosSecuenciados ps
    INNER JOIN #Allocation a
        ON a.NumeroPedido = ps.NumeroPedido
       AND a.Assy = ps.Assy;

    PRINT 'Pedidos secuenciados actualizados: ' + CONVERT(varchar(20), @@ROWCOUNT) + ' líneas.';

    /* ---------------------------------------------------------------
       4. Verificación dentro de la transacción.
       --------------------------------------------------------------- */
    SELECT
        COUNT(*) AS TotalLineasSecuenciadas,
        SUM(CASE WHEN ISNULL(AssignedStock, 0) > 0 THEN 1 ELSE 0 END) AS LineasConAssignedStock,
        SUM(ISNULL(AssignedStock, 0)) AS TotalAssignedStock,
        SUM(CASE WHEN ISNULL(AssignedStockBeam, 0) > 0 THEN 1 ELSE 0 END) AS LineasConAssignedStockBeam,
        SUM(ISNULL(AssignedStockBeam, 0)) AS TotalAssignedStockBeam
    FROM OB.PedidosSecuenciados;

    SELECT
        NumeroPedido,
        Assy,
        Beam,
        SequenceValue,
        UnidadesPedidas,
        UniValMapex,
        AssignedStock,
        AssignedStockBeam
    FROM OB.V_PedidosSummary_Secuenciados
    WHERE Assy = 'S0PF56225828'
      AND NumeroPedido IN ('44502', '44312', '43741', '43851', '44551')
    ORDER BY Sequence;

    COMMIT TRANSACTION;
    PRINT 'Reparación confirmada: ' + CONVERT(varchar(19), GETDATE(), 120);
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;

    PRINT 'ERROR. Se ha hecho ROLLBACK: ' + ERROR_MESSAGE();
    THROW;
END CATCH;
GO

/* Verificación posterior a la confirmación */
SELECT
    COUNT(*) AS PickingDisponibles
FROM OB.V_PedidosSummary_Secuenciados
WHERE UPPER(LTRIM(RTRIM(Picking))) = 'YES';

SELECT
    Cod_producto,
    Entradas,
    Salidas,
    StockActual
FROM OB.Stock_Omegas_New
WHERE Cod_producto = 'S0PF56225828';
GO

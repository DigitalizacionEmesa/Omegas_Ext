USE [DataLakeSCCZ];
GO

/*
Objetivo:
- Reducir el tiempo de carga de /api/pedidos_secuenciados_c
- Reducir el tiempo de carga de /api/pedidos_secuenciados_w
- Mejorar joins y búsquedas de la lógica de extensores sin quitar ningún campo

Tablas afectadas:
- OB.PedidosCabecera
- OB.pedidos_exportados
- OB.Omegas
- OB.PedidosLineas

Notas:
- Todos los CREATE INDEX llevan IF NOT EXISTS para que el script sea reejecutable.
- Ejecutar idealmente fuera de picos de uso.
- Si el volumen es alto, crear primero los 4 primeros índices y medir antes de crear el quinto.
*/

SET NOCOUNT ON;
GO

/*
1. Join principal de la vista wrapper:
   OB.V_PedidosSummary_Secuenciados_Full
   LEFT JOIN OB.PedidosCabecera pc ON pc.NumeroPedido = ps.NumeroPedido
*/
IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_OB_PedidosCabecera_NumeroPedido'
      AND object_id = OBJECT_ID('OB.PedidosCabecera')
)
BEGIN
    CREATE NONCLUSTERED INDEX IX_OB_PedidosCabecera_NumeroPedido
    ON OB.PedidosCabecera (NumeroPedido)
    INCLUDE (ID_PedidoCabecera_Externa, CWT, DS, EX, TB, CWI);
END
GO

/*
2. Lookup principal de características por pedido para extensores:
   sales_document + characteristic_name.
   characteristic_value es nvarchar(max), así que no puede usarse como key column.
   Se deja como INCLUDE para cubrir la lectura.
*/
IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_OB_pedidos_exportados_sales_char'
      AND object_id = OBJECT_ID('OB.pedidos_exportados')
)
BEGIN
    CREATE NONCLUSTERED INDEX IX_OB_pedidos_exportados_sales_char
    ON OB.pedidos_exportados (sales_document, characteristic_name)
    INCLUDE (characteristic_value);
END
GO

/*
3. Match de TSD -> ExtenderVariable en OB.Omegas
*/
IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_OB_Omegas_ExtenderVariable'
      AND object_id = OBJECT_ID('OB.Omegas')
)
BEGIN
    CREATE NONCLUSTERED INDEX IX_OB_Omegas_ExtenderVariable
    ON OB.Omegas (ExtenderVariable)
    INCLUDE (Assy, OmegaType, Beam, [W/C], IF1, IF2);
END
GO

/*
4. Match de HEAD/TRAV -> OmegaType en OB.Omegas
*/
IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_OB_Omegas_OmegaType'
      AND object_id = OBJECT_ID('OB.Omegas')
)
BEGIN
    CREATE NONCLUSTERED INDEX IX_OB_Omegas_OmegaType
    ON OB.Omegas (OmegaType)
    INCLUDE (Assy, ExtenderVariable, Beam, [W/C], IF1, IF2);
END
GO

/*
5. Ayuda a la vista base que agrupa PedidosCabecera + PedidosLineas + Omegas
   y agrupa por ID_PedidoCabecera_Externa / Cod_Producto_Externo.
*/
IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_OB_PedidosLineas_Cabecera_CodProducto'
      AND object_id = OBJECT_ID('OB.PedidosLineas')
)
BEGIN
    CREATE NONCLUSTERED INDEX IX_OB_PedidosLineas_Cabecera_CodProducto
    ON OB.PedidosLineas (ID_PedidoCabecera_Externa, Cod_Producto_Externo)
    INCLUDE (UnidadesPedidas, UniValMapex);
END
GO

/*
6. Refuerzo opcional para joins con PedidosSecuenciados por NumeroPedido.
   La PK actual es (NumeroPedido, Assy), así que normalmente ya cubre este acceso.
   Se deja comentado por si en medición posterior hiciera falta.
*/
-- IF NOT EXISTS (
--     SELECT 1
--     FROM sys.indexes
--     WHERE name = 'IX_OB_PedidosSecuenciados_NumeroPedido'
--       AND object_id = OBJECT_ID('OB.PedidosSecuenciados')
-- )
-- BEGIN
--     CREATE NONCLUSTERED INDEX IX_OB_PedidosSecuenciados_NumeroPedido
--     ON OB.PedidosSecuenciados (NumeroPedido)
--     INCLUDE (Assy, PriorityOrder, SequenceValue, OFs, AssignedStock, AssignedStockBeam);
-- END
-- GO

/*
7. Actualizar estadísticas para que el optimizador use los nuevos índices.
*/
UPDATE STATISTICS OB.PedidosCabecera WITH FULLSCAN;
UPDATE STATISTICS OB.pedidos_exportados WITH FULLSCAN;
UPDATE STATISTICS OB.Omegas WITH FULLSCAN;
UPDATE STATISTICS OB.PedidosLineas WITH FULLSCAN;
UPDATE STATISTICS OB.PedidosSecuenciados WITH FULLSCAN;
GO

/*
8. Verificación rápida: índices creados.
*/
SELECT
    OBJECT_NAME(i.object_id) AS TableName,
    i.name AS IndexName,
    i.type_desc AS IndexType
FROM sys.indexes i
WHERE i.object_id IN (
    OBJECT_ID('OB.PedidosCabecera'),
    OBJECT_ID('OB.pedidos_exportados'),
    OBJECT_ID('OB.Omegas'),
    OBJECT_ID('OB.PedidosLineas')
)
  AND i.name IN (
    'IX_OB_PedidosCabecera_NumeroPedido',
        'IX_OB_pedidos_exportados_sales_char',
    'IX_OB_Omegas_ExtenderVariable',
    'IX_OB_Omegas_OmegaType',
    'IX_OB_PedidosLineas_Cabecera_CodProducto'
)
ORDER BY TableName, IndexName;
GO

/*
9. Medición manual sugerida después de ejecutar:
- Reiniciar appOMEGAS
- Cargar una vez OB_C y OB_W
- Revisar logs/view_diagnostics.log
- Comparar líneas DB: x.xxxs | MAPEX: x.xxxs antes y después
*/

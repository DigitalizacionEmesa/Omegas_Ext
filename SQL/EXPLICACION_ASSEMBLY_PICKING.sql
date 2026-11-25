-- ============================================================================
-- SCRIPT EXPLICATIVO: ¿Por qué una orden NO aparece en el secuenciador ni en Picking?
-- Base de datos : DataLakeSCCZ (esquema OB)
-- Vista clave   : OB.V_PedidosSummary_Secuenciados
-- ----------------------------------------------------------------------------
-- Este script explica, con datos reales, la lógica de las dos "banderas":
--     1) Assembly  -> decide si la orden sale en el secuenciador C/W (ES1)
--     2) Picking   -> decide si la orden sale en la pantalla de Picking
-- ============================================================================


-- ============================================================================
-- 1) CONCEPTOS PREVIOS (los 3 números que usa el sistema para cada línea)
-- ============================================================================
--   UnidadesPedidas  : cuántas unidades se pidieron
--   UniValMapex      : cuántas dice SAP/MAPEX que YA están producidas
--   AssignedStock    : stock que ya está reservado para cubrir lo que falta
--
-- Con estos 3 números se calculan Assembly y Picking.


-- ============================================================================
-- 2) LA REGLA DE "ASSEMBLY" (secuenciador ES1)
-- ============================================================================
--   Assembly = 'Yes C' o 'Yes W'   cuando TODAVÍA falta fabricar:
--
--       (UnidadesPedidas - UniValMapex) > AssignedStock
--
--   Si no falta nada por fabricar -> Assembly = 'No'  (se oculta del secuenciador)
-- ============================================================================


-- ============================================================================
-- 3) LA REGLA DE "PICKING" (en 3 pasos, EN ESTE ORDEN)
-- ============================================================================
--   PASO A) Si UnidadesPedidas = UniValMapex
--             -> Picking = 'No'   (orden "completada del todo": NO sale en nada)
--
--   PASO B) Si NO hay ninguna línea en Assembly
--           Y  UnidadesPedidas = UniValMapex + AssignedStock
--             -> Picking = 'Yes'  (no hay que ensamblar, solo recoger el material)
--
--   PASO C) Cualquier otro caso
--             -> Picking = 'No'   (todavía está en el secuenciador)
-- ============================================================================


-- ============================================================================
-- 4) CASO REAL: la orden 40951 (la que NO aparece en el secuenciador ES1)
-- ============================================================================
-- Se ven sus líneas y las banderas YA calculadas por la vista:
SELECT
    NumeroPedido,
    Assy,
    [C/W],
    UnidadesPedidas          AS Pedidas,
    UniValMapex              AS Producidas,
    AssignedStock            AS StockAsignado,
    Assembly,
    Picking
FROM OB.V_PedidosSummary_Secuenciados WITH (NOLOCK)
WHERE NumeroPedido = '40951';

-- Resultado esperado:
--   Pedidas = Producidas (5=5 y 3=3) -> Picking = 'No' y Assembly = 'No'
--   Por eso NO sale ni en el secuenciador ni en Picking.


-- ============================================================================
-- 5) MISMO CASO PERO CALCULADO "A MANO" (para ver POR QUÉ da 'No')
-- ============================================================================
SELECT
    NumeroPedido,
    Assy,
    [C/W],
    UnidadesPedidas                       AS Pedidas,
    UniValMapex                           AS Producidas,
    AssignedStock                         AS StockAsignado,
    UnidadesPedidas - UniValMapex         AS Restante_Por_Producir,

    -- -------- Replicación manual de ASSEMBLY --------
    CASE
        WHEN (UnidadesPedidas - UniValMapex) > AssignedStock
            THEN 'Yes ' + [C/W]            -- aún falta ensamblar
        ELSE 'No'                          -- no falta nada -> se oculta
    END                                    AS Assembly_Calculado,

    -- -------- Replicación manual de PICKING (los 3 pasos) --------
    CASE
        WHEN UnidadesPedidas = UniValMapex
            THEN 'No - COMPLETADA (paso A)'           -- 100% producida
        WHEN (UnidadesPedidas - UniValMapex) <= AssignedStock
         AND UnidadesPedidas = UniValMapex + AssignedStock
            THEN 'Yes - LISTA PARA RECOGER (paso B)'
        ELSE 'No - SIGUE EN ASSEMBLY (paso C)'
    END                                    AS Picking_Calculado

FROM OB.V_PedidosSummary_Secuenciados WITH (NOLOCK)
WHERE NumeroPedido = '40951';


-- ============================================================================
-- 6) EJEMPLOS DE ÓRDENES QUE SÍ SALEN EN PICKING (Picking = 'Yes')
-- ============================================================================
-- Fíjate: Producidas = 0, pero el StockAsignado cubre TODO lo pedido.
-- Es decir: no hay que ensamblar, solo recoger material.
SELECT TOP 10
    NumeroPedido,
    Assy,
    [C/W],
    UnidadesPedidas   AS Pedidas,
    UniValMapex       AS Producidas,
    AssignedStock     AS StockAsignado,
    Assembly,
    Picking
FROM OB.V_PedidosSummary_Secuenciados WITH (NOLOCK)
WHERE UPPER(LTRIM(RTRIM(Picking))) = 'YES'
ORDER BY Sequence ASC;


-- ============================================================================
-- 7) EJEMPLOS DE ÓRDENES QUE SÍ SALEN EN EL SECUENCIADOR (Assembly = Yes C/W)
-- ============================================================================
-- Fíjate: falta por fabricar más de lo que cubre el stock asignado.
SELECT TOP 10
    NumeroPedido,
    Assy,
    [C/W],
    UnidadesPedidas   AS Pedidas,
    UniValMapex       AS Producidas,
    AssignedStock     AS StockAsignado,
    Assembly,
    Picking
FROM OB.V_PedidosSummary_Secuenciados WITH (NOLOCK)
WHERE UPPER(LTRIM(RTRIM(Assembly))) IN ('YES C', 'YES W')
ORDER BY Sequence ASC;


-- ============================================================================
-- 8) RESUMEN: cuántas hay en cada estado HOY
-- ============================================================================
SELECT
    SUM(CASE WHEN UPPER(LTRIM(RTRIM(Assembly))) IN ('YES C','YES W') THEN 1 ELSE 0 END) AS En_Assembly_Secuenciador,
    SUM(CASE WHEN UPPER(LTRIM(RTRIM(Picking)))   = 'YES'                THEN 1 ELSE 0 END) AS En_Picking,
    SUM(CASE WHEN UPPER(LTRIM(RTRIM(Assembly)))  = 'NO'
             AND UPPER(LTRIM(RTRIM(Picking)))    = 'NO'                 THEN 1 ELSE 0 END) AS Completadas_Ocultas
FROM OB.V_PedidosSummary_Secuenciados WITH (NOLOCK);


-- ============================================================================
-- 9) AVISO IMPORTANTE: qué pasaría si se QUITA la regla del paso A
-- ============================================================================
-- Las órdenes "completadas" (producidas al 100%) se quedan acumuladas en la
-- tabla OB.PedidosSecuenciados aunque estén ocultas. Si se quitara la regla
-- "Pedidas = Producidas -> ocultar", aparecerían TODAS estas de golpe:
SELECT
    COUNT(*)                                             AS Lineas_Completadas,
    MIN(ps.FechaSecuenciacion)                           AS Completada_Mas_Antigua,
    MAX(ps.FechaSecuenciacion)                           AS Completada_Mas_Reciente
FROM OB.PedidosSecuenciados ps WITH (NOLOCK)
INNER JOIN OB.V_PedidosSummary_Secuenciados v WITH (NOLOCK)
    ON v.NumeroPedido = ps.NumeroPedido
   AND v.Assy         = ps.Assy
WHERE v.UnidadesPedidas = v.UniValMapex
  AND UPPER(LTRIM(RTRIM(v.Assembly))) = 'NO';

-- Conclusión:
--   NO conviene quitar la regla sin más, porque reaparecerían cientos/miles de
--   órdenes ya terminadas. La solución correcta es decidir CUÁNDO debe
--   desaparecer una orden (p.ej. un botón de "recogido" en Picking) y borrarla
--   de OB.PedidosSecuenciados en ese momento.

-- ============================================================================
-- FIN DEL SCRIPT
-- ============================================================================

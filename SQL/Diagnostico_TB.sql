-- ============================================================================
-- DIAGNÓSTICO TB: Verificar por qué TB no funciona correctamente
-- ============================================================================
-- Ejecutar paso a paso en DataLakeSCCZ para entender el flujo

-- PASO 1: Verificar que OB.Omegas tiene registros con W/C='TB'
-- ============================================================================
PRINT '=== PASO 1: Verificar W/C=TB en OB.Omegas ==='
SELECT COUNT(*) as CantidadTB
FROM [OB].[Omegas]
WHERE LTRIM(RTRIM([W/C])) = 'TB'

-- Mostrar ejemplos
SELECT TOP 5 
	Assy, 
	[W/C], 
	ExtenderVariable,
	DATALENGTH(Assy) as LenAssy,
	DATALENGTH([W/C]) as LenWC
FROM [OB].[Omegas]
WHERE LTRIM(RTRIM([W/C])) = 'TB'

-- ============================================================================
-- PASO 2: Verificar PedidosCabecera.TB está poblado
-- ============================================================================
PRINT '=== PASO 2: Verificar TB en PedidosCabecera ==='
SELECT COUNT(*) as CantidadConTB
FROM [OB].[PedidosCabecera]
WHERE TB IS NOT NULL AND TB != ''

SELECT TOP 10
	NumeroPedido,
	EX,
	TB,
	DATALENGTH(TB) as TBLength
FROM [OB].[PedidosCabecera]
WHERE TB IS NOT NULL AND TB != ''

-- ============================================================================
-- PASO 3: Comparar ausencia de TB vs presencia de EX
-- ============================================================================
PRINT '=== PASO 3: Comparar EX vs TB ==='
SELECT 
	COUNT(CASE WHEN EX IS NOT NULL AND EX != '' THEN 1 END) as PedidosConEX,
	COUNT(CASE WHEN TB IS NOT NULL AND TB != '' THEN 1 END) as PedidosConTB,
	COUNT(*) as TotalPedidos
FROM [OB].[PedidosCabecera]

-- ============================================================================
-- PASO 4: Verificar si TB viene NULL o está vacío
-- ============================================================================
PRINT '=== PASO 4: Análisis NULL vs vacío ==='
SELECT 
	NumeroPedido,
	EX,
	TB,
	CASE WHEN TB IS NULL THEN 'NULL'
		 WHEN TB = '' THEN 'Vacío'
		 WHEN TB IS NOT NULL THEN 'Con valor: ' + TB
	END as EstadoTB
FROM [OB].[PedidosCabecera]
WHERE NumeroPedido IN (
	SELECT TOP 20 NumeroPedido FROM [OB].[PedidosCabecera] ORDER BY ID_PedidoCabecera DESC
)

-- ============================================================================
-- PASO 5: Verificar Sequenced_Omegas hereda TB desde PedidosCabecera
-- ============================================================================
PRINT '=== PASO 5: Heredanza en secuenciados ==='
SELECT TOP 10
	ps.NumeroPedido,
	ps.TB as TB_FromVista,
	pc.TB as TB_FromPedidosCabecera,
	CASE WHEN ps.TB = pc.TB THEN 'OK' ELSE 'MISMATCH' END as Estado
FROM OB.V_PedidosSummary_Secuenciados ps
LEFT JOIN OB.PedidosCabecera pc ON ps.NumeroPedido = pc.NumeroPedido
WHERE ps.TB IS NOT NULL OR pc.TB IS NOT NULL

-- ============================================================================
-- PASO 6: Buscar un pedido de prueba que tenga TB en OB.Omegas
-- ============================================================================
PRINT '=== PASO 6: Encontrar pedidos procesables ==='
SELECT TOP 5
	Assy,
	[W/C]
FROM [OB].[Omegas]
WHERE LTRIM(RTRIM([W/C])) = 'TB'

-- Para probar export, este Assy debería venir en Excel
-- y cuando lo proceses, debería asignarse a PedidosCabecera.TB

-- ============================================================================
-- PASO 7: Revisar si V_PedidosSummary_Secuenciados_Full trae TB
-- ============================================================================
PRINT '=== PASO 7: Contenido de vista wrapper Full ==='
SELECT TOP 1 *
FROM OB.V_PedidosSummary_Secuenciados_Full
WHERE TB IS NOT NULL OR TB != ''

-- ============================================================================
-- RESUMEN ESPERADO:
-- ============================================================================
-- ✅ Si PASO 1 muestra > 0: W/C='TB' existe en OB.Omegas
-- ✅ Si PASO 2 muestra > 0: TB se está guardando en PedidosCabecera
-- ✅ Si PASO 3 muestra balance similar EX/TB: Ambos se procesan igual
-- ✅ Si PASO 4 muestra valores: TB tiene datos, no NULL
-- ✅ Si PASO 5 muestra OK: Vista hereda TB correctamente
-- ✅ Si PASO 6 muestra resultados: Hay TB en catálogo
-- ✅ Si PASO 7 muestra resultados: Vista wrapper incluye TB

-- Envía resultados de estos PASOS para diagnosticar dónde está el cuello de botella

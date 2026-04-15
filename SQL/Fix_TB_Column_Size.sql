-- ============================================================================
-- DIAGNÓSTICO Y FIX DE TAMAÑO DE COLUMNA TB
-- ============================================================================

-- PASO 1: Verificar tamaño actual de EX y TB
-- ============================================================================
PRINT '=== PASO 1: Verificar definición de columnas en PedidosCabecera ==='

SELECT 
	COLUMN_NAME,
	DATA_TYPE,
	CHARACTER_MAXIMUM_LENGTH,
	IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'OB' 
	AND TABLE_NAME = 'PedidosCabecera'
	AND COLUMN_NAME IN ('EX', 'TB')
ORDER BY COLUMN_NAME

-- PASO 2: Verificar tamaño de Assy en OB.Omegas
-- ============================================================================
PRINT '=== PASO 2: Verificar definición de columnas en OB.Omegas ==='

SELECT 
	COLUMN_NAME,
	DATA_TYPE,
	CHARACTER_MAXIMUM_LENGTH
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'OB' 
	AND TABLE_NAME = 'Omegas'
	AND COLUMN_NAME = 'Assy'

-- PASO 3: Ver máximas longitudes en datos reales
-- ============================================================================
PRINT '=== PASO 3: Máximas longitudes en datos ==='

SELECT 
	MAX(DATALENGTH(EX)) as MaxLenEX,
	MAX(DATALENGTH(TB)) as MaxLenTB
FROM [OB].[PedidosCabecera]

SELECT 
	MAX(DATALENGTH(Assy)) as MaxLenAssy
FROM [OB].[Omegas]

-- PASO 4: FIX - Aumentar tamaño de TB si es necesario
-- ============================================================================
-- Descomenta este bloque si necesitas aumentar TB a VARCHAR(20) como EX

/*
PRINT '=== PASO 4: Aumentando tamaño de TB ==='

ALTER TABLE [OB].[PedidosCabecera]
ALTER COLUMN TB VARCHAR(20) NULL

PRINT 'TB aumentado a VARCHAR(20)'
*/

-- PASO 5: Verificar que ambas columnas tengan el mismo tamaño
-- ============================================================================
PRINT '=== PASO 5: Verificar tamaños después del fix ==='

SELECT 
	COLUMN_NAME,
	DATA_TYPE,
	CHARACTER_MAXIMUM_LENGTH
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'OB' 
	AND TABLE_NAME = 'PedidosCabecera'
	AND COLUMN_NAME IN ('EX', 'TB')
ORDER BY COLUMN_NAME

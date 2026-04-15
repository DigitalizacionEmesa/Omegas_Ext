-- ====================================================================================
-- BÚSQUEDA DE CAMPOS GRP_* EN MAPEXBP
-- Archivo para encontrar dónde están: GRP_HSK_TYPE, GRP_NUM_OMEGA, GRP_OMEGA_BRACKET_TYPE_TSD
-- ====================================================================================
-- INSTRUCCIONES:
-- 1. Abre SQL Server Management Studio
-- 2. Conecta a MAPEXBP (172.16.10.10)
-- 3. Abre este archivo
-- 4. Selecciona CADA SCRIPT y ejecuta con F5
-- 5. Pasa los resultados al développeur
-- ====================================================================================

-- ===== SCRIPT 1: VER TODAS LAS TABLAS EN MAPEXBP =====
-- Ejecutar primero para ver qué tablas existen
-- Busca nombres que contengan: carac, material, atrib, variable, producto
-- ====================================================================================
USE mapexbp;
SELECT 
    TABLE_SCHEMA,
    TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_SCHEMA, TABLE_NAME;

-- ===== SCRIPT 2: BÚSQUEDA CRÍTICA - COLUMNAS "GRP_*" =====
-- ESTE ES EL MÁS IMPORTANTE
-- Ejecutar para encontrar exactamente dónde están los campos GRP_*
-- ====================================================================================
USE mapexbp;
SELECT 
    TABLE_SCHEMA,
    TABLE_NAME,
    COLUMN_NAME,
    DATA_TYPE,
    CHARACTER_MAXIMUM_LENGTH,
    IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE COLUMN_NAME LIKE '%GRP%'
   OR COLUMN_NAME LIKE '%HSK%'
   OR COLUMN_NAME LIKE '%OMEGA%'
   OR COLUMN_NAME LIKE '%BRACKET%'
ORDER BY TABLE_NAME, ORDINAL_POSITION;

-- ===== SCRIPT 3: COLUMNAS DE HIS_WAM_LINEA_PEDIDO_CLIENTE =====
-- Ver qué columnas tiene esta tabla
-- ¿Tiene ya los campos GRP_* o están en otra tabla?
-- ====================================================================================
USE mapexbp;
SELECT 
    ORDINAL_POSITION,
    COLUMN_NAME,
    DATA_TYPE,
    CHARACTER_MAXIMUM_LENGTH,
    IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'his_wam_linea_pedido_cliente'
ORDER BY ORDINAL_POSITION;

-- ===== SCRIPT 4: BUSCAR TABLAS DE CARACTERÍSTICAS/MATERIAL =====
-- Busca tablas con nombres relacionados a características o material
-- ====================================================================================
USE mapexbp;
SELECT 
    TABLE_SCHEMA,
    TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE = 'BASE TABLE'
  AND (
    TABLE_NAME LIKE '%carac%'
    OR TABLE_NAME LIKE '%CARAC%'
    OR TABLE_NAME LIKE '%atrib%'
    OR TABLE_NAME LIKE '%ATRIB%'
    OR TABLE_NAME LIKE '%material%'
    OR TABLE_NAME LIKE '%MATERIAL%'
    OR TABLE_NAME LIKE '%variable%'
    OR TABLE_NAME LIKE '%VARIABLE%'
    OR TABLE_NAME LIKE '%caracteristic%'
    OR TABLE_NAME LIKE '%CARACTERISTIC%'
  )
ORDER BY TABLE_NAME;

-- ===== SCRIPT 5: BUSCAR "Id_producto" EN TODAS LAS TABLAS =====
-- Encontrar cuáles tablas tienen Id_producto (para hacer JOINs)
-- ====================================================================================
USE mapexbp;
SELECT 
    TABLE_SCHEMA,
    TABLE_NAME,
    COLUMN_NAME
FROM INFORMATION_SCHEMA.COLUMNS
WHERE COLUMN_NAME IN ('Id_producto', 'ID_PRODUCTO', 'Id_Producto', 'IDPRODUCTO', 'IdProducto', 'id_producto')
ORDER BY TABLE_NAME;

-- ===== SCRIPT 6: VER PRIMEROS REGISTROS DE HIS_WAM_LINEA_PEDIDO_CLIENTE =====
-- Para ver cómo se ve el data
-- ====================================================================================
USE mapexbp;
SELECT TOP 5 * 
FROM his_wam_linea_pedido_cliente;

-- ===== SCRIPT 7: SI ENCONTRASTE UNA TABLA, EXPLORA SUS COLUMNAS =====
-- Cambia "XXX" por el nombre de la tabla que encontraste con GRP_*
-- Ejemplo: SELECT * FROM carac_producto LIMIT 5
-- ====================================================================================
-- USE mapexbp;
-- SELECT TOP 5 * 
-- FROM [NOMBRE_TABLA_QUE_ENCONTRASTE];

-- ===== SCRIPT 8: INTENTA UN JOIN MANUAL SI ENCONTRASTE LA TABLA =====
-- Cambia "XXX" por la tabla y sus columnas
-- Esto es para probar si puedes unir el data correctamente
-- ====================================================================================
-- USE mapexbp;
-- SELECT 
--     L.id_his_wam_linea_pedido_cliente,
--     L.Id_producto,
--     XXX.GRP_HSK_TYPE,
--     XXX.GRP_NUM_OMEGA,
--     XXX.GRP_OMEGA_BRACKET_TYPE_TSD
-- FROM his_wam_linea_pedido_cliente L
-- LEFT JOIN [TABLA_GRP] XXX ON XXX.Id_producto = L.Id_producto
-- LIMIT 10;

-- ====================================================================================
-- PASOS A SEGUIR:
-- 1. Ejecuta SCRIPT 1 → Anota los nombres de tablas que ves
-- 2. Ejecuta SCRIPT 2 → Si da resultados, dime la tabla y columnas
-- 3. Ejecuta SCRIPT 4 → Busca tablas con nombres de características
-- 4. Ejecuta SCRIPT 5 → Para encontrar cuáles tienen Id_producto
-- 5. Si encuentras la tabla, descomenta SCRIPT 7 y 8 y modifica
-- ====================================================================================

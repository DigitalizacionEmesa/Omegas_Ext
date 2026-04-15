-- ====================================================================================
-- DIAGNÓSTICO: Por qué el pedido 28614 (NumeroPedido 34039) no aparece en la app
-- ====================================================================================

-- 1. Ver la definición completa de la vista
EXEC sp_helptext 'OB.V_PedidosSummary_Pendientes'

-- ====================================================================================

-- 2a. Ver columnas reales de OB.PedidosLineas
SELECT COLUMN_NAME, DATA_TYPE 
FROM INFORMATION_SCHEMA.COLUMNS 
WHERE TABLE_SCHEMA = 'OB' AND TABLE_NAME = 'PedidosLineas'
ORDER BY ORDINAL_POSITION

-- 2b. Ver líneas del pedido con JOIN a OB.Omegas (columnas reales)
SELECT 
    L.ID_PedidoLinea_Externa,
    L.Cod_Producto_Externo,
    L.UnidadesPedidas,
    L.UniValMapex,
    L.Beam,
    L.WC,
    O.Assy,
    O.[W/C]  AS WC_Omegas,
    O.Beam   AS Beam_Omegas,
    O.IF1,
    O.IF2
FROM OB.PedidosLineas L
LEFT JOIN OB.Omegas O ON O.Assy = L.Cod_Producto_Externo
WHERE L.ID_PedidoCabecera_Externa = 28614

-- ====================================================================================

-- 3. Ver qué Bsark tienen los pedidos que SÍ aparecen en la vista
SELECT DISTINCT Bsark FROM OB.V_PedidosSummary_Pendientes

-- ====================================================================================

-- 4. Comprobar si el pedido está en PedidosCabecera con todos sus campos
SELECT * FROM OB.PedidosCabecera 
WHERE ID_PedidoCabecera_Externa = 28614

-- ====================================================================================

-- 5. Simular el JOIN que hace la vista con los nombres reales de columna
SELECT 
    C.NumeroPedido,
    C.Bsark,
    C.CWT,
    C.DS,
    COUNT(L.ID_PedidoLinea_Externa)                              AS TotalLineas,
    SUM(CASE WHEN O.Assy IS NOT NULL THEN 1 ELSE 0 END)          AS LineasConOmega,
    SUM(CASE WHEN O.Assy IS NULL     THEN 1 ELSE 0 END)          AS LineasSinOmega
FROM OB.PedidosCabecera C
LEFT JOIN OB.PedidosLineas L ON L.ID_PedidoCabecera_Externa = C.ID_PedidoCabecera_Externa
LEFT JOIN OB.Omegas O        ON O.Assy = L.Cod_Producto_Externo
WHERE C.ID_PedidoCabecera_Externa = 28614
GROUP BY C.NumeroPedido, C.Bsark, C.CWT, C.DS

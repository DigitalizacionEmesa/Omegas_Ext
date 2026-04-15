# TB (Tie Bracket) - Líneas Exactas de Código

## 1. ASIGNACIÓN Y ACTUALIZACIÓN DE TB

### Línea 382: Inicialización de variables
```python
cwt, ds, ex, tb = None, None, None, None
```

### Líneas 395-396: DETECCIÓN Y ASIGNACIÓN DE TB
```python
elif wc_type == 'TB' and not tb:
    tb = linea['Cod_producto']
```

### Línea 426: INSERT en PedidosCabecera
```python
sql_cabecera = "INSERT INTO OB.PedidosCabecera (ID_PedidoCabecera_Externa, NumeroPedido, FechaEntrega, Bsark, EstadoERP, Id_wam_estado_pedido_cliente, CWT, DS, EX, TB) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);"
```

---

## 2. MODIFICACIÓN DE V_PedidosSummary_Secuenciados_Full

### Línea 1068: Comentario sobre inclusión de EX y TB
```python
# Usar la vista wrapper que ya incluye EX y TB
```

### Línea 1071: SELECT de la vista
```python
FROM OB.V_PedidosSummary_Secuenciados_Full
```

---

## 3. ENDPOINTS QUE ACTUALIZAN TB/EX

### Línea 1122-1131: Endpoint `/api/sequence/reorder-batch` - UPDATE PedidosSecuenciados
```python
UPDATE OB.PedidosSecuenciados 
SET PriorityOrder = ? 
WHERE NumeroPedido IN (?)
```

**Nota:** Este endpoint NO actualiza TB directamente, pero reordena los pedidos secuenciados que pueden tener TB.

---

## 4. CÓMO SE DETECTA SI UN PEDIDO TIENE TB

### Línea 1724: Filtro en endpoint `/api/pedidos_tb`
```sql
WHERE ps.TB IS NOT NULL AND LTRIM(RTRIM(ps.TB)) != ''
```

### Línea 1721: Query completa de /api/pedidos_tb
```sql
SELECT 
    ps.Sequence AS Sequence,
    ps.NumeroPedido AS SalesOrder,
    ps.UnidadesPedidas AS Qty,
    ps.Assy AS Assy,
    ISNULL(ps.TB, '') AS TieBracket,
    ISNULL(ps.EX, '') AS Extender,
    ps.PriorityOrder,
    CASE 
        WHEN ps.EX IS NOT NULL AND LTRIM(RTRIM(ps.EX)) != ''
        THEN ps.UnidadesPedidas - 2
        ELSE NULL
    END AS ExtenderQuantity
FROM OB.V_PedidosSummary_Secuenciados_Full ps
WHERE ps.TB IS NOT NULL AND LTRIM(RTRIM(ps.TB)) != ''
ORDER BY 
    CASE WHEN ps.PriorityOrder IS NULL THEN 1 ELSE 0 END,
    ps.PriorityOrder ASC,
    ps.Sequence ASC
```

---

## 5. ESTRUCTURA DE PedidosSecuenciados Y CÓMO HEREDA TB

### Línea 492-510: Estructura de PedidosSecuenciados
La tabla `PedidosSecuenciados` NO contiene TB directamente. Se obtiene a través de JOIN con PedidosCabecera:

```sql
FROM OB.PedidosSecuenciados ps
INNER JOIN OB.PedidosCabecera pc ON ps.NumeroPedido = pc.NumeroPedido
```

**Columnas en PedidosSecuenciados:**
- NumeroPedido
- Assy
- Beam
- AssignedStock
- AssignedStockBeam
- SequenceValue
- PriorityOrder

**TB viene de: OB.PedidosCabecera.TB** (heredado en la vista)

---

## 6. TABLA PedidosCabecera - DEFINICIÓN Y ESQUEMA

### Línea 2-39: Script de creación de columna TB (SQL/ADD_TB_COLUMN.sql)
```sql
ALTER TABLE [OB].[PedidosCabecera]
ADD [TB] NVARCHAR(100) NULL;

CREATE INDEX [IX_OB_PedidosCabecera_TB] 
ON [OB].[PedidosCabecera] ([TB]);
```

---

## 7. MAPEO DE OMEGAS (CÓMO SE DETECTA W/C = 'TB')

### Línea 315: Creación del mapa omegas_map
```python
omegas_map = {row.Assy: row[1] for row in cursor_main.fetchall()}
```

### Línea 314: Query para llenar el mapa
```python
cursor_main.execute("SELECT Assy, [W/C] FROM OB.Omegas")
```

### Línea 388: Uso del mapa para detectar TB
```python
wc_type = omegas_map.get(linea['Cod_producto'])
```

**Lo que hace:**
- `linea['Cod_producto']` = código del Assy (ej: 'O-B L 1002 106 1 LH')
- Se busca en `omegas_map`
- Si `wc_type == 'TB'`, entonces ese producto es un TieBracket

---

## 📊 TABLA: COLUMNAS EN PedidosSecuenciados vs PedidosCabecera

| Campo | Tabla | Tipo | Notas |
|-------|-------|------|-------|
| NumeroPedido | PedidosSecuenciados | NVARCHAR | PK parte 1 |
| Assy | PedidosSecuenciados | NVARCHAR | PK parte 2 |
| Beam | PedidosSecuenciados | NVARCHAR | NULL si no hay |
| AssignedStock | PedidosSecuenciados | INT | Actualizado por auto_sync |
| AssignedStockBeam | PedidosSecuenciados | INT | Actualizado por auto_sync |
| SequenceValue | PedidosSecuenciados | INT | Secuencia original |
| PriorityOrder | PedidosSecuenciados | INT | Prioridad manual |
| **TB** | **PedidosCabecera** | **NVARCHAR(100)** | **NO en PedidosSecuenciados** |
| **EX** | **PedidosCabecera** | **NVARCHAR(100)** | **NO en PedidosSecuenciados** |
| **CWT** | **PedidosCabecera** | **NVARCHAR(100)** | **NO en PedidosSecuenciados** |
| **DS** | **PedidosCabecera** | **NVARCHAR(100)** | **NO en PedidosSecuenciados** |

---

## 🎯 RESUMEN FINAL

### ¿Dónde se ASIGNA TB?
- **Línea 395-396**: En el bucle de sincronización cuando detecta W/C='TB'
- **Línea 426**: Se INSERT en OB.PedidosCabecera.TB

### ¿Cómo se DETECTA si un pedido tiene TB?
- **Línea 1724**: En la query: `WHERE ps.TB IS NOT NULL AND LTRIM(RTRIM(ps.TB)) != ''`
- En el backend se verifica `if tb and tb.strip():`

### ¿Dónde está TB almacenado?
- **Tabla**: OB.PedidosCabecera
- **Columna**: TB (NVARCHAR(100), nullable)
- **Índice**: IX_OB_PedidosCabecera_TB

### ¿Cómo se EXPONE en pantallas?
- **Vista**: OB.V_PedidosSummary_Secuenciados_Full
- **Endpoint**: GET /api/pedidos_tb (línea 1694)
- **Pantalla HTML**: Tie_Brackets.html

### ¿En PedidosSecuenciados?
- **NO:** TB no está directamente en PedidosSecuenciados
- **Se hereda** a través de JOIN en la vista


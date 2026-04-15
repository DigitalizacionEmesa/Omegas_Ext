# Análisis Completo: Asignación y Detección de TB (Tie Brackets) en el Sistema Omegas

---

## 📋 RESUMEN EJECUTIVO

El campo **TB (Tie Bracket)** se maneja en dos niveles:
1. **Nivel de cabecera**: Se asigna en `OB.PedidosCabecera` durante la sincronización de datos
2. **Nivel de consulta**: Se expone a través de la vista `OB.V_PedidosSummary_Secuenciados_Full` para pantallas

**NO está directamente en la tabla `OB.PedidosSecuenciados`**, sino que se hereda desde `PedidosCabecera` a través de JOINs en la vista.

---

## 🔍 1. DETECCIÓN DE TB EN LOS DATOS DE ENTRADA

### Ubicación: [api/appOMEGAS.py](api/appOMEGAS.py#L310-L402)

#### Paso 1: Crear el mapa `omegas_map` (líneas 310-318)
```python
# Obtener Omegas locales para mapear Assy → W/C
omegas_map = {}
try:
    with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
        cursor_main = conn_main.cursor()
        cursor_main.execute("SELECT Assy, [W/C] FROM OB.Omegas")
        omegas_map = {row.Assy: row[1] for row in cursor_main.fetchall()}
except Exception as e:
    print(f"[SCHEDULER] ERROR al obtener Omegas: {e}")
    return
```

**Lo que hace:**
- Lee la tabla `OB.Omegas` 
- Crea un diccionario donde la **clave es el código Assy** y el **valor es la columna W/C**
- Ejemplo: `{'O-B L 1002 106 1 LH': 'TB', 'O-B L 1002 110 1 LH': 'EX', ...}`

---

#### Paso 2: Procesar líneas de pedidos (líneas 375-402)
```python
# Procesar cada pedido y sus líneas
for pedido_id, lineas in pedidos_agrupados.items():
    cwt, ds, ex, tb = None, None, None, None  # ← Inicializar
    
    primera_linea = lineas[0]
    
    for linea in lineas:
        # Verificar CWT/DS/EX/TB
        wc_type = omegas_map.get(linea['Cod_producto'])  # ← Buscar en mapa
        if wc_type == 'CWT' and not cwt: 
            cwt = linea['Cod_producto']
        elif wc_type == 'DS' and not ds: 
            ds = linea['Cod_producto']
        elif wc_type == 'EX' and not ex:
            ex = linea['Cod_producto']
        elif wc_type == 'TB' and not tb:  # ← DETECCIÓN DE TB
            tb = linea['Cod_producto']     # ← ASIGNACIÓN DEL CÓDIGO
```

**Lógica de detección:**
1. Itera sobre las líneas del pedido
2. Para cada línea, obtiene su `Cod_producto` (código Assy)
3. Busca ese Assy en `omegas_map` para obtener su tipo (W/C)
4. **Si `W/C == 'TB'`**, guarda el código del producto en la variable `tb`
5. Solo guarda el **primer TB encontrado** (restricción con `and not tb`)

**Restricciones importantes:**
- ⚠️ Solo se asigna un TB por pedido (`and not tb` previene múltiples)
- ⚠️ Se asigna el `Cod_producto` (no el número de línea)
- ⚠️ Datos deben venir organizados en líneas con un Assy que tenga `W/C='TB'`

---

## 💾 2. INSERCIÓN Y ALMACENAMIENTO DE TB

### Ubicación: [api/appOMEGAS.py](api/appOMEGAS.py#L426)

```python
# Insertar en OB.PedidosCabecera
sql_cabecera = """
    INSERT INTO OB.PedidosCabecera 
    (ID_PedidoCabecera_Externa, NumeroPedido, FechaEntrega, Bsark, EstadoERP, 
     Id_wam_estado_pedido_cliente, CWT, DS, EX, TB) 
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""
cursor_main.executemany(sql_cabecera, lista_cabeceras)
```

**Datos almacenados:**
| Campo | Tipo | Descripción |
|-------|------|-------------|
| `TB` | NVARCHAR(100) | Código Assy del Tie Bracket (ej: 'O-B L 1002 106 1 LH') |
| Tabla | `OB.PedidosCabecera` | Tabla principal donde se guarda |

### Estructura de PedidosCabecera con TB

Según [SQL/ADD_TB_COLUMN.sql](SQL/ADD_TB_COLUMN.sql):
- La columna `TB` fue agregada a `OB.PedidosCabecera` con tipo `NVARCHAR(100) NULL`
- Se creó un índice: `IX_OB_PedidosCabecera_TB` para búsquedas rápidas
- El campo es **nullable** (puede ser NULL si no hay TB)

---

## 📊 3. TABLA PedidosSecuenciados - ESTRUCTURA

### Ubicación: Consultas en [api/appOMEGAS.py](api/appOMEGAS.py#L480-L500)

```sql
SELECT 
    ps.NumeroPedido,      -- Número de pedido
    ps.Assy,              -- Código del assembly
    ps.Beam,              -- Código del beam (si aplica)
    ps.AssignedStock,     -- Stock asignado para Assy
    ps.AssignedStockBeam, -- Stock asignado para Beam
    ps.SequenceValue,     -- Número de secuencia original
    ps.PriorityOrder      -- Prioridad manual asignada
FROM OB.PedidosSecuenciados ps
INNER JOIN OB.PedidosCabecera pc ON ps.NumeroPedido = pc.NumeroPedido
```

**⚠️ IMPORTANTE: `TB` NO está en la tabla `PedidosSecuenciados`**

La tabla `PedidosSecuenciados` contiene:
- `NumeroPedido`, `Assy`, `Beam`
- `AssignedStock`, `AssignedStockBeam` (actualizadas por auto_sync_sequenced)
- `SequenceValue`, `PriorityOrder`

---

## 📺 4. CÓMO SE EXPONE TB EN PANTALLAS

### Vista Wrapper: `OB.V_PedidosSummary_Secuenciados_Full`

Esta es la vista que **combina datos de múltiples tablas** para exponer TB:

**Ubicación de uso:**
- [api/appOMEGAS.py línea 1068-1078](api/appOMEGAS.py#L1068-L1078) - Endpoint principal

```python
# Uso en /api/summary/sequenced
query = """
    SELECT * 
    FROM OB.V_PedidosSummary_Secuenciados_Full
    ORDER BY
        CASE WHEN PriorityOrder IS NOT NULL THEN 0 ELSE 1 END,
        PriorityOrder ASC,
        Sequence ASC
"""
```

**Cómo funciona la vista:**
1. JOINea `PedidosSecuenciados` con `PedidosCabecera` en `NumeroPedido`
2. De `PedidosCabecera` obtiene los campos: `TB`, `EX`, `CWT`, `DS`
3. Expone el campo `TB` junto con otros metadatos

---

## 🔗 5. ENDPOINT ESPECÍFICO PARA TB

### Endpoint: GET `/api/pedidos_tb`
**Ubicación:** [api/appOMEGAS.py líneas 1694-1741](api/appOMEGAS.py#L1694-L1741)

```python
@app.route('/api/pedidos_tb', methods=['GET'])
@cross_origin()
def get_pedidos_tb():
    """
    Devuelve los pedidos secuenciados que tengan TB (Tie Bracket) asignado.
    Usa la vista wrapper OB.V_PedidosSummary_Secuenciados_Full que ya incluye EX y TB.
    Exclusiva para pedidos con TB para evitar solapamientos con OB_C/OB_W.
    """
    query = '''
        SELECT 
            ps.Sequence AS Sequence,
            ps.NumeroPedido AS SalesOrder,
            ps.UnidadesPedidas AS Qty,
            ps.Assy AS Assy,
            ISNULL(ps.TB, '') AS TieBracket,    -- ← CAMPO TB
            ISNULL(ps.EX, '') AS Extender,
            ps.PriorityOrder,
            CASE 
                WHEN ps.EX IS NOT NULL AND LTRIM(RTRIM(ps.EX)) != ''
                THEN ps.UnidadesPedidas - 2
                ELSE NULL
            END AS ExtenderQuantity
        FROM OB.V_PedidosSummary_Secuenciados_Full ps
        WHERE ps.TB IS NOT NULL AND LTRIM(RTRIM(ps.TB)) != ''  -- ← FILTRO POR TB
        ORDER BY 
            CASE WHEN ps.PriorityOrder IS NULL THEN 1 ELSE 0 END,
            ps.PriorityOrder ASC,
            ps.Sequence ASC
    '''
```

**Lo que hace:**
- Devuelve SOLO pedidos que tengan TB asignado
- Filtra: `WHERE ps.TB IS NOT NULL AND LTRIM(RTRIM(ps.TB)) != ''`
- Retorna el campo `TieBracket` con el código del Assy
- Pantalla HTML correspondiente: [Pantallas/Pantallas_VerPedidos/Tie_Brackets.html](Pantallas/Pantallas_VerPedidos/Tie_Brackets.html)

---

## 🎯 6. CÓMO DETECTAR SI UN PEDIDO TIENE TB

### Método 1: En la Base de Datos
```sql
-- Verificar si un pedido tiene TB
SELECT NumeroPedido, TB
FROM OB.PedidosCabecera
WHERE NumeroPedido = '12345'
  AND TB IS NOT NULL 
  AND TB != ''
```

### Método 2: En Python (Backend)
```python
# Verificar en código
if tb and tb.strip():  # tb contiene el Assy del TB
    print(f"El pedido tiene TB: {tb}")
else:
    print("El pedido NO tiene TB")
```

### Método 3: En Frontend (JavaScript)
```javascript
// Cuando se llama al endpoint /api/pedidos_tb
// El JSON retornado contiene el campo TieBracket
if (row.TieBracket && row.TieBracket.trim() !== '') {
    console.log(`Pedido ${row.SalesOrder} tiene TB: ${row.TieBracket}`);
}
```

### Método 4: Diagnóstico SQL Completo
Ver [SQL/Diagnostico_TB.sql](SQL/Diagnostico_TB.sql) para pasos de verificación:
- PASO 1: Verificar que `OB.Omegas` tiene registros con `W/C='TB'`
- PASO 2: Verificar que `PedidosCabecera.TB` está poblado
- PASO 3: Comparar EX vs TB (cantidades)
- PASO 4: Análisis NULL vs vacío
- PASO 5: Ver si la vista hereda TB correctamente

---

## 📍 7. UBICACIONES EXACTAS DE CÓDIGO - RESUMEN

### 🔴 ASIGNACIÓN DE TB

| Línea | Archivo | Descripción |
|-------|---------|-------------|
| **382** | [api/appOMEGAS.py](api/appOMEGAS.py#L382) | Inicializar: `cwt, ds, ex, tb = None, None, None, None` |
| **388** | [api/appOMEGAS.py](api/appOMEGAS.py#L388-L396) | Detectar TB: `wc_type = omegas_map.get(linea['Cod_producto'])` |
| **395-396** | [api/appOMEGAS.py](api/appOMEGAS.py#L395-L396) | Asignar: `elif wc_type == 'TB' and not tb: tb = linea['Cod_producto']` |
| **401** | [api/appOMEGAS.py](api/appOMEGAS.py#L401) | Pasar a tupla: `..., cwt, ds, ex, tb` |
| **426** | [api/appOMEGAS.py](api/appOMEGAS.py#L426) | INSERT: `INSERT INTO OB.PedidosCabecera (..., TB) VALUES (..., ?)` |

### 🟢 LECTURA DE TB

| Línea | Archivo | Descripción |
|-------|---------|-------------|
| **1068-1078** | [api/appOMEGAS.py](api/appOMEGAS.py#L1068-L1078) | Endpoint `/api/summary/sequenced` - Lee de vista |
| **1694-1741** | [api/appOMEGAS.py](api/appOMEGAS.py#L1694-L1741) | Endpoint `/api/pedidos_tb` - Filtra por TB |
| **1721** | [api/appOMEGAS.py](api/appOMEGAS.py#L1721) | Query: `FROM OB.V_PedidosSummary_Secuenciados_Full ps WHERE ps.TB IS NOT NULL` |

### 🔵 DEFINICIÓN EN BD

| Línea | Archivo | Descripción |
|-------|---------|-------------|
| **2-22** | [SQL/ADD_TB_COLUMN.sql](SQL/ADD_TB_COLUMN.sql) | Crear columna TB en PedidosCabecera |
| **27-39** | [SQL/ADD_TB_COLUMN.sql](SQL/ADD_TB_COLUMN.sql) | Crear índice IX_OB_PedidosCabecera_TB |

### 🟡 DIAGNÓSTICO

| Línea | Archivo | Descripción |
|-------|---------|-------------|
| **1-100** | [SQL/Diagnostico_TB.sql](SQL/Diagnostico_TB.sql) | 7 pasos para verificar TB en todo el sistema |

---

## 📌 RESUMEN DE LÍNEAS CLAVE

### ✅ DONDE SE ASIGNA/ACTUALIZA TB

**Línea 382:** Inicialización
```python
cwt, ds, ex, tb = None, None, None, None
```

**Líneas 395-396:** Asignación (CRÍTICA)
```python
elif wc_type == 'TB' and not tb:
    tb = linea['Cod_producto']
```

**Línea 426:** INSERT en PedidosCabecera
```python
sql_cabecera = "INSERT INTO OB.PedidosCabecera (..., TB) VALUES (..., ?);"
```

### ✅ COMO SE DETECTA SI UN PEDIDO TIENE TB

**Método 1: En SQL**
```sql
WHERE TB IS NOT NULL AND LTRIM(RTRIM(TB)) != ''
```

**Línea 1724 (Frontend Query)**
```sql
WHERE ps.TB IS NOT NULL AND LTRIM(RTRIM(ps.TB)) != ''
```

**Método 2: En Python**
```python
if tb and tb.strip():  # Verificar no vacío
```

---

## 🚀 CASOS DE USO

### Caso 1: Ver todos los pedidos con TB
```python
GET /api/pedidos_tb
# Retorna: lista de pedidos con TB poblado
```

### Caso 2: Verificar si UN pedido tiene TB
```sql
SELECT TB FROM OB.PedidosCabecera 
WHERE NumeroPedido = '23511'
-- Retorna: 'O-B L 1002 106 1 LH' (tiene TB) o NULL (no tiene)
```

### Caso 3: Ver TB en contexto de secuencias
```python
GET /api/summary/sequenced
# Retorna: todos los pedidos secuenciados con TB en cada fila
```

---

## 📋 CONCLUSIONES

1. **TB se asigna en el nivel de cabecera** (`PedidosCabecera`) durante la sincronización
2. **No está en `PedidosSecuenciados`** - se hereda a través de JOINs en la vista `V_PedidosSummary_Secuenciados_Full`
3. **Detección**: Se busca en `OB.Omegas` por columna `W/C == 'TB'`
4. **Una restricción**: Solo se asigna UN TB por pedido (validado con `and not tb`)
5. **Almacenamiento**: Se guarda el código Assy del product (ej: 'O-B L 1002 106 1 LH')
6. **Exposición**: A través del endpoint `/api/pedidos_tb` y la vista `V_PedidosSummary_Secuenciados_Full`
7. **Pantalla**: [Tie_Brackets.html](Pantallas/Pantallas_VerPedidos/Tie_Brackets.html) muestra pedidos con TB

---

## 📚 REFERENCIAS A ARCHIVOS

- Backend: [api/appOMEGAS.py](api/appOMEGAS.py)
- SQL Schemas: [SQL/ADD_TB_COLUMN.sql](SQL/ADD_TB_COLUMN.sql), [SQL/Diagnostico_TB.sql](SQL/Diagnostico_TB.sql)
- Front-End: [Pantallas/Pantallas_VerPedidos/Tie_Brackets.html](Pantallas/Pantallas_VerPedidos/Tie_Brackets.html)


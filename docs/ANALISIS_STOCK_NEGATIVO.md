# ANÁLISIS DE STOCK NEGATIVO — SEQ / OMEGAS

> **Fecha del análisis**: 2026-06-23
> **Contexto**: La aplicación SEQ recibe movimientos de stock desde Mapex. Aparecen valores negativos de stock de forma intermitente.

---

## 🗺️ ARQUITECTURA DEL FLUJO DE STOCK

```
┌─────────────────────────────────────────────────────────────┐
│                     MAPEX (mapexbp)                         │
│  ┌──────────────────┐  ┌─────────────────────────────────┐ │
│  │ F_HIS_CT()       │  │ his_lectura                     │ │
│  │ (producción)     │  │ (consumos/lecturas)             │ │
│  └───────┬──────────┘  └──────────────┬──────────────────┘ │
└──────────┼────────────────────────────┼────────────────────┘
           │                            │
           ▼                            ▼
┌──────────────────────┐   ┌──────────────────────────────────┐
│ SQL Server Agent Job │   │  Hilo Python (cada 15 seg)       │
│ sp_Sync_Omegas_RawData│   │  auto_sync_beams_stock()        │
│ (cada 5 min)         │   │  → sp_Sync_Beams_RawData         │
└──────────┬───────────┘   └──────────────┬───────────────────┘
           │                              │
           ▼                              ▼
┌──────────────────────┐   ┌──────────────────────────────────┐
│ OB.Omegas_Produccion │   │ OB.Beams_Produccion              │
│ OB.Omegas_Lecturas   │   │ OB.Beams_Consumos               │
└──────────┬───────────┘   └──────────────┬───────────────────┘
           │                              │
           ▼                              ▼
┌──────────────────────┐   ┌──────────────────────────────────┐
│ OB.Stock_Omegas_New  │   │ OB.Stock_Beams_New (VIEW)        │
│ (VIEW: Prod - Lec)   │   │ (VIEW: Prod - Cons)              │
└──────────┬───────────┘   └──────────────┬───────────────────┘
           │                              │
           ▼                              ▼
┌─────────────────────────────────────────────────────────────┐
│         auto_sync_sequenced() — cada N segundos              │
│   Lee Stock_Omegas_New + Stock_Beams_New                     │
│   Asigna AssignedStock y AssignedStockBeam a pedidos         │
│   UPDATE OB.PedidosSecuenciados                              │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  RESET MANUAL: /api/reset_stock → sp_Reset_Omega_Stock       │
│                /api/beams/stock/adjust → sp_Reset_Beam_Stock │
└─────────────────────────────────────────────────────────────┘
```

---

# 📋 PUNTO 1 — Clases, Métodos y Componentes de Gestión de Stock

## 1.1 CLASES DE CONEXIÓN A BASE DE DATOS

| # | Archivo | Clase | Líneas | Descripción | Categoría |
|---|---------|-------|--------|-------------|-----------|
| 1.1 | `api/appOMEGAS.py` | `ConexionODBC` | L2999-3038 | Conexión a BD principal (DataLakeSCCZ). Itera servidores/drivers. `autocommit=True` por defecto. `__enter__`/`__exit__` para context manager. | `[INTEGRACION]` |
| 1.2 | `api/appOMEGAS.py` | `ConexionODBCCZ` | L3040-3079 | Conexión a BD CZ (mapexbp por defecto, también DataLakeSCCZ). Misma arquitectura que `ConexionODBC`. `autocommit=True`. | `[INTEGRACION]` `[MAPEX]` |

## 1.2 LOCKS Y SINCRONIZACIÓN ENTRE HILOS

| # | Archivo | Variable | Línea | Descripción | Categoría |
|---|---------|----------|-------|-------------|-----------|
| 2.1 | `api/appOMEGAS.py` | `PEDIDOS_DB_LOCK` | L109 | `threading.Lock()` — protege `sync_pending_orders()` y `auto_sync_sequenced()` de ejecutarse simultáneamente | `[SYNC]` `[BACKGROUND]` |
| 2.2 | `api/appOMEGAS.py` | `ENDPOINT_RESPONSE_CACHE_LOCK` | L110 | Protege la caché de respuestas de endpoints | `[SYNC]` |
| 2.3 | `api/appOMEGAS.py` | `MANUAL_SYNC_STATE_LOCK` | L115 | Protege el estado de sincronización manual | `[SYNC]` |
| 2.4 | `api/appOMEGAS.py` | `CLINCHING_MASTER_CACHE_LOCK` | L116 | Protege caché de clinching master | `[SYNC]` |
| 2.5 | `api/appOMEGAS.py` | `MAPEX_COMPONENT_QTY_CACHE_LOCK` | L117 | Protege caché de cantidades de componentes desde MAPEX | `[MAPEX]` |

## 1.3 FUNCIONES DE SINCRONIZACIÓN DE PEDIDOS (MAPEX → DataLake)

| # | Archivo | Función | Líneas | Descripción | Categoría |
|---|---------|---------|--------|-------------|-----------|
| 3.1 | `api/appOMEGAS.py` | `sync_pending_orders()` | L437-665 | **Función central de importación**. Conecta a `mapexbp`, consulta `his_wam_pedido_cliente` + `his_wam_linea_pedido_cliente` + `V_Cfg_producto`, agrupa por pedido, deriva CWT/DS/EX/TB/CWI desde `OB.Omegas.[W/C]`, inserta en `OB.PedidosCabecera` y `OB.PedidosLineas`. Usa `PEDIDOS_DB_LOCK`. Transacción manual (`autocommit=False`). | `[MAPEX]` `[SYNC]` `[STOCK]` |
| 3.2 | `api/appOMEGAS.py` | `run_startup_sync()` | L667-677 | Envuelve `sync_pending_orders(lookback_days=1)` para el arranque | `[BACKGROUND]` `[SYNC]` |
| 3.3 | `api/appOMEGAS.py` | `run_manual_full_sync_background()` | L690-700 | Sync manual completa en background, guarda resultado en `MANUAL_SYNC_STATE` | `[BACKGROUND]` `[SYNC]` |
| 3.4 | `api/appOMEGAS.py` | `scheduled_daily_sync()` | L705-713 | Sync diaria programada a las 00:00 via `schedule` | `[BACKGROUND]` `[SYNC]` |
| 3.5 | `api/appOMEGAS.py` | `run_scheduler()` | L715-729 | Worker que ejecuta `schedule.run_pending()` cada 60s | `[BACKGROUND]` |

## 1.4 FUNCIONES DE STOCK — ASIGNACIÓN A PEDIDOS SECUENCIADOS

| # | Archivo | Función | Líneas | Descripción | Categoría |
|---|---------|---------|--------|-------------|-----------|
| 4.1 | `api/appOMEGAS.py` | `auto_sync_sequenced()` | L737-890 | **Función crítica de asignación de stock**. Bucle infinito cada `AUTO_SYNC_SEQUENCED_INTERVAL_SECONDS` (15s). Lee `Stock_Omegas_New` y `Stock_Beams_New`, itera pedidos secuenciados ordenados por `PriorityOrder → SequenceValue`, asigna `AssignedStock` y `AssignedStockBeam` con lógica `min(cantidad_necesaria, stock_disponible)`. Hace UPDATE sobre `OB.PedidosSecuenciados`. **Usa `PEDIDOS_DB_LOCK`**. | `[STOCK]` `[SYNC]` `[BACKGROUND]` |
| 4.2 | `api/appOMEGAS.py` | Endpoint incremental | L2450-2520 | Endpoint que recalcula `AssignedStock`/`AssignedStockBeam` para todos los pedidos. Misma lógica que `auto_sync_sequenced` pero bajo demanda. | `[STOCK]` `[SYNC]` |

## 1.5 FUNCIONES DE STOCK — SINCRONIZACIÓN DE BEAMS

| # | Archivo | Función | Líneas | Descripción | Categoría |
|---|---------|---------|--------|-------------|-----------|
| 5.1 | `api/appOMEGAS.py` | `auto_sync_beams_stock()` | L895-916 | **Hilo que sincroniza stock de Beams cada 15s**. Ejecuta `{CALL OB.sp_Sync_Beams_RawData}`. **NO usa `PEDIDOS_DB_LOCK`** — se ejecuta concurrentemente con `auto_sync_sequenced()`. | `[STOCK]` `[SYNC]` `[BACKGROUND]` |

## 1.6 ENDPOINTS DE STOCK (API REST)

| # | Archivo | Endpoint | Líneas | Descripción | Categoría |
|---|---------|----------|--------|-------------|-----------|
| 6.1 | `api/appOMEGAS.py` | `GET /api/stock_omegas` | L3595-3614 | Devuelve stock actual de Omegas desde `OB.Stock_Omegas_New` | `[STOCK]` |
| 6.2 | `api/appOMEGAS.py` | `POST /api/reset_stock` | L3617-3649 | Resetea stock de un Omega. Llama a `sp_Reset_Omega_Stock`. **Borra todo el histórico** de producción y lecturas. | `[STOCK]` `[RESET]` |
| 6.3 | `api/appOMEGAS.py` | `GET /api/stock_sap_omegas` | L3655-3720 | Consulta stock en SAP (tabla MARD) y compara con el local | `[STOCK]` `[SAP]` |
| 6.4 | `api/appOMEGAS.py` | `GET /api/beams/stock` | L4400-4420 | Devuelve stock de Beams desde `OB.Stock_Beams_New` | `[STOCK]` |
| 6.5 | `api/appOMEGAS.py` | `POST /api/beams/stock/adjust` | L4425-4448 | Ajusta stock de un Beam. Llama a `sp_Reset_Beam_Stock`. **Borra TODO el histórico** (producción, consumos, BeamStocks, Sync_PostedTotals). | `[STOCK]` `[RESET]` |

## 1.7 STORED PROCEDURES SQL — STOCK

| # | Archivo | SP | Descripción | Categoría |
|---|---------|----|-------------|-----------|
| 7.1 | `SQL/OB_sp_Sync_Omegas_RawData_fix_intradia.sql` | `OB.sp_Sync_Omegas_RawData` | **SP principal de sync de Omegas**. Ejecutado por SQL Agent Job cada 5 min. MERGE en `Omegas_Produccion` desde `F_HIS_CT()`, INSERT en `Omegas_Lecturas` desde `his_lectura`. Usa `Last_Sync_omegas` para incremental. **Contiene condición OR de riesgo** (ver punto 3). | `[STOCK]` `[PRODUCCION]` `[CONSUMO]` `[MAPEX]` |
| 7.2 | `SQL/sp_Sync_Beams_RawData.sql` | `OB.sp_Sync_Beams_RawData` | **SP de sync de Beams**. MERGE en `Beams_Produccion` y `Beams_Consumos` desde `F_HIS_CT()`. **Los consumos vienen de la producción de Omegas tipo C con Beam asignado**, no de consumos reales. MERGE final en `BeamSync_PostedTotals`. | `[STOCK]` `[PRODUCCION]` `[CONSUMO]` `[MAPEX]` |
| 7.3 | `SQL/sp_Reset_Omega_Stock.sql` | `OB.sp_Reset_Omega_Stock` | Borra `Omegas_Produccion` + `Omegas_Lecturas` para un producto, actualiza `Last_Sync_omegas`, inserta ajuste manual si `@NuevoStock ≠ 0` | `[STOCK]` `[RESET]` |
| 7.4 | `SQL/FIX_sp_Reset_Omega_Stock.sql` | `OB.sp_Reset_Omega_Stock` (FIX) | **Corrección**: antes de borrar, guarda `MAX(Fecha_fin)` y `MAX(fecha)` y pone `Last_Sync_Date = Fecha_fin + 1s` para evitar que el sync reimporte producción antigua | `[STOCK]` `[RESET]` |
| 7.5 | `SQL/sp_Reset_Beam_Stock.sql` | `OB.sp_Reset_Beam_Stock` | **Transacción**: Borra `BeamStocks`, `Beams_Produccion`, `Beams_Consumos`, `BeamSync_PostedTotals`. MERGE en `Last_Sync_Beams` y `BeamSync_PostedTotals`. Inserta ajuste manual si `@NuevoStock ≠ 0`. | `[STOCK]` `[RESET]` |
| 7.6 | `SQL/sp_AddBeamStockMovement.sql` | `OB.sp_AddBeamStockMovement` | Inserta un movimiento en `OB.BeamStocks`. Corrige el signo según `MovementID` (entradas positivo, salidas negativo). **No se usa en el cálculo de stock** (`Stock_Beams_New` usa `Beams_Produccion` y `Beams_Consumos`, no `BeamStocks`). | `[STOCK]` |

## 1.8 VISTAS SQL DE STOCK

| # | Archivo | Vista | Descripción | Categoría |
|---|---------|-------|-------------|-----------|
| 8.1 | *(en BD)* | `OB.Stock_Omegas_New` | `SELECT Cod_producto, (SUM(Produccion) - COUNT(Lecturas)) AS StockActual` — cálculo directo de stock disponible | `[STOCK]` |
| 8.2 | `SQL/Stock_Beams_New.sql` | `OB.Stock_Beams_New` | CTE: `Entradas = SUM(Beams_Produccion)`, `Salidas = SUM(Beams_Consumos)`, `StockActual = Entradas - Salidas`. **Sin floor a 0** → puede mostrar negativos. | `[STOCK]` |

## 1.9 TABLAS DE STOCK (referenciadas en código)

| # | Tabla | Esquema | Rol |
|---|-------|---------|-----|
| 9.1 | `Omegas_Produccion` | `OB` | Producción de Omegas desde MAPEX (entradas) |
| 9.2 | `Omegas_Lecturas` | `OB` | Lecturas/consumos de Omegas desde `his_lectura` (salidas) |
| 9.3 | `Beams_Produccion` | `OB` | Producción de Beams desde MAPEX (entradas, con `SYSTEM_VERSIONING`) |
| 9.4 | `Beams_Consumos` | `OB` | Consumos de Beams — derivados de producción de Omegas tipo C (salidas, con `SYSTEM_VERSIONING`) |
| 9.5 | `BeamStocks` | `OB` | Movimientos individuales de Beam (no usado en cálculo de stock) |
| 9.6 | `BeamSync_PostedTotals` | `OB` | Totales posted por Beam y fuente (PROD/CONS) |
| 9.7 | `Last_Sync_omegas` | `OB` | Marca de agua para sync incremental de Omegas |
| 9.8 | `Last_Sync_Beams` | `OB` | Marca de agua para sync incremental de Beams (PK: `Cod_producto, Fuente`) |
| 9.9 | `PedidosSecuenciados` | `OB` | Pedidos secuenciados con `AssignedStock` y `AssignedStockBeam` |
| 9.10 | `PedidosCabecera` | `OB` | Cabeceras de pedido importadas (CWT, DS, EX, TB, CWI) |
| 9.11 | `PedidosLineas` | `OB` | Líneas de pedido (UnidadesPedidas, UniValMapex) |

## 1.10 HILOS Y PROCESAMIENTO EN BACKGROUND

| # | Archivo | Hilo | Target | Intervalo | Categoría |
|---|---------|------|--------|-----------|-----------|
| 10.1 | `api/appOMEGAS.py` L5960 | `StartupSync` | `run_startup_sync()` | Una vez al arranque | `[BACKGROUND]` |
| 10.2 | `api/appOMEGAS.py` L5966 | `PedidosSync` | `auto_sync_sequenced()` | Cada 15s | `[BACKGROUND]` `[STOCK]` |
| 10.3 | `api/appOMEGAS.py` L5972 | `BeamStockSync` | `auto_sync_beams_stock()` | Cada 15s | `[BACKGROUND]` `[STOCK]` |
| 10.4 | `api/appOMEGAS.py` L5984 | `CleanupSync` | `cleanup_sequenced_orders()` | Cada 60s | `[BACKGROUND]` |
| 10.5 | `api/appOMEGAS.py` L5989 | `CleanupOldSync` | `cleanup_old_unsequenced_orders()` | Cada 120s | `[BACKGROUND]` |
| 10.6 | `api/appOMEGAS.py` L5995 | `DailyScheduler` | `run_scheduler()` | Cada 60s (schedule check) | `[BACKGROUND]` |
| 10.7 | *(SQL Agent)* | — | `sp_Sync_Omegas_RawData` | Cada 5 min | `[STOCK]` `[MAPEX]` |

## 1.11 SCRIPTS DE DIAGNÓSTICO

| # | Archivo | Descripción |
|---|---------|-------------|
| 11.1 | `diagnostico_descuadres_stock.py` | Compara stock App vs SAP para 26 Omegas, mostrando producción, lecturas, stock calculado y diferencia |
| 11.2 | `diagnostico_extender_pedidos.py` | Diagnostica por qué pedidos específicos no tienen ExtenderQuantity |
| 11.3 | `diagnostico_extensores_hoy.py` | Revisa campo EX en pedidos C/W, conteo de EX poblado vs vacío, líneas EX en PedidosLineas |
| 11.4 | `diagnostico_mapex_beams.py` | Verifica si MAPEX tiene datos, compara con datos locales, ejecuta `DIAGNÓSTICO_MAPEX_BEAMS.sql` |
| 11.5 | `trazar_38492.py` | Traza un pedido en todas las etapas: PedidosCabecera, PedidosLineas, vista secuenciados |
| 11.6 | `SQL/ANÁLISIS_POR_QUÉ_NO_ACTUALIZA.sql` | Diagnostica por qué `sp_Sync_Beams_RawData` no actualiza — verifica Last_Sync_Date vs fechas MAPEX |
| 11.7 | `SQL/DIAGNÓSTICO_MAPEX_BEAMS.sql` | Diagnóstico completo: últimas syncs, datos en MAPEX, datos locales, comparación |
| 11.8 | `SQL/VER_INSERCIONES_REALES.sql` | Muestra últimas inserciones en Beams_Consumos y Beams_Produccion |
| 11.9 | `SQL/TEMP_Resync_Beams.sql` | Fuerza resincronización: resetea Last_Sync_Date a 7 días atrás y ejecuta sync 5 veces |

## 1.12 OTROS COMPONENTES RELACIONADOS

| # | Archivo | Componente | Líneas | Descripción | Categoría |
|---|---------|------------|--------|-------------|-----------|
| 12.1 | `api/appOMEGAS.py` | `run_sequencing()` | L2530-2920 | Endpoint que secuencia pedidos. Inserta en `PedidosSecuenciados` con `AssignedStock=0, AssignedStockBeam=0`. Luego `auto_sync_sequenced` los actualiza. | `[STOCK]` |
| 12.2 | `api/appOMEGAS.py` | `build_wc_line_apply_sql()` | L3308-3328 | OUTER APPLY que resuelve cualquier W/C desde PedidosLineas + OB.Omegas | `[MAPEX]` |
| 12.3 | `api/appOMEGAS.py` | `build_sequenced_orders_extender_query()` | L3412-3520 | Query set-based para tarjetas C/W con CTEs para extender value/target/quantity | `[STOCK]` |
| 12.4 | `api/appOMEGAS.py` | SAP sync | L42-46 | `SAP_STOCK_URL` — conexión a SAP para consultar stock | `[SAP]` `[STOCK]` |
| 12.5 | `analisis_por_que_no_actualiza.py` | — | Script raíz | Script Python para diagnóstico de por qué no actualiza | `[STOCK]` |
| 12.6 | `stock_sap_omegas.json` | — | Archivo datos | Cache local de stock SAP | `[STOCK]` `[SAP]` |

### ⚠️ HALLAZGOS PRELIMINARES DE RIESGO

Durante el mapeo ya se detectaron varios patrones preocupantes:

1. **`BeamStockSync` vs `PedidosSync` sin lock común**: `auto_sync_beams_stock()` (L895) NO usa `PEDIDOS_DB_LOCK`, pero modifica datos que `auto_sync_sequenced()` (L737) lee → **race condition confirmada**.

2. **`sp_Sync_Beams_RawData` replica el patrón de doble condición OR** que ya causó bugs en `sp_Sync_Omegas_RawData` (corregido en `FIX_sp_Reset_Omega_Stock.sql`).

3. **La tabla `BeamStocks` no se usa en el cálculo de stock** — `Stock_Beams_New` solo mira `Beams_Produccion` y `Beams_Consumos`. Los movimientos individuales (ventas, bajas, etc.) insertados por `sp_AddBeamStockMovement` no afectan al stock visible.

4. **`Stock_Beams_New` no tiene `MAX(0, ...)`** — puede devolver valores negativos.

---

# 📋 PUNTO 2 — Operaciones que afectan al Stock

## 🔼 2.A — OPERACIONES QUE INCREMENTAN STOCK

### 2.A.1 — MERGE de producción de Omegas desde MAPEX

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/OB_sp_Sync_Omegas_RawData_fix_intradia.sql` |
| **SP** | `OB.sp_Sync_Omegas_RawData` |
| **Líneas** | 38-68 |
| **Tipo** | `MERGE INTO OB.Omegas_Produccion` |
| **Origen datos** | `mapexbp.dbo.F_HIS_CT('WORKCENTER', 'DAY', 'PRODUCT', ...)` |
| **Filtro** | `WorkGroup1 = '50 Assembly' AND Unidades_OK > 0` |
| **Disparador** | SQL Server Agent Job cada 5 minutos |

```sql
MERGE OB.Omegas_Produccion AS Target
USING (
    SELECT f.Cod_producto, f.WorkGroup, f.Fecha_inicio, f.Fecha_fin,
           CAST(f.Unidades_OK AS INT) AS Unidades_OK
    FROM mapexbp.dbo.F_HIS_CT('WORKCENTER', 'DAY', 'PRODUCT', @MinProdDateFloor, @CurrentTime, 2) f
    INNER JOIN OB.Last_Sync_omegas lso ON f.Cod_producto = lso.Cod_producto AND lso.Fuente = 'PROD'
    WHERE (f.WorkGroup1 = '50 Assembly' AND f.Unidades_OK > 0 AND f.Fecha_inicio >= lso.Last_Sync_Date)
       OR (f.WorkGroup1 = '50 Assembly' AND f.Fecha_fin > lso.Last_Sync_Date AND f.Fecha_inicio < lso.Last_Sync_Date)
) AS Source
ON (Target.Cod_producto = Source.Cod_producto AND Target.WorkGroup = Source.WorkGroup
    AND Target.Fecha_inicio = Source.Fecha_inicio)
WHEN MATCHED THEN UPDATE SET Fecha_fin = Source.Fecha_fin, Unidades_OK = Source.Unidades_OK, SyncDate = GETDATE()
WHEN NOT MATCHED BY TARGET THEN INSERT (...);
```

> 🔴 **RIESGO**: La condición `OR` (`Fecha_fin > LastSync AND Fecha_inicio < LastSync`) puede reimportar producción que ya fue reseteada, inflando el stock.

### 2.A.2 — MERGE de producción de Beams desde MAPEX

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/sp_Sync_Beams_RawData.sql` |
| **SP** | `OB.sp_Sync_Beams_RawData` |
| **Líneas** | 120-175 |
| **Tipo** | `MERGE INTO OB.Beams_Produccion` |
| **Origen datos** | `mapexbp.dbo.F_HIS_CT('WORKCENTER', 'DETAIL', 'PRODUCT', ...)` |
| **Filtro** | `WorkGroup1 = '50 Assembly' AND Unidades_OK > 0` + JOIN con `OB.Beams` (`IsActive = 1`) |
| **Disparador** | Hilo Python `auto_sync_beams_stock()` cada 15 segundos |

```sql
MERGE OB.Beams_Produccion AS Target
USING (
    SELECT f.Cod_producto, ...Unidades_OK
    FROM mapexbp.dbo.F_HIS_CT(...) f
    INNER JOIN OB.Beams b ON b.BeamCode = f.Cod_producto AND b.IsActive = 1
    INNER JOIN OB.Last_Sync_Beams lsb ON lsb.Cod_producto = f.Cod_producto AND lsb.Fuente = 'PROD'
    WHERE f.WorkGroup1 = '50 Assembly' AND f.Unidades_OK > 0
      AND (f.Fecha_inicio >= lsb.Last_Sync_Date
           OR (f.Fecha_fin > lsb.Last_Sync_Date AND f.Fecha_inicio < lsb.Last_Sync_Date))
) ...
```

> 🔴 **RIESGO**: **Mismo patrón de doble condición OR** que el bug ya corregido en Omegas. Si se resetea un Beam, `Last_Sync_Date` se actualiza pero la condición OR puede reimportar producción antigua.

### 2.A.3 — Ajuste manual en Reset de Omega

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/FIX_sp_Reset_Omega_Stock.sql` |
| **SP** | `OB.sp_Reset_Omega_Stock` |
| **Líneas** | 52-54 |
| **Tipo** | `INSERT INTO OB.Omegas_Produccion` |

```sql
IF @NuevoStock <> 0
    INSERT INTO OB.Omegas_Produccion (Cod_producto, WorkGroup, Fecha_inicio, Fecha_fin, Unidades_OK)
    VALUES (@Cod_producto, 'AJUSTE_MANUAL', @CurrentTime, @CurrentTime, @NuevoStock);
```

> ⚠️ Inserta con `WorkGroup = 'AJUSTE_MANUAL'`. No hay validación de que `@NuevoStock > 0`.

### 2.A.4 — Ajuste manual en Reset de Beam

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/sp_Reset_Beam_Stock.sql` |
| **SP** | `OB.sp_Reset_Beam_Stock` |
| **Líneas** | 60-69 |
| **Tipo** | `INSERT INTO OB.Beams_Produccion` + `INSERT INTO OB.BeamStocks` |

```sql
IF @NuevoStock <> 0
BEGIN
    INSERT INTO OB.Beams_Produccion (Cod_producto, WorkGroup, Fecha_inicio, Fecha_fin, Unidades_OK)
    VALUES (@BeamCode, 'AJUSTE_MANUAL', @CurrentTime, @CurrentTime, @NuevoStock);
    INSERT INTO OB.BeamStocks (BeamID, MovementID, Quantity, ID_Usuario, Notes)
    VALUES (@BeamID, 3, @NuevoStock, @UsuarioID, 'AJUSTE_MANUAL');
END
```

### 2.A.5 — Movimiento de entrada individual (Beam)

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/sp_AddBeamStockMovement.sql` |
| **SP** | `OB.sp_AddBeamStockMovement` |
| **Líneas** | 27-47 |
| **Tipo** | `INSERT INTO OB.BeamStocks` |
| **Movements de entrada** | `MovementID IN (1=Producción, 4=Compra, 6=Devolución)` |

```sql
-- Fuerza signo positivo para entradas
ELSE IF @MovementID IN (1, 4, 6) AND @Quantity < 0
    SET @FinalQuantity = @Quantity * -1;
INSERT INTO OB.BeamStocks (BeamID, MovementID, Quantity, ID_Usuario, Notes)
VALUES (@BeamID, @MovementID, @FinalQuantity, @UsuarioID, @Notes);
```

> ⚠️ **IMPORTANTE**: Esta tabla (`BeamStocks`) **NO se usa en la vista `Stock_Beams_New`**. El stock visible se calcula solo desde `Beams_Produccion - Beams_Consumos`.

## 🔽 2.B — OPERACIONES QUE DECREMENTAN STOCK

### 2.B.1 — INSERT de lecturas/consumos de Omegas

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/OB_sp_Sync_Omegas_RawData_fix_intradia.sql` |
| **SP** | `OB.sp_Sync_Omegas_RawData` |
| **Líneas** | 85-97 |
| **Tipo** | `INSERT INTO OB.Omegas_Lecturas` |
| **Origen datos** | `mapexbp.dbo.his_lectura` |

```sql
INSERT INTO OB.Omegas_Lecturas (id_his_lectura, producto, numero_serie, id_operario, fecha)
SELECT h.id_his_lectura, h.producto, h.numero_serie, h.id_operario, h.fecha
FROM mapexbp.dbo.his_lectura h
INNER JOIN OB.Last_Sync_omegas lso ON h.producto = lso.Cod_producto AND lso.Fuente = 'LEC'
WHERE h.fecha > lso.Last_Sync_Date
  AND NOT EXISTS (SELECT 1 FROM OB.Omegas_Lecturas ol WHERE ol.id_his_lectura = h.id_his_lectura);
```

> ✅ Tiene `NOT EXISTS` para evitar duplicados. Pero **cada lectura descuenta 1 unidad** del stock (la vista `Stock_Omegas_New` cuenta filas, no cantidades).

### 2.B.2 — MERGE de consumos de Beams (desde producción de Omegas C)

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/sp_Sync_Beams_RawData.sql` |
| **SP** | `OB.sp_Sync_Beams_RawData` |
| **Líneas** | 197-240 |
| **Tipo** | `MERGE INTO OB.Beams_Consumos` |
| **Origen datos** | `mapexbp.dbo.F_HIS_CT(...)` — **producción de Omegas**, no consumos reales |

```sql
MERGE OB.Beams_Consumos AS Target
USING (
    SELECT beam.BeamCode AS Cod_producto, omega.Assy AS WorkGroup,
           f.Fecha_inicio, f.Fecha_fin, CAST(f.Unidades_OK AS INT) AS Unidades_OK
    FROM mapexbp.dbo.F_HIS_CT(...) f
    INNER JOIN OB.Omegas omega ON omega.Assy = f.Cod_producto
                               AND omega.[W/C] = 'C'
                               AND omega.Beam IS NOT NULL
    INNER JOIN OB.Beams beam ON beam.BeamCode = omega.Beam AND beam.IsActive = 1
    INNER JOIN OB.Last_Sync_Beams lsb ON lsb.Cod_producto = beam.BeamCode AND lsb.Fuente = 'CONS'
    WHERE f.WorkGroup1 = '50 Assembly' AND f.Unidades_OK > 0
      AND (f.Fecha_inicio >= lsb.Last_Sync_Date OR (...))
) ...
```

> 🔴 **CRÍTICO**: Los "consumos" de Beam **no son consumos reales**. Son la producción de Omegas tipo C (`W/C='C'`) que tienen un Beam asignado. Esto asume que **cada Omega C producida consume 1 Beam**. Si esta asunción falla (ej. un Omega C no usa Beam, o usa más de 1), el stock de Beam será incorrecto.

### 2.B.3 — Asignación de stock en `auto_sync_sequenced()` (decremento lógico)

| Campo | Valor |
|-------|-------|
| **Archivo** | `api/appOMEGAS.py` |
| **Función** | `auto_sync_sequenced()` |
| **Líneas** | 807-891 |
| **Tipo** | Decremento en diccionario Python + UPDATE en BD |

```python
# Lee stock actual
cursor_main.execute("SELECT Cod_producto, StockActual FROM OB.Stock_Omegas_New")
stock_disponible = {row.Cod_producto: row.StockActual for row in cursor_main.fetchall()}

cursor_main.execute("SELECT Cod_producto, StockActual FROM OB.Stock_Beams_New")
stock_beams = {row.Cod_producto: row.StockActual for row in cursor_main.fetchall()}

# Para cada pedido:
nuevo_stock_asignado_assy = min(cantidad_necesaria, stock_actual_para_assy)
stock_disponible[assy] = max(0, stock_actual_para_assy - nuevo_stock_asignado_assy)  # ⬅ DECREMENTO

nuevo_stock_asignado_beam = min(cantidad_necesaria_beam, stock_actual_para_beam)
stock_beams[beam] = max(0, stock_actual_para_beam - nuevo_stock_asignado_beam)  # ⬅ DECREMENTO

# UPDATE en BD
UPDATE OB.PedidosSecuenciados SET AssignedStock = ?, AssignedStockBeam = ?
WHERE NumeroPedido = ? AND Assy = ?
```

> 🔴 **CRÍTICO**: El decremento ocurre en un **diccionario Python en memoria**, no en la BD. El `UPDATE` solo escribe `AssignedStock`/`AssignedStockBeam` en `PedidosSecuenciados`, pero **no bloquea ni actualiza el stock real**. Si otro proceso lee el stock entre la lectura y la escritura, ve el stock antiguo → **race condition**.

### 2.B.4 — Movimiento de salida individual (Beam)

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/sp_AddBeamStockMovement.sql` |
| **SP** | `OB.sp_AddBeamStockMovement` |
| **Líneas** | 27-47 |
| **Tipo** | `INSERT INTO OB.BeamStocks` |
| **Movements de salida** | `MovementID IN (2=Lectura, 5=Venta, 7=Baja, 9=Salida Trazabilidad)` |

```sql
IF @MovementID IN (2, 5, 7, 9) AND @Quantity > 0
    SET @FinalQuantity = @Quantity * -1;
INSERT INTO OB.BeamStocks (BeamID, MovementID, Quantity, ID_Usuario, Notes)
VALUES (...);
```

> ⚠️ **No afecta al stock visible** (mismo problema que 2.A.5).

## 🔄 2.C — OPERACIONES QUE RECALCULAN STOCK

### 2.C.1 — Vista `Stock_Omegas_New`

| Campo | Valor |
|-------|-------|
| **Ubicación** | SQL Server (no hay archivo .sql en el repo) |
| **Cálculo** | `StockActual = SUM(Omegas_Produccion.Unidades_OK) - COUNT(Omegas_Lecturas.id_his_lectura)` |

> ⚠️ **Asimetría**: Producción usa `SUM(Unidades_OK)`, pero Lecturas usa `COUNT(*)`. Si una lectura representa 1 unidad, es correcto. Si no, hay descuadre.

### 2.C.2 — Vista `Stock_Beams_New`

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/Stock_Beams_New.sql` |
| **Cálculo** | `StockActual = SUM(Beams_Produccion.Unidades_OK) - SUM(Beams_Consumos.Unidades_OK)` |

```sql
WITH Entradas AS (
    SELECT Cod_producto, SUM(Unidades_OK) AS TotalEntradas FROM OB.Beams_Produccion GROUP BY Cod_producto
),
Salidas AS (
    SELECT Cod_producto, SUM(Unidades_OK) AS TotalSalidas FROM OB.Beams_Consumos GROUP BY Cod_producto
)
SELECT b.BeamID, b.BeamCode AS Cod_producto,
    ISNULL(e.TotalEntradas, 0) AS Entradas,
    ISNULL(s.TotalSalidas, 0) AS Salidas,
    (ISNULL(e.TotalEntradas, 0) - ISNULL(s.TotalSalidas, 0)) AS StockActual  -- ⬅ SIN floor
FROM OB.Beams b
LEFT JOIN Entradas e ON b.BeamCode = e.Cod_producto
LEFT JOIN Salidas s ON b.BeamCode = s.Cod_producto
WHERE b.IsActive = 1;
```

> ⚠️ `StockActual` **no tiene `MAX(0, ...)`** → puede devolver valores negativos.

### 2.C.3 — Recalculo de `AssignedStock`/`AssignedStockBeam` en endpoint incremental

| Campo | Valor |
|-------|-------|
| **Archivo** | `api/appOMEGAS.py` |
| **Endpoint** | `POST /api/pedidos/incremental_sync` (o similar) |
| **Líneas** | 2450-2520 |
| **Tipo** | Recalculo completo de asignación para todos los pedidos |

Misma lógica que `auto_sync_sequenced()` pero bajo demanda. Lee `Stock_Omegas_New` + `Stock_Beams_New`, recalcula y hace UPDATE.

## 🔁 2.D — OPERACIONES QUE SINCRONIZAN STOCK

| # | Operación | Disparador | Frecuencia | Qué sincroniza |
|---|-----------|------------|------------|----------------|
| D.1 | `sp_Sync_Omegas_RawData` | SQL Agent Job | 5 min | `Omegas_Produccion` + `Omegas_Lecturas` desde MAPEX |
| D.2 | `sp_Sync_Beams_RawData` | `auto_sync_beams_stock()` (Python) | 15 seg | `Beams_Produccion` + `Beams_Consumos` desde MAPEX |
| D.3 | `sync_pending_orders()` | Arranque / manual / scheduler | Bajo demanda | `PedidosCabecera` + `PedidosLineas` desde MAPEX |
| D.4 | `auto_sync_sequenced()` | Hilo Python | 15 seg | `AssignedStock`/`AssignedStockBeam` en `PedidosSecuenciados` |

## 🩹 2.E — OPERACIONES QUE CORRIGEN STOCK

### 2.E.1 — Reset de Omega (`POST /api/reset_stock`)

| Paso | Operación | Tabla |
|------|-----------|-------|
| 1 | Guarda `MAX(Fecha_fin)` de producción existente | `Omegas_Produccion` |
| 2 | Guarda `MAX(fecha)` de lecturas existentes | `Omegas_Lecturas` |
| 3 | `DELETE FROM OB.Omegas_Produccion WHERE Cod_producto = @Cod_producto` | `Omegas_Produccion` |
| 4 | `DELETE FROM OB.Omegas_Lecturas WHERE producto = @Cod_producto` | `Omegas_Lecturas` |
| 5 | `UPDATE Last_Sync_omegas SET Last_Sync_Date = DATEADD(SECOND, 1, @LatestProdFinish)` | `Last_Sync_omegas` |
| 6 | Si `@NuevoStock ≠ 0`: `INSERT INTO Omegas_Produccion (...'AJUSTE_MANUAL'...)` | `Omegas_Produccion` |

### 2.E.2 — Reset de Beam (`POST /api/beams/stock/adjust`)

| Paso | Operación | Tabla |
|------|-----------|-------|
| 1 | `DELETE FROM OB.BeamStocks WHERE BeamID = @BeamID` | `BeamStocks` |
| 2 | `DELETE FROM OB.Beams_Produccion WHERE Cod_producto = @BeamCode` | `Beams_Produccion` |
| 3 | `DELETE FROM OB.Beams_Consumos WHERE Cod_producto = @BeamCode` | `Beams_Consumos` |
| 4 | `DELETE FROM OB.BeamSync_PostedTotals WHERE BeamID = @BeamID` | `BeamSync_PostedTotals` |
| 5 | `MERGE Last_Sync_Beams` (actualiza Last_Sync_Date a `GETDATE()`) | `Last_Sync_Beams` |
| 6 | Si `@NuevoStock ≠ 0`: Inserta en `Beams_Produccion` + `BeamStocks` + `MERGE BeamSync_PostedTotals` | Múltiples |
| 7 | `COMMIT TRANSACTION` | — |

> 🔴 **CRÍTICO**: El reset de Beam **no guarda las fechas máximas antes de borrar** (a diferencia del FIX de Omega). Solo pone `Last_Sync_Date = GETDATE()`. Si en ese momento hay producción en MAPEX con `Fecha_inicio < GETDATE() < Fecha_fin`, la condición OR del sync la reimportará.

## 📊 2.F — DIAGRAMA DE FLUJO COMPLETO DEL STOCK

```
MAPEX (mapexbp)
│
├── F_HIS_CT('WORKCENTER', 'DAY', 'PRODUCT') ──→ sp_Sync_Omegas_RawData (c/5min SQL Agent)
│   └── MERGE → OB.Omegas_Produccion (+)
│
├── his_lectura ──→ sp_Sync_Omegas_RawData (c/5min SQL Agent)
│   └── INSERT → OB.Omegas_Lecturas (-)
│
├── F_HIS_CT('WORKCENTER', 'DETAIL', 'PRODUCT')
│   ├──→ sp_Sync_Beams_RawData (c/15s Python thread)
│   │   ├── MERGE → OB.Beams_Produccion (+)  [JOIN: OB.Beams WHERE IsActive=1]
│   │   └── MERGE → OB.Beams_Consumos (-)    [JOIN: OB.Omegas W/C='C' con Beam asignado]
│   │
│   └──→ sp_Sync_Beams_RawData
│       └── MERGE → OB.BeamSync_PostedTotals (totales)
│
└── his_wam_pedido_cliente + his_wam_linea_pedido_cliente + V_Cfg_producto
    └──→ sync_pending_orders() (arranque/manual/diario)
        ├── INSERT → OB.PedidosCabecera (CWT, DS, EX, TB)
        └── INSERT → OB.PedidosLineas (UnidadesPedidas, UniValMapex)

        ┌──────────────────────────────────────────────┐
        │          VISTAS DE STOCK (read-only)          │
        ├──────────────────────────────────────────────┤
        │ Stock_Omegas_New = SUM(Prod) - COUNT(Lec)    │
        │ Stock_Beams_New  = SUM(Prod) - SUM(Cons)     │
        └──────────────┬───────────────────────────────┘
                       │
                       ▼
        auto_sync_sequenced() (c/15s Python thread)
        │
        ├── Lee Stock_Omegas_New → dict en memoria
        ├── Lee Stock_Beams_New  → dict en memoria
        ├── Itera pedidos secuenciados (PriorityOrder → Sequence)
        ├── Asigna min(necesario, disponible) → AssignedStock, AssignedStockBeam
        └── UPDATE OB.PedidosSecuenciados

        ⚠️ STOCK REAL NUNCA SE BLOQUEA NI SE DECREMENTA EN BD
        ⚠️ SOLO SE ACTUALIZA AssignedStock EN PedidosSecuenciados
```

## 🎯 HALLAZGOS CLAVE DEL PUNTO 2

1. **El stock nunca se bloquea**: `auto_sync_sequenced()` lee el stock, lo decrementa en un dict Python, y hace UPDATE de `AssignedStock`. Pero el stock "real" (las vistas) sigue intacto. Si dos instancias o dos iteraciones leen antes de que la otra escriba, **ambas asignan el mismo stock**.

2. **Dos fuentes de verdad para Beams**: `BeamStocks` (movimientos individuales) vs `Beams_Produccion + Beams_Consumos` (sync desde MAPEX). **La vista solo usa la segunda**. Los movimientos insertados por `sp_AddBeamStockMovement` son invisibles para el cálculo de stock.

3. **Los consumos de Beam no son consumos reales**: Son la producción de Omegas tipo C, bajo la asunción de relación 1:1. Si falla esa asunción, el stock de Beam descuadra.

4. **El reset de Beam no tiene la protección que sí tiene el reset de Omega** (no guarda fechas máximas antes de borrar).

---

# 📋 PUNTO 3 — Transacciones, Race Conditions y Concurrencia

## 🔐 3.A — TRANSACCIONES SQL

### 3.A.1 — Transacción en `sync_pending_orders()` (Python)

| Campo | Valor |
|-------|-------|
| **Archivo** | `api/appOMEGAS.py` L597-636 |
| **Método** | `sync_pending_orders()` |
| **Tipo** | Transacción manual (`autocommit = False`) |
| **Alcance** | DELETE de PedidosSecuenciados (terminales) + DELETE de PedidosLineas + DELETE de PedidosCabecera + INSERT de cabeceras + INSERT de líneas |
| **Protección** | `PEDIDOS_DB_LOCK` |

```python
conn_main.autocommit = False
try:
    # 1. DELETE PedidosSecuenciados (pedidos terminales)
    # 2. DELETE PedidosLineas (affected)
    # 3. DELETE PedidosCabecera (affected)
    # 4. INSERT PedidosCabecera
    # 5. INSERT PedidosLineas
    conn_main.commit()
except Exception:
    conn_main.rollback()
    raise
finally:
    conn_main.autocommit = True
```

**✅ Correcto**: Transacción bien formada con rollback en caso de error. Protegida por `PEDIDOS_DB_LOCK`. Pero opera sobre tablas de pedidos, **no sobre tablas de stock directamente**.

### 3.A.2 — Transacción en `sp_Reset_Beam_Stock`

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/sp_Reset_Beam_Stock.sql` L29-88 |
| **SP** | `OB.sp_Reset_Beam_Stock` |
| **Tipo** | `BEGIN TRANSACTION ... COMMIT / ROLLBACK` |
| **Alcance** | 4 DELETEs + 2 MERGEs + 2 INSERTs opcionales |

```sql
BEGIN TRANSACTION;
BEGIN TRY
    DELETE FROM OB.BeamStocks WHERE BeamID = @BeamID;
    DELETE FROM OB.Beams_Produccion WHERE Cod_producto = @BeamCode;
    DELETE FROM OB.Beams_Consumos WHERE Cod_producto = @BeamCode;
    DELETE FROM OB.BeamSync_PostedTotals WHERE BeamID = @BeamID;
    MERGE OB.Last_Sync_Beams ...;
    IF @NuevoStock <> 0
        INSERT INTO OB.Beams_Produccion ...;
        INSERT INTO OB.BeamStocks ...;
    MERGE OB.BeamSync_PostedTotals ...;
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH
```

**✅ Correcto**: Transacción atómica. Si algo falla, todo se revierte. Pero...

> 🔴 **PROBLEMA**: Durante la transacción, **no se bloquean las lecturas externas**. `auto_sync_beams_stock()` puede ejecutar `sp_Sync_Beams_RawData` concurrentemente y leer/escribir en las mismas tablas. El `DELETE` seguido del `MERGE` en `Last_Sync_Beams` puede interferir con el sync.

### 3.A.3 — Transacción en `sp_Reset_Omega_Stock`

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/sp_Reset_Omega_Stock.sql` / `SQL/FIX_sp_Reset_Omega_Stock.sql` |
| **SP** | `OB.sp_Reset_Omega_Stock` |
| **Tipo** | **Sin transacción explícita** |

```sql
-- No hay BEGIN TRANSACTION
DELETE FROM OB.Omegas_Produccion WHERE Cod_producto = @Cod_producto;
DELETE FROM OB.Omegas_Lecturas WHERE producto = @Cod_producto;
UPDATE OB.Last_Sync_omegas SET Last_Sync_Date = ...;
IF @NuevoStock <> 0
    INSERT INTO OB.Omegas_Produccion (...'AJUSTE_MANUAL'...);
```

> 🔴 **CRÍTICO**: **No hay `BEGIN TRANSACTION`**. Si el SP falla a mitad, los DELETEs ya se ejecutaron pero el INSERT de ajuste no → **stock perdido**. Además, al no tener transacción, el SQL Agent Job puede ejecutar `sp_Sync_Omegas_RawData` entre el DELETE y el INSERT y reimportar datos.

### 3.A.4 — `sp_Sync_Beams_RawData` y `sp_Sync_Omegas_RawData`

| Campo | Valor |
|-------|-------|
| **Tipo** | **Sin transacción explícita** en ninguno de los dos |

Ambos SPs ejecutan múltiples operaciones (MERGE + UPDATE + MERGE + UPDATE) sin `BEGIN TRANSACTION`. Cada sentencia se autocommitea individualmente.

> ⚠️ Si el SP falla a mitad de ejecución, la primera mitad de los datos ya está committed y la segunda no → **estado inconsistente**.

## 🏎️ 3.B — RACE CONDITIONS

### 3.B.1 — RACE CONDITION CRÍTICA: `auto_sync_sequenced()` vs `auto_sync_beams_stock()`

| Campo | Valor |
|-------|-------|
| **Archivo** | `api/appOMEGAS.py` |
| **Hilo A** | `auto_sync_sequenced()` (L737) — target `PedidosSync` |
| **Hilo B** | `auto_sync_beams_stock()` (L895) — target `BeamStockSync` |
| **Lock común** | ❌ **NO comparten lock** |

```
Timeline de la race condition:
═══════════════════════════════════════════════════════════════
T1: PedidosSync lee Stock_Beams_New → stock_beams = {B1: 10}
T2: BeamStockSync ejecuta sp_Sync_Beams_RawData
    → INSERT Beams_Consumos: B1 consume 5 unidades
    → Ahora Stock_Beams_New para B1 = 5
T3: PedidosSync asigna AssignedStockBeam = 10 a pedido (usando stock antiguo)
    → UPDATE PedidosSecuenciados SET AssignedStockBeam = 10
    → ⚠️ ASIGNÓ 10 CUANDO SOLO HABÍA 5
═══════════════════════════════════════════════════════════════
```

| Riesgo | **Stock negativo**: Se asigna más stock del que realmente existe |
|-------|-------|
| **Criticidad** | 🔴 **ALTA** |

**Código exacto:**

```python
# Hilo A: PedidosSync (L807-813)
cursor_main.execute("SELECT Cod_producto, StockActual FROM OB.Stock_Beams_New")
stock_beams = {row.Cod_producto: row.StockActual for row in cursor_main.fetchall()}
# ... (procesa pedidos, decrementa stock_beams en memoria, UPDATE PedidosSecuenciados)

# Hilo B: BeamStockSync (L895-916) — se ejecuta concurrentemente
def auto_sync_beams_stock():
    while True:
        with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
            cursor_main.execute("{CALL OB.sp_Sync_Beams_RawData}")  # ⬅ MODIFICA Beams_Consumos
        time.sleep(15)
```

### 3.B.2 — RACE CONDITION: `auto_sync_sequenced()` consigo misma

| Campo | Valor |
|-------|-------|
| **Archivo** | `api/appOMEGAS.py` L737-890 |
| **Protección** | `PEDIDOS_DB_LOCK` — pero solo contra `sync_pending_orders()` |

Aunque `auto_sync_sequenced()` usa `PEDIDOS_DB_LOCK`, **solo se锁a a sí misma contra `sync_pending_orders()`**. Si el intervalo es de 15 segundos y una iteración tarda más de 15 segundos, **dos iteraciones pueden solaparse**:

```python
# L739: Adquiere el lock al inicio del bucle
with PEDIDOS_DB_LOCK:
    with ConexionODBCCZ(database='DataLakeSCCZ') as conn_main:
        # ... procesa 200+ pedidos ...
        # Si esto tarda > 15 segundos, la siguiente iteración
        # esperará al lock, pero el stock ya cambió mientras tanto
```

| Riesgo | **Solapamiento de iteraciones**: Si el procesamiento tarda más del intervalo, la siguiente iteración usará datos parcialmente actualizados |
|-------|-------|
| **Criticidad** | 🟡 **MEDIA** |

### 3.B.3 — RACE CONDITION: Reset vs Sync

| Campo | Valor |
|-------|-------|
| **Escenario** | Usuario resetea stock de Beam mientras el sync está corriendo |

```
Timeline:
═══════════════════════════════════════════════════════════════
T1: BeamStockSync ejecuta sp_Sync_Beams_RawData → MERGE Beams_Consumos
T2: Usuario llama POST /api/beams/stock/adjust
    → sp_Reset_Beam_Stock: DELETE Beams_Consumos, DELETE Beams_Produccion
T3: BeamStockSync continúa → UPDATE Last_Sync_Beams basado en datos ya borrados
    → Last_Sync_Date queda desactualizado
T4: Siguiente sync → condición OR reimporta producción antigua
═══════════════════════════════════════════════════════════════
```

| Riesgo | **Datos inconsistentes y reimportación de producción antigua** |
|-------|-------|
| **Criticidad** | 🔴 **ALTA** |

### 3.B.4 — RACE CONDITION: `sp_Sync_Beams_RawData` con SQL Agent Job

| Campo | Valor |
|-------|-------|
| **Hilo A** | `auto_sync_beams_stock()` → `sp_Sync_Beams_RawData` (cada 15s) |
| **Proceso B** | SQL Agent Job → `sp_Sync_Omegas_RawData` (cada 5 min) |

Ambos leen de `mapexbp.dbo.F_HIS_CT()` y escriben en tablas del esquema `OB`. `sp_Sync_Beams_RawData` lee `OB.Omegas` para el JOIN de consumos (L197-200):

```sql
INNER JOIN OB.Omegas omega ON omega.Assy = f.Cod_producto
                           AND omega.[W/C] = 'C'
                           AND omega.Beam IS NOT NULL
```

Si `sp_Sync_Omegas_RawData` actualiza `OB.Omegas` concurrentemente, el JOIN de consumos puede ver datos inconsistentes.

| Riesgo | **Consumos mal calculados** si `OB.Omegas.Beam` cambia durante la ejecución |
|-------|-------|
| **Criticidad** | 🟡 **MEDIA** |

## 📖 3.C — LECTURAS SIN BLOQUEO (NOLOCK / READ UNCOMMITTED)

### 3.C.1 — Uso masivo de `WITH (NOLOCK)` en queries de vistas

| Archivo | `api/appOMEGAS.py` |
|---------|---------------------|
| **Líneas** | L3308-3520 (funciones `build_*_sql`) |

Todas las funciones que construyen queries SQL para endpoints usan `WITH (NOLOCK)`:

```sql
FROM OB.V_PedidosSummary_Secuenciados_Full ps WITH (NOLOCK)
LEFT JOIN OB.PedidosCabecera pc WITH (NOLOCK) ON ...
LEFT JOIN OB.Omegas o WITH (NOLOCK) ON ...
INNER JOIN OB.pedidos_exportados pe_lh WITH (NOLOCK)
```

| Riesgo | **Lecturas sucias (dirty reads)**: Puede leer datos no committeados o inconsistentes de transacciones en curso |
|-------|-------|
| **Criticidad** | 🟡 **MEDIA** — aceptable para consultas de solo lectura en pantallas, pero peligroso si se usa para tomar decisiones de stock |

### 3.C.2 — Lectura de stock sin bloqueo en `auto_sync_sequenced()`

```python
# L807-813: Lee stock sin ningún locking hint
cursor_main.execute("SELECT Cod_producto, StockActual FROM OB.Stock_Omegas_New")
cursor_main.execute("SELECT Cod_producto, StockActual FROM OB.Stock_Beams_New")
```

Estas lecturas usan el isolation level por defecto de pyodbc (`READ COMMITTED`). **No hay `WITH (UPDLOCK)` ni `WITH (HOLDLOCK)`**. Esto significa que:

1. Dos hilos pueden leer el mismo valor de stock simultáneamente
2. Ambos pueden decidir asignar ese stock a pedidos diferentes
3. El stock se "duplica" lógicamente

| Riesgo | **Sobre-asignación de stock**: Mismo stock asignado a múltiples pedidos |
|-------|-------|
| **Criticidad** | 🔴 **ALTA** |

## 🔀 3.D — ACTUALIZACIONES CONCURRENTES

### 3.D.1 — Múltiples escritores sobre `OB.PedidosSecuenciados`

| Escritor | Operación | Frecuencia |
|----------|-----------|------------|
| `auto_sync_sequenced()` | `UPDATE AssignedStock, AssignedStockBeam` | Cada 15s |
| `run_sequencing()` | `INSERT` nuevos pedidos | Bajo demanda |
| `sync_pending_orders()` | `DELETE` pedidos terminales | Arranque/manual/diario |
| `cleanup_sequenced_orders()` | `DELETE` pedidos que ya no cumplen criterios | Cada 60s |

Los 4 acceden a la misma tabla. `auto_sync_sequenced` y `sync_pending_orders` comparten `PEDIDOS_DB_LOCK`, pero `run_sequencing` y `cleanup_sequenced_orders` **no** están bajo ese lock.

### 3.D.2 — Múltiples escritores sobre tablas de stock

| Tabla | Escritores |
|-------|------------|
| `OB.Omegas_Produccion` | `sp_Sync_Omegas_RawData` (MERGE, c/5min) + `sp_Reset_Omega_Stock` (DELETE/INSERT, manual) |
| `OB.Omegas_Lecturas` | `sp_Sync_Omegas_RawData` (INSERT, c/5min) + `sp_Reset_Omega_Stock` (DELETE, manual) |
| `OB.Beams_Produccion` | `sp_Sync_Beams_RawData` (MERGE, c/15s) + `sp_Reset_Beam_Stock` (DELETE/INSERT, manual) |
| `OB.Beams_Consumos` | `sp_Sync_Beams_RawData` (MERGE, c/15s) + `sp_Reset_Beam_Stock` (DELETE/INSERT, manual) |
| `OB.Last_Sync_Beams` | `sp_Sync_Beams_RawData` (INSERT bootstrap + UPDATE) + `sp_Reset_Beam_Stock` (MERGE) |
| `OB.Last_Sync_omegas` | `sp_Sync_Omegas_RawData` (INSERT bootstrap + UPDATE) + `sp_Reset_Omega_Stock` (UPDATE) |

> 🔴 **Todas estas tablas tienen múltiples escritores concurrentes sin coordinación entre ellos.**

## ⚡ 3.E — OPERACIONES ASYNC NO CONTROLADAS

### 3.E.1 — 6 hilos daemon sin orquestación central

```python
# L5960-5995: Todos los hilos se lanzan secuencialmente sin coordinación
threading.Thread(target=run_startup_sync, daemon=True).start()       # StartupSync
threading.Thread(target=auto_sync_sequenced, daemon=True).start()    # PedidosSync
threading.Thread(target=auto_sync_beams_stock, daemon=True).start()  # BeamStockSync
threading.Thread(target=cleanup_sequenced_orders, daemon=True).start() # CleanupSync
threading.Thread(target=cleanup_old_unsequenced_orders, daemon=True).start()
threading.Thread(target=run_scheduler, daemon=True).start()          # DailyScheduler
```

| Problema | Detalle |
|----------|---------|
| **Sin orquestación** | No hay un manager que coordine el orden de arranque o dependencias |
| **Sin health check** | Si un hilo muere silenciosamente (ej. `BeamStockSync`), el stock de Beams deja de actualizarse sin alerta |
| **Sin backpressure** | Si `PedidosSync` va lento, las colas de trabajo no se gestionan |
| **`daemon=True`** | Si el proceso principal muere, los hilos mueren sin terminar su trabajo → **datos a medias** |

## 📊 3.F — DIAGRAMA DE CONCURRENCIA

```
┌─────────────────────────────────────────────────────────────────┐
│                     HILOS PYTHON (appOMEGAS.py)                  │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ PedidosSync  │  │BeamStockSync │  │    CleanupSync       │   │
│  │ (c/15s)      │  │ (c/15s)      │  │    (c/60s)           │   │
│  │              │  │              │  │                      │   │
│  │ LOCK:        │  │ LOCK:        │  │ LOCK:                │   │
│  │ PEDIDOS_DB   │  │ ❌ NINGUNO   │  │ ❌ NINGUNO           │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
│         │                 │                      │               │
│         │    ⚠️ RACE      │       ⚠️ RACE        │               │
│         │◄───────────────►│◄────────────────────►│               │
│         │                 │                      │               │
│         ▼                 ▼                      ▼               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              SQL SERVER (DataLakeSCCZ)                    │   │
│  │                                                          │   │
│  │  ┌─────────────────────┐  ┌────────────────────────────┐ │   │
│  │  │ sp_Sync_Omegas      │  │ sp_Sync_Beams_RawData      │ │   │
│  │  │ (SQL Agent c/5min)  │  │ (llamado por BeamStockSync) │ │   │
│  │  │ SIN TRANSACTION     │  │ SIN TRANSACTION            │ │   │
│  │  └─────────┬───────────┘  └──────────────┬─────────────┘ │   │
│  │            │                              │               │   │
│  │            ▼                              ▼               │   │
│  │  ┌─────────────────────┐  ┌────────────────────────────┐ │   │
│  │  │ Omegas_Produccion   │  │ Beams_Produccion           │ │   │
│  │  │ Omegas_Lecturas     │  │ Beams_Consumos             │ │   │
│  │  │ Last_Sync_omegas    │  │ Last_Sync_Beams            │ │   │
│  │  └─────────────────────┘  └────────────────────────────┘ │   │
│  │                                                          │   │
│  │  ⚠️ Tablas compartidas, escritores múltiples,            │   │
│  │     sin transacciones, sin bloqueo entre SPs             │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 📋 3.G — RESUMEN DE HALLAZGOS DEL PUNTO 3

| # | Hallazgo | Criticidad |
|---|----------|------------|
| 1 | `sp_Reset_Omega_Stock` **sin transacción** — DELETEs sin ROLLBACK posible | 🔴 ALTA |
| 2 | `auto_sync_sequenced` vs `auto_sync_beams_stock` **sin lock común** — race condition confirmada | 🔴 ALTA |
| 3 | Lectura de stock en `auto_sync_sequenced` **sin UPDLOCK/HOLDLOCK** — sobre-asignación | 🔴 ALTA |
| 4 | `sp_Sync_Beams_RawData` y `sp_Sync_Omegas_RawData` **sin transacción** — estado inconsistente si fallan | 🔴 ALTA |
| 5 | Reset de Beam vs Sync de Beams **sin coordinación** — reimportación de datos borrados | 🔴 ALTA |
| 6 | `WITH (NOLOCK)` masivo en queries de endpoints — dirty reads | 🟡 MEDIA |
| 7 | 6 hilos daemon sin health check — si uno muere, no hay alerta | 🟡 MEDIA |
| 8 | `run_sequencing` y `cleanup_sequenced_orders` fuera de `PEDIDOS_DB_LOCK` | 🟡 MEDIA |
| 9 | `daemon=True` en todos los hilos — trabajo puede quedar a medias al apagar | 🟢 BAJA |

---

# 📋 PUNTO 4 — Revisión de Stored Procedures

## 4.1 — `OB.sp_Sync_Omegas_RawData`

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/OB_sp_Sync_Omegas_RawData_fix_intradia.sql` |
| **Ejecutado por** | SQL Server Agent Job cada 5 minutos |
| **Transacción** | ❌ No |

### Estructura del SP

```
PASO 1: Bootstrap de Last_Sync_omegas
        INSERT INTO Last_Sync_omegas (PROD + LEC) para Omegas C/W que no tengan registro

PASO 2: MERGE Omegas_Produccion
        FROM mapexbp.dbo.F_HIS_CT('WORKCENTER', 'DAY', 'PRODUCT', ...)
        WHERE WorkGroup1 = '50 Assembly' AND Unidades_OK > 0
        Doble condición OR (Fecha_inicio >= LastSync) OR (Fecha_fin > LastSync AND Fecha_inicio < LastSync)

PASO 3: UPDATE Last_Sync_omegas (PROD)
        SET Last_Sync_Date = MAX(Fecha_fin) de Omegas_Produccion

PASO 4: INSERT Omegas_Lecturas
        FROM mapexbp.dbo.his_lectura
        WHERE fecha > Last_Sync_Date AND NOT EXISTS (mismo id_his_lectura)

PASO 5: UPDATE Last_Sync_omegas (LEC)
        SET Last_Sync_Date = MAX(fecha) de Omegas_Lecturas
```

### Operaciones detectadas

| Tipo | Tabla | Línea |
|------|-------|-------|
| `INSERT` | `Last_Sync_omegas` (bootstrap) | 10-23 |
| `MERGE` | `Omegas_Produccion` | 38-68 |
| `UPDATE` | `Last_Sync_omegas` (PROD) | 70-79 |
| `INSERT` | `Omegas_Lecturas` | 84-97 |
| `UPDATE` | `Last_Sync_omegas` (LEC) | 99-106 |

### 🔴 Riesgo: Condición OR en MERGE — reimportación de producción antigua

```sql
WHERE (f.WorkGroup1 = '50 Assembly' AND f.Unidades_OK > 0
       AND f.Fecha_inicio >= lso.Last_Sync_Date)          -- ✅ CONDICIÓN NORMAL
   OR (f.WorkGroup1 = '50 Assembly'
       AND f.Fecha_fin > lso.Last_Sync_Date                -- 🔴 CONDICIÓN PELIGROSA
       AND f.Fecha_inicio < lso.Last_Sync_Date)            -- Producción que empezó ANTES del reset
```

**Escenario de fallo:**
1. Producción de Omega X: 09:10 → 11:44 (20 unidades)
2. A las 10:53 se hace reset de stock → `Last_Sync_Date = 10:53`
3. Siguiente sync: `Fecha_fin(11:44) > Last_Sync_Date(10:53)` ✅ Y `Fecha_inicio(09:10) < Last_Sync_Date(10:53)` ✅
4. → Se reimporta la producción antigua → **stock inflado en 20 unidades**

> ✅ **El FIX** (`FIX_sp_Reset_Omega_Stock.sql`) mitiga esto poniendo `Last_Sync_Date = MAX(Fecha_fin) + 1s` antes de borrar. Pero el patrón de riesgo **sigue existiendo en el SP de sync**.

## 4.2 — `OB.sp_Sync_Beams_RawData`

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/sp_Sync_Beams_RawData.sql` |
| **Ejecutado por** | `auto_sync_beams_stock()` (Python) cada 15 segundos |
| **Transacción** | ❌ No |

### Estructura del SP

```
PASO 1: Bootstrap de Last_Sync_Beams
        INSERT para Beams activos que no tengan registro (PROD + CONS)

PASO 2: MERGE Beams_Produccion
        FROM F_HIS_CT('WORKCENTER', 'DETAIL', 'PRODUCT', ...)
        JOIN OB.Beams (IsActive=1) + JOIN Last_Sync_Beams (PROD)
        Doble condición OR (igual que Omegas)

PASO 3: UPDATE Last_Sync_Beams (PROD)
        SET Last_Sync_Date = MAX(Fecha_fin) de Beams_Produccion

PASO 4: MERGE Beams_Consumos
        FROM F_HIS_CT(...) 
        JOIN OB.Omegas (W/C='C', Beam IS NOT NULL)
        JOIN OB.Beams (IsActive=1)
        JOIN Last_Sync_Beams (CONS)

PASO 5: UPDATE Last_Sync_Beams (CONS)
        SET Last_Sync_Date = MAX(Fecha_fin) de Beams_Consumos

PASO 6: MERGE BeamSync_PostedTotals
```

### Operaciones detectadas

| Tipo | Tabla | Nota |
|------|-------|------|
| `INSERT` | `Last_Sync_Beams` | Bootstrap para PROD + CONS |
| `MERGE` | `Beams_Produccion` | Desde MAPEX |
| `UPDATE` | `Last_Sync_Beams` | Marca de agua PROD |
| `MERGE` | `Beams_Consumos` | ⚠️ No son consumos reales (ver abajo) |
| `UPDATE` | `Last_Sync_Beams` | Marca de agua CONS |
| `MERGE` | `BeamSync_PostedTotals` | Totales |

### 🔴 Riesgo: Consumos de Beam = Producción de Omegas C

```sql
-- L197-210: Los "consumos" NO vienen de una tabla de consumos
SELECT beam.BeamCode AS Cod_producto, omega.Assy AS WorkGroup,
       f.Fecha_inicio, f.Fecha_fin, CAST(f.Unidades_OK AS INT) AS Unidades_OK
FROM mapexbp.dbo.F_HIS_CT(...) f           -- ⬅ Datos de PRODUCCIÓN
INNER JOIN OB.Omegas omega 
    ON omega.Assy = f.Cod_producto          -- ⬅ f.Cod_producto es el Omega C producido
    AND omega.[W/C] = 'C'                   -- ⬅ Solo Omegas tipo C
    AND omega.Beam IS NOT NULL              -- ⬅ Que tengan Beam asignado
INNER JOIN OB.Beams beam 
    ON beam.BeamCode = omega.Beam           -- ⬅ El Beam asociado a ese Omega C
```

**La asunción implícita es**: "Cada Omega C producida consume exactamente 1 unidad del Beam asociado". Si esto no es cierto (ej. un Omega C no usa Beam, o usa 2 Beams), el stock descuadra.

## 4.3 — `OB.sp_Reset_Omega_Stock` (versión actual con FIX)

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/FIX_sp_Reset_Omega_Stock.sql` |
| **Ejecutado por** | `POST /api/reset_stock` |
| **Transacción** | ❌ No |

### Operaciones detectadas

| Tipo | Tabla | Línea |
|------|-------|-------|
| `SELECT MAX(Fecha_fin)` | `Omegas_Produccion` | 29-31 — guarda antes de borrar |
| `SELECT MAX(fecha)` | `Omegas_Lecturas` | 33-35 — guarda antes de borrar |
| `DELETE` | `Omegas_Produccion` | 38 |
| `DELETE` | `Omegas_Lecturas` | 39 |
| `UPDATE` | `Last_Sync_omegas` (PROD) | 43-45 — FIX: `DATEADD(SECOND, 1, MAX(Fecha_fin))` |
| `UPDATE` | `Last_Sync_omegas` (LEC) | 47-49 |
| `INSERT` | `Omegas_Produccion` | 52-54 — ajuste manual si `@NuevoStock ≠ 0` |

> ✅ El FIX **guarda las fechas máximas antes de borrar** y pone `Last_Sync_Date = MAX(Fecha_fin) + 1s`. Esto evita que el sync reimporte producción antigua.

> 🔴 Pero **sigue sin transacción**: los DELETEs no tienen ROLLBACK si algo falla después.

## 4.4 — `OB.sp_Reset_Beam_Stock`

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/sp_Reset_Beam_Stock.sql` |
| **Ejecutado por** | `POST /api/beams/stock/adjust` |
| **Transacción** | ✅ `BEGIN TRANSACTION ... COMMIT / ROLLBACK` |

### Operaciones detectadas

| Tipo | Tabla | Línea |
|------|-------|-------|
| `SELECT` | `OB.Beams` | 22-25 — validación de BeamCode |
| `DELETE` | `BeamStocks` | 32 |
| `DELETE` | `Beams_Produccion` | 34 |
| `DELETE` | `Beams_Consumos` | 36 |
| `DELETE` | `BeamSync_PostedTotals` | 38 |
| `MERGE` | `Last_Sync_Beams` | 41-53 |
| `INSERT` (cond.) | `Beams_Produccion` | 57-58 |
| `INSERT` (cond.) | `BeamStocks` | 60-61 |
| `MERGE` | `BeamSync_PostedTotals` | 63-73 |

> ✅ Tiene `BEGIN TRANSACTION` con `TRY/CATCH` y `ROLLBACK`. Es el **único SP con transacción correcta**.

> 🔴 Pero **NO guarda las fechas máximas antes de borrar** (a diferencia del FIX de Omega). Solo pone `Last_Sync_Date = GETDATE()`. Esto deja la puerta abierta a la reimportación por la condición OR del sync.

## 4.5 — `OB.sp_AddBeamStockMovement`

| Campo | Valor |
|-------|-------|
| **Archivo** | `SQL/sp_AddBeamStockMovement.sql` |
| **Transacción** | ❌ No |

### Operaciones detectadas

| Tipo | Tabla | Nota |
|------|-------|------|
| `SELECT` (validación) | `OB.Beams` | Verifica que el Beam existe |
| `SELECT` (validación) | `OB.Movement` | Verifica que el MovementID existe |
| `INSERT` | `OB.BeamStocks` | Con signo corregido según tipo de movimiento |

```sql
-- Movimientos de salida → fuerza negativo
IF @MovementID IN (2, 5, 7, 9) AND @Quantity > 0
    SET @FinalQuantity = @Quantity * -1;
-- Movimientos de entrada → fuerza positivo
ELSE IF @MovementID IN (1, 4, 6) AND @Quantity < 0
    SET @FinalQuantity = @Quantity * -1;

INSERT INTO OB.BeamStocks (BeamID, MovementID, Quantity, ID_Usuario, Notes)
VALUES (@BeamID, @MovementID, @FinalQuantity, @UsuarioID, @Notes);
```

> ⚠️ **IMPORTANTE**: Esta tabla (`BeamStocks`) no es usada por `Stock_Beams_New`. Existe un sistema paralelo de movimientos que no afecta al stock visible.

## 4.6 — TRIGGERS

| Resultado | No se han encontrado triggers en el código analizado |
|-----------|------------------------------------------------------|

Las tablas `Beams_Produccion` y `Beams_Consumos` usan `SYSTEM_VERSIONING` (temporal tables), pero no tienen triggers DML tradicionales. No hay evidencia de triggers en los scripts SQL del repositorio.

## 4.7 — RECÁLCULOS AUTOMÁTICOS

### 4.7.1 — Vista `Stock_Omegas_New` (recálculo bajo demanda)

Cada vez que se consulta la vista, recalcula:
```sql
StockActual = SUM(Omegas_Produccion.Unidades_OK) - COUNT(Omegas_Lecturas.id_his_lectura)
```

### 4.7.2 — Vista `Stock_Beams_New` (recálculo bajo demanda)

```sql
StockActual = SUM(Beams_Produccion.Unidades_OK) - SUM(Beams_Consumos.Unidades_OK)
-- Sin MAX(0, ...) → puede ser negativo
```

### 4.7.3 — `auto_sync_sequenced()` (recálculo de asignación cada 15s)

```python
# Recalcula AssignedStock para TODOS los pedidos cada 15 segundos
for pedido in pedidos_actuales:
    nuevo_stock_asignado_assy = min(cantidad_necesaria, stock_actual_para_assy)
    stock_disponible[assy] = max(0, stock_actual_para_assy - nuevo_stock_asignado_assy)
```

> ⚠️ Este recálculo parte de cero cada 15 segundos. Si un pedido ya tenía stock asignado pero ahora el stock real es menor, se reasigna menos stock → **el AssignedStock puede bajar entre iteraciones**, lo cual es correcto pero puede causar confusión en los operarios.

## 4.8 — TABLA DE SISTEMA DE VERSIONADO (Temporal Tables)

| Tabla | History Table |
|-------|---------------|
| `OB.Beams_Produccion` | `OB.Beams_Produccion_History` |
| `OB.Beams_Consumos` | `OB.Beams_Consumos_History` |

```sql
-- Definido en sp_Sync_Beams_RawData.sql L54-69
CREATE TABLE OB.Beams_Produccion (
    ...
    ValidFrom DATETIME2 GENERATED ALWAYS AS ROW START NOT NULL,
    ValidTo   DATETIME2 GENERATED ALWAYS AS ROW END NOT NULL,
    PERIOD FOR SYSTEM_TIME (ValidFrom, ValidTo),
    CONSTRAINT PK_Beams_Produccion PRIMARY KEY (Id),
    CONSTRAINT UQ_Beams_Produccion_Natural UNIQUE (Cod_producto, WorkGroup, Fecha_inicio)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = OB.Beams_Produccion_History));
```

> ✅ Positivo: Las temporal tables permiten auditoría histórica (quién cambió qué y cuándo). Pero **no se están consultando en ningún diagnóstico** actual.

## 📊 4.9 — RESUMEN VISUAL DE SPs

```
┌────────────────────────────────────────────────────────────────────┐
│                    STORED PROCEDURES DE STOCK                       │
├──────────┬──────────┬──────────┬──────────┬──────────┬────────────┤
│ SP       │ MERGE    │ INSERT   │ UPDATE   │ DELETE   │ TRANSACTION│
├──────────┼──────────┼──────────┼──────────┼──────────┼────────────┤
│ Sync     │ Omegas   │ Omegas   │ Last_Sync│ —        │ ❌ NO      │
│ Omegas   │ Produccion│ Lecturas │ (x2)    │          │            │
├──────────┼──────────┼──────────┼──────────┼──────────┼────────────┤
│ Sync     │ Beams    │ Last_Sync│ Last_Sync│ —        │ ❌ NO      │
│ Beams    │ Prod+Cons│ (boot)   │ (x2)    │          │            │
│          │ +Posted  │          │         │          │            │
├──────────┼──────────┼──────────┼──────────┼──────────┼────────────┤
│ Reset    │ —        │ Omegas   │ Last_Sync│ Omegas   │ ❌ NO      │
│ Omega    │          │ Produccion│ (x2)    │ Prod+Lec │            │
├──────────┼──────────┼──────────┼──────────┼──────────┼────────────┤
│ Reset    │ Last_Sync│ Beams    │ —        │ BeamStocks│ ✅ SI     │
│ Beam     │ +Posted  │ Prod+Stk │          │ Prod+Cons│ (único)   │
│          │          │          │          │ +Posted  │            │
├──────────┼──────────┼──────────┼──────────┼──────────┼────────────┤
│ Add      │ —        │ BeamStocks│ —       │ —        │ ❌ NO      │
│ Movement │          │          │          │          │            │
└──────────┴──────────┴──────────┴──────────┴──────────┴────────────┘
```

## 🎯 HALLAZGOS CLAVE DEL PUNTO 4

| # | Hallazgo | Criticidad |
|---|----------|------------|
| 1 | Ambos SPs de sync (`Omegas` y `Beams`) **sin transacción** — estado inconsistente si fallan a mitad | 🔴 ALTA |
| 2 | `sp_Reset_Omega_Stock` **sin transacción** — DELETEs sin protección | 🔴 ALTA |
| 3 | `sp_Sync_Beams_RawData` usa **producción de Omegas C como consumos de Beam** — asunción no validada | 🔴 ALTA |
| 4 | La condición OR de reimportación existe en **AMBOS** SPs de sync | 🔴 ALTA |
| 5 | `sp_Reset_Beam_Stock` **no guarda fechas máximas** antes de borrar — a diferencia del FIX de Omega | 🔴 ALTA |
| 6 | `sp_AddBeamStockMovement` escribe en tabla **no usada** por la vista de stock — datos huérfanos | 🟡 MEDIA |
| 7 | `SYSTEM_VERSIONING` en Beams está bien implementado pero **no se usa para diagnóstico** | 🟢 BAJA |

---

# 📋 INFORME FINAL — Puntos 5, 6 y 7

## 🔴 5 — INFORME DE RIESGOS POR ARCHIVO/MÉTODO (con criticidad)

### 🔴 CRITICIDAD ALTA

| # | Archivo | Método / SP | Riesgo | Explicación técnica |
|---|---------|-------------|--------|---------------------|
| **R1** | `api/appOMEGAS.py` L737-890 | `auto_sync_sequenced()` | **Race condition: stock sobre-asignado** | Lee `Stock_Omegas_New` y `Stock_Beams_New` sin `UPDLOCK`, decrementa en dict Python, hace UPDATE de `AssignedStock`. Si el sync de Beams (`auto_sync_beams_stock`) se ejecuta entre la lectura y la escritura, el stock real ya cambió pero `AssignedStock` se calculó con el valor antiguo. Dos pedidos pueden recibir el mismo stock. |
| **R2** | `api/appOMEGAS.py` L895 vs L737 | `auto_sync_beams_stock()` vs `auto_sync_sequenced()` | **Hilos sin lock común** | `BeamStockSync` (L895) modifica `Beams_Consumos` y `Beams_Produccion` vía `sp_Sync_Beams_RawData` cada 15s. `PedidosSync` (L737) lee esas mismas tablas cada 15s. No comparten `PEDIDOS_DB_LOCK`. Escenario: T1 lee stock=10, T2 sync reduce stock a 5, T3 asigna 10 → **stock negativo lógico**. |
| **R3** | `SQL/sp_Sync_Beams_RawData.sql` L120-240 | `sp_Sync_Beams_RawData` | **SP sin transacción** | Ejecuta MERGE (prod) + UPDATE (LastSync) + MERGE (cons) + UPDATE (LastSync) + MERGE (PostedTotals) secuencialmente sin `BEGIN TRANSACTION`. Si falla a mitad, la primera mitad está committeada y la segunda no → `Last_Sync_Date` desincronizado de los datos reales. |
| **R4** | `SQL/OB_sp_Sync_Omegas_RawData_fix_intradia.sql` L38-68 | `sp_Sync_Omegas_RawData` (MERGE) | **Condición OR reimporta producción reseteada** | `WHERE (Fecha_inicio >= LastSync) OR (Fecha_fin > LastSync AND Fecha_inicio < LastSync)`. La segunda condición captura producción que empezó antes del reset pero terminó después. Mismo bug que ya se parcheó en el reset de Omegas pero **sigue existiendo en el SP de sync**. |
| **R5** | `SQL/sp_Sync_Beams_RawData.sql` L197-240 | `sp_Sync_Beams_RawData` (consumos) | **Los consumos de Beam NO son consumos reales** | El MERGE de `Beams_Consumos` toma datos de `F_HIS_CT` (producción) filtrando por `OB.Omegas.[W/C]='C' AND Beam IS NOT NULL`. Asume relación 1:1 entre Omega C producida y Beam consumido. Si esta relación no es exacta, el stock de Beam descuadra sistemáticamente. |
| **R6** | `SQL/sp_Reset_Omega_Stock.sql` completo | `sp_Reset_Omega_Stock` | **Sin transacción** | Dos DELETEs + UPDATE + INSERT opcional sin `BEGIN TRANSACTION`. Si falla tras los DELETEs, el stock histórico se pierde sin posibilidad de rollback. |
| **R7** | `SQL/sp_Reset_Beam_Stock.sql` L41-53 | `sp_Reset_Beam_Stock` (MERGE LastSync) | **No guarda fechas máximas antes de borrar** | A diferencia del FIX de Omega, el reset de Beam pone `Last_Sync_Date = GETDATE()` sin consultar `MAX(Fecha_fin)` previo. Si hay producción en curso (Fecha_inicio < GETDATE() < Fecha_fin), el siguiente sync la reimporta → **stock inflado**. |
| **R8** | `api/appOMEGAS.py` L807-813 | `auto_sync_sequenced()` (lectura stock) | **Lectura sin locking hints** | `SELECT ... FROM Stock_Omegas_New` y `Stock_Beams_New` sin `WITH (UPDLOCK, HOLDLOCK)`. El isolation level por defecto (`READ COMMITTED`) solo garantiza que no lee datos uncommitted, pero no previene que otro proceso modifique los datos entre lectura y escritura. |

### 🟡 CRITICIDAD MEDIA

| # | Archivo | Método / SP | Riesgo | Explicación técnica |
|---|---------|-------------|--------|---------------------|
| **R9** | `api/appOMEGAS.py` L3308-3520 | `build_*_sql()` | **NOLOCK masivo en queries de endpoints** | Todas las funciones que construyen SQL para pantallas usan `WITH (NOLOCK)`. Esto permite dirty reads: un pedido podría mostrarse con stock asignado que aún no se ha committeado (o que se va a rollbackear). |
| **R10** | `api/appOMEGAS.py` L5960-5995 | `__main__` (arranque) | **6 hilos daemon sin health check** | Si `BeamStockSync` muere silenciosamente (ej. por error de conexión no capturado), el stock de Beams deja de actualizarse sin ninguna alerta. Todos los hilos son `daemon=True`: si el proceso principal muere, los hilos se interrumpen sin terminar su trabajo. |
| **R11** | `api/appOMEGAS.py` L2530-2920 | `run_sequencing()` | **Secuenciación sin lock contra sync** | `run_sequencing()` INSERTA en `PedidosSecuenciados` sin adquirir `PEDIDOS_DB_LOCK`. Si `auto_sync_sequenced()` está iterando los pedidos al mismo tiempo, puede procesar la lista a medias. |
| **R12** | `SQL/sp_AddBeamStockMovement.sql` | `sp_AddBeamStockMovement` | **Tabla BeamStocks no usada en cálculo de stock** | Los movimientos individuales (ventas, bajas, devoluciones) se insertan en `BeamStocks` pero `Stock_Beams_New` solo usa `Beams_Produccion` y `Beams_Consumos`. Cualquier movimiento registrado por este SP es **invisible** para el stock. |
| **R13** | `SQL/sp_Sync_Beams_RawData.sql` L197 | Consumos JOIN con `OB.Omegas` | **Dependencia de `OB.Omegas.Beam` poblado** | Si `OB.Omegas.Beam` es NULL para un Omega C, ese consumo no se registra → el stock del Beam queda inflado. Si `OB.Omegas.Beam` apunta al Beam equivocado → consumo mal atribuido. |

### 🟢 CRITICIDAD BAJA

| # | Archivo | Método / SP | Riesgo | Explicación técnica |
|---|---------|-------------|--------|---------------------|
| **R14** | `SQL/Stock_Beams_New.sql` | Vista `Stock_Beams_New` | **StockActual sin floor a 0** | `(ISNULL(e.TotalEntradas,0) - ISNULL(s.TotalSalidas,0)) AS StockActual` — devuelve negativo si salidas > entradas. Esto es un **síntoma**, no la causa. |
| **R15** | `SQL/sp_Sync_Beams_RawData.sql` | `@BootstrapSyncDate = DATEADD(MINUTE, -5, GETDATE())` | **Ventana de bootstrap fija** | Si el servidor estuvo caído >5 minutos, el bootstrap no cubre el hueco y se pierden datos de MAPEX de ese período. |
| **R16** | `api/appOMEGAS.py` L5960 | Hilo `StartupSync` | **Sync inicial sin verificación** | `run_startup_sync()` se lanza en background sin esperar a que termine. Si falla, el sistema arranca igual sin los pedidos sincronizados. |

---

## 📐 6 — DISEÑO DEL SISTEMA DE AUDITORÍA

### 6.1 — Tabla de auditoría: `OB.Stock_Audit`

```sql
CREATE TABLE OB.Stock_Audit (
    AuditID             BIGINT IDENTITY(1,1) PRIMARY KEY,
    AuditTimestamp      DATETIME2 NOT NULL DEFAULT GETDATE(),
    
    -- Identificación del material
    MaterialCode        VARCHAR(50) NOT NULL,          -- Código del Omega o Beam
    MaterialType        VARCHAR(10) NOT NULL,          -- 'OMEGA' o 'BEAM'
    
    -- Stock antes del cambio
    StockAnterior       INT NOT NULL,                  -- Stock antes de la operación
    
    -- Movimiento recibido
    MovimientoTipo      VARCHAR(30) NOT NULL,          -- 'PRODUCCION', 'CONSUMO', 'LECTURA', 'AJUSTE_MANUAL', 'RESET', 'ASIGNACION'
    MovimientoCantidad  INT NOT NULL,                  -- Cantidad del movimiento (+ entrada, - salida)
    MovimientoOrigen    VARCHAR(50) NOT NULL,          -- 'MAPEX', 'MANUAL', 'SYNC', 'API'
    MovimientoFuenteSP  VARCHAR(100) NULL,             -- SP que generó el cambio
    
    -- Stock después del cambio
    StockPosterior      INT NOT NULL,
    
    -- Flag de anomalía
    StockNegativo       BIT NOT NULL DEFAULT 0,        -- 1 si StockPosterior < 0
    
    -- Trazabilidad
    MensajeID           VARCHAR(100) NULL,             -- ID del mensaje/lote de MAPEX si aplica
    UsuarioID           INT NULL,                      -- Usuario que hizo el cambio manual
    ProcesoOrigen       VARCHAR(100) NULL,             -- 'auto_sync_beams_stock', 'auto_sync_sequenced', etc.
    Hostname            VARCHAR(100) NULL,             -- Servidor desde el que se ejecutó
    
    -- Datos adicionales
    StockRealMapex      INT NULL,                      -- Stock en MAPEX en ese momento (si se pudo consultar)
    Notas               NVARCHAR(1000) NULL,           -- Cualquier detalle relevante
    
    -- Índices
    INDEX IX_Stock_Audit_Material (MaterialCode, AuditTimestamp),
    INDEX IX_Stock_Audit_Negativo (StockNegativo, AuditTimestamp),
    INDEX IX_Stock_Audit_Timestamp (AuditTimestamp)
);
```

### 6.2 — TRIGGER de auditoría sobre la vista de stock

```sql
CREATE TRIGGER OB.TR_Stock_Audit_OnStockChange
ON OB.Beams_Consumos
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    
    DECLARE @AuditTimestamp DATETIME2 = GETDATE();
    
    -- Para cada Beam afectado, calcular stock antes/después y registrar
    INSERT INTO OB.Stock_Audit (
        MaterialCode, MaterialType, StockAnterior,
        MovimientoTipo, MovimientoCantidad, MovimientoOrigen, MovimientoFuenteSP,
        StockPosterior, StockNegativo, ProcesoOrigen, Hostname
    )
    SELECT 
        ISNULL(i.Cod_producto, d.Cod_producto),
        'BEAM',
        -- Stock anterior = stock actual - cambio
        ISNULL(sb.StockActual, 0) - ISNULL(ISNULL(i.Unidades_OK, 0) - ISNULL(d.Unidades_OK, 0), 0),
        'CONSUMO',
        ISNULL(i.Unidades_OK, 0) - ISNULL(d.Unidades_OK, 0),
        'MAPEX',
        'sp_Sync_Beams_RawData',
        ISNULL(sb.StockActual, 0),
        CASE WHEN ISNULL(sb.StockActual, 0) < 0 THEN 1 ELSE 0 END,
        'sp_Sync_Beams_RawData',
        HOST_NAME()
    FROM (
        SELECT Cod_producto, SUM(Unidades_OK) AS Unidades_OK FROM inserted GROUP BY Cod_producto
    ) i
    FULL OUTER JOIN (
        SELECT Cod_producto, SUM(Unidades_OK) AS Unidades_OK FROM deleted GROUP BY Cod_producto
    ) d ON i.Cod_producto = d.Cod_producto
    LEFT JOIN OB.Stock_Beams_New sb ON sb.Cod_producto = ISNULL(i.Cod_producto, d.Cod_producto);
END;
GO
```

> ⚠️ **Nota importante**: Los triggers en tablas con `SYSTEM_VERSIONING` requieren cuidado adicional. Alternativa más segura: modificar los SPs para que ellos mismos inserten en la tabla de auditoría.

### 6.3 — Versión alternativa: Auditoría dentro de los SPs (recomendado)

En lugar de triggers, añadir la auditoría **dentro de cada SP** que modifica stock:

```sql
-- Ejemplo: Añadir al final de sp_Sync_Beams_RawData
INSERT INTO OB.Stock_Audit (
    MaterialCode, MaterialType, StockAnterior,
    MovimientoTipo, MovimientoCantidad, MovimientoOrigen, MovimientoFuenteSP,
    StockPosterior, StockNegativo, ProcesoOrigen, MensajeID
)
SELECT 
    b.BeamCode, 'BEAM',
    ISNULL(sb_old.StockActual, 0),
    'CONSUMO',
    ISNULL(new_cons.Unidades_OK, 0),
    'MAPEX',
    'sp_Sync_Beams_RawData',
    ISNULL(sb_new.StockActual, 0),
    CASE WHEN ISNULL(sb_new.StockActual, 0) < 0 THEN 1 ELSE 0 END,
    'SQL_AGENT',
    CAST(@CurrentTime AS VARCHAR)
FROM ...
WHERE ISNULL(sb_new.StockActual, 0) < 0;  -- Solo registrar si stock queda negativo
```

### 6.4 — Auditoría en Python (`auto_sync_sequenced`)

```python
# Añadir dentro de auto_sync_sequenced(), después de calcular AssignedStockBeam:
if nuevo_stock_asignado_beam > 0 and stock_actual_para_beam - nuevo_stock_asignado_beam < 0:
    # REGISTRAR ANOMALÍA
    cursor_main.execute("""
        INSERT INTO OB.Stock_Audit (
            MaterialCode, MaterialType, StockAnterior,
            MovimientoTipo, MovimientoCantidad, MovimientoOrigen,
            StockPosterior, StockNegativo, ProcesoOrigen, Notas
        ) VALUES (?, 'BEAM', ?, 'ASIGNACION', ?, 'auto_sync_sequenced', ?, 1, 'auto_sync_sequenced', ?)
    """, (
        beam, stock_actual_para_beam, nuevo_stock_asignado_beam,
        stock_actual_para_beam - nuevo_stock_asignado_beam,
        f'Pedido {pedido.NumeroPedido} Assy {assy} asignó {nuevo_stock_asignado_beam} de {stock_actual_para_beam} disponible'
    ))
```

### 6.5 — Alerta automática por email

```python
# Función a ejecutar periódicamente (cada 5 min)
def check_stock_anomalies():
    with ConexionODBCCZ(database='DataLakeSCCZ') as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM OB.Stock_Audit
            WHERE StockNegativo = 1
              AND AuditTimestamp > DATEADD(MINUTE, -5, GETDATE())
        """)
        count = cursor.fetchone()[0]
        if count > 0:
            enviar_alerta_email(
                asunto=f'⚠️ ALERTA: {count} stock(s) negativo(s) detectados',
                cuerpo=f'Se detectaron {count} registros de stock negativo en los últimos 5 minutos.'
            )
```

---

## ⚠️ 7 — PUNTOS DONDE EL STOCK PUEDE QUEDAR EN ESTADO INCORRECTO

### 7.1 — STOCK MENOR QUE CERO

| # | Causa | Mecanismo | Probabilidad |
|---|-------|-----------|-------------|
| **N1** | Consumo antes de producción en MAPEX | El operario escanea (consume) el material antes de reportar la producción. MAPEX registra la lectura en `his_lectura` → el sync la importa → `Omegas_Lecturas` tiene la lectura pero `Omegas_Produccion` aún no tiene la producción → `StockActual = 0 - 1 = -1` | **Alta** (es el problema original) |
| **N2** | Beam consumido antes de ser producido | Similar a N1 pero para Beams: `Beams_Consumos` recibe el registro de consumo (producción del Omega C) antes de que `Beams_Produccion` tenga el registro del Beam → `StockActual < 0` | **Alta** |
| **N3** | Sobre-asignación por race condition | `auto_sync_sequenced` lee stock=10, asigna 10 al pedido A, pero `auto_sync_beams_stock` ya había consumido 5 en ese Beam → el sistema cree que hay stock para el pedido B pero no lo hay | **Media** |
| **N4** | Vista `Stock_Beams_New` sin `MAX(0,...)` | Si `SUM(Consumos) > SUM(Produccion)`, la vista devuelve negativo directamente. No es la causa raíz pero **visibiliza** el problema. | **Alta** (síntoma) |
| **N5** | Doble contabilización por condición OR | Tras un reset, la condición `OR (Fecha_fin > LastSync AND Fecha_inicio < LastSync)` reimporta producción antigua, inflando el stock. Luego los consumos reales lo bajan, pero mientras tanto el stock es artificialmente alto. Cuando llegan consumos no esperados → puede bajar a negativo. | **Alta** |

### 7.2 — STOCK DESINCRONIZADO RESPECTO A MAPEX

| # | Causa | Mecanismo |
|---|-------|-----------|
| **D1** | `Last_Sync_Date` mal actualizado | Si el SP de sync falla a mitad (sin transacción), `Last_Sync_Date` avanza pero los datos no se insertaron → MAPEX tiene datos que nunca se importarán. |
| **D2** | Bootstrap no cubre huecos | `@BootstrapSyncDate = DATEADD(MINUTE, -5, GETDATE())` en `sp_Sync_Beams_RawData`. Si el servicio estuvo caído >5 min, los datos de MAPEX en ese intervalo se pierden para siempre. |
| **D3** | Ventana diferente entre Omegas y Beams | Omegas usa `'DAY'` en `F_HIS_CT` y Beams usa `'DETAIL'`. Si MAPEX reporta a nivel de detalle datos que no aparecen en el resumen diario, hay descuadre. |
| **D4** | `sp_AddBeamStockMovement` no reflejado | Los movimientos individuales (ventas, bajas) registrados en `BeamStocks` no se reflejan en `Stock_Beams_New`. El stock visible no coincide con el stock real. |
| **D5** | `OB.Omegas.Beam` NULL o incorrecto | Si el campo `Beam` en `OB.Omegas` no está poblado o apunta al Beam equivocado, los consumos se atribuyen mal → el stock del Beam real no se descuenta y el del Beam equivocado se descuenta indebidamente. |

### 7.3 — STOCK INCONSISTENTE TRAS REINICIO DEL SERVICIO

| # | Causa | Mecanismo |
|---|-------|-----------|
| **I1** | Hilos `daemon=True` interrumpidos | Si el proceso Python se reinicia mientras `auto_sync_sequenced` estaba a mitad de iteración, algunos pedidos recibieron `AssignedStock` actualizado y otros no. Al reiniciar se recalcula desde cero, lo cual es correcto, pero la vista durante el reinicio muestra datos inconsistentes. |
| **I2** | `sync_pending_orders` al arranque | `run_startup_sync()` se lanza en background sin esperar. Si tarda 30s, durante ese tiempo las pantallas muestran pedidos desactualizados. |
| **I3** | SQL Agent Job vs hilo Python | Al reiniciar solo el proceso Python (no SQL Server), `BeamStockSync` se reinicia pero `sp_Sync_Omegas_RawData` (SQL Agent) sigue corriendo. Esto crea una ventana donde Omegas está actualizado pero Beams no, o viceversa. |
| **I4** | Cache de endpoints no invalidada | `ENDPOINT_RESPONSE_CACHE` (TTL 15s) puede devolver datos stale tras un reinicio si no se limpia explícitamente. |
| **I5** | `AssignedStock` en `PedidosSecuenciados` | Al arrancar, `auto_sync_sequenced` recalcula `AssignedStock` para todos los pedidos. Pero si la primera iteración tarda (muchos pedidos), las pantallas muestran `AssignedStock=0` (valor inicial del INSERT en `run_sequencing`) para pedidos nuevos. |

---

## 📊 RESUMEN EJECUTIVO FINAL

### Top 5 riesgos a corregir (por orden de prioridad)

| Prioridad | Riesgo | Acción recomendada |
|-----------|--------|-------------------|
| **1** | `auto_sync_beams_stock()` y `auto_sync_sequenced()` sin lock común (R1, R2) | Unificar bajo `PEDIDOS_DB_LOCK` o crear un lock separado compartido |
| **2** | SPs de sync sin transacciones (R3) | Envolver cada SP en `BEGIN TRANSACTION` con `TRY/CATCH` |
| **3** | Condición OR en MERGE de ambos SPs de sync (R4) | Eliminar la segunda condición `OR (Fecha_fin > LastSync AND Fecha_inicio < LastSync)` — ya no es necesaria si los resets se hacen bien |
| **4** | Reset de Beam no guarda fechas máximas (R7) | Aplicar el mismo FIX que `sp_Reset_Omega_Stock`: guardar `MAX(Fecha_fin)` antes de borrar y poner `Last_Sync_Date = MAX(Fecha_fin) + 1s` |
| **5** | Consumos de Beam = producción de Omegas C (R5) | Verificar con negocio si la relación es realmente 1:1. Si no, rediseñar la fuente de consumos |

### Acciones inmediatas (quick wins)

| # | Acción | Esfuerzo | Impacto |
|---|--------|----------|---------|
| 1 | Crear tabla `OB.Stock_Audit` y añadir INSERT en los SPs de sync | 2h | Permite detectar el problema cuando ocurra |
| 2 | Añadir `MAX(0, ...)` en la vista `Stock_Beams_New` | 5min | Evita mostrar negativos (aunque no soluciona la causa) |
| 3 | Añadir health check al hilo `BeamStockSync` con alerta email | 1h | Detecta caídas silenciosas del sync |
| 4 | Poner `PEDIDOS_DB_LOCK` también en `auto_sync_beams_stock()` | 5min | Elimina la race condition principal |

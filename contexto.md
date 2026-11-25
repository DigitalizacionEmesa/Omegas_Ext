┌─────────────────────────────────────────────────────────────────────┐
│                     FLUJO DE IMPORTACIÓN                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1️⃣ MAPEX (mapexbp)                                                │
│     ├─ his_wam_pedido_cliente  →  cabeceras de pedidos              │
│     └─ his_wam_linea_pedido_cliente + V_Cfg_producto → líneas      │
│                                                                     │
│  2️⃣ sync_pending_orders() — Clasificación de líneas               │
│     ┌──────────────────────────────────────────────────────────┐   │
│     │ Para cada línea, se busca su W/C en OB.Omegas:           │   │
│     │   W/C='CWT' → PedidosCabecera.CWT = Cod_Producto         │   │
│     │   W/C='DS'  → PedidosCabecera.DS  = Cod_Producto         │   │
│     │   W/C='EX'  → PedidosCabecera.EX  = Cod_Producto  ⬅️    │   │
│     │   W/C='TB'  → PedidosCabecera.TB  = Cod_Producto         │   │
│     │   W/C='CWI' → PedidosCabecera.CWI = Cod_Producto         │   │
│     │   (resto)   → Solo se guarda en PedidosLineas            │   │
│     └──────────────────────────────────────────────────────────┘   │
│                                                                     │
│  3️⃣ Inserción en DataLakeSCCZ:                                     │
│     ├─ OB.PedidosCabecera (1 fila por pedido)                       │
│     └─ OB.PedidosLineas (N filas, todas las líneas)                 │
│                                                                     │
│  4️⃣ Secuenciación (manual o auto) → OB.PedidosSecuenciados         │
│     └─ Se asigna Sequence, Assembly ('Yes C'/'Yes W')               │
│                                                                     │
│  5️⃣ Pantalla OB_C / OB_W                                           │
│     └─ endpoint consulta V_PedidosSummary_Secuenciados_Full         │
│        + 3 OUTER APPLYs para resolver Extender                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
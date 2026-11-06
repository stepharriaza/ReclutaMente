# Tablero Power BI - ReclutaMente (PBIP)

Proyecto Power BI (.pbip) generado para el tablero de evaluaciones de ReclutaMente.
Incluye modelo semántico (TMDL) y reporte (formato PBIR) con dos páginas.

> Estado: **experimental**. El proyecto se armó siguiendo el formato oficial PBIP/PBIR.
> Los 15 archivos JSON del reporte validan contra los esquemas oficiales de Microsoft
> (page 2.1.0, visualContainer 2.7.0, report 3.2.0, versionMetadata 1.0.0 y
> pagesMetadata 1.0.0). No se pudo validar abriéndolo en Power BI Desktop desde este
> entorno. Si algo falla, revisa la sección "Solución de problemas".

## Estructura

```
powerbi/
├── ReclutaMente.pbip
├── ReclutaMente.Report/
│   ├── definition.pbir
│   ├── StaticResources/SharedResources/BaseThemes/CY26SU02.json
│   └── definition/
│       ├── report.json
│       ├── version.json
│       └── pages/
│           ├── pages.json
│           ├── 1a2b3c4d5e6f708192a3/   (Resumen)
│           └── 2b3c4d5e6f708192a3b4/   (Detalle por prueba)
└── ReclutaMente.SemanticModel/
    ├── definition.pbism
    └── definition/
        ├── database.tmdl
        ├── model.tmdl
        └── tables/evaluaciones.tmdl
```

## Requisitos

- Power BI Desktop actualizado (versión con soporte PBIR, junio 2026 o superior).
- Activar las vistas previas en **Archivo > Opciones y configuración > Opciones > Características en versión preliminar**:
  - **Power BI Project (.pbip) save option**
  - **Store reports using enhanced metadata format (PBIR)**

## Cómo abrirlo

1. Abre `powerbi/ReclutaMente.pbip` con Power BI Desktop.
2. Deberías ver dos páginas:
   - **Resumen**: KPIs, puntaje IA por candidato, distribución por recomendación y tabla de detalle.
   - **Detalle por prueba**: puntaje promedio por prueba y tabla de intentos.
3. El modelo trae **datos de ejemplo** para que el reporte renderice sin credenciales.

## Conectar a tu Lakehouse `reclutamente_lh`

El modelo usa una partición de ejemplo (`#table(...)`) en
`ReclutaMente.SemanticModel/definition/tables/evaluaciones.tmdl`.
Reemplázala por la conexión real. En Power BI Desktop puedes hacerlo desde
**Transformar datos > Editor de Power Query**, o editar el TMDL.

### Opción A: SQL endpoint del Lakehouse

```m
let
    Origen = Sql.Database("TU_ENDPOINT.datawarehouse.fabric.microsoft.com", "reclutamente_lh"),
    dbo_evaluaciones = Origen{[Schema="dbo",Item="evaluaciones"]}[Data]
in
    dbo_evaluaciones
```

### Opción B: Fabric SQL Database / Warehouse

```m
let
    Origen = Sql.Database("TU_ENDPOINT.datawarehouse.fabric.microsoft.com", "reclutamente"),
    dbo_evaluaciones = Origen{[Schema="dbo",Item="evaluaciones"]}[Data]
in
    dbo_evaluaciones
```

La tabla/consulta debe llamarse `evaluaciones` y tener las mismas columnas que el
CSV que exporta la app (ver `FABRIC_CAMPOS_CSV` en `Reclutamente/views.py`):

```
generado_en, empresa_id, empresa_nombre, plaza_id, plaza_nombre,
persona_id, persona_nombre, persona_email, puntaje_ia, recomendacion_ia,
fortalezas_ia, brechas_ia, informe_ia, criterios, sesgo, sesgo_detalle,
intento_id, test_id, test_nombre, fecha_intento, puntaje_total,
puntaje_dimensiones_json, prueba_puntaje_ia, prueba_fortalezas_ia,
prueba_brechas_ia, prueba_informe_ia
```

Si tu tabla tiene otros nombres, renombra las columnas en Power Query o ajusta el TMDL.

## Medidas incluidas

| Medida | DAX |
|---|---|
| Total candidatos | `DISTINCTCOUNT(evaluaciones[persona_id])` |
| Total evaluaciones | `COUNTROWS(evaluaciones)` |
| Promedio puntaje IA | `AVERAGE(evaluaciones[puntaje_ia])` |
| Promedio puntaje pruebas | `AVERAGE(evaluaciones[puntaje_total])` |
| Candidatos recomendados | recomendación que empieza con "Recomendado" o contiene "Altamente" |
| % Recomendados | `DIVIDE([Candidatos recomendados], [Total candidatos])` |
| Brecha IA vs pruebas | `[Promedio puntaje IA] - [Promedio puntaje pruebas]` |

## Publicar y conectar con la app

1. En Power BI Desktop: **Publicar** en el workspace `ReclutaMente`.
2. En Fabric/Power BI, abre el reporte publicado.
3. **Archivo > Insertar informe > Sitio web o portal** y copia la URL.
4. Colócala en `.env` como `FABRIC_POWERBI_EMBED_URL`.
5. Opcional: coloca la URL del workspace en `FABRIC_WORKSPACE_URL`.

## Solución de problemas

- **"Cannot read properties of undefined (reading 'visualContainers')"**:
  suele ser un visual con un tipo o rol no soportado. Abre el `visual.json`
  problemático o elimínalo temporalmente.
- **El reporte abre vacío**: verifica que `version.json` sea `2.0.0` y que exista
  `StaticResources/SharedResources/BaseThemes/CY26SU02.json`.
- **No aparece el modelo**: revisa `ReclutaMente.Report/definition.pbir` y que la
  carpeta `ReclutaMente.SemanticModel` esté al mismo nivel.
- **Error al refrescar**: la partición de ejemplo no conecta a Fabric. Reemplázala
  por la conexión real (ver arriba).

## Alternativa si el PBIP no abre

Si Power BI Desktop rechaza el proyecto por diferencias de versión, la vía más
rápida es:

1. Crear un reporte en blanco en Power BI Desktop.
2. Conectar a tu tabla `evaluaciones` del Lakehouse.
3. Recrear los visuales con la especificación de la sección "Cómo abrirlo"
   (KPIs, barras, dona y tablas) y las medidas de la tabla de arriba.

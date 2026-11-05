# PRD — Sistema de Conciliación Bancaria

| | |
|---|---|
| **Stack actual** | Python · Django · SQLite (desarrollo) · openpyxl y ReportLab (exportación) |

---

## 1. Resumen

Aplicación web que compara la información del **banco** contra la de la **empresa** y detecta qué coincide, qué falta de cada lado y qué difiere. Su diferenciador es que **no exige que los archivos tengan el mismo formato ni la misma estructura**: el sistema interpreta cada archivo, lo lleva a un modelo común y lo compara con algoritmos. Donde los algoritmos no logran un emparejamiento seguro, **la persona revisa y corrige**.

## 2. Problema

Conciliar a mano es lento y propenso a errores:

- Cada banco exporta con columnas, formatos de fecha y signos distintos.
- La contabilidad de la empresa usa otra estructura (por ejemplo `cargo`/`abono` en lugar de un monto con signo).
- Los movimientos no siempre coinciden uno a uno: comisiones que solo conoce el banco, cheques en tránsito, depósitos agrupados, errores de captura.
- Encontrar la causa de una diferencia consume más tiempo que el cálculo en sí.

## 3. Objetivos

1. Aceptar archivos de **distintos formatos y estructuras** para cada lado de la conciliación.
2. Normalizar los datos a un **modelo común** sin que el usuario tenga que reformatear los archivos.
3. **Emparejar automáticamente** los movimientos con algoritmos transparentes, indicando el nivel de confianza.
4. **Reportar lo que falta**: movimientos en un solo lado, campos vacíos, duplicados, filas ilegibles.
5. Permitir que el usuario **revise y ajuste** los emparejamientos donde el sistema no pudo decidir.
6. Dejar **trazabilidad** de quién concilió qué y cuándo.

## 4. Alcance y no objetivos

**Dentro del alcance (producto completo)**
- Carga de archivos principales y complementarios por cada lado.
- Lectura de CSV, Excel (.xlsx) y, en etapas posteriores, PDF con texto e imágenes escaneadas.
- Mapeo de columnas (sugerido y manual), emparejamiento, revisión manual, reporte y exportación.

**Fuera del alcance (por ahora)**
- Contabilidad completa (pólizas, asientos, cierre contable).
- Conexión directa con APIs bancarias.
- Conciliación multi-moneda con tipo de cambio.
- Aprendizaje automático. Primero se usan reglas y puntuaciones explicables.

> **Sobre "cualquier tipo de archivo":** el objetivo es cubrir progresivamente los formatos más comunes. CSV y Excel son confiables; PDF y, sobre todo, imágenes escaneadas requieren extracción de texto/OCR y tienen errores de lectura. Por eso, para esos formatos la revisión humana es obligatoria y no opcional.

## 5. Usuarios

| Perfil | Necesidad |
|---|---|
| **Contador / auxiliar contable** (principal) | Conciliar rápido, entender las diferencias y corregir lo que el sistema no resolvió. |
| **Revisor / responsable** | Ver el resultado final, las partidas pendientes y quién hizo cada ajuste. |
| **Administrador** | Gestionar usuarios y cuentas. |

## 6. Flujo principal

```
Iniciar sesión
   → Nueva conciliación (rango de fechas por lado)
   → Cargar archivo principal + complementarios (banco y empresa)
   → Mapear columnas (sugerencia automática, ajuste manual)
   → Ejecutar análisis y emparejamiento
   → Revisar vista previa: conciliado / sugerido / pendiente
   → Ajustar manualmente lo no resuelto
   → Revisar reporte y exportarlo
```

## 7. Requerimientos funcionales

### 7.1 Acceso al sistema
- **RF-01** El sistema debe requerir un incio de sesion para acceder a cualquier pantalla. — **[Hecho]**
- **RF-02** Cada usuario debe ver unicamente sus propias conciliaciones. — **[Hecho]**
- **RF-03** El sistema debe mostrar un historial de conciliaciones y permitir reabrir cada una. — **[Hecho]**

### 7.2 Carga de archivos
- **RF-04** El usuario debe poder indicar un rango de fechas para el banco  otro para la empresa. — **[Hecho]** El rango también puede tomarse del archivo principal.
- **RF-05** El usuario debe poder cargar un archivo principal y varios complementarios. — **[Hecho]**
- **RF-06** El usuario debe poder cargar un archivo principal y varios complemetnarios en caso de ser necesario. — **[Hecho]** (es el mismo requerimiento que RF-05).
- **RF-07** El sistema debe abisar si un archivo complementario repite filas ya existentes o tiene columnas que no coinciden con el principal — **[Hecho]** Avisa filas repetidas entre archivos y columnas que no coinciden; no excluye las repetidas de los totales.
- **RF-08** El sistema debe aceptar distintos tipos de archivos (CSV, PDF, SWIFT, XLSX, etc.). — **[Parcial]** Hoy solo CSV; Excel es lo siguiente. PDF, SWIFT e imágenes están pendientes.

### 7.3 Interpretacion de datos
- **RF-09** El sistema debe detectar automaticamente codificacion, separador, formato de fecha y formato numerico. — **[Parcial]** En CSV detecta codificación (UTF-8/Latin-1), separador, 4 formatos de fecha y montos con `$`, comas y paréntesis; asume punto decimal.
- **RF-10** El sistema debe sugerir a que campo corresponde cada columna (fecha, monto, descripcion, referencia) y permitir al usuario corregirlo manualmente — **[Parcial]** Sugiere la columna por el nombre del encabezado; falta el selector manual.
- **RF-11** El sistema debe soportar montos en una sola columna con signo o en dos columnas (cargo y abono). — **[Hecho]**
- **RF-12** Las filas que no se puedan interpretar deben listarse con su motivo, nunca descartarse en silencio. — **[Hecho]** Se listan con archivo, número de fila y motivo (el reporte muestra hasta 5 ejemplos).

### 7.4 Comparacion y emparejamiento
- **RF-13** El sistema debe emparejar movimientos entre banco y empresa mediante reglas por capas (monto, fecha, tolerancia de dias, referencia). — **[Hecho]** 4 capas.
- **RF-14** Cada emparejamiento debe indicar la regla que lo origino y un nivel de confianza. — **[Hecho]**
- **RF-15** Si un movimiento tiene varios candidatos posibles, el sistema no debe emparejarlo solo, debe dejarlo como sugerencia. — **[Hecho]**
- **RF-16** El sistema debe soportar emparejamientos de uno a varios movimientos (una suma contra varios). — **[Parcial]** Se puede hacer manualmente (1 a varios y varios a varios); falta el emparejamiento automático.
- **RF-17** El sistema debe comparar por similitud de texto cuando no haya referencia. — **[Pendiente]**

### 7.5 Revision y ajustes manuales
- **RF-18** El sistema debe mostrar una vista previa con los movimientos de ambos lados y su estado (conciliado, sugerido, pendiente). — **[Hecho]** Tabla de coincidencias con estados, colores y filtros, además de la vista previa de los archivos.
- **RF-19** El usuario debe poder aceptar o rechazar una sugerencia. — **[Parcial]** Se puede aceptar; falta rechazar.
- **RF-20** El usuario debe poder emparejar movimientso manualmente, siempre que los totales en ambos lados coincidan. — **[Hecho]**
- **RF-21** El usuario debe poder deshacer cualquier ermparejamiento. — **[Hecho]**
- **RF-22** El usuario debe poder marcar una partida pendiente con una nota de justificacion. — **[Pendiente]** Hoy la nota se agrega al conciliar manualmente, no a una partida pendiente.
- **RF-23** El sistema debe registrar quien realizo cada accion y cuando — **[Parcial]** Se guarda quién y cuándo creó cada conciliación manual; falta registrar el deshacer y el resto de acciones.

### 7.6 Reporte 
- **RF-24** El reporte debe mostrar, por lado, el numero de movimientos, ingresos, egresos, neto y la diferencia entre ambos. — **[Hecho]**
- **RF-25** El reporte debe listar los datos faltantes: movimientos presentes solo en el banco, solo en la empresa, campos vacios, duplicados y filas no interpretadas. — **[Parcial]** Se listan los movimientos solo en el banco y solo en la empresa, y las filas repetidas o no interpretadas; los campos vacíos aún no se reportan.
- **RF-26** El reporte debe sugrerir la posible causa de cada partida pendiente cuando sea identificable (por ejemplo, comision bancaria). — **[Pendiente]** Hay sugerencias generales en los avisos, pero no una causa por partida.
- **RF-27** El usuario debe poder exportar el reporte (Excel o PDF). — **[Hecho]** Excel (4 hojas, con tabla de balance/match), PDF (con gráficas y observaciones) y CSV.

## 8. Modelo común de datos

Todo archivo, sin importar su origen, se transforma a un **movimiento normalizado**:

| Campo | Descripción |
|---|---|
| `origen` | `BANCO` o `EMPRESA` |
| `archivo` | Archivo del que proviene (trazabilidad) |
| `fila_original` | Número de fila o posición en el archivo |
| `fecha` | Fecha normalizada |
| `monto` | Decimal con signo: positivo = ingreso, negativo = egreso |
| `descripcion` | Texto normalizado (sin acentos, minúsculas, sin ruido) |
| `referencia` | Folio, número de factura, clave de rastreo, etc. |
| `estado` | `pendiente` · `sugerido` · `conciliado` |
| `conciliacion` | Grupo al que pertenece, si lo hay |

Esto es lo que permite comparar archivos que "no son los mismos": se comparan movimientos normalizados, no archivos.

> **Estado de implementación:** hoy los movimientos se normalizan en memoria cada vez que se abre la conciliación y no se guardan en la base de datos (incremento 1 de la hoja de ruta). Cada movimiento se identifica por su **archivo y su número de fila** (el encabezado es la fila 1), y así se guardan las conciliaciones manuales. El estado (`pendiente`, `sugerido`, `conciliado`, y `manual`) se calcula al emparejar.

## 9. Algoritmos de análisis

Se ejecutan por **capas**; lo que una capa empareja con seguridad sale del conjunto para la siguiente.

| Capa | Regla | Confianza | Estado |
|---|---|---|---|
| 1 | Monto exacto + misma fecha + misma referencia | Alta | **Hecho** (100 %) |
| 2 | Monto exacto + fecha dentro de la tolerancia (± N días) + referencia coincidente | Alta | **Hecho** (90 %) |
| 3 | Monto exacto + fecha en tolerancia, sin referencia | Media | **Hecho**, en dos pasos: misma fecha (75 %) y fecha dentro de la tolerancia (60 %) |
| 4 | Monto exacto + descripción similar (similitud de texto), fecha en tolerancia ampliada | Media | **Pendiente** |
| 5 | Suma de varios movimientos de un lado = un movimiento del otro (1 a N) | Media-baja → siempre a revisión | **Parcial**: solo de forma manual |
| 6 | Monto con diferencia pequeña + referencia igual (posible error de captura) | Baja → siempre a revisión | **Pendiente** |

Además de las capas, las conciliaciones manuales se aplican primero y sus movimientos salen del conjunto antes del emparejamiento automático. Un par solo se concilia automáticamente si **ambos movimientos tienen un único candidato** (unicidad mutua); si no, queda como sugerido.

**Criterios de decisión**
- Si una fila tiene un único candidato claro, se empareja.
- Si tiene varios candidatos con puntaje parecido, queda **sugerida** con las opciones.
- Si no hay candidatos, queda **pendiente** y se clasifica en el reporte.

**Detección automática de estructura**
- Columnas: por nombre de encabezado (sinónimos) y por el contenido (¿parece fecha?, ¿parece monto?).
- Fechas: prueba de varios formatos y se elige el que interpreta más filas.
- Números: manejo de separadores de miles/decimales, paréntesis como negativo y símbolos de moneda.

## 10. Requerimientos no funcionales

- **RNF-01** Los montos deben manejarse con precision decimal, nunca con punto flotante. — **[Hecho]**
- **RNF-02** Ante la duda, el sistema debe dejar un movimiento penditente en lugar de emparejarlo incorrectamente. — **[Hecho]**
- **RNF-03** Cada movimiento debe poder rastrearse hasta su archivo y su fila original. — **[Hecho]** Cada movimiento guarda su archivo y su fila; el Excel incluye la fila de origen.
- **RNF-04** Un archivo de hasta 10,000 filas debe procesarse en un tiempo razonable sin que la interfaz se congele. — **[Hecho]** Medido con 10,000 filas por lado (entorno de pruebas): abrir la conciliación ≈ 1 s, Excel ≈ 3 s, PDF ≈ 1 s. El procesamiento es síncrono.
- **RNF-05** Un usuario debe poder completar una conciliacion sin editar los archivos originales. — **[Parcial]** Se cumple con CSV cuyas columnas se reconocen por nombre; falta el selector manual.
- **RNF-06** La logica de emparejamiento debe estar separada de la interfaz y cubierta por pruebas automaticas. — **[Hecho]** El motor está en `services.py`, separado de la interfaz, con 62 pruebas automáticas.

## 11. Métricas de éxito

| Métrica | Meta inicial |
|---|---|
| % de movimientos emparejados automáticamente | ≥ 80 % en archivos limpios |
| Emparejamientos automáticos incorrectos | < 1 % |
| Tiempo para conciliar un periodo | Reducción frente al proceso manual actual |
| Ajustes manuales por conciliación | Tendencia a la baja conforme se afinan las reglas |

## 12. Riesgos

| Riesgo | Mitigación |
|---|---|
| Formatos muy distintos entre bancos | Mapeo manual de columnas siempre disponible |
| Lectura incorrecta de PDF/imagen | Dejar esos formatos para una etapa posterior y exigir revisión |
| Falsos emparejamientos | Puntaje de confianza, capas conservadoras y revisión de casos ambiguos |
| Archivos complementarios que duplican filas | Detección de duplicados antes de calcular totales |
| Datos financieros sensibles | Autenticación, permisos por usuario, almacenamiento seguro |

## 13. Hoja de ruta (por incrementos pequeños)

1. **Persistir movimientos** normalizados en la base de datos. — **[Pendiente]**
2. **Selector manual de columnas** y detección de duplicados. — **[Parcial]** Los duplicados se avisan; falta el selector manual.
3. **Emparejamiento 1 a 1** exacto (monto + fecha) con pruebas. — **[Hecho]**
4. **Estados en la vista previa** (colores) para revisar el resultado. — **[Hecho]** En la tabla de coincidencias.
5. **Tolerancias y referencia**; casos ambiguos a revisión. — **[Hecho]**
6. **Reporte de partidas pendientes** y datos faltantes. — **[Parcial]** Falta la causa probable por partida.
7. **Conciliación manual** y deshacer. — **[Hecho]** Faltan rechazar sugerencias y registrar el deshacer.
8. **Excel (.xlsx)** como formato de entrada. — **[Pendiente]**
9. **Exportación del reporte.** — **[Hecho]** Excel, PDF y CSV.
10. Etapas posteriores: 1 a N, PDF/OCR, roles y aprobación. — **[Pendiente]**

**Se implementó además, sin estar en la hoja de ruta:** rango de fechas automático a partir del archivo principal; conciliación manual de 1 a N y N a N; caja de avisos del reporte (errores, advertencias, sugerencias e informativos); cuadre de la diferencia (balance) en las exportaciones; y configuración sensible fuera del código mediante variables de entorno.

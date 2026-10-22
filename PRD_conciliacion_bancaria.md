# PRD — Sistema de Conciliación Bancaria

| | |
|---|---|
| **Stack actual** | Python · Django · SQLite (desarrollo) |

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
- **RF-01** El sistema debe requerir un incio de sesion para acceder a cualquier pantalla.
- **RF-02** Cada usuario debe ver unicamente sus propias conciliaciones.
- **RF-03** El sistema debe mostrar un historial de conciliaciones y permitir reabrir cada una.

### 7.2 Carga de archivos
- **RF-04** El usuario debe poder indicar un rango de fechas para el banco  otro para la empresa.
- **RF-05** El usuario debe poder cargar un archivo principal y varios complementarios.
- **RF-06** El usuario debe poder cargar un archivo principal y varios complemetnarios en caso de ser necesario.
- **RF-07** El sistema debe abisar si un archivo complementario repite filas ya existentes o tiene columnas que no coinciden con el principal
- **RF-08** El sistema debe aceptar distintos tipos de archivos (CSV, PDF, SWIFT, XLSX, etc.).

### 7.3 Interpretacion de datos
- **RF-09** El sistema debe detectar automaticamente codificacion, separador, formato de fecha y formato numerico.
- **RF-10** El sistema debe sugerir a que campo corresponde cada columna (fecha, monto, descripcion, referencia) y permitir al usuario corregirlo manualmente
- **RF-11** El sistema debe soportar montos en una sola columna con signo o en dos columnas (cargo y abono).
- **RF-12** Las filas que no se puedan interpretar deben listarse con su motivo, nunca descartarse en silencio.

### 7.4 Comparacion y emparejamiento
- **RF-13** El sistema debe emparejar movimientos entre banco y empresa mediante reglas por capas (monto, fecha, tolerancia de dias, referencia).
- **RF-14** Cada emparejamiento debe indicar la regla que lo origino y un nivel de confianza.
- **RF-15** Si un movimiento tiene varios candidatos posibles, el sistema no debe emparejarlo solo, debe dejarlo como sugerencia.
- **RF-16** El sistema debe soportar emparejamientos de uno a varios movimientos (una suma contra varios).
- **RF-17** El sistema debe comparar por similitud de texto cuando no haya referencia.

### 7.5 Revision y ajustes manuales
- **RF-18** El sistema debe mostrar una vista previa con los movimientos de ambos lados y su estado (conciliado, sugerido, pendiente).
- **RF-19** El usuario debe poder aceptar o rechazar una sugerencia.
- **RF-20** El usuario debe poder emparejar movimientso manualmente, siempre que los totales en ambos lados coincidan.
- **RF-21** El usuario debe poder deshacer cualquier ermparejamiento.
- **RF-22** El usuario debe poder marcar una partida pendiente con una nota de justificacion.
- **RF-23** El sistema debe registrar quien realizo cada accion y cuando

### 7.6 Reporte 
- **RF-24** El reporte debe mostrar, por lado, el numero de movimientos, ingresos, egresos, neto y la diferencia entre ambos.
- **RF-25** El reporte debe listar los datos faltantes: movimientos presentes solo en el banco, solo en la empresa, campos vacios, duplicados y filas no interpretadas.
- **RF-26** El reporte debe sugrerir la posible causa de cada partida pendiente cuando sea identificable (por ejemplo, comision bancaria).
- **RF-27** El usuario debe poder exportar el reporte (Excel o PDF).

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

## 9. Algoritmos de análisis

Se ejecutan por **capas**; lo que una capa empareja con seguridad sale del conjunto para la siguiente.

| Capa | Regla | Confianza |
|---|---|---|
| 1 | Monto exacto + misma fecha + misma referencia | Alta |
| 2 | Monto exacto + fecha dentro de la tolerancia (± N días) + referencia coincidente | Alta |
| 3 | Monto exacto + fecha en tolerancia, sin referencia | Media |
| 4 | Monto exacto + descripción similar (similitud de texto), fecha en tolerancia ampliada | Media |
| 5 | Suma de varios movimientos de un lado = un movimiento del otro (1 a N) | Media-baja → siempre a revisión |
| 6 | Monto con diferencia pequeña + referencia igual (posible error de captura) | Baja → siempre a revisión |

**Criterios de decisión**
- Si una fila tiene un único candidato claro, se empareja.
- Si tiene varios candidatos con puntaje parecido, queda **sugerida** con las opciones.
- Si no hay candidatos, queda **pendiente** y se clasifica en el reporte.

**Detección automática de estructura**
- Columnas: por nombre de encabezado (sinónimos) y por el contenido (¿parece fecha?, ¿parece monto?).
- Fechas: prueba de varios formatos y se elige el que interpreta más filas.
- Números: manejo de separadores de miles/decimales, paréntesis como negativo y símbolos de moneda.

## 10. Requerimientos no funcionales

- **RNF-01** Los montos deben manejarse con precision decimal, nunca con punto flotante.
- **RNF-02** Ante la duda, el sistema debe dejar un movimiento penditente en lugar de emparejarlo incorrectamente.
- **RNF-03** Cada movimiento debe poder rastrearse hasta su archivo y su fila original.
- **RNF-04** Un archivo de hasta 10,000 filas debe procesarse en un tiempo razonable sin que la interfaz se congele.
- **RNF-05** Un usuario debe poder completar una conciliacion sin editar los archivos originales.
- **RNF-06** La logica de emparejamiento debe estar separada de la interfaz y cubierta por pruebas automaticas.

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

1. **Persistir movimientos** normalizados en la base de datos.
2. **Selector manual de columnas** y detección de duplicados.
3. **Emparejamiento 1 a 1** exacto (monto + fecha) con pruebas.
4. **Estados en la vista previa** (colores) para revisar el resultado.
5. **Tolerancias y referencia**; casos ambiguos a revisión.
6. **Reporte de partidas pendientes** y datos faltantes.
7. **Conciliación manual** y deshacer.
8. **Excel (.xlsx)** como formato de entrada.
9. **Exportación del reporte.**
10. Etapas posteriores: 1 a N, PDF/OCR, roles y aprobación.
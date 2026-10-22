# MVP — Sistema de Conciliación Bancaria

| | |
|---|---|
| **Documento relacionado** | `PRD_conciliacion_bancaria.md` |

---

## 1. Objetivo del MVP

Demostrar que el sistema puede **comparar archivos con estructuras distintas, emparejar movimientos de forma confiable y dejar que el usuario corrija lo que el sistema no resuelve**, entregando un reporte útil de lo conciliado y lo faltante.

**Hipótesis a validar:** una persona concilia más rápido y con menos errores si el sistema normaliza los archivos, propone los emparejamientos y le muestra solo lo dudoso.

## 2. Alcance del MVP

### Incluido

| Área | Qué entra |
|---|---|
| Acceso | Login, historial de conciliaciones, nueva conciliación *(ya hecho)* |
| Archivos | Archivo principal + complementarios por lado, rango de fechas por lado *(ya hecho)* |
| Formatos | **CSV y Excel (.xlsx)** |
| Normalización | Modelo común de movimiento (fecha, monto con signo, descripción, referencia) |
| Mapeo de columnas | Sugerencia automática + selector manual |
| Emparejamiento | 1 a 1 por capas: monto + fecha, tolerancia de días y referencia |
| Confianza | Puntaje por emparejamiento; ambiguos quedan como "sugeridos" |
| Revisión | Vista previa con estados por color; aceptar, rechazar, emparejar a mano y deshacer |
| Reporte | Totales, diferencia, partidas pendientes por lado y datos faltantes |
| Exportación | Reporte en Excel o PDF (uno de los dos) |

### Fuera del MVP

- Distintos archivos utilizados para conciliaciones bancarias.
- Emparejamientos 1 a N y N a N.
- Aprendizaje automático.
- Roles, aprobación y cierre de periodo.
- Multi-moneda y conexión con APIs bancarias.
- Procesamiento en segundo plano (se evalúa si el volumen lo exige).

## 3. Historias de usuario

| ID | Historia | Prioridad |
|---|---|---|
| H1 | Como contador, quiero subir archivos con columnas distintas y confirmar a qué campo corresponde cada una, para no reformatear nada. | Alta |
| H2 | Como contador, quiero que el sistema empareje automáticamente lo evidente, para revisar solo lo dudoso. | Alta |
| H3 | Como contador, quiero ver por qué se emparejó cada movimiento, para confiar en el resultado. | Alta |
| H4 | Como contador, quiero emparejar o deshacer a mano, para resolver lo que el sistema no pudo. | Alta |
| H5 | Como contador, quiero un reporte con lo que está solo en el banco y solo en la empresa, para saber qué investigar. | Alta |
| H6 | Como contador, quiero que me avise de filas ilegibles o duplicadas, para que los totales no se distorsionen. | Media |
| H7 | Como revisor, quiero exportar el reporte, para archivarlo o compartirlo. | Media |

## 4. Incrementos de desarrollo

Cada incremento termina con algo que se puede **ejecutar y probar** antes de pasar al siguiente.

| # | Incremento | Resultado verificable |
|---|---|---|
| 1 | **Persistir movimientos** normalizados en la base de datos | La vista previa se ve igual, pero lee de la BD |
| 2 | **Selector manual de columnas** + detección de duplicados | El usuario confirma fecha/monto/referencia por archivo; los duplicados se avisan |
| 3 | **Emparejamiento 1 a 1 exacto** (monto + fecha) con pruebas automáticas | Un conjunto de ejemplo empareja lo esperado |
| 4 | **Estados y colores** en la vista previa | Filas conciliadas, sugeridas y pendientes distinguibles |
| 5 | **Tolerancia de días y referencia**; ambiguos a "sugeridos" | Los casos dudosos no se emparejan solos |
| 6 | **Reporte de pendientes y datos faltantes** | Lista por lado con su posible causa |
| 7 | **Emparejar a mano y deshacer** | Cualquier ajuste es reversible y queda registrado |
| 8 | **Entrada .xlsx** | Los mismos flujos funcionan con Excel |
| 9 | **Exportar reporte** | Archivo descargable con el resumen |

## 5. Reglas del MVP

**Modelo común del movimiento:** `origen`, `archivo`, `fila_original`, `fecha`, `monto` (Decimal con signo: positivo = ingreso, negativo = egreso), `descripcion`, `referencia`, `estado`, `conciliacion`.

**Capas de emparejamiento (de la más estricta a la más flexible):**
1. Monto exacto + misma fecha + misma referencia.
2. Monto exacto + fecha en tolerancia + referencia coincidente.
3. Monto exacto + fecha en tolerancia, sin referencia.

**Decisión:**
- Un solo candidato claro → **conciliado**.
- Varios candidatos parecidos → **sugerido** (el usuario elige).
- Ningún candidato → **pendiente**.

**Principios:** se prefiere dejar un caso pendiente antes que emparejarlo mal; ninguna fila se descarta en silencio; el dinero siempre se maneja con `Decimal`.

## 6. Criterios de aceptación

- [ ] Se puede conciliar un par de archivos con estructuras distintas (por ejemplo, `Monto` con signo contra `Cargo`/`Abono`) sin editarlos.
- [ ] Cada emparejamiento muestra la regla y el puntaje que lo originó.
- [ ] Los casos ambiguos nunca se emparejan automáticamente.
- [ ] El usuario puede crear, aceptar, rechazar y deshacer emparejamientos, y cada acción queda registrada.
- [ ] El reporte lista los movimientos solo en el banco, solo en la empresa y las filas no interpretadas.
- [ ] Los totales no cambian por filas duplicadas entre archivos principal y complementarios.
- [ ] El motor de emparejamiento tiene pruebas automáticas que cubren: monto igual con fechas distintas, duplicados, varios candidatos, filas inválidas y archivos vacíos.
- [ ] Cada usuario ve únicamente sus conciliaciones.

## 7. Métricas para considerar el MVP exitoso

| Métrica | Meta |
|---|---|
| Emparejamiento automático en archivos limpios de prueba | ≥ 80 % |
| Emparejamientos automáticos incorrectos | < 1 % |
| Conciliación de un periodo de ejemplo de principio a fin | Sin editar los archivos originales |
| Casos de prueba automáticos del motor | Todos pasan |

## 8. Datos de prueba

- Usar los CSV de ejemplo del proyecto (`sample_data/`) como base.
- Agregar casos que cubran: formato `cargo`/`abono`, separador `;`, fechas `DD/MM/YYYY`, comisiones solo en el banco, partidas solo en la empresa, movimientos repetidos y filas corruptas.
- Idealmente, validar con **al menos un extracto real** (con datos anonimizados) antes de dar el MVP por terminado.

## 9. Riesgos del MVP

| Riesgo | Mitigación |
|---|---|
| Los archivos reales no se parecen a los de prueba | Probar pronto con un extracto real y mantener el mapeo manual |
| Falsos emparejamientos | Capas conservadoras y revisión de ambiguos |
| Alcance que crece | Todo lo de la sección "Fuera del MVP" se pospone sin excepción |
| Totales distorsionados por duplicados | Detección de duplicados en el incremento 2 |

## 10. Definición de "terminado"

El MVP se considera terminado cuando se cumplen los criterios de aceptación de la sección 6, el reporte se puede exportar y el flujo completo (cargar → mapear → emparejar → revisar → reportar) se ha ejecutado con al menos un caso real o realista de principio a fin.

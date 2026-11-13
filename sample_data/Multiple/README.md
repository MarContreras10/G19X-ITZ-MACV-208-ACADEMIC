# Datasets para pruebas de conciliación bancaria

## 1. Descripción
Archivos para probar la plataforma de conciliación. El período es **octubre 2026**. 
El formato de fechas varía según el archivo para probar el parser.
- Banco: `Monto` con signo.
- Empresa: `Cargo` y `Abono` separados.

## 2. Instrucciones de Uso (Según la Interfaz)

1. **Rango de fechas:** Selecciona `01/10/2026` a `31/10/2026`. 
   (El archivo banco tiene una fila el `02/11/2026` que debe ser ignorada por el filtro).
2. **Carga Principal:** Sube `banco.csv` en BANCO y `empresa.csv` en EMPRESA.
3. **Complementarios:** 
   - Puedes subir `catalogo_folios.csv` en ambos lados como apoyo.
   - Puedes subir `empresa_renta_extra.csv` en el lado de EMPRESA para probar que el sistema concatena complementarios.
4. **Advertencia de Formatos:** 
   - `empresa.csv` usa separador `;` y fechas `DD/MM/YYYY`.
   - `banco.csv` usa separador `,` y fechas `YYYY-MM-DD`.

## 3. Archivos Principales (Base)
- **banco.csv / banco.xlsx / banco.txt**
- **empresa.csv / empresa.xlsx / empresa.txt**
*(Cualquier combinación de estos da el mismo resultado).*

## 4. Complementarios (Opcionales)
- `catalogo_folios.csv`: Tabla maestra. No afecta la conciliación, solo valida.
- `cuentas_contables.csv`: Catálogo de cuentas. Clasificación.
- `empresa_renta_extra.csv`: Fragmento de libro. Pruébalo subiéndolo en "Complementarios" para ver si tu sistema lo une al principal.

## 5. Escenarios Alternativos (Reemplazan a un principal)
- **Match exacto:** Sube `empresa_v2.csv` como principal en vez de `empresa.csv` (FAC-002 se mueve al 05/10 y concilia).
- **Duplicados:** Sube `banco_dup.csv` como principal en BANCO (FAC-001 está dos veces).
- **Diferencia de importe:** Sube `banco_monto_erroneo.csv` como principal (PAG-010 tiene -4250.50, no conciliará).
- **Conciliación Perfecta:** Sube `banco_sin_comision.csv` + `empresa_sin_renta.csv`.

## 6. Resultado Esperado (Principales + Filtro de Fecha)
- **Conciliadas:** FAC-001, PAG-010, NOM-01
- **Solo banco:** Comisión bancaria -150.00
- **Solo empresa:** REN-10 6000.00
- **Excluida por fecha:** 2026-11-02 -99.00 (No debe aparecer)
- **Diferencia de fecha:** FAC-002 (Banco 05/10, Empresa 04/10). Tu sistema decidirá si concilia por tolerancia o lo deja como pendiente.

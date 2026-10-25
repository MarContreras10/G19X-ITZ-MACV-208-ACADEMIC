# Conciliación bancaria

Aplicación web hecha con Django que compara los movimientos de un **extracto bancario** contra los de la **contabilidad de la empresa**, aunque los archivos tengan columnas, separadores o formatos de fecha distintos. Empareja automáticamente lo que coincide, reporta lo que falta y deja los casos dudosos para revisión.

---

## Qué incluye hasta ahora

- **Acceso:** inicio de sesión; cada usuario ve solo sus conciliaciones.
- **Inicio:** botón de nueva conciliación e historial.
- **Carga de archivos:** por cada lado (banco y empresa), un rango de fechas, un archivo principal y varios complementarios. Selectores con arrastrar y soltar.
- **Vista previa:** paneles desplazables con las filas de cada lado. Azul = banco, verde = empresa; los complementarios se distinguen con borde punteado y un **+**. Las columnas que se comparan aparecen resaltadas.
- **Tabla de coincidencias:** muestra cada movimiento como *Conciliado*, *Por revisar*, *Solo banco* o *Solo empresa*, con la regla aplicada y su confianza. Tiene filtros y una tolerancia de fecha ajustable.
- **Reporte:** tarjetas de resumen, totales (movimientos, ingresos, egresos, neto), diferencia banco − empresa y una caja desplegable de **avisos** (errores, advertencias, sugerencias e informativos).

## Requisitos

- **Python 3.10 o superior.**
- Las dependencias están fijadas en `requirements.txt` (Django 5.2 LTS y python-dotenv), por lo que todos instalan las mismas versiones con las que se probó el proyecto.
- Git (opcional, para clonar el repositorio).

## Instalación y ejecución

Los comandos son para **CMD de Windows**. En Linux o macOS cambia solo la activación del entorno virtual (se indica abajo).

```cmd
:: 1. Entrar a la carpeta del proyecto (donde está manage.py)
cd ruta\a\conciliacion_bancaria

:: 2. Crear y activar el entorno virtual
python -m venv .venv
.venv\Scripts\activate

:: 3. Instalar dependencias
pip install -r requirements.txt

:: 4. Crear tu archivo de configuración a partir de la plantilla
copy .env.example .env

:: 5. Generar una clave secreta y copiarla en .env (DJANGO_SECRET_KEY=...)
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

:: 6. Crear la base de datos - Actualmente es SQLite
python manage.py migrate

:: 7. Crear un usuario para iniciar sesión
python manage.py createsuperuser

:: 8. Iniciar el servidor
python manage.py runserver
```

Abre **http://127.0.0.1:8000/** e inicia sesión con el usuario del paso 7.

### Configuración (`.env`)

La configuración sensible **no está en el código**: se lee del archivo `.env`, que no se sube a Git. Si falta la clave, el proyecto no arranca y muestra un mensaje que lo indica.

| Variable | Obligatoria | Descripción |
|---|---|---|
| `DJANGO_SECRET_KEY` | Sí | Clave secreta de Django. Debe ser única y no compartirse. |
| `DJANGO_DEBUG` | No (por defecto `False`) | `True` solo en desarrollo. Con `True` Django muestra detalles internos cuando hay un error. |
| `DJANGO_ALLOWED_HOSTS` | No (por defecto `127.0.0.1,localhost`) | Dominios o IPs permitidos, separados por comas. |

Para trabajar en tu computadora, deja `DJANGO_DEBUG=True` en tu `.env`.

> En Linux/macOS activa el entorno con `source .venv/bin/activate`.

## Uso rápido

1. En **Inicio**, pulsa **+ Nueva conciliación**.
2. Elige el rango de fechas del banco y de la empresa.
3. Carga el archivo principal de cada lado y, si quieres, archivos complementarios.
4. Pulsa **Cargar y analizar**. Se abre la conciliación con la vista previa, las coincidencias y el reporte.
5. Para volver a analizar con otros archivos o fechas, cámbialos en la barra lateral y pulsa **Actualizar análisis**.

## Formato de los archivos

Por ahora solo se aceptan archivos **`.csv`** con encabezados en la primera fila.

| Dato | Nombres de columna reconocidos |
|---|---|
| Fecha | `fecha`, `date` |
| Monto | `monto`, `importe`, `amount` |
| Cargo / abono (alternativa al monto) | `cargo`, `retiro`, `debito` / `abono`, `deposito`, `credito` |
| Descripción | `descripcion`, `concepto`, `detalle`, `description` |
| Referencia | `referencia`, `folio`, `reference` |

- Se detectan solos la **codificación** (UTF-8 o Latin-1) y el **separador** (`,` `;` tabulador o `|`).
- Formatos de fecha aceptados: `AAAA-MM-DD`, `DD/MM/AAAA`, `DD-MM-AAAA` y `DD/MM/AA`.
- **Signo del monto:** positivo = ingreso, negativo = egreso. Con cargo y abono se calcula *abono − cargo*. Si un archivo usa la convención contraria, no habrá coincidencias; el reporte lo avisa.
- Los **complementarios** se alinean al principal por el nombre de la columna. Las columnas que el principal no tiene se ignoran (y se avisa).

## Cómo se empareja

Se exige siempre el **mismo monto** y se aplican capas, de la más estricta a la más flexible:

| Capa | Regla | Confianza |
|---|---|---|
| 1 | Monto, fecha y referencia exactos | 100 % |
| 2 | Monto y referencia; fecha dentro de la tolerancia | 90 % |
| 3 | Monto y fecha exactos | 75 % |
| 4 | Monto; fecha dentro de la tolerancia | 60 % |

Un par se concilia solo si **ambos movimientos tienen un único candidato**. Si hay más de uno, queda como **Por revisar** y no se empareja automáticamente. La tolerancia por defecto es de **3 días** y se cambia en la tabla de coincidencias (o con `?tol=N` en la URL).

---

## Pruebas

### Pruebas automáticas

```cmd
python manage.py test conciliaciones
```

(Requiere que exista tu archivo `.env` con la clave configurada.)

Cubren la lectura de archivos con formatos distintos, el emparejamiento (tolerancia, ambigüedad, referencia, unicidad) y las alertas del reporte.

### Pruebas con los datos de ejemplo

La carpeta `sample_data/` contiene:

| Archivo | Contenido |
|---|---|
| `banco.csv` | 5 movimientos de octubre + 1 de noviembre (fuera de rango). Separador `,`, monto con signo, fechas `AAAA-MM-DD`. |
| `empresa.csv` | 5 movimientos de octubre. Separador `;`, columnas `Cargo`/`Abono`, fechas `DD/MM/AAAA`. |
| `banco_complemento.csv` / `empresa_complemento.csv` | 2 movimientos más por lado (intereses y comisión SPEI). Traen una columna extra (`Notas`) que se ignora. |
| `banco_ambiguo.csv` / `empresa_ambiguo.csv` | Los mismos 2 movimientos anteriores, más 2 pagos de 50.00 que generan coincidencias ambiguas. |

**Rango de fechas base: del 01/10/2026 al 31/10/2026**, en banco y en empresa.

| # | Archivos | Rangos (banco / empresa) | Resultado esperado |
|---|---|---|---|
| 1 | `banco.csv` + `empresa.csv` | 01/10–31/10 / 01/10–31/10 | **4 conciliados**, 1 solo banco (comisión, −150), 1 solo empresa (renta, −6,000). Diferencia **5,850.00**. La fila de noviembre no aparece. |
| 2 | Principales + `banco_complemento.csv` y `empresa_complemento.csv` | 01/10–31/10 / 01/10–31/10 | **6 conciliados**; pendientes y diferencia iguales al caso 1. Aviso informativo de columnas ignoradas. |
| 3 | Principales + `banco_ambiguo.csv` y `empresa_ambiguo.csv` | 01/10–31/10 / 01/10–31/10 | **6 conciliados, 2 por revisar**; advertencia de coincidencia ambigua. |
| 4 | Solo principales | 01/10–05/10 / 01/10–05/10 | **3 conciliados**, 1 solo banco (comisión), 0 solo empresa. Diferencia −150.00. |
| 5 | Solo principales | 01/10–05/10 / 01/10–03/10 | Advertencia de **rangos distintos**. 2 conciliados y 2 solo banco (la factura del 04/10 queda fuera del rango de la empresa). |
| 6 | Solo principales, con `?tol=0` | 01/10–31/10 / 01/10–31/10 | **3 conciliados**: FAC-002 (05/10 en banco, 04/10 en empresa) deja de emparejarse. |
| 7 | Solo principales | 01/12–31/12 / 01/12–31/12 | **Error** «No hay movimientos interpretables» y aviso de que ninguna fila cae en el rango. |
| 8 | Cualquiera | 31/10–01/10 | Error de validación: la fecha final no puede ser anterior a la inicial. |

**Qué más verificar en la interfaz**
- Los filtros de la tabla (Conciliados, Por revisar, Solo banco, Solo empresa) muestran el número de filas indicado en cada botón.
- Los archivos complementarios aparecen con **+** y borde punteado, y cada fila indica su archivo de origen.
- La caja de **Avisos del análisis** se despliega y los avisos con detalle se expanden.
- Quitar un complementario con la **×** del panel *Archivos cargados* actualiza el análisis.
- Reabrir una conciliación desde el historial conserva las fechas elegidas.

---

## Estructura del proyecto

```
conciliacion_bancaria/
├── manage.py
├── requirements.txt             # Dependencias con versión fija
├── .env.example                 # Plantilla de configuración (se sube a Git)
├── .env                         # Tu configuración real (NO se sube a Git)
├── config/                      # Configuración de Django (settings, urls)
├── conciliaciones/
│   ├── models.py                # Conciliacion, ArchivoConciliacion
│   ├── forms.py                 # Formulario con archivos principal y complementarios
│   ├── views.py                 # Inicio, nueva conciliación, detalle, eliminar archivo
│   ├── services.py              # Lectura de CSV, emparejamiento y reporte
│   ├── urls.py
│   ├── tests.py
│   ├── migrations/
│   └── templates/
│       ├── registration/login.html
│       └── conciliaciones/      # base, home, conciliacion y componentes (_*.html)
├── sample_data/                 # CSV de ejemplo
└── media/                       # Archivos subidos (se genera solo)
```

## Para subir a Git

Crea un `.gitignore` en la raíz con:

```
.venv/
__pycache__/
*.pyc
db.sqlite3
media/
.env
```

## Limitaciones conocidas

- Solo CSV (Excel, PDF, otros archivos e imágenes están pendientes).
- Los movimientos no se guardan en la base de datos: se vuelven a leer de los archivos en cada consulta.
- La tolerancia de fecha no se guarda; vuelve a 3 días al recargar la página.
- Todavía no hay conciliación manual ni deshacer; los casos *Por revisar* solo se muestran.
- El reporte no se puede exportar.
- Pensado para desarrollo local con SQLite. Antes de publicarlo en un servidor: `DJANGO_DEBUG=False`, una `DJANGO_SECRET_KEY` nueva y `DJANGO_ALLOWED_HOSTS` con tu dominio, una base de datos de producción, HTTPS y un servidor de producción en lugar de `runserver`.

## Documentación relacionada

- `PRD_conciliacion_bancaria.md`: visión y requerimientos de producto.
- `MVP_conciliacion_bancaria.md`: alcance del MVP e incrementos de desarrollo.
- `Requerimientos_conciliacion_bancaria.docx`: requerimientos funcionales y no funcionales.
- `conciliacion_bancaria.sql`: esquema objetivo de la base de datos.

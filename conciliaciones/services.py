"""Lectura de archivos CSV, emparejamiento de movimientos y reporte de la conciliación."""
import codecs
import csv
import io
import re
import unicodedata
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook

FORMATOS_FECHA = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y")
MAX_FILAS_VISTA = 1000
TOLERANCIA_DIAS = 3
NIVELES = ("error", "advertencia", "sugerencia", "info")
ETIQUETAS_LADO = {"BANCO": "Banco", "EMPRESA": "Empresa"}
CERO = Decimal("0.00")
CLAVES_FECHA = ("fecha", "date")

# Formatos de archivo que se pueden cargar. Es la única lista: formularios, endpoint y JavaScript la usan.
EXTENSIONES_ACEPTADAS = (".csv", ".txt", ".tsv", ".xlsx")
FORMATOS_TEXTO = "CSV, TXT, TSV o XLSX"
MAX_BYTES_ARCHIVO = 25 * 1024 * 1024      # tamaño máximo de un archivo subido
MAX_FILAS_ARCHIVO = 200_000
MAX_DESCOMPRIMIDO = 150 * 1024 * 1024     # un .xlsx es un zip: se limita lo que ocupa al descomprimirlo


def extension_valida(nombre):
    return (nombre or "").lower().endswith(EXTENSIONES_ACEPTADAS)


class ErrorArchivo(Exception):
    pass


# ---------------------------------------------------------------- utilidades
def _norm(texto):
    sin_acentos = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in sin_acentos if unicodedata.category(c) != "Mn").strip().lower()


def _fmt_fecha(f):
    return f.strftime("%d/%m/%Y")


def _fmt_monto(m):
    return f"{m:,.2f}"


def _aviso(nivel, titulo, detalle="", origen=""):
    return {"nivel": nivel, "titulo": titulo, "detalle": detalle, "origen": origen}


def _buscar(columnas, claves):
    for i, c in enumerate(columnas):
        n = _norm(c)
        if any(k in n for k in claves):
            return i
    return None


_FECHA_SERIAL = re.compile(r"^\d{5}(?:\.0+)?$")


def _fecha(texto):
    """Interpreta una fecha. Acepta los formatos de FORMATOS_FECHA, con hora opcional
    («2026-10-01 14:35») y el número de serie de Excel (p. ej. 46296)."""
    t = (texto or "").strip()
    if not t:
        return None
    for candidato in (t, re.split(r"[ T]", t, maxsplit=1)[0]):
        for fmt in FORMATOS_FECHA:
            try:
                return datetime.strptime(candidato, fmt).date()
            except ValueError:
                continue
    if _FECHA_SERIAL.match(t):
        n = int(float(t))
        if 20000 <= n <= 80000:           # de 1954 a 2118: descarta números que no son fechas
            return date(1899, 12, 30) + timedelta(days=n)
    return None


# Montos: el separador decimal puede ser punto («1,234.50») o coma («1.234,50»). Se decide por
# archivo a partir de los valores que lo dejan claro; ante la duda se avisa y nunca se adivina.
_PREFIJO = r"\(?-?\$?-?"
_SUFIJO = r"\)?-?"
_COMA_DECIMAL = re.compile(rf"^{_PREFIJO}(?:\d{{1,3}}(?:\.\d{{3}})+|\d+),\d{{1,2}}{_SUFIJO}$")
_PUNTO_DECIMAL = re.compile(rf"^{_PREFIJO}(?:\d{{1,3}}(?:,\d{{3}})+|\d+)\.\d{{1,2}}{_SUFIJO}$")
_PUNTO_MILES = re.compile(rf"^{_PREFIJO}\d{{1,3}}(?:\.\d{{3}})+{_SUFIJO}$")   # «1.234»: ¿miles o 3 decimales?


def _limpio(texto):
    return re.sub(r"[\s\u00a0]", "", texto or "")


def convencion_decimal(valores):
    """Decide si una columna de montos usa punto o coma como separador decimal.

    Devuelve {"convencion": "." o ",", "coma": n, "punto": n, "ambiguos": n}. `coma` y `punto`
    cuentan los valores que solo son válidos con esa convención; si ambos son mayores que cero la
    columna mezcla formatos. `ambiguos` cuenta valores como «1.234» cuando no hay ninguna pista más.
    """
    coma = punto = miles = 0
    for v in valores:
        t = _limpio(v)
        if _COMA_DECIMAL.match(t):
            coma += 1
        elif _PUNTO_DECIMAL.match(t):
            punto += 1
        elif _PUNTO_MILES.match(t):
            miles += 1
    return {"convencion": "," if coma > punto else ".", "coma": coma, "punto": punto,
            "ambiguos": miles if not (coma or punto) else 0}


def _contradice(texto, convencion):
    """True si el valor solo es válido con la convención contraria a la del archivo."""
    t = _limpio(texto)
    return bool((_COMA_DECIMAL if convencion == "." else _PUNTO_DECIMAL).match(t))


def _monto(texto, convencion="."):
    """Convierte texto a Decimal. Acepta `$`, paréntesis o guion final como negativo y
    separadores de miles. Devuelve None si no es un número válido y finito."""
    t = _limpio(texto).replace("$", "")
    if not t:
        return None
    negativo = t.startswith("(") and t.endswith(")")
    if negativo:
        t = t[1:-1]
    if t.endswith("-"):
        t = "-" + t[:-1].lstrip("-")
    t = t.replace(".", "").replace(",", ".") if convencion == "," else t.replace(",", "")
    try:
        valor = Decimal(t)
    except InvalidOperation:
        return None
    if not valor.is_finite():              # «NaN» o «Infinity» no son montos
        return None
    return -valor if negativo else valor


# ------------------------------------------------------------------ lectura
def _bytes_de(archivo):
    try:
        archivo.open("rb")
        datos = archivo.read()
    except (OSError, ValueError) as e:
        raise ErrorArchivo(f"No se pudo abrir el archivo: {e}")
    finally:
        try:
            archivo.close()
        except Exception:
            pass
    if len(datos) > MAX_BYTES_ARCHIVO:
        raise ErrorArchivo(f"El archivo pesa más de {MAX_BYTES_ARCHIVO // (1024 * 1024)} MB.")
    return datos


def _decodificar(datos):
    """Texto del archivo. Detecta UTF-8/16/32 por su marca (BOM), UTF-16 sin marca por sus bytes
    nulos y, si no, UTF-8 o Windows-1252 (con Latin-1 como último recurso)."""
    if datos.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return datos.decode("utf-32")
    if datos.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return datos.decode("utf-16")
    if datos.startswith(codecs.BOM_UTF8):
        return datos.decode("utf-8-sig")
    muestra = datos[:400]
    if muestra and muestra.count(b"\x00") > len(muestra) // 4:       # UTF-16 sin marca
        codificacion = "utf-16-le" if muestra[1::2].count(b"\x00") >= muestra[0::2].count(b"\x00") else "utf-16-be"
        try:
            return datos.decode(codificacion)
        except UnicodeDecodeError:
            pass
    for codificacion in ("utf-8", "cp1252"):
        try:
            return datos.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return datos.decode("latin-1")


def _nombres_de_columnas(encabezado, ancho):
    """Nombres de columna; las que no tienen encabezado se llaman «Columna N»."""
    return [(str(encabezado[i]).strip() if i < len(encabezado) and str(encabezado[i]).strip() else f"Columna {i + 1}")
            for i in range(ancho)]


def _leer_texto(datos):
    """CSV, TXT o TSV: separador detectado (`,` `;` tabulador o `|`); el encabezado es la primera fila con datos."""
    if datos.startswith(b"%PDF"):
        raise ErrorArchivo(f"Parece un PDF. Por ahora solo se leen archivos {FORMATOS_TEXTO}.")
    if datos.startswith(b"\xd0\xcf\x11\xe0"):
        raise ErrorArchivo("Parece un Excel antiguo (.xls). Guárdalo como .xlsx e inténtalo de nuevo.")
    texto = _decodificar(datos)
    if not texto.strip():
        raise ErrorArchivo("El archivo está vacío.")
    if "\x00" in texto[:4000]:
        raise ErrorArchivo("El archivo no parece de texto (contiene caracteres nulos). "
                           "Si viene de Excel, guárdalo como .xlsx o como CSV UTF-8.")
    try:
        dialecto = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t|")
    except csv.Error:
        dialecto = csv.excel
    try:
        filas = list(csv.reader(io.StringIO(texto), dialecto))
    except csv.Error as e:
        raise ErrorArchivo(f"No se pudo leer como texto delimitado: {e}")
    if len(filas) > MAX_FILAS_ARCHIVO + 1:
        raise ErrorArchivo(f"El archivo tiene más de {MAX_FILAS_ARCHIVO:,} filas.")
    inicio = next((i for i, f in enumerate(filas) if any(c.strip() for c in f)), None)
    if inicio is None:
        raise ErrorArchivo("El archivo está vacío.")
    columnas = [c.strip() for c in filas[inicio]]
    cuerpo, numeros = [], []
    for n, f in enumerate(filas[inicio + 1:], start=inicio + 2):
        if not any(c.strip() for c in f):
            continue
        f = [c.strip() for c in f][: len(columnas)]
        f += [""] * (len(columnas) - len(f))
        cuerpo.append(f)
        numeros.append(n)
    return columnas, cuerpo, numeros, []


def _celda_a_texto(v):
    """Valor de una celda de Excel como texto, en la forma que espera el resto del sistema:
    fechas en ISO, números sin ceros ni ruido de coma flotante."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, bool):
        return "Sí" if v else "No"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return ""
        if v.is_integer():
            return str(int(v))
        return format(Decimal(repr(round(v, 8))), "f")
    return str(v).strip()


def _leer_xlsx(datos):
    """Excel (.xlsx): primera hoja visible con datos; el encabezado es su primera fila con contenido."""
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            infos = z.infolist()
            if len(infos) > 5000 or sum(i.file_size for i in infos) > MAX_DESCOMPRIMIDO:
                raise ErrorArchivo("El archivo de Excel es demasiado grande una vez descomprimido.")
            if "xl/workbook.xml" not in set(z.namelist()):
                raise ErrorArchivo("El archivo es un zip, pero no un libro de Excel (.xlsx).")
    except zipfile.BadZipFile:
        raise ErrorArchivo("El archivo no es un Excel (.xlsx) válido.")
    try:
        libro = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    except Exception as e:   # openpyxl lanza varios tipos de error según el daño del archivo
        raise ErrorArchivo(f"No se pudo abrir el Excel: {e}")

    try:
        for hoja in libro.worksheets:
            if hoja.sheet_state != "visible":
                continue
            try:
                hoja.reset_dimensions()    # algunos programas guardan mal las dimensiones de la hoja
            except Exception:
                pass
            crudas = []
            for fila in hoja.iter_rows(values_only=True):
                crudas.append(fila)
                if len(crudas) > MAX_FILAS_ARCHIVO + 1:
                    raise ErrorArchivo(f"La hoja tiene más de {MAX_FILAS_ARCHIVO:,} filas.")
            textos = [[_celda_a_texto(v) for v in fila] for fila in crudas]   # el índice + 1 es el número de fila de Excel
            if any(any(c for c in f) for f in textos):
                break
        else:
            raise ErrorArchivo("El libro no tiene hojas visibles con datos.")
        notas = []
        if len(libro.worksheets) > 1:
            notas.append(("info", f"Se leyó la hoja «{hoja.title}»",
                          f"El libro tiene {len(libro.worksheets)} hojas; se usa la primera visible con datos."))
    finally:
        libro.close()

    inicio = next(i for i, f in enumerate(textos) if any(f))
    ancho = max((max((j for j, c in enumerate(f) if c), default=-1) + 1 for f in textos), default=0)
    columnas = _nombres_de_columnas(textos[inicio], ancho)
    cuerpo, numeros = [], []
    for i, f in enumerate(textos[inicio + 1:], start=inicio + 2):
        if not any(f):
            continue
        cuerpo.append((f + [""] * ancho)[:ancho])
        numeros.append(i)
    return columnas, cuerpo, numeros, notas


def leer_tabla_con_notas(archivo):
    """Devuelve (columnas, filas, numeros, notas) de un archivo CSV, TXT, TSV o XLSX.

    `numeros[i]` es el número de fila de `filas[i]` en el archivo original (el de Excel, si es
    Excel). El formato se decide por el contenido, no por la extensión. `notas` son avisos
    informativos sobre cómo se leyó (por ejemplo, qué hoja de Excel se usó).
    """
    datos = _bytes_de(archivo)
    if datos.startswith(b"PK\x03\x04"):
        return _leer_xlsx(datos)
    return _leer_texto(datos)


def leer_tabla(archivo):
    """Como `leer_tabla_con_notas`, pero sin las notas."""
    return leer_tabla_con_notas(archivo)[:3]


def _columnas_leidas(columnas, maximo=8):
    """Texto con las columnas que se leyeron, para que el usuario vea qué entendió el sistema."""
    visibles = [c for c in columnas if c][:maximo]
    return f"Columnas leídas: {', '.join(visibles)}{'…' if len(columnas) > maximo else ''}." if visibles else ""


class ArchivoEnMemoria:
    """Envuelve bytes con la interfaz mínima (open/read/close) que usa `leer_tabla`.

    Sirve para leer un archivo subido sin cerrarlo: así se puede guardar después.
    """
    def __init__(self, datos):
        self._datos = datos

    def open(self, modo="rb"):
        pass

    def read(self):
        return self._datos

    def close(self):
        pass


def rango_fechas(archivo):
    """Fecha más antigua y más reciente de un CSV (para proponer el rango de la conciliación).

    Devuelve {"desde", "hasta", "filas", "invalidas", "columna"}. Levanta
    ErrorArchivo si el archivo no se puede leer, no tiene columna de fecha o
    ninguna fecha se puede interpretar.
    """
    columnas, filas, _ = leer_tabla(archivo)
    i_fecha = _buscar(columnas, CLAVES_FECHA)
    if i_fecha is None:
        raise ErrorArchivo("No se encontró una columna de fecha (se busca un encabezado como «Fecha»). "
                           + _columnas_leidas(columnas))
    fechas = [f for f in (_fecha(fila[i_fecha]) for fila in filas) if f]
    if not fechas:
        raise ErrorArchivo(f"No se pudo interpretar ninguna fecha de la columna «{columnas[i_fecha]}».")
    return {"desde": min(fechas), "hasta": max(fechas), "filas": len(filas),
            "invalidas": len(filas) - len(fechas), "columna": columnas[i_fecha]}


# ------------------------------------------------------------------ análisis
def analizar(archivos, desde, hasta, lado="BANCO"):
    """Lee el archivo principal y los complementarios de un lado.

    `archivos`: lista de ArchivoConciliacion, el principal primero. Los
    complementarios se alinean al principal por el nombre de sus columnas.

    Devuelve un dict con la vista previa (`columnas`, `filas`), los totales
    (`stats`), los movimientos normalizados listos para emparejar
    (`movimientos`) y los avisos (`avisos`, cada uno con nivel y detalle).

    Convención: monto positivo = ingreso, negativo = egreso. Si el archivo trae
    columnas cargo/abono se usa abono - cargo.
    """
    origen = ETIQUETAS_LADO.get(lado, lado)
    res = {"error": None, "lado": lado, "origen": origen, "columnas": [], "filas": [],
           "total": 0, "mostradas": 0, "comparados": [], "avisos": [], "stats": None,
           "movimientos": [], "sin_interpretar": 0, "rango_principal": None}

    def avisar(nivel, titulo, detalle=""):
        res["avisos"].append(_aviso(nivel, titulo, detalle, origen))

    if not archivos:
        res["error"] = "No hay archivos cargados."
        return res

    principal, *complementarios = archivos
    try:
        columnas, filas_principal, nums_principal, notas = leer_tabla_con_notas(principal.archivo)
    except ErrorArchivo as e:
        res["error"] = f"{principal.nombre}: {e}"
        return res
    for nivel, titulo, detalle in notas:
        avisar(nivel, f"{principal.nombre}: {titulo}", detalle)

    i_fecha = _buscar(columnas, CLAVES_FECHA)
    i_monto = _buscar(columnas, ("monto", "importe", "amount"))
    i_abono = _buscar(columnas, ("abono", "deposito", "credito"))
    i_cargo = _buscar(columnas, ("cargo", "retiro", "debito"))
    i_desc = _buscar(columnas, ("descripcion", "concepto", "detalle", "description"))
    i_ref = _buscar(columnas, ("referencia", "folio", "reference"))
    usa_monto = i_monto is not None
    usa_cargo_abono = not usa_monto and i_abono is not None and i_cargo is not None
    calcula = usa_monto or usa_cargo_abono
    comparados = [i for i in (
        i_fecha, i_monto if usa_monto else None,
        i_abono if usa_cargo_abono else None, i_cargo if usa_cargo_abono else None,
        i_ref,
    ) if i is not None]

    if i_fecha is None:
        avisar("advertencia", "No se encontró la columna de fecha",
               "No se puede filtrar por rango ni emparejar por fecha. "
               "Revisa que el archivo tenga un encabezado como «Fecha». " + _columnas_leidas(columnas))
    if not calcula:
        avisar("advertencia", "No se encontró la columna de monto",
               "Se busca «monto» o «importe», o el par «cargo» y «abono». "
               "Sin ella no se calculan totales ni coincidencias.")
    if i_ref is None:
        avisar("sugerencia", "El archivo no tiene columna de referencia",
               "Una columna de referencia o folio mejora la precisión de las coincidencias.")

    # Registros: (archivo, es_principal, número_de_fila, fila) en las columnas del principal
    registros = [(principal.nombre, True, n, f, getattr(principal, "pk", None))
                 for n, f in zip(nums_principal, filas_principal)]
    claves = [_norm(c) for c in columnas]
    for comp in complementarios:
        try:
            cols, filas, nums, notas = leer_tabla_con_notas(comp.archivo)
        except ErrorArchivo as e:
            avisar("advertencia", f"Se omitió {comp.nombre}", str(e))
            continue
        for nivel, titulo, detalle in notas:
            avisar(nivel, f"{comp.nombre}: {titulo}", detalle)
        indice = {_norm(c): i for i, c in enumerate(cols)}
        mapa = [indice.get(k) for k in claves]
        if all(m is None for m in mapa):
            avisar("advertencia", f"Se omitió {comp.nombre}",
                   "Ninguna de sus columnas coincide con las del archivo principal.")
            continue
        faltan = [columnas[i] for i in comparados if mapa[i] is None]
        if faltan:
            avisar("advertencia", f"{comp.nombre} no tiene columnas necesarias",
                   f"Le faltan: {', '.join(faltan)}. Sus filas no se podrán interpretar por completo.")
        extras = [c for c in cols if _norm(c) not in claves]
        if extras:
            avisar("info", f"{comp.nombre}: columnas ignoradas",
                   f"El principal no tiene estas columnas, por eso no se usan: {', '.join(extras)}.")
        for n, f in zip(nums, filas):
            registros.append((comp.nombre, False, n, [f[m] if m is not None else "" for m in mapa],
                              getattr(comp, "pk", None)))

    # Filas repetidas entre archivos distintos del mismo lado
    vistos, repetidas = {}, defaultdict(int)
    for nombre, _, _, fila, _ in registros:
        clave = tuple(_norm(c) for c in fila)
        if clave in vistos and vistos[clave] != nombre:
            repetidas[nombre] += 1
        else:
            vistos.setdefault(clave, nombre)
    for nombre, n in repetidas.items():
        avisar("advertencia", f"{nombre}: {n} fila(s) repetida(s) de otro archivo",
               "Si un complementario repite movimientos del principal, los totales se duplican. "
               "Revisa que solo aporte información nueva.")

    # Separador decimal de los montos: se decide por archivo y nunca en silencio
    convenciones = {}
    if calcula:
        columnas_monto = [i_monto] if usa_monto else [i_abono, i_cargo]
        valores_por_archivo = defaultdict(list)
        for nombre, _, _, fila, _ in registros:
            valores_por_archivo[nombre].extend(fila[i] for i in columnas_monto)
        for nombre, valores in valores_por_archivo.items():
            c = convencion_decimal(valores)
            convenciones[nombre] = c["convencion"]
            if c["coma"] and c["punto"]:
                avisar("advertencia", f"{nombre}: los montos mezclan formatos",
                       f"Hay {c['coma']} valor(es) con coma decimal (1.234,50) y {c['punto']} con punto decimal (1,234.50). "
                       f"Se usa el formato mayoritario («{c['convencion']}») y las filas que no lo siguen se reportan como no interpretables.")
            elif c["coma"]:
                avisar("info", f"{nombre}: montos con coma decimal",
                       "Los montos usan coma decimal y punto de miles (por ejemplo, 1.234,50 = 1234.50); se interpretaron así.")
            elif c["ambiguos"]:
                avisar("advertencia", f"{nombre}: montos ambiguos",
                       f"Hay {c['ambiguos']} valor(es) como «1.234» que podrían usar el punto como separador de miles. "
                       "Se interpretaron como decimales; revísalos.")

    visibles, problemas = [], []
    fechas_principal = []
    ingresos = egresos = CERO
    movimientos = 0
    for nombre, es_principal, numero, fila, archivo_pk in registros:
        fecha = None
        if i_fecha is not None:
            fecha = _fecha(fila[i_fecha])
            if fecha is None:
                problemas.append(f"{nombre}, fila {numero}: fecha inválida «{fila[i_fecha]}»")
                continue
            if es_principal:
                fechas_principal.append(fecha)
            if not (desde <= fecha <= hasta):
                continue
        visibles.append({"archivo": nombre, "principal": es_principal, "celdas": fila})
        if not calcula:
            continue
        conv = convenciones.get(nombre, ".")
        valores = (fila[i_monto],) if usa_monto else (fila[i_abono], fila[i_cargo])
        contradictorio = next((v for v in valores if _contradice(v, conv)), None)
        if contradictorio is not None:
            problemas.append(f"{nombre}, fila {numero}: el monto «{contradictorio}» usa un formato distinto al del resto del archivo")
            continue
        if usa_monto:
            m = _monto(fila[i_monto], conv)
        else:
            ab, ca = _monto(fila[i_abono], conv), _monto(fila[i_cargo], conv)
            invalido = (_limpio(fila[i_abono]) and ab is None) or (_limpio(fila[i_cargo]) and ca is None)
            m = None if invalido or (ab is None and ca is None) else (ab or 0) - (ca or 0)
        if m is None:
            problemas.append(f"{nombre}, fila {numero}: monto inválido o vacío")
            continue
        movimientos += 1
        if m >= 0:
            ingresos += m
        else:
            egresos += m
        if fecha is not None:
            res["movimientos"].append({
                "id": len(res["movimientos"]), "lado": lado, "archivo": nombre,
                "archivo_id": archivo_pk, "clave": f"{archivo_pk}:{numero}",
                "principal": es_principal, "fila": numero, "fecha": fecha, "monto": m,
                "descripcion": fila[i_desc] if i_desc is not None else "",
                "referencia": fila[i_ref] if i_ref is not None else "",
            })

    if problemas:
        ejemplos = "; ".join(problemas[:5]) + (" …" if len(problemas) > 5 else "")
        avisar("advertencia", f"{len(problemas)} fila(s) no se pudieron interpretar", ejemplos)
    if i_fecha is not None and registros and not visibles and not problemas:
        avisar("advertencia", "Ninguna fila cae dentro del rango de fechas",
               f"Rango elegido: {_fmt_fecha(desde)} – {_fmt_fecha(hasta)}. Revisa las fechas del archivo y del rango.")

    if fechas_principal:
        res["rango_principal"] = (min(fechas_principal), max(fechas_principal))
    res["sin_interpretar"] = len(problemas)
    res["columnas"] = columnas
    res["comparados"] = comparados
    res["total"] = len(visibles)
    res["filas"] = visibles[:MAX_FILAS_VISTA]
    res["mostradas"] = len(res["filas"])
    if calcula:
        res["stats"] = {"movimientos": movimientos, "ingresos": ingresos,
                        "egresos": egresos, "neto": ingresos + egresos}
    return res


# ------------------------------------------------------------- emparejamiento
ETIQUETAS_ESTADO = {"conciliado": "Conciliado", "manual": "Manual", "sugerido": "Revisar",
                    "pend_banco": "Solo banco", "pend_empresa": "Solo empresa"}


def emparejar(banco, empresa, tolerancia=TOLERANCIA_DIAS, manuales=()):
    """Empareja movimientos del banco con los de la empresa.

    1. Se aplican primero las conciliaciones manuales (`manuales`): esos
       movimientos salen del conjunto. Cada una es un dict con `id`, `claves`
       (las claves "archivo:fila" de todos sus movimientos) y datos opcionales
       (`nota`, `usuario`, `creado`, `tipo_label`). Si alguno de sus movimientos
       ya no está disponible (p. ej. quedó fuera del rango de fechas) se
       devuelve en `manuales_huerfanas` y no se aplica.
    2. Con el resto se aplican capas automáticas. Cada capa exige el mismo
       monto y es menos estricta que la anterior. Solo se empareja cuando hay
       UN candidato y ese candidato tampoco tiene otro posible (unicidad
       mutua). Si hay duda queda como "sugerido".
    """
    def dias(b, e):
        return abs((b["fecha"] - e["fecha"]).days)

    def misma_ref(b, e):
        rb = _norm(b["referencia"])
        return bool(rb) and rb == _norm(e["referencia"])

    capas = (
        ("Monto, fecha y referencia exactos", 100, lambda b, e: dias(b, e) == 0 and misma_ref(b, e)),
        ("Monto y referencia; fecha dentro de la tolerancia", 90, lambda b, e: dias(b, e) <= tolerancia and misma_ref(b, e)),
        ("Monto y fecha exactos", 75, lambda b, e: dias(b, e) == 0),
        ("Monto; fecha dentro de la tolerancia", 60, lambda b, e: dias(b, e) <= tolerancia),
    )

    # --- 1) conciliaciones manuales
    idx_b = {m["clave"]: m for m in banco if m.get("clave")}
    idx_e = {m["clave"]: m for m in empresa if m.get("clave")}
    aplicadas, huerfanas, usadas = [], [], set()
    for g in manuales:
        bs = [idx_b[c] for c in g["claves"] if c in idx_b]
        es = [idx_e[c] for c in g["claves"] if c in idx_e]
        if not bs or not es or len(bs) + len(es) != len(g["claves"]) or usadas.intersection(g["claves"]):
            huerfanas.append(g)
            continue
        usadas.update(g["claves"])
        aplicadas.append({**g, "bancos": bs, "empresas": es,
                          "monto": sum((b["monto"] for b in bs), CERO)})

    libres_b = [m for m in banco if m.get("clave") not in usadas]
    libres_e = [m for m in empresa if m.get("clave") not in usadas]

    # --- 2) capas automáticas
    conciliados = []
    for nombre, confianza, condicion in capas:
        por_monto = defaultdict(list)
        for e in libres_e:
            por_monto[e["monto"]].append(e)
        candidatos = {b["id"]: [e for e in por_monto.get(b["monto"], ()) if condicion(b, e)]
                      for b in libres_b}
        usos = defaultdict(int)
        for es in candidatos.values():
            for e in es:
                usos[e["id"]] += 1
        usados_b, usados_e = set(), set()
        for b in libres_b:
            es = candidatos[b["id"]]
            if len(es) == 1 and usos[es[0]["id"]] == 1:
                e = es[0]
                conciliados.append({"banco": b, "empresa": e, "regla": nombre,
                                    "confianza": confianza, "dias": dias(b, e)})
                usados_b.add(b["id"])
                usados_e.add(e["id"])
        libres_b = [b for b in libres_b if b["id"] not in usados_b]
        libres_e = [e for e in libres_e if e["id"] not in usados_e]

    # Lo que quedó: con candidatos posibles -> sugerido; sin ninguno -> pendiente
    por_monto = defaultdict(list)
    for e in libres_e:
        por_monto[e["monto"]].append(e)
    sugeridos, pend_banco, en_sugerencia = [], [], set()
    for b in libres_b:
        cands = sorted((e for e in por_monto.get(b["monto"], ()) if dias(b, e) <= tolerancia),
                       key=lambda e: (dias(b, e), e["id"]))
        if cands:
            b["sugerido"] = True
            for e in cands:
                e["sugerido"] = True
            sugeridos.append({"banco": b, "candidatos": cands})
            en_sugerencia.update(e["id"] for e in cands)
        else:
            pend_banco.append(b)
    pend_empresa = [e for e in libres_e if e["id"] not in en_sugerencia]

    # Filas para la tabla de coincidencias (bancos y empresas son siempre listas)
    filas = []
    for c in conciliados:
        filas.append({"estado": "conciliado", "bancos": [c["banco"]], "empresas": [c["empresa"]],
                      "regla": c["regla"], "confianza": c["confianza"], "dias": c["dias"]})
    for g in aplicadas:
        filas.append({"estado": "manual", "bancos": g["bancos"], "empresas": g["empresas"],
                      "regla": g.get("tipo_label") or "Conciliación manual", "confianza": None, "dias": None,
                      "manual_id": g["id"], "nota": g.get("nota", ""), "usuario": g.get("usuario", ""),
                      "creado": g.get("creado")})
    for s_ in sugeridos:
        filas.append({"estado": "sugerido", "bancos": [s_["banco"]], "empresas": s_["candidatos"],
                      "regla": "Varios candidatos posibles: requiere revisión", "confianza": None, "dias": None})
    for b in pend_banco:
        filas.append({"estado": "pend_banco", "bancos": [b], "empresas": [], "regla": "", "confianza": None, "dias": None})
    for e in pend_empresa:
        filas.append({"estado": "pend_empresa", "bancos": [], "empresas": [e], "regla": "", "confianza": None, "dias": None})
    for f in filas:
        f["etiqueta"] = ETIQUETAS_ESTADO[f["estado"]]

    def primero(f):
        m = (f["bancos"] or f["empresas"])[0]
        return (m["fecha"], m["id"])
    filas.sort(key=primero)

    def cobertura(n, total):
        return round(100 * n / total) if total else None

    conc_b = len(conciliados) + sum(len(g["bancos"]) for g in aplicadas)
    conc_e = len(conciliados) + sum(len(g["empresas"]) for g in aplicadas)
    resumen = {
        "tolerancia": tolerancia,
        "total_banco": len(banco), "total_empresa": len(empresa),
        "conciliados": len(conciliados), "manuales": len(aplicadas),
        "manuales_huerfanas": len(huerfanas),
        "conciliados_total": len(conciliados) + len(aplicadas),
        "sugeridos": len(sugeridos),
        "pend_banco": len(pend_banco), "pend_empresa": len(pend_empresa),
        "monto_conciliado": sum((c["banco"]["monto"] for c in conciliados), CERO)
                            + sum((g["monto"] for g in aplicadas), CERO),
        "monto_pend_banco": sum((m["monto"] for m in pend_banco), CERO),
        "monto_pend_empresa": sum((m["monto"] for m in pend_empresa), CERO),
        "cobertura_banco": cobertura(conc_b, len(banco)),
        "cobertura_empresa": cobertura(conc_e, len(empresa)),
    }

    orden = lambda m: (m["fecha"], m["id"])
    return {"filas": filas[:MAX_FILAS_VISTA], "filas_todas": filas, "total_filas": len(filas), "resumen": resumen,
            "conciliados": conciliados, "sugeridos": sugeridos,
            "pend_banco": pend_banco, "pend_empresa": pend_empresa,
            "manuales": aplicadas, "manuales_huerfanas": huerfanas,
            # Todo lo que aún se puede conciliar a mano (pendientes y por revisar)
            "pendientes": {"banco": sorted(libres_b, key=orden), "empresa": sorted(libres_e, key=orden)}}


# -------------------------------------------------------------------- reporte
def _ejemplos(movs, n=5):
    partes = []
    for m in movs[:n]:
        texto = f"{_fmt_fecha(m['fecha'])} · {_fmt_monto(m['monto'])}"
        if m["descripcion"]:
            texto += f" · {m['descripcion'][:40]}"
        partes.append(texto)
    return "; ".join(partes) + (" …" if len(movs) > n else "")


def reporte(banco, empresa, coincidencias, conciliacion=None):
    """Totales, resumen de coincidencias y lista de avisos ordenada por gravedad."""
    rs = coincidencias["resumen"]
    r = {"banco": banco["stats"], "empresa": empresa["stats"], "diferencia": None,
         "resumen": rs, "alertas": [], "conteo": {n: 0 for n in NIVELES}}
    alertas = r["alertas"]

    for lado in (banco, empresa):
        if lado["error"]:
            alertas.append(_aviso("error", "No se pudo leer el archivo principal", lado["error"], lado["origen"]))
        alertas.extend(lado["avisos"])

    if r["banco"] and r["empresa"]:
        r["diferencia"] = r["banco"]["neto"] - r["empresa"]["neto"]

    if conciliacion is not None and (conciliacion.banco_desde, conciliacion.banco_hasta) != \
            (conciliacion.empresa_desde, conciliacion.empresa_hasta):
        alertas.append(_aviso(
            "advertencia", "Los rangos de fecha de banco y empresa son distintos",
            f"Banco: {_fmt_fecha(conciliacion.banco_desde)} – {_fmt_fecha(conciliacion.banco_hasta)}. "
            f"Empresa: {_fmt_fecha(conciliacion.empresa_desde)} – {_fmt_fecha(conciliacion.empresa_hasta)}. "
            "Los movimientos fuera del rango del otro lado aparecerán como pendientes."))

    if rs["manuales_huerfanas"]:
        alertas.append(_aviso(
            "advertencia", f"{rs['manuales_huerfanas']} conciliación(es) manual(es) no se pudieron aplicar",
            "Alguno de sus movimientos ya no está disponible, por ejemplo porque quedó fuera del rango de fechas. "
            "No se borraron: vuelve al rango anterior o deshazlas desde la sección de conciliación manual."))
    if rs["manuales"]:
        alertas.append(_aviso(
            "info", f"{rs['manuales']} conciliación(es) manual(es)",
            "Fueron hechas por una persona y se pueden deshacer desde la sección de conciliación manual."))

    if conciliacion is not None:
        for lado, d, h in ((banco, conciliacion.banco_desde, conciliacion.banco_hasta),
                           (empresa, conciliacion.empresa_desde, conciliacion.empresa_hasta)):
            rp = lado.get("rango_principal")
            if rp and (d > rp[0] or h < rp[1]):
                alertas.append(_aviso(
                    "sugerencia", "El rango elegido no cubre todo el archivo principal",
                    f"El archivo principal abarca {_fmt_fecha(rp[0])} – {_fmt_fecha(rp[1])}, pero el rango elegido es "
                    f"{_fmt_fecha(d)} – {_fmt_fecha(h)}. Los movimientos fuera del rango no se comparan. "
                    "Usa «Usar este rango» en la barra lateral si quieres incluirlos todos.", lado["origen"]))

    hay_b, hay_e = rs["total_banco"], rs["total_empresa"]
    if not hay_b and not hay_e and not banco["error"] and not empresa["error"]:
        alertas.append(_aviso("error", "No hay movimientos interpretables para comparar",
                              "Revisa las fechas, los montos y los rangos elegidos."))
    elif hay_b and hay_e:
        alertas.append(_aviso(
            "info", f"{rs['conciliados']} coincidencia(s) automática(s)",
            f"Cobertura total (automáticas y manuales): {rs['cobertura_banco']}% de los movimientos del banco y "
            f"{rs['cobertura_empresa']}% de los de la empresa (tolerancia de {rs['tolerancia']} día(s))."))
        if not rs["conciliados"] and not rs["manuales"]:
            alertas.append(_aviso("advertencia", "No se encontró ninguna coincidencia",
                                  "Verifica los rangos de fecha y que los montos usen la misma convención de signo."))
            negativos = {-m["monto"] for m in empresa["movimientos"]}
            if {m["monto"] for m in banco["movimientos"]} & negativos:
                alertas.append(_aviso(
                    "sugerencia", "Los signos de los montos parecen invertidos",
                    "Hay montos iguales con signo contrario entre banco y empresa. "
                    "Revisa si en uno de los archivos los egresos van como positivos."))
        if rs["sugeridos"]:
            alertas.append(_aviso(
                "advertencia", f"{rs['sugeridos']} movimiento(s) con coincidencia ambigua",
                "Tienen varios candidatos con el mismo monto y fechas cercanas, por eso no se emparejaron solos. "
                "Revísalos en la tabla de coincidencias (filtro «Por revisar»)."))
        if rs["pend_banco"]:
            alertas.append(_aviso(
                "sugerencia", f"{rs['pend_banco']} movimiento(s) solo en el banco ({_fmt_monto(rs['monto_pend_banco'])})",
                "Revisa si son comisiones, intereses o cargos que aún no se registran en la empresa. "
                + _ejemplos(coincidencias["pend_banco"])))
        if rs["pend_empresa"]:
            alertas.append(_aviso(
                "sugerencia", f"{rs['pend_empresa']} movimiento(s) solo en la empresa ({_fmt_monto(rs['monto_pend_empresa'])})",
                "Pueden ser cheques o depósitos en tránsito, o movimientos que el banco no reporta en este periodo. "
                "Si falta información del banco, puedes cargar un archivo complementario. "
                + _ejemplos(coincidencias["pend_empresa"])))

    alertas.sort(key=lambda a: NIVELES.index(a["nivel"]))
    for a in alertas:
        r["conteo"][a["nivel"]] += 1
    return r


def balance(banco, empresa, coincidencias):
    """Cuadre de la diferencia entre banco y empresa.

    Neto del banco - partidas sin conciliar del banco + partidas sin conciliar de
    la empresa = neto de la empresa. Las coincidencias (automáticas y manuales) tienen
    siempre el mismo monto en ambos lados, por lo que la diferencia debería explicarse
    por completo con lo que no se concilió. Devuelve None si falta algún total.
    """
    sb, se = banco["stats"], empresa["stats"]
    if not sb or not se:
        return None
    p = coincidencias["pendientes"]
    sin_b = sum((m["monto"] for m in p["banco"]), CERO)
    sin_e = sum((m["monto"] for m in p["empresa"]), CERO)
    ajustado = sb["neto"] - sin_b + sin_e
    return {
        "neto_banco": sb["neto"], "neto_empresa": se["neto"],
        "sin_conciliar_banco": sin_b, "n_banco": len(p["banco"]),
        "sin_conciliar_empresa": sin_e, "n_empresa": len(p["empresa"]),
        "neto_ajustado": ajustado, "sin_explicar": ajustado - se["neto"],
        "cuadra": ajustado == se["neto"],
        # Si hay filas sin fecha no participan en el emparejamiento y el cuadre no es exacto
        "completo": sb["movimientos"] == len(banco["movimientos"]) and se["movimientos"] == len(empresa["movimientos"]),
    }

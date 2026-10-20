"""Lectura de archivos CSV y cálculo de la vista previa / reporte."""
import csv
import io
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation

FORMATOS_FECHA = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y")
MAX_FILAS_VISTA = 1000


class ErrorArchivo(Exception):
    pass


def _norm(texto):
    sin_acentos = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in sin_acentos if unicodedata.category(c) != "Mn").strip().lower()


def leer_tabla(archivo):
    """Devuelve (columnas, filas) de un CSV. Detecta codificación y separador."""
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

    try:
        texto = datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = datos.decode("latin-1")
    if not texto.strip():
        raise ErrorArchivo("El archivo está vacío.")

    try:
        dialecto = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t|")
    except csv.Error:
        dialecto = csv.excel
    filas = [f for f in csv.reader(io.StringIO(texto), dialecto)]
    columnas = [c.strip() for c in filas[0]]
    cuerpo = []
    for f in filas[1:]:
        if not any(c.strip() for c in f):
            continue
        f = [c.strip() for c in f][: len(columnas)]
        f += [""] * (len(columnas) - len(f))
        cuerpo.append(f)
    return columnas, cuerpo


def _buscar(columnas, claves):
    for i, c in enumerate(columnas):
        n = _norm(c)
        if any(k in n for k in claves):
            return i
    return None


def _fecha(texto):
    for fmt in FORMATOS_FECHA:
        try:
            return datetime.strptime(texto.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _monto(texto):
    t = (texto or "").strip().replace("$", "").replace(",", "").replace(" ", "")
    if not t:
        return None
    negativo = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        valor = Decimal(t)
    except InvalidOperation:
        return None
    return -valor if negativo else valor


def analizar(archivos, desde, hasta):
    """Lee el archivo principal y los complementarios, filtra por rango y calcula totales.

    `archivos` es una lista de ArchivoConciliacion con el principal primero. Los
    complementarios se alinean al principal por el nombre de sus columnas; las
    columnas que el principal no tiene se ignoran. Se antepone una columna
    "Archivo" para saber de dónde viene cada fila.

    Convención: monto positivo = ingreso, negativo = egreso. Si el archivo trae
    columnas cargo/abono se usa abono - cargo.
    """
    res = {"error": None, "columnas": [], "filas": [], "total": 0, "mostradas": 0,
           "comparados": [], "avisos": [], "stats": None}
    if not archivos:
        res["error"] = "No hay archivos cargados."
        return res

    principal, *complementarios = archivos
    try:
        columnas, filas_principal = leer_tabla(principal.archivo)
    except ErrorArchivo as e:
        res["error"] = f"{principal.nombre}: {e}"
        return res

    i_fecha = _buscar(columnas, ("fecha", "date"))
    i_monto = _buscar(columnas, ("monto", "importe", "amount"))
    i_abono = _buscar(columnas, ("abono", "deposito", "credito"))
    i_cargo = _buscar(columnas, ("cargo", "retiro", "debito"))
    usa_monto = i_monto is not None
    usa_cargo_abono = not usa_monto and i_abono is not None and i_cargo is not None
    calcula = usa_monto or usa_cargo_abono
    comparados = [i for i in (
        i_fecha, i_monto if usa_monto else None,
        i_abono if usa_cargo_abono else None, i_cargo if usa_cargo_abono else None,
    ) if i is not None]

    if i_fecha is None:
        res["avisos"].append("No se encontró una columna de fecha; no se filtró por rango.")
    if not calcula:
        res["avisos"].append("No se encontró columna de monto (monto/importe o cargo y abono); no se calcularon totales.")

    # Registros (nombre_de_archivo, fila) en las columnas del principal
    registros = [(principal.nombre, f) for f in filas_principal]
    claves = [_norm(c) for c in columnas]
    for comp in complementarios:
        try:
            cols, filas = leer_tabla(comp.archivo)
        except ErrorArchivo as e:
            res["avisos"].append(f"{comp.nombre}: {e} Se omitió.")
            continue
        indice = {_norm(c): i for i, c in enumerate(cols)}
        mapa = [indice.get(k) for k in claves]
        if all(m is None for m in mapa):
            res["avisos"].append(f"{comp.nombre}: ninguna columna coincide con el archivo principal. Se omitió.")
            continue
        faltan = [columnas[i] for i in comparados if mapa[i] is None]
        if faltan:
            res["avisos"].append(f"{comp.nombre}: no tiene la(s) columna(s) comparada(s) {', '.join(faltan)}.")
        extras = [c for c in cols if _norm(c) not in claves]
        if extras:
            res["avisos"].append(f"{comp.nombre}: se ignoraron columnas que el principal no tiene ({', '.join(extras)}).")
        for f in filas:
            registros.append((comp.nombre, [f[m] if m is not None else "" for m in mapa]))

    visibles, sin_interpretar = [], 0
    ingresos = egresos = Decimal("0.00")
    movimientos = 0
    for nombre, fila in registros:
        if i_fecha is not None:
            f = _fecha(fila[i_fecha])
            if f is None:
                sin_interpretar += 1
                continue
            if not (desde <= f <= hasta):
                continue
        visibles.append([nombre] + fila)
        if not calcula:
            continue
        if usa_monto:
            m = _monto(fila[i_monto])
        else:
            ab, ca = _monto(fila[i_abono]), _monto(fila[i_cargo])
            m = None if ab is None and ca is None else (ab or 0) - (ca or 0)
        if m is None:
            sin_interpretar += 1
            continue
        movimientos += 1
        if m >= 0:
            ingresos += m
        else:
            egresos += m

    if sin_interpretar:
        res["avisos"].append(f"{sin_interpretar} fila(s) no se pudieron interpretar (fecha o monto inválidos).")

    res["columnas"] = ["Archivo"] + columnas
    res["comparados"] = [i + 1 for i in comparados]  # +1 por la columna "Archivo"
    res["total"] = len(visibles)
    res["filas"] = visibles[:MAX_FILAS_VISTA]
    res["mostradas"] = len(res["filas"])
    if calcula:
        res["stats"] = {"movimientos": movimientos, "ingresos": ingresos,
                        "egresos": egresos, "neto": ingresos + egresos}
    return res

def reporte(banco, empresa):
    r = {"banco": banco["stats"], "empresa": empresa["stats"], "diferencia": None,
         "avisos": [f"Banco: {a}" for a in banco["avisos"]] + [f"Empresa: {a}" for a in empresa["avisos"]]}
    if banco["error"]:
        r["avisos"].insert(0, f"Banco: {banco['error']}")
    if empresa["error"]:
        r["avisos"].insert(0, f"Empresa: {empresa['error']}")
    if r["banco"] and r["empresa"]:
        r["diferencia"] = r["banco"]["neto"] - r["empresa"]["neto"]
    return r

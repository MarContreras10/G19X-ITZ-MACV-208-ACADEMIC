"""Exportación del reporte de una conciliación: Excel (.xlsx), CSV de balance/match y PDF.

Todas las funciones reciben el mismo diccionario `datos` (armado en views.py):
conciliacion, usuario, generado, tolerancia, archivos, banco, empresa,
coincidencias, reporte y balance.
"""
import csv
import io
from decimal import Decimal
from xml.sax.saxutils import escape

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

CERO = Decimal("0.00")
AZUL, VERDE_AZULADO = "1D4ED8", "0F766E"
MARINO = "1F3A5F"
ESTADOS = {  # clave: (etiqueta, color de relleno claro, color fuerte)
    "conciliado": ("Conciliado", "DCFCE7", "16A34A"),
    "manual": ("Manual", "EDE9FE", "7C3AED"),
    "sugerido": ("Por revisar", "FEF3C7", "D97706"),
    "pend_banco": ("Solo banco", "DBEAFE", AZUL),
    "pend_empresa": ("Solo empresa", "CCFBF1", VERDE_AZULADO),
}
NIVELES = {  # clave: (etiqueta, color fuerte)
    "error": ("Error", "B42318"), "advertencia": ("Advertencia", "B45309"),
    "sugerencia": ("Sugerencia", "1D4ED8"), "info": ("Informativo", "4B5563"),
}
COLUMNAS_MATCH = [  # (clave, encabezado, ancho)
    ("n", "#", 5), ("estado", "Estado", 14), ("regla", "Regla", 34), ("confianza", "Confianza %", 11),
    ("b_fecha", "Fecha banco", 13), ("b_desc", "Descripción banco", 30), ("b_ref", "Ref. banco", 14),
    ("b_archivo", "Archivo banco", 18), ("b_monto", "Monto banco", 14),
    ("e_fecha", "Fecha empresa", 13), ("e_desc", "Descripción empresa", 30), ("e_ref", "Ref. empresa", 14),
    ("e_archivo", "Archivo empresa", 18), ("e_monto", "Monto empresa", 14),
    ("diferencia", "Diferencia (banco - empresa)", 16), ("observacion", "Observación", 46),
]


# ------------------------------------------------------------------ utilidades
def local(dt):
    """Pasa una fecha-hora con zona horaria (UTC en la base de datos) a la hora local."""
    return timezone.localtime(dt) if dt is not None and timezone.is_aware(dt) else dt


def fmt_fecha(f):
    return f.strftime("%d/%m/%Y") if f else ""


def fmt_monto(m):
    return "" if m is None else f"{m:,.2f}"


def _juntar(movs, campo, vacio=""):
    valores = [str(m.get(campo) or "") for m in movs]
    return " | ".join(v for v in valores if v) or vacio


def _fechas(movs):
    """Una fecha real si hay un solo movimiento; si hay varios, un texto con todas."""
    if not movs:
        return None
    if len(movs) == 1:
        return movs[0]["fecha"]
    return "; ".join(fmt_fecha(m["fecha"]) for m in movs)


def _observacion(f):
    estado = f["estado"]
    if estado == "conciliado":
        return f"{f['dias']} día(s) de diferencia entre las fechas" if f.get("dias") else "Misma fecha en ambos lados"
    if estado == "manual":
        partes = [f.get("usuario") or ""]
        if f.get("creado"):
            partes.append(local(f["creado"]).strftime("%d/%m/%Y %H:%M"))
        if f.get("nota"):
            partes.append(f["nota"])
        return " · ".join(p for p in partes if p)
    if estado == "sugerido":
        return f"{len(f['empresas'])} candidato(s) posible(s) en la empresa: requiere revisión"
    return "Sin pareja en la empresa" if estado == "pend_banco" else "Sin pareja en el banco"


def filas_balance_match(datos):
    """Una fila por cada resultado de la conciliación (pareja, grupo manual o movimiento sin pareja)."""
    filas = []
    for n, f in enumerate(datos["coincidencias"]["filas_todas"], start=1):
        bancos, empresas = f["bancos"], f["empresas"]
        monto_b = sum((m["monto"] for m in bancos), CERO) if bancos else None
        if f["estado"] == "sugerido":          # los candidatos tienen todos el mismo monto
            monto_e = empresas[0]["monto"]
        else:
            monto_e = sum((m["monto"] for m in empresas), CERO) if empresas else None
        filas.append({
            "n": n, "estado": ESTADOS[f["estado"]][0], "estado_clave": f["estado"],
            "regla": f["regla"] or "", "confianza": f.get("confianza"),
            "b_fecha": _fechas(bancos), "b_desc": _juntar(bancos, "descripcion"), "b_ref": _juntar(bancos, "referencia"),
            "b_archivo": _juntar(bancos, "archivo"), "b_monto": monto_b,
            "e_fecha": _fechas(empresas), "e_desc": _juntar(empresas, "descripcion"), "e_ref": _juntar(empresas, "referencia"),
            "e_archivo": _juntar(empresas, "archivo"), "e_monto": monto_e,
            "diferencia": (monto_b or CERO) - (monto_e or CERO), "observacion": _observacion(f),
        })
    return filas


def _montos_por_estado(datos):
    c = datos["coincidencias"]
    return {
        "auto": sum((x["banco"]["monto"] for x in c["conciliados"]), CERO),
        "manual": sum((g["monto"] for g in c["manuales"]), CERO),
        "sugerido": sum((s["banco"]["monto"] for s in c["sugeridos"]), CERO),
        "pend_banco": c["resumen"]["monto_pend_banco"], "pend_empresa": c["resumen"]["monto_pend_empresa"],
    }


def _archivos_texto(datos, lado):
    nombres = datos["archivos"][lado]
    principal = next((n for n, es_p in nombres if es_p), "—")
    comp = ", ".join(n for n, es_p in nombres if not es_p) or "—"
    return principal, comp


# ------------------------------------------------------------------------ CSV
def generar_csv(datos):
    """Tabla de balance/match en CSV (UTF-8 con BOM para que Excel respete los acentos)."""
    salida = io.StringIO()
    w = csv.writer(salida)
    w.writerow([h for _, h, _ in COLUMNAS_MATCH])
    for f in filas_balance_match(datos):
        fila = []
        for clave, _, _ in COLUMNAS_MATCH:
            v = f[clave]
            fila.append(v.isoformat() if hasattr(v, "isoformat") else ("" if v is None else str(v)))
        w.writerow(fila)
    return salida.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------- Excel
_BORDE = Border(*(Side(style="thin", color="D1D5DB"),) * 4)
_ENCABEZADO_FONT = Font(bold=True, color="FFFFFF")
_ENCABEZADO_FILL = PatternFill("solid", fgColor=MARINO)
_NUM = '#,##0.00;[Red]-#,##0.00'
_FECHA = "dd/mm/yyyy"


def _encabezado(ws, fila, textos, col_inicio=1):
    for i, t in enumerate(textos):
        c = ws.cell(row=fila, column=col_inicio + i, value=t)
        c.font, c.fill, c.border = _ENCABEZADO_FONT, _ENCABEZADO_FILL, _BORDE
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _tabla(ws, fila, titulo, encabezados, filas, formatos=None):
    """Escribe un título, un encabezado y filas. Devuelve la siguiente fila libre."""
    ws.cell(row=fila, column=1, value=titulo).font = Font(bold=True, size=12, color=MARINO)
    _encabezado(ws, fila + 1, encabezados)
    for r, datos_fila in enumerate(filas, start=fila + 2):
        for c, v in enumerate(datos_fila, start=1):
            celda = ws.cell(row=r, column=c, value=v)
            celda.border = _BORDE
            celda.alignment = Alignment(vertical="top", wrap_text=True)
            if formatos and formatos.get(c) and not isinstance(v, str):
                celda.number_format = formatos[c]
            elif hasattr(v, "year"):
                celda.number_format = _FECHA
            elif isinstance(v, Decimal):
                celda.number_format = _NUM
    return fila + 2 + len(filas) + 1


def _hoja_resumen(ws, d):
    ws.title = "Resumen"
    c, rs, rep, bal = d["conciliacion"], d["coincidencias"]["resumen"], d["reporte"], d["balance"]
    ws["A1"] = "Reporte de conciliación bancaria"
    ws["A1"].font = Font(bold=True, size=16, color=MARINO)
    ws["A2"] = f"Conciliación #{c.pk} · generado el {d['generado']:%d/%m/%Y %H:%M} por {d['usuario']}"
    ws["A2"].font = Font(italic=True, color="6B7280")

    pb, cb = _archivos_texto(d, "BANCO")
    pe, ce = _archivos_texto(d, "EMPRESA")
    fila = _tabla(ws, 4, "Periodos y archivos", ["Lado", "Desde", "Hasta", "Archivo principal", "Complementarios"], [
        ["Banco", c.banco_desde, c.banco_hasta, pb, cb], ["Empresa", c.empresa_desde, c.empresa_hasta, pe, ce]])

    m = _montos_por_estado(d)
    fila = _tabla(ws, fila, "Resultado de la conciliación", ["Concepto", "Cantidad", "Monto (lado banco)"], [
        ["Conciliados automáticamente", rs["conciliados"], m["auto"]],
        ["Conciliados manualmente", rs["manuales"], m["manual"]],
        ["Por revisar (coincidencia ambigua)", rs["sugeridos"], m["sugerido"]],
        ["Solo en el banco", rs["pend_banco"], m["pend_banco"]],
        ["Solo en la empresa", rs["pend_empresa"], m["pend_empresa"]],
        ["Cobertura del banco (% de sus movimientos conciliados)", rs["cobertura_banco"], None],
        ["Cobertura de la empresa (% de sus movimientos conciliados)", rs["cobertura_empresa"], None],
        ["Tolerancia de fecha usada (días)", rs["tolerancia"], None]])

    sb, se = rep["banco"], rep["empresa"]
    def g(s, k):
        return s[k] if s else "—"
    filas = [["Movimientos", g(sb, "movimientos"), g(se, "movimientos")],
             ["Ingresos", g(sb, "ingresos"), g(se, "ingresos")],
             ["Egresos", g(sb, "egresos"), g(se, "egresos")],
             ["Neto", g(sb, "neto"), g(se, "neto")],
             ["Diferencia (banco - empresa)", rep["diferencia"] if rep["diferencia"] is not None else "—", None]]
    fila = _tabla(ws, fila, "Totales del periodo", ["Concepto", "Banco", "Empresa"], filas)
    for r in range(fila - 6, fila - 1):
        ws.cell(row=r, column=1).font = Font(bold=ws.cell(row=r, column=1).value in ("Neto", "Diferencia (banco - empresa)"))

    if bal:
        filas = [["Neto del banco", bal["neto_banco"], ""],
                 ["(-) Sin conciliar en el banco", bal["sin_conciliar_banco"], f"{bal['n_banco']} movimiento(s), incluye los por revisar"],
                 ["(+) Sin conciliar en la empresa", bal["sin_conciliar_empresa"], f"{bal['n_empresa']} movimiento(s), incluye los por revisar"],
                 ["(=) Neto del banco ajustado", bal["neto_ajustado"], ""],
                 ["Neto de la empresa", bal["neto_empresa"], ""],
                 ["Diferencia sin explicar", bal["sin_explicar"], ""],
                 ["Resultado", "CUADRA" if bal["cuadra"] else "NO CUADRA",
                  "" if bal["completo"] else "Hay filas sin fecha que no participan en el emparejamiento."]]
        fila = _tabla(ws, fila, "Balance: cuadre de la diferencia", ["Concepto", "Monto", "Detalle"], filas)
        resultado = ws.cell(row=fila - 2, column=2)
        resultado.font = Font(bold=True, color="166534" if bal["cuadra"] else "B42318")
    else:
        ws.cell(row=fila, column=1, value="Balance no disponible: falta la columna de monto en algún archivo.").font = Font(italic=True)

    for col, ancho in zip("ABCDE", (52, 20, 22, 30, 40)):
        ws.column_dimensions[col].width = ancho


def _hoja_balance_match(ws, d):
    ws.title = "Balance-Match"
    filas = filas_balance_match(d)
    _encabezado(ws, 1, [h for _, h, _ in COLUMNAS_MATCH])
    ws.row_dimensions[1].height = 46
    for i, (clave, _, ancho) in enumerate(COLUMNAS_MATCH, start=1):
        ws.column_dimensions[get_column_letter(i)].width = ancho
    for r, f in enumerate(filas, start=2):
        for i, (clave, _, _) in enumerate(COLUMNAS_MATCH, start=1):
            v = f[clave]
            celda = ws.cell(row=r, column=i, value=v)
            celda.border = _BORDE
            celda.alignment = Alignment(vertical="top", wrap_text=True)
            if hasattr(v, "year"):
                celda.number_format = _FECHA
            elif isinstance(v, Decimal):
                celda.number_format = _NUM
        _, relleno, _ = ESTADOS[f["estado_clave"]]
        ws.cell(row=r, column=2).fill = PatternFill("solid", fgColor=relleno)
        ws.cell(row=r, column=2).font = Font(bold=True)
    ultima = len(filas) + 1
    ws.freeze_panes = "C2"
    if filas:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNAS_MATCH))}{ultima}"
    # Totales
    fila_t = ultima + 2
    ws.cell(row=fila_t, column=1, value="Totales").font = Font(bold=True)
    for clave in ("b_monto", "e_monto", "diferencia"):
        col = [k for k, _, _ in COLUMNAS_MATCH].index(clave) + 1
        total = sum((f[clave] for f in filas if f[clave] is not None), CERO)
        celda = ws.cell(row=fila_t, column=col, value=total)
        celda.number_format, celda.font = _NUM, Font(bold=True)
        celda.border = Border(top=Side(style="medium", color=MARINO))


def _hoja_pendientes(ws, d):
    ws.title = "Pendientes"
    p = d["coincidencias"]["pendientes"]
    filas = []
    for lado, movs in (("Banco", p["banco"]), ("Empresa", p["empresa"])):
        for m in movs:
            filas.append([lado, "Por revisar" if m.get("sugerido") else "Sin pareja", m["fecha"], m["descripcion"],
                          m["referencia"], m["monto"], m["archivo"], m["fila"]])
    _encabezado(ws, 1, ["Lado", "Estado", "Fecha", "Descripción", "Referencia", "Monto", "Archivo", "Fila en el archivo"])
    for r, fila in enumerate(filas, start=2):
        for c, v in enumerate(fila, start=1):
            celda = ws.cell(row=r, column=c, value=v)
            celda.border = _BORDE
            if hasattr(v, "year"):
                celda.number_format = _FECHA
            elif isinstance(v, Decimal):
                celda.number_format = _NUM
        color = AZUL if fila[0] == "Banco" else VERDE_AZULADO
        ws.cell(row=r, column=1).font = Font(bold=True, color=color)
    if not filas:
        ws.cell(row=2, column=1, value="No quedan movimientos pendientes.").font = Font(italic=True)
    else:
        ws.auto_filter.ref = f"A1:H{len(filas) + 1}"
    ws.freeze_panes = "A2"
    for col, ancho in zip("ABCDEFGH", (10, 13, 13, 40, 18, 15, 24, 12)):
        ws.column_dimensions[col].width = ancho


def _hoja_avisos(ws, d):
    ws.title = "Avisos"
    _encabezado(ws, 1, ["Nivel", "Origen", "Aviso", "Detalle"])
    alertas = d["reporte"]["alertas"]
    for r, a in enumerate(alertas, start=2):
        etiqueta, color = NIVELES[a["nivel"]]
        valores = [etiqueta, a["origen"], a["titulo"], a["detalle"]]
        for c, v in enumerate(valores, start=1):
            celda = ws.cell(row=r, column=c, value=v)
            celda.border = _BORDE
            celda.alignment = Alignment(vertical="top", wrap_text=True)
        ws.cell(row=r, column=1).font = Font(bold=True, color=color)
    if not alertas:
        ws.cell(row=2, column=1, value="Sin avisos.").font = Font(italic=True)
    ws.freeze_panes = "A2"
    for col, ancho in zip("ABCD", (14, 12, 48, 90)):
        ws.column_dimensions[col].width = ancho


def generar_xlsx(datos):
    wb = Workbook()
    _hoja_resumen(wb.active, datos)
    _hoja_balance_match(wb.create_sheet(), datos)
    _hoja_pendientes(wb.create_sheet(), datos)
    _hoja_avisos(wb.create_sheet(), datos)
    wb.properties.title = f"Conciliación #{datos['conciliacion'].pk}"
    wb.properties.creator = datos["usuario"]
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------------ PDF
def _estilos():
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle("t", parent=base["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24,
                                 textColor=colors.HexColor("#" + MARINO), alignment=0, spaceAfter=2),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=9, textColor=colors.HexColor("#6B7280")),
        "h1": ParagraphStyle("h1", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16,
                             textColor=colors.HexColor("#" + MARINO), spaceBefore=14, spaceAfter=6, keepWithNext=1),
        "h2": ParagraphStyle("h2", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=10, leading=13,
                             textColor=colors.HexColor("#374151"), spaceBefore=8, spaceAfter=3, keepWithNext=1),
        "p": ParagraphStyle("p", parent=base["Normal"], fontSize=9.5, leading=13),
        "peq": ParagraphStyle("peq", parent=base["Normal"], fontSize=8, leading=10, textColor=colors.HexColor("#6B7280")),
        "celda": ParagraphStyle("c", parent=base["Normal"], fontSize=8, leading=10),
        "celda_der": ParagraphStyle("cd", parent=base["Normal"], fontSize=8, leading=10, alignment=2),
        "encab": ParagraphStyle("e", parent=base["Normal"], fontSize=8, leading=10, textColor=colors.white, fontName="Helvetica-Bold"),
        "kpi_n": ParagraphStyle("kn", parent=base["Normal"], fontSize=20, leading=22, fontName="Helvetica-Bold", alignment=1),
        "kpi_t": ParagraphStyle("kt", parent=base["Normal"], fontSize=7.5, leading=9, alignment=1, textColor=colors.HexColor("#6B7280")),
    }


def _p(texto, estilo):
    return Paragraph(escape(str(texto)) if texto is not None else "", estilo)


def _tabla_pdf(filas, anchos, st, encabezado=True, derecha=(), extra=()):
    """Tabla con encabezado azul y filas con rayas. `filas` son listas de textos o Paragraphs."""
    tabla = Table(filas, colWidths=anchos, repeatRows=1 if encabezado else 0)
    estilo = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
              ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    if encabezado:
        estilo += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + MARINO))]
        estilo += [("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")])]
    tabla.setStyle(TableStyle(estilo + list(extra)))
    return tabla


def _kpis(d, st):
    rs = d["coincidencias"]["resumen"]
    items = [("Conciliados\nautomáticos", rs["conciliados"], "16A34A"), ("Conciliados\nmanuales", rs["manuales"], "7C3AED"),
             ("Por revisar", rs["sugeridos"], "D97706"), ("Solo en\nel banco", rs["pend_banco"], AZUL),
             ("Solo en\nla empresa", rs["pend_empresa"], VERDE_AZULADO)]
    celdas = [[Paragraph(f'<font color="#{c}">{n}</font>', st["kpi_n"]) for _, n, c in items],
              [Paragraph(t.replace("\n", "<br/>"), st["kpi_t"]) for t, _, _ in items]]
    t = Table(celdas, colWidths=[3.5 * cm] * 5)
    estilo = [("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")), ("TOPPADDING", (0, 0), (-1, 0), 8),
              ("BOTTOMPADDING", (0, 1), (-1, 1), 8), ("ALIGN", (0, 0), (-1, -1), "CENTER")]
    for i, (_, _, c) in enumerate(items):
        estilo += [("LINEABOVE", (i, 0), (i, 0), 3, colors.HexColor("#" + c)), ("LINEBEFORE", (i, 0), (i, -1), 0.5, colors.HexColor("#E5E7EB"))]
    t.setStyle(TableStyle(estilo))
    return t


# --- gráficas
def _vacio(texto, ancho=17 * cm):
    dib = Drawing(ancho, 1.6 * cm)
    dib.add(String(0, 0.6 * cm, texto, fontName="Helvetica-Oblique", fontSize=9, fillColor=colors.HexColor("#6B7280")))
    return dib


def _grafica_estados(d):
    rs = d["coincidencias"]["resumen"]
    cats = [("Conciliados (auto)", rs["conciliados"], "16A34A"), ("Manuales", rs["manuales"], "7C3AED"),
            ("Por revisar", rs["sugeridos"], "D97706"), ("Solo banco", rs["pend_banco"], AZUL),
            ("Solo empresa", rs["pend_empresa"], VERDE_AZULADO)]
    if not any(n for _, n, _ in cats):
        return _vacio("No hay datos suficientes para graficar.")
    dib = Drawing(17 * cm, 5.2 * cm)
    bc = HorizontalBarChart()
    bc.x, bc.y, bc.width, bc.height = 95, 10, 17 * cm - 140, 5.2 * cm - 22
    bc.data = [[n for _, n, _ in reversed(cats)]]
    bc.categoryAxis.categoryNames = [t for t, _, _ in reversed(cats)]
    bc.categoryAxis.labels.fontSize, bc.categoryAxis.labels.boxAnchor = 8, "e"
    bc.categoryAxis.visibleTicks = 0
    maximo = max(n for _, n, _ in cats)
    bc.valueAxis.valueMin, bc.valueAxis.valueMax = 0, maximo + max(1, round(maximo * 0.2))
    bc.valueAxis.valueStep = max(1, round(maximo / 5))
    bc.valueAxis.labels.fontSize = 7
    bc.barWidth = 12
    bc.barLabelFormat = "%d"
    bc.barLabels.fontSize, bc.barLabels.boxAnchor, bc.barLabels.dx = 8, "w", 4
    for i, (_, _, c) in enumerate(reversed(cats)):
        bc.bars[(0, i)].fillColor = colors.HexColor("#" + c)
    bc.bars.strokeColor = None
    dib.add(bc)
    return dib


def _grafica_totales(d):
    sb, se = d["reporte"]["banco"], d["reporte"]["empresa"]
    if not sb or not se:
        return _vacio("No hay totales para graficar (falta la columna de monto en algún archivo).")
    banco = [float(sb["ingresos"]), abs(float(sb["egresos"])), float(sb["neto"])]
    empresa = [float(se["ingresos"]), abs(float(se["egresos"])), float(se["neto"])]
    dib = Drawing(17 * cm, 6.2 * cm)
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 55, 28, 17 * cm - 75, 6.2 * cm - 50
    bc.data = [banco, empresa]
    bc.categoryAxis.categoryNames = ["Ingresos", "Egresos (valor absoluto)", "Neto"]
    bc.categoryAxis.labels.fontSize = 8
    bc.categoryAxis.labels.boxAnchor = "n"
    bc.categoryAxis.labels.dy = -2
    todos = banco + empresa
    bc.valueAxis.valueMin = min(0, min(todos))
    bc.valueAxis.valueMax = max(todos) * 1.18 if max(todos) > 0 else 1
    bc.valueAxis.labelTextFormat = lambda v: f"{v:,.0f}"
    bc.valueAxis.labels.fontSize = 7
    bc.barLabelFormat = lambda v: f"{v:,.0f}"
    bc.barLabels.fontSize, bc.barLabels.nudge = 7, 6
    bc.bars[0].fillColor, bc.bars[1].fillColor = colors.HexColor("#" + AZUL), colors.HexColor("#" + VERDE_AZULADO)
    bc.bars.strokeColor = None
    bc.groupSpacing, bc.barSpacing = 14, 2
    dib.add(bc)
    leyenda = Legend()
    leyenda.x, leyenda.y, leyenda.fontSize, leyenda.alignment = 60, 6.2 * cm - 4, 8, "right"
    leyenda.columnMaximum, leyenda.deltax, leyenda.dxTextSpace = 1, 70, 4
    leyenda.colorNamePairs = [(colors.HexColor("#" + AZUL), "Banco"), (colors.HexColor("#" + VERDE_AZULADO), "Empresa")]
    dib.add(leyenda)
    return dib


def _grafica_por_dia(d):
    movs_b, movs_e = d["banco"]["movimientos"], d["empresa"]["movimientos"]
    fechas = sorted({m["fecha"] for m in movs_b + movs_e})
    if not fechas:
        return _vacio("No hay movimientos con fecha para graficar.")
    por_mes = (fechas[-1] - fechas[0]).days > 62
    clave = (lambda f: f.strftime("%Y-%m")) if por_mes else (lambda f: f)
    claves = sorted({clave(f) for f in fechas})
    cuenta = lambda movs: [sum(1 for m in movs if clave(m["fecha"]) == k) for k in claves]
    paso = max(1, -(-len(claves) // 16))      # como máximo ~16 etiquetas en el eje
    etiquetas = [(k if por_mes else k.strftime("%d/%m")) if i % paso == 0 else "" for i, k in enumerate(claves)]
    dib = Drawing(17 * cm, 6.2 * cm)
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 40, 38, 17 * cm - 55, 6.2 * cm - 58
    bc.data = [cuenta(movs_b), cuenta(movs_e)]
    bc.categoryAxis.categoryNames = etiquetas
    bc.categoryAxis.labels.fontSize = 7
    bc.categoryAxis.labels.angle, bc.categoryAxis.labels.boxAnchor = 45, "ne"
    bc.categoryAxis.labels.dx, bc.categoryAxis.labels.dy = 2, -2
    maximo = max(max(bc.data[0]), max(bc.data[1]))
    bc.valueAxis.valueMin, bc.valueAxis.valueMax = 0, maximo + 1
    bc.valueAxis.valueStep = max(1, round((maximo + 1) / 5))
    bc.valueAxis.labels.fontSize = 7
    bc.bars[0].fillColor, bc.bars[1].fillColor = colors.HexColor("#" + AZUL), colors.HexColor("#" + VERDE_AZULADO)
    bc.bars.strokeColor = None
    bc.groupSpacing, bc.barSpacing = 3, 0
    dib.add(bc)
    leyenda = Legend()
    leyenda.x, leyenda.y, leyenda.fontSize, leyenda.alignment = 60, 6.2 * cm - 4, 8, "right"
    leyenda.columnMaximum, leyenda.deltax, leyenda.dxTextSpace = 1, 70, 4
    leyenda.colorNamePairs = [(colors.HexColor("#" + AZUL), "Banco"), (colors.HexColor("#" + VERDE_AZULADO), "Empresa")]
    dib.add(leyenda)
    return dib, ("por mes" if por_mes else "por día")


# --- secciones de texto
def _resumen_texto(d):
    rs, bal = d["coincidencias"]["resumen"], d["balance"]
    c = d["coincidencias"]
    conc_b = len(c["conciliados"]) + sum(len(g["bancos"]) for g in c["manuales"])
    conc_e = len(c["conciliados"]) + sum(len(g["empresas"]) for g in c["manuales"])
    frases = []
    if rs["total_banco"] and rs["total_empresa"]:
        frases.append(
            f"Se compararon {rs['total_banco']} movimiento(s) del banco y {rs['total_empresa']} de la empresa. "
            f"Quedaron conciliados {conc_b} del banco ({rs['cobertura_banco']}%) y {conc_e} de la empresa "
            f"({rs['cobertura_empresa']}%): {rs['conciliados']} de forma automática (tolerancia de {rs['tolerancia']} día(s)) "
            f"y {rs['manuales']} de forma manual.")
    else:
        frases.append("No hay movimientos suficientes en ambos lados para calcular una cobertura.")
    if bal:
        if bal["cuadra"]:
            frases.append(
                f"La diferencia de {bal['neto_banco'] - bal['neto_empresa']:,.2f} entre banco y empresa se explica por completo con "
                f"{bal['n_banco']} movimiento(s) del banco y {bal['n_empresa']} de la empresa que no tienen pareja.")
        else:
            frases.append(
                f"Después de considerar las partidas sin conciliar queda una diferencia sin explicar de {bal['sin_explicar']:,.2f}. "
                "Suele deberse a filas sin fecha o sin monto que no participaron en el emparejamiento.")
    return frases


def _tabla_pendientes(titulo, movs, st, limite=20):
    elementos = [Paragraph(f"{titulo} ({len(movs)})", st["h2"])]
    if not movs:
        elementos.append(Paragraph("Sin movimientos pendientes.", st["peq"]))
        return elementos
    ordenados = sorted(movs, key=lambda m: -abs(m["monto"]))[:limite]
    filas = [[_p(t, st["encab"]) for t in ("Fecha", "Descripción", "Referencia", "Archivo", "Estado", "Monto")]]
    for m in ordenados:
        filas.append([_p(fmt_fecha(m["fecha"]), st["celda"]), _p(m["descripcion"] or "(sin descripción)", st["celda"]),
                      _p(m["referencia"], st["celda"]), _p(m["archivo"], st["celda"]),
                      _p("Por revisar" if m.get("sugerido") else "Sin pareja", st["celda"]),
                      _p(fmt_monto(m["monto"]), st["celda_der"])])
    elementos.append(_tabla_pdf(filas, [2.0 * cm, 4.9 * cm, 2.4 * cm, 4.0 * cm, 1.9 * cm, 2.4 * cm], st))
    if len(movs) > limite:
        elementos.append(Paragraph(f"Se muestran los {limite} de mayor monto de {len(movs)}. El detalle completo está en el Excel (hoja «Pendientes»).", st["peq"]))
    return elementos


class _LienzoNumerado(canvas.Canvas):
    """Pone «Página X de Y» y un encabezado discreto en cada página."""
    titulo = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paginas = []

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor("#6B7280"))
            self.drawString(2 * cm, letter[1] - 1.3 * cm, self.titulo)
            self.drawRightString(letter[0] - 2 * cm, 1.2 * cm, f"Página {self._pageNumber} de {total}")
            self.setStrokeColor(colors.HexColor("#E5E7EB"))
            self.line(2 * cm, letter[1] - 1.45 * cm, letter[0] - 2 * cm, letter[1] - 1.45 * cm)
            super().showPage()
        super().save()


def generar_pdf(datos):
    st = _estilos()
    c, rs, rep, bal = datos["conciliacion"], datos["coincidencias"]["resumen"], datos["reporte"], datos["balance"]
    story = []

    # --- Portada / resumen
    story += [Paragraph("Reporte de conciliación bancaria", st["titulo"]),
              Paragraph(f"Conciliación #{c.pk} · generado el {datos['generado']:%d/%m/%Y %H:%M} por {escape(datos['usuario'])}", st["sub"]),
              Spacer(1, 10), _kpis(datos, st), Spacer(1, 8)]
    for frase in _resumen_texto(datos):
        story += [Paragraph(escape(frase), st["p"]), Spacer(1, 4)]

    pb, cb = _archivos_texto(datos, "BANCO")
    pe, ce = _archivos_texto(datos, "EMPRESA")
    story.append(Paragraph("Periodos y archivos", st["h1"]))
    filas = [[_p(t, st["encab"]) for t in ("Lado", "Periodo", "Archivo principal", "Complementarios")],
             [_p("Banco", st["celda"]), _p(f"{fmt_fecha(c.banco_desde)} - {fmt_fecha(c.banco_hasta)}", st["celda"]), _p(pb, st["celda"]), _p(cb, st["celda"])],
             [_p("Empresa", st["celda"]), _p(f"{fmt_fecha(c.empresa_desde)} - {fmt_fecha(c.empresa_hasta)}", st["celda"]), _p(pe, st["celda"]), _p(ce, st["celda"])]]
    story.append(_tabla_pdf(filas, [2 * cm, 4.4 * cm, 5.6 * cm, 5.6 * cm], st))

    # --- Totales y balance
    story.append(Paragraph("Totales y balance", st["h1"]))
    sb, se = rep["banco"], rep["empresa"]
    def g(s, k, money=True):
        if not s:
            return "—"
        return fmt_monto(s[k]) if money else str(s[k])
    filas = [[_p(t, st["encab"]) for t in ("Concepto", "Banco", "Empresa")],
             [_p("Movimientos", st["celda"]), _p(g(sb, "movimientos", False), st["celda_der"]), _p(g(se, "movimientos", False), st["celda_der"])],
             [_p("Ingresos", st["celda"]), _p(g(sb, "ingresos"), st["celda_der"]), _p(g(se, "ingresos"), st["celda_der"])],
             [_p("Egresos", st["celda"]), _p(g(sb, "egresos"), st["celda_der"]), _p(g(se, "egresos"), st["celda_der"])],
             [_p("Neto", st["celda"]), _p(g(sb, "neto"), st["celda_der"]), _p(g(se, "neto"), st["celda_der"])]]
    story.append(_tabla_pdf(filas, [7 * cm, 5.1 * cm, 5.1 * cm], st, extra=[("FONTNAME", (0, 4), (-1, 4), "Helvetica-Bold")]))
    if bal:
        story += [Spacer(1, 8), Paragraph("Cuadre de la diferencia", st["h2"])]
        color_res = "#166534" if bal["cuadra"] else "#B42318"
        filas = [[_p(t, st["encab"]) for t in ("Concepto", "Monto", "Detalle")],
                 [_p("Neto del banco", st["celda"]), _p(fmt_monto(bal["neto_banco"]), st["celda_der"]), _p("", st["celda"])],
                 [_p("(-) Sin conciliar en el banco", st["celda"]), _p(fmt_monto(bal["sin_conciliar_banco"]), st["celda_der"]),
                  _p(f"{bal['n_banco']} movimiento(s), incluye los por revisar", st["celda"])],
                 [_p("(+) Sin conciliar en la empresa", st["celda"]), _p(fmt_monto(bal["sin_conciliar_empresa"]), st["celda_der"]),
                  _p(f"{bal['n_empresa']} movimiento(s), incluye los por revisar", st["celda"])],
                 [_p("(=) Neto del banco ajustado", st["celda"]), _p(fmt_monto(bal["neto_ajustado"]), st["celda_der"]), _p("", st["celda"])],
                 [_p("Neto de la empresa", st["celda"]), _p(fmt_monto(bal["neto_empresa"]), st["celda_der"]), _p("", st["celda"])],
                 [_p("Diferencia sin explicar", st["celda"]), _p(fmt_monto(bal["sin_explicar"]), st["celda_der"]),
                  Paragraph(f'<font color="{color_res}"><b>{"CUADRA" if bal["cuadra"] else "NO CUADRA"}</b></font>', st["celda"])]]
        story.append(_tabla_pdf(filas, [6.2 * cm, 3.6 * cm, 7.9 * cm], st, extra=[("FONTNAME", (0, 4), (-1, 4), "Helvetica-Bold")]))
        if not bal["completo"]:
            story.append(Paragraph("Nota: hay filas sin fecha que no participan en el emparejamiento, por lo que el cuadre puede no ser exacto.", st["peq"]))

    # --- Gráficas
    story.append(KeepTogether([Paragraph("Gráficas", st["h1"]),
                               Paragraph("Resultado de la conciliación (cantidad)", st["h2"]), _grafica_estados(datos)]))
    story.append(KeepTogether([Paragraph("Banco contra empresa: totales del periodo", st["h2"]), _grafica_totales(datos)]))
    por_dia = _grafica_por_dia(datos)
    if isinstance(por_dia, tuple):
        dibujo, agrupacion = por_dia
        story.append(KeepTogether([Paragraph(f"Movimientos {agrupacion}: banco contra empresa", st["h2"]), dibujo]))
    else:
        story.append(KeepTogether([Paragraph("Movimientos por día: banco contra empresa", st["h2"]), por_dia]))

    # --- Observaciones
    story.append(Paragraph("Observaciones", st["h1"]))
    if not rep["alertas"]:
        story.append(Paragraph("El análisis no generó avisos.", st["p"]))
    for a in rep["alertas"]:
        etiqueta, color = NIVELES[a["nivel"]]
        origen = f" [{a['origen']}]" if a["origen"] else ""
        texto = f'<font color="#{color}"><b>{etiqueta}{escape(origen)}:</b></font> <b>{escape(a["titulo"])}</b>'
        if a["detalle"]:
            texto += f'<br/><font color="#4B5563">{escape(a["detalle"])}</font>'
        story += [Paragraph(texto, st["p"]), Spacer(1, 5)]

    # --- Pendientes
    p = datos["coincidencias"]["pendientes"]
    story.append(Paragraph("Partidas pendientes", st["h1"]))
    story += _tabla_pendientes("Movimientos del banco sin conciliar", p["banco"], st)
    story += _tabla_pendientes("Movimientos de la empresa sin conciliar", p["empresa"], st)

    # --- Conciliaciones manuales
    manuales = datos["coincidencias"]["manuales"]
    if manuales:
        story.append(Paragraph(f"Conciliaciones manuales ({len(manuales)})", st["h1"]))
        filas = [[_p(t, st["encab"]) for t in ("Cuándo / quién", "Banco", "Empresa", "Monto", "Nota")]]
        for gr in manuales[:30]:
            cuando = f"{local(gr['creado']):%d/%m/%Y %H:%M}" if gr.get("creado") else ""
            filas.append([_p(f"{cuando} · {gr.get('usuario', '')}", st["celda"]),
                          _p("; ".join(f"{fmt_fecha(m['fecha'])} {m['descripcion'][:28]}" for m in gr["bancos"]), st["celda"]),
                          _p("; ".join(f"{fmt_fecha(m['fecha'])} {m['descripcion'][:28]}" for m in gr["empresas"]), st["celda"]),
                          _p(fmt_monto(gr["monto"]), st["celda_der"]), _p(gr.get("nota", ""), st["celda"])])
        story.append(_tabla_pdf(filas, [3.2 * cm, 4.6 * cm, 4.6 * cm, 2.1 * cm, 3.2 * cm], st))
        if len(manuales) > 30:
            story.append(Paragraph(f"Se muestran 30 de {len(manuales)}.", st["peq"]))

    story.append(Spacer(1, 14))
    story.append(Paragraph("Este reporte lo generó el sistema a partir de los archivos cargados. Los emparejamientos automáticos "
                           "se basan en monto, fecha y referencia; conviene revisar los casos marcados como «Por revisar».", st["peq"]))

    buf = io.BytesIO()
    titulo = f"Conciliación bancaria · Conciliación #{c.pk}"
    lienzo = type("Lienzo", (_LienzoNumerado,), {"titulo": titulo})
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=1.8 * cm,
                            title=f"Reporte de conciliación #{c.pk}", author=datos["usuario"])
    doc.build(story, canvasmaker=lienzo)
    return buf.getvalue()

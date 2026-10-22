from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from . import services

D = Decimal


class _Archivo:
    """Archivo falso con la interfaz mínima que usa services.leer_tabla."""
    def __init__(self, contenido):
        self._datos = contenido.encode("utf-8")

    def open(self, modo="rb"):
        pass

    def read(self):
        return self._datos

    def close(self):
        pass


def archivo(nombre, contenido):
    return SimpleNamespace(nombre=nombre, archivo=_Archivo(contenido))


def mov(id, dia, monto, ref="", desc=""):
    return {"id": id, "lado": "X", "archivo": "a.csv", "principal": True, "fila": id + 2,
            "fecha": date(2026, 10, dia), "monto": D(monto), "descripcion": desc, "referencia": ref}


RANGO = (date(2026, 10, 1), date(2026, 10, 31))


class EmparejarTests(SimpleTestCase):
    def test_empareja_monto_fecha_y_referencia(self):
        r = services.emparejar([mov(0, 1, "100", "A")], [mov(0, 1, "100", "A")])
        self.assertEqual(r["resumen"]["conciliados"], 1)
        self.assertEqual(r["conciliados"][0]["confianza"], 100)

    def test_tolerancia_de_fecha(self):
        r = services.emparejar([mov(0, 1, "100")], [mov(0, 4, "100")], tolerancia=3)
        self.assertEqual(r["resumen"]["conciliados"], 1)
        r = services.emparejar([mov(0, 1, "100")], [mov(0, 5, "100")], tolerancia=3)
        self.assertEqual(r["resumen"]["conciliados"], 0)
        self.assertEqual((r["resumen"]["pend_banco"], r["resumen"]["pend_empresa"]), (1, 1))

    def test_monto_distinto_no_empareja(self):
        r = services.emparejar([mov(0, 1, "100.00")], [mov(0, 1, "100.01")])
        self.assertEqual(r["resumen"]["conciliados"], 0)

    def test_ambiguo_queda_sugerido_y_no_se_empareja_solo(self):
        banco = [mov(0, 1, "50"), mov(1, 1, "50")]
        empresa = [mov(0, 1, "50"), mov(1, 2, "50")]
        r = services.emparejar(banco, empresa)
        self.assertEqual(r["resumen"]["conciliados"], 0)
        self.assertEqual(r["resumen"]["sugeridos"], 2)

    def test_la_referencia_desambigua(self):
        banco = [mov(0, 1, "50", "X"), mov(1, 1, "50", "Y")]
        empresa = [mov(0, 1, "50", "Y"), mov(1, 1, "50", "X")]
        r = services.emparejar(banco, empresa)
        self.assertEqual(r["resumen"]["conciliados"], 2)
        pares = {(c["banco"]["id"], c["empresa"]["id"]) for c in r["conciliados"]}
        self.assertEqual(pares, {(0, 1), (1, 0)})

    def test_un_movimiento_de_empresa_no_se_usa_dos_veces(self):
        banco = [mov(0, 1, "10"), mov(1, 2, "10")]
        empresa = [mov(0, 1, "10")]
        r = services.emparejar(banco, empresa)
        usados = [c["empresa"]["id"] for c in r["conciliados"]]
        self.assertEqual(len(usados), len(set(usados)))
        self.assertLessEqual(r["resumen"]["conciliados"], 1)

    def test_listas_vacias(self):
        r = services.emparejar([], [])
        self.assertEqual(r["total_filas"], 0)
        self.assertIsNone(r["resumen"]["cobertura_banco"])


class AnalizarTests(SimpleTestCase):
    BANCO = "Fecha,Descripcion,Referencia,Monto\n2026-10-01,Dep A,F1,100.00\n2026-10-02,Pago,P1,-40.50\n2026-11-09,Fuera,,-1\n"
    EMPRESA = "Fecha;Concepto;Folio;Cargo;Abono\n01/10/2026;Cobro;F1;;100.00\n02/10/2026;Pago;P1;40.50;\n"

    def test_normaliza_formatos_distintos(self):
        b = services.analizar([archivo("b.csv", self.BANCO)], *RANGO, "BANCO")
        e = services.analizar([archivo("e.csv", self.EMPRESA)], *RANGO, "EMPRESA")
        self.assertEqual(len(b["movimientos"]), 2)          # la fila de noviembre queda fuera del rango
        self.assertEqual(b["stats"]["neto"], D("59.50"))
        self.assertEqual(e["stats"]["neto"], D("59.50"))    # abono - cargo
        r = services.emparejar(b["movimientos"], e["movimientos"])
        self.assertEqual(r["resumen"]["conciliados"], 2)

    def test_complementario_aporta_filas_y_avisa_columnas_ignoradas(self):
        comp = "Fecha,Descripcion,Referencia,Monto,Notas\n2026-10-10,Interes,I1,5.00,x\n"
        b = services.analizar([archivo("b.csv", self.BANCO), archivo("c.csv", comp)], *RANGO, "BANCO")
        self.assertEqual(len(b["movimientos"]), 3)
        self.assertEqual(b["filas"][-1]["archivo"], "c.csv")
        self.assertFalse(b["filas"][-1]["principal"])
        self.assertTrue(any("columnas ignoradas" in a["titulo"] for a in b["avisos"]))

    def test_filas_repetidas_entre_archivos_generan_advertencia(self):
        b = services.analizar([archivo("b.csv", self.BANCO), archivo("c.csv", self.BANCO)], *RANGO, "BANCO")
        self.assertTrue(any(a["nivel"] == "advertencia" and "repetida" in a["titulo"] for a in b["avisos"]))

    def test_filas_invalidas_se_reportan_con_numero_de_fila(self):
        malo = "Fecha,Monto\nmala,10\n2026-10-03,abc\n2026-10-04,5\n"
        b = services.analizar([archivo("m.csv", malo)], *RANGO, "BANCO")
        self.assertEqual(len(b["movimientos"]), 1)
        aviso = next(a for a in b["avisos"] if "no se pudieron interpretar" in a["titulo"])
        self.assertIn("fila 2", aviso["detalle"])
        self.assertIn("fila 3", aviso["detalle"])

    def test_archivo_vacio_o_sin_archivos(self):
        self.assertIn("vacío", services.analizar([archivo("v.csv", "  ")], *RANGO)["error"])
        self.assertIsNotNone(services.analizar([], *RANGO)["error"])

    def test_sin_columna_de_monto(self):
        b = services.analizar([archivo("x.csv", "Fecha,Texto\n2026-10-01,hola\n")], *RANGO, "BANCO")
        self.assertIsNone(b["stats"])
        self.assertTrue(any("monto" in a["titulo"] for a in b["avisos"]))


class ReporteTests(SimpleTestCase):
    def _reporte(self, banco_csv, empresa_csv):
        b = services.analizar([archivo("b.csv", banco_csv)], *RANGO, "BANCO")
        e = services.analizar([archivo("e.csv", empresa_csv)], *RANGO, "EMPRESA")
        c = services.emparejar(b["movimientos"], e["movimientos"])
        return services.reporte(b, e, c)

    def test_alertas_ordenadas_por_gravedad_y_conteo(self):
        r = self._reporte("Fecha,Monto\n2026-10-01,100\n2026-10-02,-5\n", "Fecha,Monto\n2026-10-01,100\n2026-10-03,-9\n")
        niveles = [a["nivel"] for a in r["alertas"]]
        self.assertEqual(niveles, sorted(niveles, key=services.NIVELES.index))
        self.assertEqual(sum(r["conteo"].values()), len(r["alertas"]))
        self.assertEqual(r["diferencia"], D("4"))

    def test_detecta_signos_invertidos(self):
        r = self._reporte("Fecha,Monto\n2026-10-01,100\n", "Fecha,Monto\n2026-10-01,-100\n")
        self.assertTrue(any("signos" in a["titulo"] for a in r["alertas"]))

    def test_error_si_no_hay_nada_que_comparar(self):
        r = self._reporte("Fecha,Monto\n2027-01-01,1\n", "Fecha,Monto\n2027-01-01,1\n")
        self.assertGreaterEqual(r["conteo"]["error"], 1)

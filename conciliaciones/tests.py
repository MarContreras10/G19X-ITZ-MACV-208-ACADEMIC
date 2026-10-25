import shutil
import tempfile
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from . import services
from .models import ArchivoConciliacion, Conciliacion, Emparejamiento, EmparejamientoItem

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


def archivo(nombre, contenido, pk=None):
    return SimpleNamespace(nombre=nombre, archivo=_Archivo(contenido), pk=pk)


def mov(id, dia, monto, ref="", desc="", lado="X"):
    return {"id": id, "lado": lado, "archivo": "a.csv", "principal": True, "fila": id + 2,
            "clave": f"{lado}:{id}",
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


def grupo(id, *claves):
    return {"id": id, "claves": list(claves), "nota": "", "usuario": "ana", "creado": None, "tipo_label": "Conciliación manual"}


class EmparejarManualesTests(SimpleTestCase):
    def test_conciliacion_manual_uno_a_varios(self):
        banco = [mov(0, 1, "100", lado="B")]
        empresa = [mov(0, 20, "60", lado="E"), mov(1, 21, "40", lado="E")]
        r = services.emparejar(banco, empresa, manuales=[grupo(7, "B:0", "E:0", "E:1")])
        self.assertEqual(r["resumen"]["manuales"], 1)
        self.assertEqual(r["manuales"][0]["monto"], D("100"))
        self.assertEqual((r["resumen"]["pend_banco"], r["resumen"]["pend_empresa"]), (0, 0))
        self.assertEqual(r["pendientes"], {"banco": [], "empresa": []})
        self.assertEqual(r["resumen"]["cobertura_banco"], 100)
        self.assertEqual(r["resumen"]["cobertura_empresa"], 100)
        self.assertEqual(r["filas"][0]["estado"], "manual")
        self.assertEqual(len(r["filas"][0]["empresas"]), 2)

    def test_lo_manual_sale_del_emparejamiento_automatico(self):
        # Dos movimientos iguales: sin lo manual serían ambiguos; al resolver uno, el otro se empareja solo.
        banco = [mov(0, 1, "50", lado="B"), mov(1, 1, "50", lado="B")]
        empresa = [mov(0, 1, "50", lado="E"), mov(1, 1, "50", lado="E")]
        self.assertEqual(services.emparejar(banco, empresa)["resumen"]["sugeridos"], 2)
        r = services.emparejar(banco, empresa, manuales=[grupo(1, "B:0", "E:0")])
        self.assertEqual((r["resumen"]["manuales"], r["resumen"]["conciliados"], r["resumen"]["sugeridos"]), (1, 1, 0))

    def test_grupo_con_movimientos_no_disponibles_queda_huerfano(self):
        banco = [mov(0, 1, "10", lado="B")]
        empresa = [mov(0, 25, "10", lado="E")]
        r = services.emparejar(banco, empresa, manuales=[grupo(3, "B:0", "E:99")])
        self.assertEqual((r["resumen"]["manuales"], r["resumen"]["manuales_huerfanas"]), (0, 1))
        self.assertEqual(len(r["pendientes"]["banco"]), 1)   # no se perdió el movimiento
        self.assertEqual(r["manuales_huerfanas"][0]["id"], 3)

    def test_un_movimiento_no_puede_estar_en_dos_grupos(self):
        banco = [mov(0, 1, "10", lado="B")]
        empresa = [mov(0, 25, "10", lado="E"), mov(1, 26, "10", lado="E")]
        r = services.emparejar(banco, empresa, manuales=[grupo(1, "B:0", "E:0"), grupo(2, "B:0", "E:1")])
        self.assertEqual((r["resumen"]["manuales"], r["resumen"]["manuales_huerfanas"]), (1, 1))

    def test_reporte_informa_manuales_y_huerfanas(self):
        b = services.analizar([archivo("b.csv", "Fecha,Monto\n2026-10-01,10\n", pk=1)], *RANGO, "BANCO")
        e = services.analizar([archivo("e.csv", "Fecha,Monto\n2026-10-25,10\n", pk=2)], *RANGO, "EMPRESA")
        self.assertEqual((b["movimientos"][0]["clave"], e["movimientos"][0]["clave"]), ("1:2", "2:2"))
        c = services.emparejar(b["movimientos"], e["movimientos"], manuales=[grupo(1, "1:2", "2:99")])
        r = services.reporte(b, e, c)
        self.assertTrue(any("no se pudieron aplicar" in a["titulo"] for a in r["alertas"]))


CSV_BANCO = "Fecha,Descripcion,Referencia,Monto\n2026-10-01,Deposito grande,D1,100.00\n2026-10-02,Pago,P1,30.00\n2026-10-05,Mismo dia,M1,7.00\n"
CSV_EMPRESA = "Fecha,Concepto,Folio,Monto\n2026-10-20,Cobro uno,X1,60.00\n2026-10-21,Cobro dos,X2,40.00\n2026-10-22,Otro,X3,30.00\n2026-10-05,Mismo dia,M1,7.00\n"
FECHAS = {"banco_desde": "2026-10-01", "banco_hasta": "2026-10-31", "empresa_desde": "2026-10-01", "empresa_hasta": "2026-10-31"}


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ConciliacionManualVistasTests(TestCase):
    """Flujo completo contra la base de datos: permisos, validaciones, deshacer y archivos."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.ana = User.objects.create_user("ana")      # sin contraseña: las pruebas usan force_login
        self.otro = User.objects.create_user("otro")
        self.client.force_login(self.ana)
        r = self.client.post("/conciliacion/nueva/", {
            **FECHAS,
            "banco_principal": SimpleUploadedFile("banco.csv", CSV_BANCO.encode()),
            "empresa_principal": SimpleUploadedFile("empresa.csv", CSV_EMPRESA.encode())})
        self.assertEqual(r.status_code, 302)
        self.c = Conciliacion.objects.get()
        self.ab = self.c.archivos.get(lado="BANCO")
        self.ae = self.c.archivos.get(lado="EMPRESA")
        # Filas (encabezado = fila 1): banco 2=100.00 3=30.00 4=7.00 · empresa 2=60 3=40 4=30 5=7.00
        self.url = f"/conciliacion/{self.c.pk}/manual/"

    def k(self, archivo, fila):
        return f"{archivo.pk}:{fila}"

    def post(self, banco, empresa, **extra):
        return self.client.post(self.url, {"banco": banco, "empresa": empresa, "tol": "3", **extra}, follow=True)

    def mensajes(self, resp):
        return [str(m) for m in resp.context["messages"]]

    def test_el_mismo_dia_se_concilia_solo_y_no_se_ofrece_para_lo_manual(self):
        resp = self.client.get(f"/conciliacion/{self.c.pk}/?tol=3")
        pend = resp.context["coincidencias"]["pendientes"]
        # Solo el 7.00 del mismo día se concilia solo; el 30.00 está a 20 días (fuera de la tolerancia)
        self.assertEqual(resp.context["coincidencias"]["resumen"]["conciliados"], 1)
        self.assertNotIn(self.k(self.ab, 4), [m["clave"] for m in pend["banco"]])

    def test_concilia_uno_a_varios_con_totales_iguales(self):
        resp = self.post([self.k(self.ab, 2)], [self.k(self.ae, 2), self.k(self.ae, 3)], nota="Depósito agrupado")
        self.assertTrue(any("Conciliación creada" in m for m in self.mensajes(resp)))
        e = Emparejamiento.objects.get()
        self.assertEqual((e.creado_por, e.nota, e.items.count()), (self.ana, "Depósito agrupado", 3))
        manual = resp.context["coincidencias"]["manuales"]
        self.assertEqual(len(manual), 1)
        self.assertEqual(manual[0]["monto"], D("100.00"))

    def test_rechaza_totales_distintos(self):
        resp = self.post([self.k(self.ab, 2)], [self.k(self.ae, 2)])
        self.assertTrue(any("totales no coinciden" in m for m in self.mensajes(resp)))
        self.assertEqual(Emparejamiento.objects.count(), 0)

    def test_exige_ambos_lados(self):
        resp = self.post([self.k(self.ab, 2)], [])
        self.assertTrue(any("al menos un movimiento" in m for m in self.mensajes(resp)))

    def test_rechaza_movimiento_ya_conciliado_automaticamente(self):
        # banco fila 4 y empresa fila 5 (7.00, mismo día) se concilian solos
        resp = self.post([self.k(self.ab, 4)], [self.k(self.ae, 5)])
        self.assertTrue(any("ya está conciliado" in m for m in self.mensajes(resp)))
        self.assertEqual(Emparejamiento.objects.count(), 0)

    def test_rechaza_claves_inventadas_o_de_otra_conciliacion(self):
        resp = self.post(["999:2"], [self.k(self.ae, 2)])
        self.assertTrue(any("ya no está disponible" in m for m in self.mensajes(resp)))
        resp = self.post(["abc"], [self.k(self.ae, 2)])
        self.assertEqual(Emparejamiento.objects.count(), 0)

    def test_un_movimiento_no_se_concilia_dos_veces(self):
        self.post([self.k(self.ab, 3)], [self.k(self.ae, 4)])               # 30 = 30
        self.assertEqual(Emparejamiento.objects.count(), 1)
        resp = self.post([self.k(self.ab, 3)], [self.k(self.ae, 4)])
        self.assertTrue(any("ya está conciliado" in m for m in self.mensajes(resp)))
        self.assertEqual(Emparejamiento.objects.count(), 1)

    def test_otro_usuario_no_puede_conciliar_ni_deshacer(self):
        self.post([self.k(self.ab, 3)], [self.k(self.ae, 4)])
        e = Emparejamiento.objects.get()
        self.client.force_login(self.otro)
        self.assertEqual(self.client.post(self.url, {"banco": [self.k(self.ab, 3)], "empresa": [self.k(self.ae, 4)]}).status_code, 404)
        self.assertEqual(self.client.post(f"/emparejamientos/{e.pk}/deshacer/").status_code, 404)
        self.assertEqual(Emparejamiento.objects.count(), 1)

    def test_deshacer_libera_los_movimientos(self):
        self.post([self.k(self.ab, 3)], [self.k(self.ae, 4)])
        e = Emparejamiento.objects.get()
        r = self.client.post(f"/emparejamientos/{e.pk}/deshacer/", {"tol": "3", "ancla": "manual"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].endswith("?tol=3#manual"))
        self.assertEqual((Emparejamiento.objects.count(), EmparejamientoItem.objects.count()), (0, 0))

    def test_solo_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_sugerencia_aceptada_queda_registrada_como_tal(self):
        self.post([self.k(self.ab, 3)], [self.k(self.ae, 4)], tipo="ACEPTADA")
        self.assertEqual(Emparejamiento.objects.get().tipo, "ACEPTADA")
        self.post([self.k(self.ab, 2)], [self.k(self.ae, 2), self.k(self.ae, 3)], tipo="inventado")
        self.assertEqual(Emparejamiento.objects.order_by("id").last().tipo, "MANUAL")

    def test_eliminar_complementario_deshace_sus_conciliaciones(self):
        self.client.post(f"/conciliacion/{self.c.pk}/", {
            **FECHAS, "empresa_complementarios": [SimpleUploadedFile("extra.csv", b"Fecha,Concepto,Folio,Monto\n2026-10-15,Extra,E1,100.00\n")]})
        extra = self.c.archivos.get(principal=False)
        self.post([self.k(self.ab, 2)], [self.k(extra, 2)])                 # 100 = 100
        self.assertEqual(Emparejamiento.objects.count(), 1)
        resp = self.client.post(f"/archivos/{extra.pk}/eliminar/", follow=True)
        self.assertEqual(Emparejamiento.objects.count(), 0)
        self.assertTrue(any("conciliación(es) manual(es) que usaban" in m for m in self.mensajes(resp)))

    def test_reemplazar_el_principal_deshace_sus_conciliaciones_y_avisa(self):
        self.post([self.k(self.ab, 3)], [self.k(self.ae, 4)])
        resp = self.client.post(f"/conciliacion/{self.c.pk}/", {
            **FECHAS, "banco_principal": SimpleUploadedFile("banco2.csv", CSV_BANCO.encode())}, follow=True)
        self.assertEqual(Emparejamiento.objects.count(), 0)
        self.assertTrue(any("se deshicieron 1" in m.lower() for m in self.mensajes(resp)))

    def test_cambiar_el_rango_deja_la_conciliacion_como_no_aplicada_sin_borrarla(self):
        self.post([self.k(self.ab, 3)], [self.k(self.ae, 4)])               # banco 2026-10-02
        resp = self.client.post(f"/conciliacion/{self.c.pk}/", {**FECHAS, "banco_desde": "2026-10-10"}, follow=True)
        r = resp.context["coincidencias"]
        self.assertEqual((r["resumen"]["manuales"], r["resumen"]["manuales_huerfanas"]), (0, 1))
        self.assertEqual(Emparejamiento.objects.count(), 1)                 # sigue guardada
        self.assertIn("No aplicada", resp.content.decode())

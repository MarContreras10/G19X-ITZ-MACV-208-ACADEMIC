from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from . import services
from .forms import ConciliacionForm
from .models import ArchivoConciliacion, Conciliacion, Emparejamiento, EmparejamientoItem

Lado = ArchivoConciliacion.Lado
ANCLAS = ("manual", "coincidencias", "reporte")


# ------------------------------------------------------------------ utilidades
def _tolerancia_valida(valor):
    """Tolerancia de fecha en días (entre 0 y 30); si no es un número, la de por defecto."""
    try:
        valor = int(valor)
    except (TypeError, ValueError):
        valor = services.TOLERANCIA_DIAS
    return max(0, min(30, valor))


def _destino(conciliacion_pk, tolerancia, ancla=None):
    """URL de la conciliación conservando la tolerancia y la sección en la que estaba el usuario."""
    url = reverse("conciliacion", args=[conciliacion_pk]) + f"?tol={tolerancia}"
    return url + (f"#{ancla}" if ancla in ANCLAS else "")


def _analizar(obj):
    archivos_banco = list(obj.archivos_de(Lado.BANCO))
    archivos_empresa = list(obj.archivos_de(Lado.EMPRESA))
    banco = services.analizar(archivos_banco, obj.banco_desde, obj.banco_hasta, Lado.BANCO.value)
    empresa = services.analizar(archivos_empresa, obj.empresa_desde, obj.empresa_hasta, Lado.EMPRESA.value)
    return archivos_banco, archivos_empresa, banco, empresa


def _grupos_manuales(obj):
    """Conciliaciones manuales guardadas, en el formato que espera services.emparejar."""
    grupos = []
    for e in obj.emparejamientos.select_related("creado_por").prefetch_related("items"):
        grupos.append({
            "id": e.pk, "claves": [f"{i.archivo_id}:{i.fila}" for i in e.items.all()],
            "nota": e.nota, "tipo": e.tipo, "tipo_label": e.get_tipo_display(),
            "usuario": e.creado_por.get_username() if e.creado_por else "", "creado": e.creado,
        })
    return grupos


def _emparejar(obj, banco, empresa, tolerancia):
    return services.emparejar(banco["movimientos"], empresa["movimientos"], tolerancia, _grupos_manuales(obj))


def _avisar_manuales_eliminados(request, form):
    n = getattr(form, "manuales_eliminados", 0)
    if n:
        messages.warning(request, f"Se deshicieron {n} conciliación(es) manual(es) porque usaban un archivo que se reemplazó.")


# ----------------------------------------------------------------------- vistas
class MisConciliaciones(LoginRequiredMixin):
    def get_queryset(self):
        return Conciliacion.objects.filter(usuario=self.request.user)


class Inicio(MisConciliaciones, ListView):
    template_name = "conciliaciones/home.html"
    context_object_name = "conciliaciones"


class VistaPreviaMixin:
    """Agrega vista previa, coincidencias y reporte cuando la conciliación ya existe."""
    form_class = ConciliacionForm
    template_name = "conciliaciones/conciliacion.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        obj = getattr(self, "object", None)
        if obj and obj.pk:
            archivos_banco, archivos_empresa, banco, empresa = _analizar(obj)
            tolerancia = _tolerancia_valida(self.request.GET.get("tol"))
            coincidencias = _emparejar(obj, banco, empresa, tolerancia)
            ctx.update(archivos_banco=archivos_banco, archivos_empresa=archivos_empresa,
                       banco=banco, empresa=empresa, tolerancia=tolerancia, coincidencias=coincidencias,
                       reporte=services.reporte(banco, empresa, coincidencias, obj))
        return ctx

    def get_success_url(self):
        return reverse_lazy("conciliacion", args=[self.object.pk])


class Nueva(LoginRequiredMixin, VistaPreviaMixin, CreateView):
    def form_valid(self, form):
        form.instance.usuario = self.request.user
        messages.success(self.request, "Archivos cargados correctamente.")
        respuesta = super().form_valid(form)
        _avisar_manuales_eliminados(self.request, form)
        return respuesta


class Detalle(MisConciliaciones, VistaPreviaMixin, UpdateView):
    def form_valid(self, form):
        messages.success(self.request, "Vista previa actualizada.")
        respuesta = super().form_valid(form)
        _avisar_manuales_eliminados(self.request, form)
        return respuesta


class EliminarArchivo(LoginRequiredMixin, View):
    def post(self, request, pk):
        archivo = get_object_or_404(ArchivoConciliacion, pk=pk, conciliacion__usuario=request.user)
        conciliacion_pk = archivo.conciliacion_id
        if archivo.principal:
            messages.error(request, "El archivo principal no se elimina; sube otro para reemplazarlo.")
        else:
            afectadas = Emparejamiento.objects.filter(items__archivo=archivo).distinct().count()
            archivo.delete()
            messages.success(request, "Archivo complementario eliminado.")
            if afectadas:
                messages.warning(request, f"Se deshicieron {afectadas} conciliación(es) manual(es) que usaban ese archivo.")
        return redirect("conciliacion", pk=conciliacion_pk)


class ConciliarManual(LoginRequiredMixin, View):
    """Crea una conciliación manual (o acepta una sugerencia) con los movimientos elegidos."""
    MAX_POR_LADO = 200

    def post(self, request, pk):
        obj = get_object_or_404(Conciliacion, pk=pk, usuario=request.user)
        tolerancia = _tolerancia_valida(request.POST.get("tol"))
        destino = _destino(obj.pk, tolerancia, request.POST.get("ancla"))

        # dict.fromkeys quita repetidos conservando el orden
        claves_b = list(dict.fromkeys(request.POST.getlist("banco")))
        claves_e = list(dict.fromkeys(request.POST.getlist("empresa")))
        if not claves_b or not claves_e:
            messages.error(request, "Selecciona al menos un movimiento del banco y uno de la empresa.")
            return redirect(destino)
        if len(claves_b) > self.MAX_POR_LADO or len(claves_e) > self.MAX_POR_LADO:
            messages.error(request, f"Se pueden conciliar como máximo {self.MAX_POR_LADO} movimientos por lado a la vez.")
            return redirect(destino)

        # Nunca se confía en lo que manda el navegador: se recalculan los movimientos
        # pendientes y los montos a partir de los archivos.
        _, _, banco, empresa = _analizar(obj)
        pendientes = _emparejar(obj, banco, empresa, tolerancia)["pendientes"]
        libres_b = {m["clave"]: m for m in pendientes["banco"]}
        libres_e = {m["clave"]: m for m in pendientes["empresa"]}
        if any(c not in libres_b for c in claves_b) or any(c not in libres_e for c in claves_e):
            messages.error(request, "Alguno de los movimientos ya está conciliado o ya no está disponible. "
                                    "Revisa la lista actualizada e inténtalo de nuevo.")
            return redirect(destino)

        suma_b = sum((libres_b[c]["monto"] for c in claves_b), Decimal("0.00"))
        suma_e = sum((libres_e[c]["monto"] for c in claves_e), Decimal("0.00"))
        if suma_b != suma_e:
            messages.error(request, f"Los totales no coinciden: banco {suma_b:,.2f} y empresa {suma_e:,.2f} "
                                    f"(diferencia {suma_b - suma_e:,.2f}).")
            return redirect(destino)

        tipo = request.POST.get("tipo")
        if tipo not in Emparejamiento.Tipo.values:
            tipo = Emparejamiento.Tipo.MANUAL
        try:
            with transaction.atomic():
                e = Emparejamiento.objects.create(
                    conciliacion=obj, tipo=tipo, creado_por=request.user,
                    nota=request.POST.get("nota", "").strip()[:255])
                EmparejamientoItem.objects.bulk_create([
                    EmparejamientoItem(emparejamiento=e, archivo_id=int(c.split(":")[0]), fila=int(c.split(":")[1]))
                    for c in claves_b + claves_e])
        except IntegrityError:  # otra petición los concilió al mismo tiempo
            messages.error(request, "Alguno de los movimientos acaba de ser conciliado por otra acción.")
            return redirect(destino)

        messages.success(request, f"Conciliación creada: {len(claves_b)} del banco ↔ {len(claves_e)} de la empresa "
                                  f"({suma_b:,.2f}).")
        return redirect(destino)


class DeshacerManual(LoginRequiredMixin, View):
    def post(self, request, pk):
        emparejamiento = get_object_or_404(Emparejamiento, pk=pk, conciliacion__usuario=request.user)
        conciliacion_pk = emparejamiento.conciliacion_id
        emparejamiento.delete()
        messages.success(request, "Conciliación deshecha: los movimientos vuelven a estar disponibles.")
        return redirect(_destino(conciliacion_pk, _tolerancia_valida(request.POST.get("tol")), request.POST.get("ancla")))

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from . import services
from .forms import ConciliacionForm
from .models import ArchivoConciliacion, Conciliacion

Lado = ArchivoConciliacion.Lado


class MisConciliaciones(LoginRequiredMixin):
    def get_queryset(self):
        return Conciliacion.objects.filter(usuario=self.request.user)


class Inicio(MisConciliaciones, ListView):
    template_name = "conciliaciones/home.html"
    context_object_name = "conciliaciones"


class VistaPreviaMixin:
    """Agrega vista previa y reporte cuando la conciliación ya existe."""
    form_class = ConciliacionForm
    template_name = "conciliaciones/conciliacion.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        obj = getattr(self, "object", None)
        if obj and obj.pk:
            archivos_banco = list(obj.archivos_de(Lado.BANCO))
            archivos_empresa = list(obj.archivos_de(Lado.EMPRESA))
            banco = services.analizar(archivos_banco, obj.banco_desde, obj.banco_hasta, Lado.BANCO.value)
            empresa = services.analizar(archivos_empresa, obj.empresa_desde, obj.empresa_hasta, Lado.EMPRESA.value)
            tolerancia = self._tolerancia()
            coincidencias = services.emparejar(banco["movimientos"], empresa["movimientos"], tolerancia)
            ctx.update(archivos_banco=archivos_banco, archivos_empresa=archivos_empresa,
                       banco=banco, empresa=empresa, tolerancia=tolerancia, coincidencias=coincidencias,
                       reporte=services.reporte(banco, empresa, coincidencias, obj))
        return ctx

    def _tolerancia(self):
        """Tolerancia de fecha en días, tomada de ?tol=N (entre 0 y 30)."""
        try:
            valor = int(self.request.GET.get("tol", services.TOLERANCIA_DIAS))
        except ValueError:
            valor = services.TOLERANCIA_DIAS
        return max(0, min(30, valor))

    def get_success_url(self):
        return reverse_lazy("conciliacion", args=[self.object.pk])


class Nueva(LoginRequiredMixin, VistaPreviaMixin, CreateView):
    def form_valid(self, form):
        form.instance.usuario = self.request.user
        messages.success(self.request, "Archivos cargados correctamente.")
        return super().form_valid(form)


class Detalle(MisConciliaciones, VistaPreviaMixin, UpdateView):
    def form_valid(self, form):
        messages.success(self.request, "Vista previa actualizada.")
        return super().form_valid(form)


class EliminarArchivo(LoginRequiredMixin, View):
    def post(self, request, pk):
        archivo = get_object_or_404(ArchivoConciliacion, pk=pk, conciliacion__usuario=request.user)
        conciliacion_pk = archivo.conciliacion_id
        if archivo.principal:
            messages.error(request, "El archivo principal no se elimina; sube otro para reemplazarlo.")
        else:
            archivo.delete()
            messages.success(request, "Archivo complementario eliminado.")
        return redirect("conciliacion", pk=conciliacion_pk)

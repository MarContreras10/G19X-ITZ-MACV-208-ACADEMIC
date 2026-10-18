from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView

from . import services
from .forms import ConciliacionForm
from .models import Conciliacion


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
            banco = services.analizar(obj.banco_archivo, obj.banco_desde, obj.banco_hasta)
            empresa = services.analizar(obj.empresa_archivo, obj.empresa_desde, obj.empresa_hasta)
            ctx.update(banco=banco, empresa=empresa, reporte=services.reporte(banco, empresa))
        return ctx

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

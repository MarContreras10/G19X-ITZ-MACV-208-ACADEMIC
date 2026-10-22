from django import forms
from django.db import transaction

from .models import ArchivoConciliacion, Conciliacion

Lado = ArchivoConciliacion.Lado


class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Campo que acepta varios archivos a la vez; devuelve una lista."""

    def clean(self, data, initial=None):
        if not data:
            return []
        if not isinstance(data, (list, tuple)):
            data = [data]
        return [forms.FileField.clean(self, d, initial) for d in data]


def _csv(attrs=None):
    return {"accept": ".csv", **(attrs or {})}


class ConciliacionForm(forms.ModelForm):
    banco_principal = forms.FileField(
        label="Archivo principal", widget=forms.FileInput(attrs=_csv()))
    banco_complementarios = MultipleFileField(
        label="Archivos complementarios (opcional)", required=False,
        widget=MultipleFileInput(attrs=_csv()))
    empresa_principal = forms.FileField(
        label="Archivo principal", widget=forms.FileInput(attrs=_csv()))
    empresa_complementarios = MultipleFileField(
        label="Archivos complementarios (opcional)", required=False,
        widget=MultipleFileInput(attrs=_csv()))

    class Meta:
        model = Conciliacion
        fields = ["banco_desde", "banco_hasta", "empresa_desde", "empresa_hasta"]
        widgets = {c: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d") for c in fields}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:  # al editar, el principal ya existe: reemplazarlo es opcional
            self.fields["banco_principal"].required = False
            self.fields["empresa_principal"].required = False

    # --- validación: solo .csv ---
    def _solo_csv(self, campo):
        valor = self.cleaned_data.get(campo)
        archivos = valor if isinstance(valor, list) else ([valor] if valor else [])
        for a in archivos:
            if not a.name.lower().endswith(".csv"):
                raise forms.ValidationError(f"'{a.name}': por ahora solo se aceptan archivos .csv")
        return valor

    def clean_banco_principal(self):
        return self._solo_csv("banco_principal")

    def clean_banco_complementarios(self):
        return self._solo_csv("banco_complementarios")

    def clean_empresa_principal(self):
        return self._solo_csv("empresa_principal")

    def clean_empresa_complementarios(self):
        return self._solo_csv("empresa_complementarios")

    def clean(self):
        datos = super().clean()
        for lado in ("banco", "empresa"):
            desde, hasta = datos.get(f"{lado}_desde"), datos.get(f"{lado}_hasta")
            if desde and hasta and desde > hasta:
                self.add_error(f"{lado}_hasta", "La fecha final no puede ser anterior a la inicial.")
        return datos

    @transaction.atomic
    def save(self, commit=True):
        obj = super().save(commit=commit)
        for prefijo, lado in (("banco", Lado.BANCO), ("empresa", Lado.EMPRESA)):
            principal = self.cleaned_data.get(f"{prefijo}_principal")
            if principal:
                for anterior in obj.archivos.filter(lado=lado, principal=True):
                    anterior.delete()
                ArchivoConciliacion.objects.create(conciliacion=obj, lado=lado, archivo=principal, principal=True)
            for f in self.cleaned_data.get(f"{prefijo}_complementarios", []):
                ArchivoConciliacion.objects.create(conciliacion=obj, lado=lado, archivo=f, principal=False)
        return obj

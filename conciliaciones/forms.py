from django import forms
from django.db import transaction

from . import services
from .models import ArchivoConciliacion, Conciliacion, Emparejamiento

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


def _aceptados(attrs=None):
    """Atributos del campo de archivo: los formatos permitidos salen de services.EXTENSIONES_ACEPTADAS."""
    return {"accept": ",".join(services.EXTENSIONES_ACEPTADAS), **(attrs or {})}


class ConciliacionForm(forms.ModelForm):
    banco_principal = forms.FileField(
        label="Archivo principal", widget=forms.FileInput(attrs=_aceptados()))
    banco_complementarios = MultipleFileField(
        label="Archivos complementarios (opcional)", required=False,
        widget=MultipleFileInput(attrs=_aceptados()))
    empresa_principal = forms.FileField(
        label="Archivo principal", widget=forms.FileInput(attrs=_aceptados()))
    empresa_complementarios = MultipleFileField(
        label="Archivos complementarios (opcional)", required=False,
        widget=MultipleFileInput(attrs=_aceptados()))

    class Meta:
        model = Conciliacion
        fields = ["banco_desde", "banco_hasta", "empresa_desde", "empresa_hasta"]
        widgets = {c: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d") for c in fields}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:  # al editar, el principal ya existe: reemplazarlo es opcional
            self.fields["banco_principal"].required = False
            self.fields["empresa_principal"].required = False
        # Las fechas son opcionales: si faltan se toman del archivo principal (ver clean)
        for campo in ("banco_desde", "banco_hasta", "empresa_desde", "empresa_hasta"):
            self.fields[campo].required = False

    # --- validación: formato y tamaño del archivo ---
    def _validar_archivos(self, campo):
        valor = self.cleaned_data.get(campo)
        archivos = valor if isinstance(valor, list) else ([valor] if valor else [])
        for a in archivos:
            if not services.extension_valida(a.name):
                raise forms.ValidationError(f"'{a.name}': solo se aceptan archivos {services.FORMATOS_TEXTO}.")
            if a.size > services.MAX_BYTES_ARCHIVO:
                raise forms.ValidationError(
                    f"'{a.name}': pesa más de {services.MAX_BYTES_ARCHIVO // (1024 * 1024)} MB.")
        return valor

    def clean_banco_principal(self):
        return self._validar_archivos("banco_principal")

    def clean_banco_complementarios(self):
        return self._validar_archivos("banco_complementarios")

    def clean_empresa_principal(self):
        return self._validar_archivos("empresa_principal")

    def clean_empresa_complementarios(self):
        return self._validar_archivos("empresa_complementarios")

    def _rango_del_principal(self, prefijo, lado):
        """Rango de fechas del archivo principal de un lado (el recién subido o el ya guardado)."""
        subido = self.cleaned_data.get(f"{prefijo}_principal")
        if subido:
            subido.seek(0)
            datos = subido.read()
            subido.seek(0)   # se deja listo para guardarlo después
            return services.rango_fechas(services.ArchivoEnMemoria(datos))
        if self.instance.pk:
            guardado = self.instance.archivos.filter(lado=lado, principal=True).first()
            if guardado:
                return services.rango_fechas(guardado.archivo)
        return None

    def _completar_fechas(self, datos):
        """Si falta alguna fecha de un lado, la toma del archivo principal."""
        self.rangos_automaticos = []   # [(etiqueta, desde, hasta)] para avisar al usuario
        for prefijo, lado, etiqueta in (("banco", Lado.BANCO, "Banco"), ("empresa", Lado.EMPRESA, "Empresa")):
            faltan = [c for c in (f"{prefijo}_desde", f"{prefijo}_hasta") if not datos.get(c)]
            if not faltan or self.errors.get(f"{prefijo}_principal"):
                continue
            try:
                rango = self._rango_del_principal(prefijo, lado)
            except services.ErrorArchivo as e:
                for c in faltan:
                    self.add_error(c, f"No se pudo tomar la fecha del archivo principal: {e}")
                continue
            if rango is None:
                for c in faltan:
                    self.add_error(c, "Indica la fecha o carga el archivo principal para tomarla de ahí.")
                continue
            if f"{prefijo}_desde" in faltan:
                datos[f"{prefijo}_desde"] = rango["desde"]
            if f"{prefijo}_hasta" in faltan:
                datos[f"{prefijo}_hasta"] = rango["hasta"]
            self.rangos_automaticos.append((etiqueta, datos[f"{prefijo}_desde"], datos[f"{prefijo}_hasta"]))

    def clean(self):
        datos = super().clean()
        self._completar_fechas(datos)
        for lado in ("banco", "empresa"):
            desde, hasta = datos.get(f"{lado}_desde"), datos.get(f"{lado}_hasta")
            if desde and hasta and desde > hasta:
                self.add_error(f"{lado}_hasta", "La fecha final no puede ser anterior a la inicial.")
        return datos

    @transaction.atomic
    def save(self, commit=True):
        obj = super().save(commit=commit)
        self.manuales_eliminados = 0   # conciliaciones manuales que dependían de un archivo reemplazado
        for prefijo, lado in (("banco", Lado.BANCO), ("empresa", Lado.EMPRESA)):
            principal = self.cleaned_data.get(f"{prefijo}_principal")
            if principal:
                for anterior in obj.archivos.filter(lado=lado, principal=True):
                    self.manuales_eliminados += Emparejamiento.objects.filter(items__archivo=anterior).distinct().count()
                    anterior.delete()
                ArchivoConciliacion.objects.create(conciliacion=obj, lado=lado, archivo=principal, principal=True)
            for f in self.cleaned_data.get(f"{prefijo}_complementarios", []):
                ArchivoConciliacion.objects.create(conciliacion=obj, lado=lado, archivo=f, principal=False)
        return obj

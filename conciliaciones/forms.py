from django import forms

from .models import Conciliacion


class ConciliacionForm(forms.ModelForm):
    class Meta:
        model = Conciliacion
        fields = ["banco_desde", "banco_hasta", "banco_archivo",
                  "empresa_desde", "empresa_hasta", "empresa_archivo"]
        widgets = {
            "banco_desde": forms.DateInput(attrs={"type": "date"}),
            "banco_hasta": forms.DateInput(attrs={"type": "date"}),
            "empresa_desde": forms.DateInput(attrs={"type": "date"}),
            "empresa_hasta": forms.DateInput(attrs={"type": "date"}),
            "banco_archivo": forms.FileInput(attrs={"accept": ".csv"}),
            "empresa_archivo": forms.FileInput(attrs={"accept": ".csv"}),
        }

    def _validar_csv(self, campo):
        archivo = self.cleaned_data.get(campo)
        if archivo and not archivo.name.lower().endswith(".csv"):
            raise forms.ValidationError("Por ahora solo se aceptan archivos .csv")
        return archivo

    def clean_banco_archivo(self):
        return self._validar_csv("banco_archivo")

    def clean_empresa_archivo(self):
        return self._validar_csv("empresa_archivo")

    def clean(self):
        datos = super().clean()
        for lado in ("banco", "empresa"):
            desde, hasta = datos.get(f"{lado}_desde"), datos.get(f"{lado}_hasta")
            if desde and hasta and desde > hasta:
                self.add_error(f"{lado}_hasta", "La fecha final no puede ser anterior a la inicial.")
        return datos

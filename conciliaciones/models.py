import os

from django.conf import settings
from django.db import models


class Conciliacion(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conciliaciones")
    creada = models.DateTimeField(auto_now_add=True)

    banco_desde = models.DateField("Desde")
    banco_hasta = models.DateField("Hasta")
    banco_archivo = models.FileField("Archivo del banco", upload_to="banco/%Y/%m/")

    empresa_desde = models.DateField("Desde")
    empresa_hasta = models.DateField("Hasta")
    empresa_archivo = models.FileField("Archivo de la empresa", upload_to="empresa/%Y/%m/")

    class Meta:
        ordering = ["-creada"]
        verbose_name_plural = "conciliaciones"

    def __str__(self):
        return f"Conciliación #{self.pk}"

    @property
    def nombre_banco(self):
        return os.path.basename(self.banco_archivo.name)

    @property
    def nombre_empresa(self):
        return os.path.basename(self.empresa_archivo.name)

import os

from django.conf import settings
from django.db import models


class Conciliacion(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conciliaciones")
    creada = models.DateTimeField(auto_now_add=True)

    banco_desde = models.DateField("Desde")
    banco_hasta = models.DateField("Hasta")
    empresa_desde = models.DateField("Desde")
    empresa_hasta = models.DateField("Hasta")

    class Meta:
        ordering = ["-creada"]
        verbose_name_plural = "conciliaciones"

    def __str__(self):
        return f"Conciliación #{self.pk}"

    def archivos_de(self, lado):
        """Archivos de un lado; el principal siempre va primero."""
        return self.archivos.filter(lado=lado)


def ruta_archivo(instance, filename):
    return f"{instance.lado.lower()}/{instance.conciliacion_id}/{filename}"


class ArchivoConciliacion(models.Model):
    class Lado(models.TextChoices):
        BANCO = "BANCO", "Banco"
        EMPRESA = "EMPRESA", "Empresa"

    conciliacion = models.ForeignKey(Conciliacion, on_delete=models.CASCADE, related_name="archivos")
    lado = models.CharField(max_length=7, choices=Lado.choices)
    archivo = models.FileField(upload_to=ruta_archivo)
    principal = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-principal", "creado", "id"]

    def __str__(self):
        return f"{self.get_lado_display()}: {self.nombre}"

    @property
    def nombre(self):
        return os.path.basename(self.archivo.name)

    def delete(self, *args, **kwargs):
        self.archivo.delete(save=False)  # también borra el archivo del disco
        return super().delete(*args, **kwargs)
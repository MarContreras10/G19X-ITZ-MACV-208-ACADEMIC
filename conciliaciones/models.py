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
        # Una conciliación manual no puede sobrevivir sin uno de sus movimientos
        Emparejamiento.objects.filter(items__archivo=self).delete()
        self.archivo.delete(save=False)  # también borra el archivo del disco
        return super().delete(*args, **kwargs)


class Emparejamiento(models.Model):
    """Conciliación hecha por una persona: agrupa movimientos del banco y de la empresa.

    Admite 1 a 1, 1 a varios y varios a varios, siempre que los totales de ambos lados coincidan.
    """

    class Tipo(models.TextChoices):
        MANUAL = "MANUAL", "Conciliación manual"
        ACEPTADA = "ACEPTADA", "Sugerencia aceptada"

    conciliacion = models.ForeignKey(Conciliacion, on_delete=models.CASCADE, related_name="emparejamientos")
    tipo = models.CharField(max_length=8, choices=Tipo.choices, default=Tipo.MANUAL)
    nota = models.CharField(max_length=255, blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado", "-id"]
        verbose_name_plural = "emparejamientos"

    def __str__(self):
        return f"{self.get_tipo_display()} #{self.pk}"


class EmparejamientoItem(models.Model):
    """Un movimiento, identificado por su archivo y su número de fila (el encabezado es la fila 1)."""

    emparejamiento = models.ForeignKey(Emparejamiento, on_delete=models.CASCADE, related_name="items")
    archivo = models.ForeignKey(ArchivoConciliacion, on_delete=models.CASCADE, related_name="items_emparejados")
    fila = models.PositiveIntegerField()

    class Meta:
        constraints = [
            # Un movimiento solo puede estar en una conciliación manual
            models.UniqueConstraint(fields=["archivo", "fila"], name="uq_movimiento_un_emparejamiento"),
        ]

    def __str__(self):
        return f"{self.archivo_id}:{self.fila}"

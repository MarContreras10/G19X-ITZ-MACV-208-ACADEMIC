import django.db.models.deletion
from django.db import migrations, models

import conciliaciones.models


def mover_archivos(apps, schema_editor):
    """Pasa los archivos que ya existían al nuevo modelo, como principales."""
    Conciliacion = apps.get_model("conciliaciones", "Conciliacion")
    Archivo = apps.get_model("conciliaciones", "ArchivoConciliacion")
    for c in Conciliacion.objects.all():
        if c.banco_archivo:
            Archivo.objects.create(conciliacion=c, lado="BANCO", archivo=c.banco_archivo.name, principal=True)
        if c.empresa_archivo:
            Archivo.objects.create(conciliacion=c, lado="EMPRESA", archivo=c.empresa_archivo.name, principal=True)


class Migration(migrations.Migration):

    dependencies = [("conciliaciones", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="ArchivoConciliacion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("lado", models.CharField(choices=[("BANCO", "Banco"), ("EMPRESA", "Empresa")], max_length=7)),
                ("archivo", models.FileField(upload_to=conciliaciones.models.ruta_archivo)),
                ("principal", models.BooleanField(default=False)),
                ("creado", models.DateTimeField(auto_now_add=True)),
                ("conciliacion", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                                   related_name="archivos", to="conciliaciones.conciliacion")),
            ],
            options={"ordering": ["-principal", "creado", "id"]},
        ),
        migrations.RunPython(mover_archivos, migrations.RunPython.noop),
        migrations.RemoveField(model_name="conciliacion", name="banco_archivo"),
        migrations.RemoveField(model_name="conciliacion", name="empresa_archivo"),
    ]
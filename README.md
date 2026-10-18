# Conciliación bancaria — interfaz

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```
Abre http://127.0.0.1:8000/ e inicia sesión.

Pantalla de conciliación: barra lateral (rangos y archivos .csv) · vista previa con paneles desplazables · reporte.
Para probar, usa `sample_data/banco.csv` y `sample_data/empresa.csv`.

Archivos CSV: se detecta separador (`,` `;` tab) y codificación. Se buscan columnas de fecha y de monto
(`monto/importe` o `cargo` y `abono`). Positivo = ingreso, negativo = egreso.

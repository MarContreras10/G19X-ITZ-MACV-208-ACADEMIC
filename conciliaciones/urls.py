from django.contrib.auth import views as auth
from django.urls import path

from . import views

urlpatterns = [
    path("login/", auth.LoginView.as_view(), name="login"),
    path("logout/", auth.LogoutView.as_view(), name="logout"),
    path("", views.Inicio.as_view(), name="home"),
    path("conciliacion/nueva/", views.Nueva.as_view(), name="nueva"),
    path("conciliacion/<int:pk>/", views.Detalle.as_view(), name="conciliacion"),
    path("archivos/<int:pk>/eliminar/", views.EliminarArchivo.as_view(), name="eliminar_archivo"),
    path("conciliacion/<int:pk>/manual/", views.ConciliarManual.as_view(), name="conciliar_manual"),
    path("emparejamientos/<int:pk>/deshacer/", views.DeshacerManual.as_view(), name="deshacer_manual"),
]

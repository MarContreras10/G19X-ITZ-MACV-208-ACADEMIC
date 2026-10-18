from django.contrib.auth import views as auth
from django.urls import path

from . import views

urlpatterns = [
    path("login/", auth.LoginView.as_view(), name="login"),
    path("logout/", auth.LogoutView.as_view(), name="logout"),
    path("", views.Inicio.as_view(), name="home"),
    path("conciliacion/nueva/", views.Nueva.as_view(), name="nueva"),
    path("conciliacion/<int:pk>/", views.Detalle.as_view(), name="conciliacion"),
]

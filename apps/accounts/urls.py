from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", views.register, name="register"),
    path("profile/", views.profile, name="profile"),
    path("profile/privacy/", views.privacy_page, name="privacy"),
    path("profile/export-data/", views.export_data, name="export_data"),
    path("profile/clear-history/", views.clear_history, name="clear_history"),
    path("profile/stop-profiling/", views.stop_profiling, name="stop_profiling"),
    path("profile/delete-account/", views.delete_account, name="delete_account"),

    # Gestiunea conturilor, pentru bibliotecar
    path("gestiune/utilizatori/", views.utilizatori, name="utilizatori"),
    path("gestiune/utilizatori/nou/", views.utilizator_salveaza, name="utilizator_creeaza"),
    path("gestiune/utilizatori/<int:pk>/", views.utilizatori, name="utilizator"),
    path("gestiune/utilizatori/<int:pk>/salveaza/", views.utilizator_salveaza, name="utilizator_salveaza"),
    path("gestiune/utilizatori/<int:pk>/sterge/", views.utilizator_sterge, name="utilizator_sterge"),
]

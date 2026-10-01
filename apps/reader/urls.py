from django.urls import path

from . import views

app_name = "reader"

urlpatterns = [
    path("books/<slug:slug>/read/", views.read_book, name="read"),
    path("books/<slug:slug>/state/", views.set_state, name="set_state"),
    path("books/<slug:slug>/reaction/", views.set_reaction, name="set_reaction"),
    path("resources/<int:resource_id>/content/", views.resource_content, name="content"),
    path("resources/<int:resource_id>/progress/", views.save_progress, name="save_progress"),
    path("my-library/", views.my_library, name="my_library"),
    path("my-library/<str:shelf>/", views.my_library, name="my_library_shelf"),
]

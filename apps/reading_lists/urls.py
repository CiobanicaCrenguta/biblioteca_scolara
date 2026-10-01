from django.urls import path

from . import views

app_name = "reading_lists"

urlpatterns = [
    path("reading-lists/", views.list_index, name="index"),
    path("reading-lists/create/", views.create, name="create"),
    path("reading-lists/<slug:slug>/", views.detail, name="detail"),
    path("reading-lists/<slug:slug>/edit/", views.edit, name="edit"),
    path("reading-lists/<slug:slug>/add/", views.add_item, name="add_item"),
    path("reading-lists/<slug:slug>/remove/", views.remove_item, name="remove_item"),
    path("reading-lists/<slug:slug>/move/", views.move, name="move"),
    path("reading-lists/<slug:slug>/publish/", views.publish, name="publish"),
    path("reading-lists/<slug:slug>/archive/", views.archive, name="archive"),
]

from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.book_list, name="book_list"),
    path("catalog/", views.book_list, name="catalog"),
    path("librarian/review/", views.review_queue, name="review_queue"),

    # Atelierul bibliotecarului
    path("gestiune/", views.atelier, name="atelier"),
    path("gestiune/carte/noua/", views.atelier_salveaza, name="atelier_creeaza"),
    path("gestiune/autori/", views.cauta_autori, name="cauta_autori"),
    path("gestiune/teme/", views.cauta_subiecte, name="cauta_subiecte"),
    path("gestiune/carte/<slug:slug>/", views.atelier, name="atelier_carte"),
    path("gestiune/carte/<slug:slug>/salveaza/", views.atelier_salveaza, name="atelier_salveaza"),
    path("gestiune/carte/<slug:slug>/sterge/", views.atelier_sterge, name="atelier_sterge"),
    path("books/<slug:slug>/", views.book_detail, name="book_detail"),
    path("books/<slug:slug>/publish/", views.publish_book, name="publish_book"),
    path("books/<slug:slug>/archive/", views.archive_book, name="archive_book"),
]

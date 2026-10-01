"""Interogări de citire. Views-urile nu scriu filtre pe status direct."""

from django.db.models import Q

from .models import Book, PublicationStatus, RightsStatus


def published_books():
    """Catalogul vizibil: publicat ȘI cu cel puțin o resursă utilizabilă."""
    return (
        Book.objects.filter(
            status=PublicationStatus.PUBLISHED,
            editions__resources__is_active=True,
            editions__resources__rights_status=RightsStatus.VERIFIED,
        )
        .distinct()
        .prefetch_related("authors", "subjects")
    )


def search_books(query="", subject_slug="", age_group=""):
    qs = published_books()
    if query:
        qs = qs.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(authors__name__icontains=query)
        ).distinct()
    if subject_slug:
        qs = qs.filter(subjects__slug=subject_slug)
    if age_group:
        qs = qs.filter(recommended_age=age_group)
    return qs


def librarian_books():
    """Bibliotecarul vede tot, inclusiv draft și arhivă."""
    return Book.objects.all().prefetch_related("authors", "editions__resources")

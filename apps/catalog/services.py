"""Regulile de publicare. Nicio altă parte a aplicației nu schimbă Book.status."""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .models import Book, BookResource, PublicationStatus, RightsStatus


class PublicationError(Exception):
    def __init__(self, problems):
        self.problems = problems if isinstance(problems, list) else [problems]
        super().__init__("; ".join(self.problems))


def usable_resources(book):
    return BookResource.objects.filter(
        edition__book=book,
        is_active=True,
        rights_status=RightsStatus.VERIFIED,
    )


def validate_for_publication(book) -> list[str]:
    """Invariantele unei cărți publicate. Adaugi o regulă nouă doar aici."""
    problems = []
    if not book.title.strip():
        problems.append("Cartea nu are titlu.")
    if not book.authors.exists():
        problems.append("Cartea nu are niciun autor.")
    if not book.subjects.exists():
        problems.append("Cartea nu are niciun subiect.")
    if not book.recommended_age:
        problems.append("Cartea nu are categorie de vârstă recomandată.")
    if not book.editions.exists():
        problems.append("Cartea nu are nicio ediție.")
    elif not usable_resources(book).exists():
        problems.append("Nu există nicio resursă activă cu drepturi verificate.")
    return problems


def can_publish(book) -> bool:
    return not validate_for_publication(book)


@transaction.atomic
def publish(book, actor) -> Book:
    if not actor.is_librarian:
        raise PermissionDenied("Doar bibliotecarul poate publica.")
    if book.status == PublicationStatus.PUBLISHED:
        return book
    problems = validate_for_publication(book)
    if problems:
        raise PublicationError(problems)
    book.status = PublicationStatus.PUBLISHED
    book.published_at = timezone.now()
    book.save(update_fields=["status", "published_at", "updated_at"])
    return book


@transaction.atomic
def archive(book, actor) -> Book:
    """Cărțile publicate se arhivează, nu se șterg. Progresul rămâne legat."""
    if not actor.is_librarian:
        raise PermissionDenied("Doar bibliotecarul poate arhiva.")
    book.status = PublicationStatus.ARCHIVED
    book.save(update_fields=["status", "updated_at"])
    return book


@transaction.atomic
def verify_rights(resource, actor, *, license_name="", license_url="") -> BookResource:
    if not actor.is_librarian:
        raise PermissionDenied("Doar bibliotecarul verifică drepturile.")
    resource.rights_status = RightsStatus.VERIFIED
    resource.rights_verified_at = timezone.now()
    resource.rights_verified_by = actor
    if license_name:
        resource.license_name = license_name
    if license_url:
        resource.license_url = license_url
    resource.save(
        update_fields=[
            "rights_status",
            "rights_verified_at",
            "rights_verified_by",
            "license_name",
            "license_url",
        ]
    )
    return resource


@transaction.atomic
def set_resource_active(resource, active: bool, actor) -> BookResource:
    """Dezactivarea ultimei resurse valide retrage automat cartea din catalog.

    Fără asta, invariantul „o carte publicată are conținut" se verifică doar la
    publicare, iar cititorii ajung la o carte pe care nu o pot deschide.
    """
    if not actor.is_librarian:
        raise PermissionDenied("Doar bibliotecarul gestionează resursele.")
    resource.is_active = active
    resource.save(update_fields=["is_active"])

    book = resource.edition.book
    if book.status == PublicationStatus.PUBLISHED and validate_for_publication(book):
        book.status = PublicationStatus.READY
        book.save(update_fields=["status", "updated_at"])
    return resource


def submit_for_rights_review(book, actor) -> Book:
    if not actor.is_librarian:
        raise PermissionDenied
    book.status = PublicationStatus.RIGHTS_REVIEW
    book.save(update_fields=["status", "updated_at"])
    return book

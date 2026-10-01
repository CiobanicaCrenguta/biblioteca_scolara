"""Regulile listelor educaționale.

Profesorul își administrează propriile liste. Bibliotecarul le poate corecta pe
toate. Studentul nu creează liste, dar le vede pe cele publicate.
"""

from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.catalog.models import PublicationStatus

from .models import ListStatus, ReadingList, ReadingListItem


class ReadingListError(Exception):
    pass


def can_edit(reading_list, user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_librarian:
        return True
    return reading_list.owner_id == user.id and user.can_curate


def can_view(reading_list, user) -> bool:
    if reading_list.is_published:
        return True
    return can_edit(reading_list, user)


def assert_can_edit(reading_list, user) -> None:
    if not can_edit(reading_list, user):
        raise PermissionDenied("Nu poți modifica această listă.")


@transaction.atomic
def create_list(owner, *, title, description="", target_age_group="") -> ReadingList:
    if not owner.can_curate:
        raise PermissionDenied("Doar profesorii și bibliotecarul creează liste.")
    if not title.strip():
        raise ReadingListError("Lista are nevoie de un titlu.")
    return ReadingList.objects.create(
        owner=owner,
        title=title.strip(),
        description=description.strip(),
        target_age_group=target_age_group,
    )


@transaction.atomic
def add_book(reading_list, book, user, *, note="") -> ReadingListItem:
    """Într-o listă intră numai cărți pe care elevii le pot deschide."""
    assert_can_edit(reading_list, user)
    if book.status != PublicationStatus.PUBLISHED:
        raise ReadingListError(
            f"„{book.title}” nu este publicată, deci nu poate intra într-o listă."
        )
    if reading_list.items.filter(book=book).exists():
        raise ReadingListError(f"„{book.title}” este deja în listă.")
    return ReadingListItem.objects.create(
        reading_list=reading_list,
        book=book,
        position=reading_list.next_position(),
        teacher_note=note.strip(),
    )


@transaction.atomic
def remove_book(reading_list, book, user) -> None:
    assert_can_edit(reading_list, user)
    reading_list.items.filter(book=book).delete()
    _renumber(reading_list)


@transaction.atomic
def move_item(reading_list, item_id, direction, user) -> None:
    """Reordonare prin schimb de poziții, ca să nu se rupă unicitatea."""
    assert_can_edit(reading_list, user)
    items = list(reading_list.items.all())
    index = next((i for i, it in enumerate(items) if it.id == item_id), None)
    if index is None:
        raise ReadingListError("Titlul nu este în listă.")

    target = index - 1 if direction == "up" else index + 1
    if target < 0 or target >= len(items):
        return

    items[index], items[target] = items[target], items[index]
    for position, item in enumerate(items, start=1):
        if item.position != position:
            item.position = position
            item.save(update_fields=["position"])


def _renumber(reading_list) -> None:
    for position, item in enumerate(reading_list.items.all(), start=1):
        if item.position != position:
            item.position = position
            item.save(update_fields=["position"])


@transaction.atomic
def publish_list(reading_list, user) -> ReadingList:
    assert_can_edit(reading_list, user)
    if not reading_list.items.exists():
        raise ReadingListError("O listă goală nu poate fi publicată.")

    unpublished = reading_list.items.exclude(
        book__status=PublicationStatus.PUBLISHED
    ).select_related("book")
    if unpublished.exists():
        titles = ", ".join(item.book.title for item in unpublished)
        raise ReadingListError(
            f"Lista conține titluri care nu mai sunt publicate: {titles}."
        )

    reading_list.status = ListStatus.PUBLISHED
    reading_list.save(update_fields=["status", "updated_at"])
    return reading_list


@transaction.atomic
def archive_list(reading_list, user) -> ReadingList:
    assert_can_edit(reading_list, user)
    reading_list.status = ListStatus.ARCHIVED
    reading_list.save(update_fields=["status", "updated_at"])
    return reading_list

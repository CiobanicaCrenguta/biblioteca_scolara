"""Accesul la lectură. Fără stoc, împrumut, rezervare sau abonament."""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import BookResource, PublicationStatus, RightsStatus

from .models import InteractionEvent, ReadingProgress, UserBookState

# O pauză mai lungă de atâtea minute înseamnă o sesiune nouă de lectură.
PAUZA_SESIUNE = 30


class ResourceUnavailable(PermissionDenied):
    pass


def readable_resources(book):
    return (
        BookResource.objects.filter(
            edition__book=book,
            is_active=True,
            rights_status=RightsStatus.VERIFIED,
        )
        .select_related("edition", "edition__book")
        .order_by("-is_primary", "-edition__is_primary", "id")
    )


def resolve_reading_resource(book, user, resource_id=None):
    """Ce fișier deschidem pentru acest utilizator.

    Toate rolurile citesc orice carte publicată. Singurele condiții sunt starea
    cărții, resursa activă și drepturile verificate.
    """
    if book.status != PublicationStatus.PUBLISHED:
        raise ResourceUnavailable("Cartea nu este publicată.")

    candidates = list(readable_resources(book))
    if not candidates:
        raise ResourceUnavailable("Cartea nu are conținut disponibil.")

    if resource_id:
        chosen = next((r for r in candidates if r.pk == int(resource_id)), None)
        if chosen is None:
            raise ResourceUnavailable("Formatul cerut nu este disponibil.")
        return chosen

    # Dacă a început deja într-un format, îl continuă în acela.
    started = (
        ReadingProgress.objects.filter(user=user, resource__in=candidates)
        .order_by("-updated_at")
        .first()
    )
    return started.resource if started else candidates[0]


def get_resource_for_download(resource_id, user):
    """Endpoint de conținut: fișierul nu se servește printr-o cale neverificată."""
    resource = (
        BookResource.objects.select_related("edition__book")
        .filter(pk=resource_id)
        .first()
    )
    if resource is None:
        raise ResourceUnavailable("Resursa nu există.")
    if not resource.is_usable:
        raise ResourceUnavailable("Resursa nu este disponibilă.")
    if resource.edition.book.status != PublicationStatus.PUBLISHED:
        raise ResourceUnavailable("Cartea nu este publicată.")
    if not resource.is_readable_inline:
        raise ResourceUnavailable("Resursa este externă.")
    return resource


@transaction.atomic
def save_progress(user, resource, location_value, percentage, location_type="page"):
    """Salvează poziția și promovează raftul la READING la prima lectură.

    Tot aici se întrețin contoarele de sesiune. O salvare la mai puțin de
    PAUZA_SESIUNE minute după precedenta continuă aceeași sesiune, iar
    intervalul dintre ele se adună la timpul de lectură. O pauză mai lungă
    deschide o sesiune nouă, fără să adauge timp: nu știm ce a făcut
    utilizatorul între timp și nu vrem să presupunem.
    """
    percentage = max(0.0, min(100.0, float(percentage)))
    acum = timezone.now()
    anterior = ReadingProgress.objects.filter(user=user, resource=resource).first()

    if anterior is None:
        sesiuni, minute = 1, 0
    else:
        reper = anterior.last_session_at or anterior.updated_at
        pauza = (acum - reper).total_seconds() / 60.0 if reper else None
        if pauza is None or pauza > PAUZA_SESIUNE:
            sesiuni = anterior.session_count + 1
            minute = anterior.total_reading_minutes
        else:
            sesiuni = max(anterior.session_count, 1)
            minute = anterior.total_reading_minutes + int(round(pauza))

    ReadingProgress.objects.update_or_create(
        user=user,
        resource=resource,
        defaults={
            "location_type": location_type,
            "location_value": str(location_value),
            "percentage": percentage,
            "session_count": sesiuni,
            "total_reading_minutes": minute,
            "last_session_at": acum,
        },
    )

    book = resource.edition.book
    state, created = UserBookState.objects.get_or_create(
        user=user,
        book=book,
        defaults={"status": UserBookState.Status.READING, "started_at": timezone.now()},
    )
    if created:
        _log(user, book, InteractionEvent.Type.READING_STARTED)
    elif state.status in {
        UserBookState.Status.WANT_TO_READ,
        UserBookState.Status.ABANDONED,
    }:
        state.status = UserBookState.Status.READING
        state.started_at = state.started_at or timezone.now()
        state.save(update_fields=["status", "started_at", "updated_at"])
        _log(user, book, InteractionEvent.Type.READING_STARTED)
    return state


@transaction.atomic
def set_book_state(user, book, status):
    if status not in UserBookState.Status.values:
        raise ValueError(f"Stare necunoscută: {status}")

    state, _ = UserBookState.objects.get_or_create(user=user, book=book)
    state.status = status
    if status == UserBookState.Status.READING and not state.started_at:
        state.started_at = timezone.now()
    if status == UserBookState.Status.FINISHED:
        state.finished_at = timezone.now()
        state.started_at = state.started_at or timezone.now()
        _log(user, book, InteractionEvent.Type.READING_FINISHED, value=2.5)
    elif status == UserBookState.Status.WANT_TO_READ:
        _log(user, book, InteractionEvent.Type.BOOK_SAVED, value=1.5)
    state.save()
    return state


@transaction.atomic
def set_reaction(user, book, reaction):
    state, _ = UserBookState.objects.get_or_create(user=user, book=book)
    state.reaction = reaction
    state.save(update_fields=["reaction", "updated_at"])
    if reaction == UserBookState.Reaction.LIKE:
        _log(user, book, InteractionEvent.Type.BOOK_LIKED, value=3.0)
    elif reaction == UserBookState.Reaction.DISLIKE:
        _log(user, book, InteractionEvent.Type.BOOK_DISLIKED, value=-3.0)
    return state


def _log(user, book, event_type, value=1.0):
    """Evenimentele se scriu doar dacă personalizarea e activă."""
    profile = getattr(user, "profile", None)
    if profile is not None and not profile.personalization_enabled:
        return None
    return InteractionEvent.objects.create(
        user=user, book=book, event_type=event_type, value=value
    )

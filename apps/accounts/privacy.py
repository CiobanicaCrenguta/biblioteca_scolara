"""Drepturile utilizatorului asupra propriilor date.

Fiecare funcție de aici corespunde unui drept concret: acces, ștergere,
retragerea consimțământului. Sunt scrise ca servicii, nu direct în view, ca să
poată fi testate și refolosite din admin sau dintr-o comandă.
"""

from django.db import transaction
from django.utils import timezone

from apps.reader.models import InteractionEvent, ReadingProgress, UserBookState

PRIVACY_NOTICE_VERSION = "1.0"


def export_user_data(user) -> dict:
    """Tot ce păstrează aplicația despre o persoană, într-un singur obiect."""
    profile = getattr(user, "profile", None)

    return {
        "generat_la": timezone.now().isoformat(),
        "versiune_informare": PRIVACY_NOTICE_VERSION,
        "cont": {
            "utilizator": user.username,
            "email": user.email,
            "rol": user.get_role_display(),
            "creat_la": user.created_at.isoformat() if user.created_at else None,
            "ultima_autentificare": user.last_login.isoformat()
            if user.last_login
            else None,
        },
        "profil": {
            "categorie_varsta": profile.age_group if profile else "",
            "limba_preferata": profile.preferred_language if profile else "",
            "subiecte_preferate": [s.name for s in profile.preferred_subjects.all()]
            if profile
            else [],
            "recomandari_personalizate": profile.personalization_enabled
            if profile
            else None,
            "informare_confidentialitate_acceptata_la": profile.privacy_acknowledged_at.isoformat()
            if profile and profile.privacy_acknowledged_at
            else None,
        },
        "raft": [
            {
                "carte": state.book.title,
                "stare": state.get_status_display(),
                "reactie": state.get_reaction_display() if state.reaction else None,
                "salvata_la": state.saved_at.isoformat(),
                "inceputa_la": state.started_at.isoformat() if state.started_at else None,
                "terminata_la": state.finished_at.isoformat()
                if state.finished_at
                else None,
            }
            for state in UserBookState.objects.filter(user=user).select_related("book")
        ],
        "progres_lectura": [
            {
                "carte": progress.resource.edition.book.title,
                "format": progress.resource.get_format_display(),
                "pozitie": progress.location_value,
                "procent": progress.percentage,
                "actualizat_la": progress.updated_at.isoformat(),
            }
            for progress in ReadingProgress.objects.filter(user=user).select_related(
                "resource__edition__book"
            )
        ],
        "evenimente_recomandari": [
            {
                "carte": event.book.title,
                "tip": event.get_event_type_display(),
                "pondere": event.value,
                "la": event.created_at.isoformat(),
            }
            for event in InteractionEvent.objects.filter(user=user).select_related("book")
        ],
        "liste_educationale": [
            {
                "titlu": reading_list.title,
                "stare": reading_list.get_status_display(),
                "titluri": [item.book.title for item in reading_list.items.all()],
            }
            for reading_list in user.reading_lists.all()
        ],
    }


@transaction.atomic
def clear_activity(user) -> dict:
    """Șterge raftul, progresul și evenimentele. Contul rămâne."""
    counts = {
        "raft": UserBookState.objects.filter(user=user).count(),
        "progres": ReadingProgress.objects.filter(user=user).count(),
        "evenimente": InteractionEvent.objects.filter(user=user).count(),
    }
    UserBookState.objects.filter(user=user).delete()
    ReadingProgress.objects.filter(user=user).delete()
    InteractionEvent.objects.filter(user=user).delete()
    return counts


@transaction.atomic
def clear_recommendation_events(user) -> int:
    """Retragerea profilării, fără să pierzi raftul sau progresul."""
    count = InteractionEvent.objects.filter(user=user).count()
    InteractionEvent.objects.filter(user=user).delete()
    profile = getattr(user, "profile", None)
    if profile:
        profile.personalization_enabled = False
        profile.save(update_fields=["personalization_enabled", "updated_at"])
    return count


@transaction.atomic
def delete_account(user) -> None:
    """Ștergerea contului duce cu ea toate datele legate, prin cascadă.

    Listele educaționale publicate ale unui profesor dispar odată cu contul.
    Este alegerea corectă din perspectiva protecției datelor, dar bibliotecarul
    trebuie să știe: dacă o listă merită păstrată, se transferă înainte.
    """
    user.delete()


def acknowledge_privacy_notice(profile) -> None:
    profile.privacy_acknowledged_at = timezone.now()
    profile.save(update_fields=["privacy_acknowledged_at", "updated_at"])

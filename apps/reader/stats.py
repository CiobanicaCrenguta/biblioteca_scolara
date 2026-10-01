"""Profilul de cititor.

Totul se calculează din datele existente. Nu adăugăm tabele noi ca să afișăm
niște cifre: raftul și progresul le conțin deja.
"""

from collections import Counter
from datetime import timedelta

from django.utils import timezone

from .models import InteractionEvent, ReadingProgress, UserBookState

LEVELS = [
    (0, "La început de drum"),
    (1, "Cititor curios"),
    (5, "Cititor constant"),
    (15, "Cititor pasionat"),
    (40, "Cititor de cursă lungă"),
]


def reading_stats(user) -> dict:
    states = list(
        UserBookState.objects.filter(user=user).select_related("book").prefetch_related(
            "book__subjects", "book__authors"
        )
    )
    progress = list(
        ReadingProgress.objects.filter(user=user).select_related(
            "resource__edition__book"
        )
    )

    by_status = Counter(state.status for state in states)
    finished = by_status.get(UserBookState.Status.FINISHED, 0)

    subjects = Counter()
    authors = Counter()
    pages = 0
    for state in states:
        if state.status in {
            UserBookState.Status.FINISHED,
            UserBookState.Status.READING,
        }:
            for subject in state.book.subjects.all():
                subjects[subject.name] += 1
            for author in state.book.authors.all():
                authors[author.name] += 1

    percentages = [p.percentage for p in progress]
    in_progress = [p for p in progress if 0 < p.percentage < 100]

    # Procentul cel mai avansat atins în oricare dintre formatele unei cărți.
    procent_pe_carte = {}
    for inregistrare in progress:
        carte = inregistrare.resource.edition.book_id
        procent_pe_carte[carte] = max(
            procent_pe_carte.get(carte, 0.0), inregistrare.percentage
        )

    terminate, in_lucru = [], []
    for state in states:
        procent = procent_pe_carte.get(state.book_id, 0.0)
        if state.status == UserBookState.Status.FINISHED:
            terminate.append({
                "book": state.book,
                "percentage": 100,
                "finished_at": state.finished_at,
                "reaction": state.reaction,
            })
        elif state.status == UserBookState.Status.READING:
            in_lucru.append({
                "book": state.book,
                "percentage": round(procent),
                "updated_at": state.updated_at,
            })
    terminate.sort(key=lambda x: x["finished_at"] or timezone.now(), reverse=True)
    in_lucru.sort(key=lambda x: x["percentage"], reverse=True)

    sesiuni = sum(p.session_count for p in progress)
    minute = sum(p.total_reading_minutes for p in progress)
    reactii = {
        "liked": sum(1 for s in states if s.reaction == UserBookState.Reaction.LIKE),
        "neutral": sum(1 for s in states if s.reaction == UserBookState.Reaction.NEUTRAL),
        "disliked": sum(1 for s in states if s.reaction == UserBookState.Reaction.DISLIKE),
    }
    incepute = by_status.get(UserBookState.Status.READING, 0) + finished
    rata = round(finished / incepute * 100) if incepute else 0

    zile = InteractionEvent.objects.filter(user=user).values_list(
        "created_at", flat=True)
    serie = _serie_zilnica(list(zile))

    return {
        "total": len(states),
        "finished": finished,
        "reading": by_status.get(UserBookState.Status.READING, 0),
        "want_to_read": by_status.get(UserBookState.Status.WANT_TO_READ, 0),
        "abandoned": by_status.get(UserBookState.Status.ABANDONED, 0),
        "liked": sum(
            1 for s in states if s.reaction == UserBookState.Reaction.LIKE
        ),
        "level": _level_for(finished),
        "top_subjects": subjects.most_common(3),
        "top_authors": authors.most_common(3),
        "average_progress": round(sum(percentages) / len(percentages), 1)
        if percentages
        else 0.0,
        "open_books": len(in_progress),
        "continue_reading": _continue_reading(progress),
        "recent_finished": _recent_finished(states),
        "activity": _activity(states),
        "has_data": bool(states),

        # Liste detaliate pentru pagina de profil
        "finished_books": terminate,
        "reading_books": in_lucru,

        # Indicatori de utilizare
        "total_sessions": sesiuni,
        "total_minutes": minute,
        "reading_hours": round(minute / 60, 1) if minute else 0,
        "books_by_reaction": reactii,
        "completion_rate": rata,
        "unique_subjects_count": len(subjects),
        "unique_authors_count": len(authors),
        "reading_streak": serie,
        "engagement_score": _scor_implicare(finished, sesiuni, rata),
    }


def _serie_zilnica(momente, azi=None) -> int:
    """Câte zile la rând, până azi, utilizatorul a interacționat cu aplicația.

    O activitate de ieri păstrează seria vie: altfel, oricine deschide
    profilul dimineața ar vedea zero, ceea ce descurajează fără motiv.
    """
    if not momente:
        return 0
    azi = azi or timezone.localdate()
    zile = sorted({m.astimezone(timezone.get_current_timezone()).date()
                   for m in momente}, reverse=True)
    if zile[0] == azi:
        asteptat = azi
    elif zile[0] == azi - timedelta(days=1):
        asteptat = azi - timedelta(days=1)
    else:
        return 0

    serie = 0
    for zi in zile:
        if zi == asteptat:
            serie += 1
            asteptat -= timedelta(days=1)
        elif zi < asteptat:
            break
    return serie


def _scor_implicare(terminate, sesiuni, rata) -> float:
    """Scor orientativ, între 0 și 100.

    Ponderile sunt euristice, la fel ca cele din motorul de recomandare, și nu
    provin din literatură. Rolul lor este să rezume într-un singur număr trei
    lucruri diferite: cât s-a citit, cât de des și cât de des s-a dus la capăt.
    """
    return min(100.0, round(terminate * 5 + sesiuni * 0.5 + rata * 0.3, 1))


def _level_for(finished: int) -> str:
    label = LEVELS[0][1]
    for threshold, name in LEVELS:
        if finished >= threshold:
            label = name
    return label


def _continue_reading(progress):
    """Ultimul lucru deschis, ca să existe un buton de reluare."""
    unfinished = [p for p in progress if p.percentage < 100]
    if not unfinished:
        return None
    latest = max(unfinished, key=lambda p: p.updated_at)
    return {
        "book": latest.resource.edition.book,
        "resource": latest.resource,
        "percentage": round(latest.percentage),
        "location": latest.location_value,
    }


def _recent_finished(states, limit=3):
    finished = [
        s for s in states
        if s.status == UserBookState.Status.FINISHED and s.finished_at
    ]
    finished.sort(key=lambda s: s.finished_at, reverse=True)
    return [s.book for s in finished[:limit]]


def _activity(states, months=6):
    """Câte cărți terminate pe lună, ultimele șase luni."""
    now = timezone.now()
    buckets = []
    for offset in range(months - 1, -1, -1):
        start = (now.replace(day=1) - timedelta(days=offset * 30)).replace(day=1)
        label = start.strftime("%b")
        count = sum(
            1
            for s in states
            if s.finished_at
            and s.finished_at.year == start.year
            and s.finished_at.month == start.month
        )
        buckets.append({"label": label, "count": count})
    peak = max((b["count"] for b in buckets), default=0) or 1
    for bucket in buckets:
        bucket["height"] = round(bucket["count"] / peak * 100)
    return buckets

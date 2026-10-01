"""Stratul prin care restul aplicației cere recomandări."""

from apps.catalog.selectors import published_books

from .engine import (
    ContentBasedRecommendationEngine,
    Recommendation,
    RecommendationEngine,
    get_index,
    invalidate_index,
)

_engine: RecommendationEngine = ContentBasedRecommendationEngine()


def set_engine(engine: RecommendationEngine) -> None:
    """Punct unic de schimbare a algoritmului, folosit și în teste."""
    global _engine
    _engine = engine


def recommendations_for(user, limit: int = 10) -> list[Recommendation]:
    if not user.is_authenticated:
        return cold_start(limit=limit)
    results = _engine.recommend(user, limit=limit)
    return results if results else cold_start(user=user, limit=limit)


def cold_start(user=None, limit: int = 10) -> list[Recommendation]:
    """Fără interacțiuni și fără preferințe nu inventăm „cele mai populare”.

    Arătăm ce putem justifica: selecția bibliotecarului, apoi listele publicate
    de profesori, apoi adăugările recente.

    Chiar și aici respectăm raftul utilizatorului. O carte refuzată explicit nu
    are voie să reapară pentru că s-a schimbat calea care produce lista.
    """
    seen = _books_already_known(user)
    picks: list[Recommendation] = []

    featured = (
        published_books().filter(featured=True).exclude(id__in=seen).order_by("-published_at")
    )
    for book in featured[:limit]:
        seen.add(book.id)
        picks.append(
            Recommendation(book=book, score=0.5, reason="Din selecția bibliotecarului.")
        )

    remaining = limit - len(picks)
    if remaining > 0:
        for book in _from_teacher_lists(exclude=seen, limit=remaining):
            seen.add(book.id)
            picks.append(
                Recommendation(
                    book=book, score=0.35, reason="Recomandată de un profesor."
                )
            )

    remaining = limit - len(picks)
    if remaining > 0:
        recent = published_books().exclude(id__in=seen).order_by("-published_at")[:remaining]
        for book in recent:
            picks.append(
                Recommendation(book=book, score=0.2, reason="Adăugată recent în catalog.")
            )
    return picks


def _books_already_known(user) -> set:
    """Cărțile care au deja o stare în raftul utilizatorului."""
    if user is None or not getattr(user, "is_authenticated", False):
        return set()
    from apps.reader.models import UserBookState

    return set(
        UserBookState.objects.filter(user=user).values_list("book_id", flat=True)
    )


def _from_teacher_lists(exclude, limit):
    """Listele publicate de profesori sunt un semnal legitim înainte de istoric."""
    from apps.reading_lists.selectors import published_lists

    books, seen = [], set(exclude)
    for reading_list in published_lists().order_by("-updated_at"):
        for item in reading_list.items.all():
            if item.book_id in seen or item.book.status != "PUBLISHED":
                continue
            seen.add(item.book_id)
            books.append(item.book)
            if len(books) >= limit:
                return books
    return books


def similar_to(book, limit: int = 4) -> list[Recommendation]:
    """„Cărți asemănătoare” pe fișa unei cărți. Nu depinde de utilizator."""
    from .engine import Recommendation as Rec
    from .engine import _is_sparse_fallback, similarities

    index = get_index()
    row = index.row(book.id)
    if row is None or not len(index):
        return []

    others = [b for b in published_books().order_by("id") if b.id != book.id]
    rows = [(b, index.row(b.id)) for b in others]
    rows = [(b, r) for b, r in rows if r is not None]
    if not rows:
        return []

    if _is_sparse_fallback(row):
        from .engine import SimpleMatrix

        matrix = SimpleMatrix(r for _, r in rows)
    else:
        from scipy import sparse

        matrix = sparse.vstack([r for _, r in rows])

    scores = similarities(row, matrix)
    ranked = sorted(zip((b for b, _ in rows), scores), key=lambda p: p[1], reverse=True)
    return [
        Rec(book=b, score=float(s), reason="Seamănă cu titlul pe care îl citești.")
        for b, s in ranked[:limit]
        if s > 0.01
    ]


def rebuild_index() -> int:
    invalidate_index()
    return len(get_index(force=True))

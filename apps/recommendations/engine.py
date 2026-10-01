"""Motorul de recomandare.

View-ul cere `engine.recommend(user, limit)` și primește o listă de
`Recommendation`. Nu știe dacă dedesubt rulează TF-IDF, KNN sau altceva. Asta
permite schimbarea algoritmului fără să atingi paginile.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from django.db.models import Max

from apps.catalog.models import Book
from apps.catalog.selectors import published_books
from apps.reader.models import UserBookState

# Ponderile semnalelor. Documentate aici, într-un singur loc.
WEIGHT_ONBOARDING = 3.0
WEIGHT_LIKED = 3.0
WEIGHT_FINISHED = 2.5
WEIGHT_SAVED = 1.5
WEIGHT_STARTED = 1.0

# Ponderile scorului final.
W_SIMILARITY = 0.70
W_SUBJECT_OVERLAP = 0.15
W_AGE = 0.10
W_FEATURED = 0.05

MAX_PER_AUTHOR = 2
MAX_SHARE_PER_SUBJECT = 0.5

AGE_ORDER = ["7-9", "10-12", "13-15", "16-18", "ADULT"]


@dataclass
class Recommendation:
    book: Book
    score: float
    matched_subjects: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def percent(self) -> int:
        return max(1, min(100, round(self.score * 100)))


class RecommendationEngine(ABC):
    """Contractul pe care îl folosesc view-urile."""

    @abstractmethod
    def recommend(self, user, limit: int = 10) -> list[Recommendation]:
        raise NotImplementedError


# --------------------------------------------------------------------------
# Reprezentarea textuală a unei cărți
# --------------------------------------------------------------------------


def book_document(book) -> str:
    """Textul din care se construiește vectorul.

    Metadate și descriere, nu textul integral al romanului: mai rapid, mai
    stabil și explicabil în fața unui utilizator.
    """
    parts = [book.title, book.title]  # titlul cântărește dublu
    parts += [a.name for a in book.authors.all()]
    parts += [s.name for s in book.subjects.all()] * 2
    if book.description:
        parts.append(book.description)
    if book.recommended_age:
        parts.append(f"varsta_{book.recommended_age}")
    if book.original_language:
        parts.append(f"limba_{book.original_language}")
    return " ".join(p for p in parts if p)


def age_relevance(book_age: str, user_age: str) -> float:
    """Vârsta este semnal de relevanță, niciodată interdicție."""
    if not book_age or not user_age:
        return 0.5
    try:
        distance = abs(AGE_ORDER.index(book_age) - AGE_ORDER.index(user_age))
    except ValueError:
        return 0.5
    return max(0.0, 1.0 - 0.35 * distance)


# --------------------------------------------------------------------------
# Indexul TF-IDF, construit o dată și reutilizat
# --------------------------------------------------------------------------


class BookIndex:
    """Matricea TF-IDF a cărților eligibile.

    Se reconstruiește când se schimbă catalogul. Cheia de versiune combină
    numărul de cărți publicate cu ultima modificare, deci un import sau o
    publicare invalidează indexul fără să ai nevoie de semnale sau de cron.
    """

    def __init__(self, book_ids, matrix, vectorizer, version):
        self.book_ids = list(book_ids)
        self.matrix = matrix
        self.vectorizer = vectorizer
        self.version = version
        self._row_of = {bid: i for i, bid in enumerate(book_ids)}

    def row(self, book_id):
        index = self._row_of.get(book_id)
        return None if index is None else self.matrix[index]

    def __len__(self):
        return len(self.book_ids)


_INDEX: BookIndex | None = None


def catalog_version() -> str:
    stats = published_books().aggregate(last=Max("updated_at"))
    count = published_books().count()
    return f"{count}:{stats['last'].isoformat() if stats['last'] else 'empty'}"


def get_index(force: bool = False) -> BookIndex:
    global _INDEX
    version = catalog_version()
    if force or _INDEX is None or _INDEX.version != version:
        _INDEX = _build_index(version)
    return _INDEX


def invalidate_index() -> None:
    global _INDEX
    _INDEX = None


def _build_index(version: str) -> BookIndex:
    books = list(published_books().order_by("id"))
    documents = [book_document(b) for b in books]
    vectorizer = _make_vectorizer()
    matrix = vectorizer.fit_transform(documents) if documents else None
    return BookIndex([b.id for b in books], matrix, vectorizer, version)


def _make_vectorizer():
    """scikit-learn dacă e instalat, altfel o implementare proprie echivalentă.

    Proiectul trebuie să pornească și pe o mașină fără scikit-learn, de exemplu
    la o prezentare pe alt calculator.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        return SimpleTfidfVectorizer()
    return TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        min_df=1,
        max_features=20000,
        strip_accents="unicode",
        token_pattern=r"(?u)\b\w\w+\b",
    )


# --------------------------------------------------------------------------
# Varianta proprie de TF-IDF, folosită doar ca rezervă
# --------------------------------------------------------------------------


class SparseVector(dict):
    """Vector rar: {index_termen: pondere}. Normă unitară după construcție."""

    def normalized(self) -> SparseVector:
        norm = math.sqrt(sum(v * v for v in self.values()))
        if not norm:
            return SparseVector()
        return SparseVector({k: v / norm for k, v in self.items()})


class SimpleMatrix(list):
    """Listă de SparseVector, cu indexare compatibilă cu numpy."""


class SimpleTfidfVectorizer:
    def __init__(self, ngram_range=(1, 2)):
        self.ngram_range = ngram_range
        self.vocabulary_: dict[str, int] = {}
        self.idf_: dict[int, float] = {}

    def _tokens(self, text: str) -> list[str]:
        import re
        import unicodedata

        text = unicodedata.normalize("NFKD", text.lower())
        text = "".join(c for c in text if not unicodedata.combining(c))
        words = re.findall(r"\b\w\w+\b", text)
        grams = list(words)
        if self.ngram_range[1] >= 2:
            grams += [f"{a} {b}" for a, b in zip(words, words[1:])]
        return grams

    def fit_transform(self, documents):
        counts, doc_freq = [], {}
        for document in documents:
            local: dict[str, int] = {}
            for token in self._tokens(document):
                local[token] = local.get(token, 0) + 1
            counts.append(local)
            for token in local:
                doc_freq[token] = doc_freq.get(token, 0) + 1

        self.vocabulary_ = {t: i for i, t in enumerate(sorted(doc_freq))}
        total = len(documents)
        self.idf_ = {
            self.vocabulary_[t]: math.log((1 + total) / (1 + df)) + 1.0
            for t, df in doc_freq.items()
        }
        return SimpleMatrix(self._weigh(local) for local in counts)

    def transform(self, documents):
        rows = []
        for document in documents:
            local: dict[str, int] = {}
            for token in self._tokens(document):
                if token in self.vocabulary_:
                    local[token] = local.get(token, 0) + 1
            rows.append(self._weigh(local))
        return SimpleMatrix(rows)

    def _weigh(self, counts) -> SparseVector:
        vector = SparseVector()
        for token, count in counts.items():
            index = self.vocabulary_.get(token)
            if index is None:
                continue
            vector[index] = (1 + math.log(count)) * self.idf_.get(index, 1.0)
        return vector.normalized()


# --------------------------------------------------------------------------
# Operații vectoriale, independente de implementare
# --------------------------------------------------------------------------


def _is_sparse_fallback(vector) -> bool:
    return isinstance(vector, (SparseVector, dict))


def weighted_mean(vectors_with_weights):
    """Profilul utilizatorului: media ponderată a vectorilor relevanți."""
    vectors_with_weights = [(v, w) for v, w in vectors_with_weights if v is not None]
    if not vectors_with_weights:
        return None

    first = vectors_with_weights[0][0]
    total = sum(w for _, w in vectors_with_weights) or 1.0

    if _is_sparse_fallback(first):
        accumulator = SparseVector()
        for vector, weight in vectors_with_weights:
            for index, value in vector.items():
                accumulator[index] = accumulator.get(index, 0.0) + value * weight / total
        return accumulator.normalized()

    import numpy as np
    from scipy import sparse

    stacked = sparse.vstack([v for v, _ in vectors_with_weights])
    weights = np.array([w / total for _, w in vectors_with_weights])
    combined = sparse.csr_matrix(stacked.multiply(weights[:, None]).sum(axis=0))
    norm = math.sqrt(combined.multiply(combined).sum())
    return combined / norm if norm else combined


def similarities(profile, matrix):
    """Cosinus între profil și fiecare carte. Vectorii sunt deja normalizați."""
    if profile is None or matrix is None:
        return []

    if _is_sparse_fallback(profile):
        scores = []
        for row in matrix:
            shorter, longer = (profile, row) if len(profile) < len(row) else (row, profile)
            scores.append(sum(value * longer.get(index, 0.0) for index, value in shorter.items()))
        return scores

    from sklearn.metrics.pairwise import cosine_similarity

    return cosine_similarity(profile, matrix)[0].tolist()


# --------------------------------------------------------------------------
# Implementarea propriu-zisă
# --------------------------------------------------------------------------


class ContentBasedRecommendationEngine(RecommendationEngine):
    def recommend(self, user, limit: int = 10) -> list[Recommendation]:
        index = get_index()
        if not len(index):
            return []

        profile = getattr(user, "profile", None)
        personalized = profile is None or profile.personalization_enabled

        states = list(
            UserBookState.objects.filter(user=user).select_related("book")
            if user.is_authenticated
            else []
        )
        excluded = self._excluded_book_ids(states)
        preferred = list(profile.preferred_subjects.all()) if profile else []

        candidates = [
            b
            for b in published_books().order_by("id")
            if b.id not in excluded
        ]
        if not candidates:
            return []

        user_vector = (
            self._profile_vector(index, states, preferred) if personalized else None
        )
        if user_vector is None:
            # Niciun semnal personal: nici istoric, nici teme bifate, sau
            # personalizarea este oprită. Motorul nu inventează un scor din
            # vârstă și noroc, ci lasă cold start-ul să dea recomandări pe care
            # le putem justifica: selecția bibliotecarului, apoi listele
            # profesorilor.
            return []

        scores = self._score(index, user_vector, candidates, profile, preferred, states)
        ranked = sorted(scores, key=lambda r: r.score, reverse=True)
        return self._diversify(ranked, limit)

    # -- semnale -----------------------------------------------------------

    def _excluded_book_ids(self, states) -> set[int]:
        """Descoperirea arată doar titluri noi.

        Orice carte care are deja o stare în raftul utilizatorului iese din
        listă: respinsă, terminată, salvată sau în curs de citire. Fără regula
        asta, cartea apreciată devine cea mai similară cu propriul profil și se
        recomandă pe ea însăși.
        """
        return {state.book_id for state in states}

    def _profile_vector(self, index, states, preferred_subjects):
        pieces = []

        for state in states:
            weight = 0.0
            if state.reaction == UserBookState.Reaction.LIKE:
                weight = WEIGHT_LIKED
            elif state.status == UserBookState.Status.FINISHED:
                weight = WEIGHT_FINISHED
            elif state.status == UserBookState.Status.WANT_TO_READ:
                weight = WEIGHT_SAVED
            elif state.status == UserBookState.Status.READING:
                weight = WEIGHT_STARTED
            if weight and state.reaction != UserBookState.Reaction.DISLIKE:
                row = index.row(state.book_id)
                if row is not None:
                    pieces.append((row, weight))

        if preferred_subjects:
            pseudo = " ".join(s.name for s in preferred_subjects)
            vector = index.vectorizer.transform([pseudo])[0]
            pieces.append((vector, WEIGHT_ONBOARDING))

        return weighted_mean(pieces)

    # -- scor --------------------------------------------------------------

    def _score(self, index, user_vector, candidates, profile, preferred_subjects,
               states=()):
        rows = [index.row(b.id) for b in candidates]
        valid = [(b, r) for b, r in zip(candidates, rows) if r is not None]
        if not valid:
            return []

        if user_vector is not None:
            if _is_sparse_fallback(user_vector):
                matrix = SimpleMatrix(r for _, r in valid)
            else:
                from scipy import sparse

                matrix = sparse.vstack([r for _, r in valid])
            sims = similarities(user_vector, matrix)
        else:
            sims = [0.0] * len(valid)

        preferred_names = {s.name for s in preferred_subjects}
        user_age = profile.age_group if profile else ""
        # Temele care apar efectiv in raftul utilizatorului. Fara ele, o carte
        # potrivita dar cu descriere lexical diferita primeste explicatia de
        # rezerva, desi motorul a ales-o pentru un motiv real.
        history_subjects = self._history_subjects(states)

        results = []
        for (book, _), similarity in zip(valid, sims):
            subject_names = {s.name for s in book.subjects.all()}
            matched = sorted(subject_names & preferred_names)
            overlap = len(matched) / len(preferred_names) if preferred_names else 0.0

            score = (
                W_SIMILARITY * max(0.0, similarity)
                + W_SUBJECT_OVERLAP * overlap
                + W_AGE * age_relevance(book.recommended_age, user_age)
                + W_FEATURED * (1.0 if book.featured else 0.0)
            )
            results.append(
                Recommendation(
                    book=book,
                    score=score,
                    matched_subjects=matched,
                    reason=build_reason(
                        book, matched, similarity, user_age,
                        history_subjects=history_subjects & subject_names,
                    ),
                )
            )
        return results

    @staticmethod
    def _history_subjects(states) -> set[str]:
        names = set()
        for state in states:
            if state.reaction == UserBookState.Reaction.DISLIKE:
                continue
            names.update(s.name for s in state.book.subjects.all())
        return names

    # -- diversificare -----------------------------------------------------

    def _diversify(self, ranked, limit):
        """Fără trei cărți la rând de la același autor sau zece din același gen."""
        chosen, per_author, per_subject = [], {}, {}
        # Minimul de 2 contează: la limit=2 un plafon de 1 carte per subiect ar
        # scoate exact al doilea titlu relevant și ar umple locul cu altceva.
        cap = max(2, math.ceil(limit * MAX_SHARE_PER_SUBJECT))

        for recommendation in ranked:
            if len(chosen) >= limit:
                break
            authors = [a.id for a in recommendation.book.authors.all()]
            if any(per_author.get(a, 0) >= MAX_PER_AUTHOR for a in authors):
                continue
            subjects = [s.id for s in recommendation.book.subjects.all()]
            if subjects and all(per_subject.get(s, 0) >= cap for s in subjects):
                continue

            chosen.append(recommendation)
            for author in authors:
                per_author[author] = per_author.get(author, 0) + 1
            for subject in subjects:
                per_subject[subject] = per_subject.get(subject, 0) + 1

        if len(chosen) < limit:
            taken = {r.book.id for r in chosen}
            for recommendation in ranked:
                if len(chosen) >= limit:
                    break
                if recommendation.book.id not in taken:
                    chosen.append(recommendation)
        return chosen


def build_reason(book, matched_subjects, similarity, user_age,
                 history_subjects=frozenset()) -> str:
    """Explicație deterministă. Fără model generativ.

    Ramurile merg de la motivul cel mai specific către cel mai general. O
    explicație generică pentru o carte pe care motorul a ales-o dintr-un motiv
    concret este mai dăunătoare decât lipsa explicației: îi sugerează
    utilizatorului că sistemul nu știe ce face.
    """
    if matched_subjects:
        if len(matched_subjects) == 1:
            return f"Ai ales „{matched_subjects[0]}” printre preferințe."
        listed = "”, „".join(matched_subjects[:2])
        return f"Se potrivește cu preferințele tale: „{listed}”."
    if history_subjects:
        return f"Din aceeași zonă cu ce ai citit: „{sorted(history_subjects)[0]}”."
    if similarity > 0.15:
        subjects = [s.name for s in book.subjects.all()][:2]
        if subjects:
            return f"Seamănă cu ce ai citit, pe teme de {' și '.join(subjects)}."
        return "Seamănă cu titlurile din raftul tău."
    if book.featured:
        return "Din selecția bibliotecarului."
    if book.recommended_age and book.recommended_age == user_age:
        return f"Potrivită pentru {book.get_recommended_age_display()}."
    return "Adăugată recent în catalog."

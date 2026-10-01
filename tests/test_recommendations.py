from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import UserProfile
from apps.catalog import services as catalog_services
from apps.catalog.models import (
    Author,
    Book,
    BookEdition,
    BookResource,
    RightsStatus,
    Subject,
)
from apps.reader import services as reader_services
from apps.reader.models import UserBookState
from apps.recommendations import services as rec_services
from apps.recommendations.engine import (
    ContentBasedRecommendationEngine,
    SimpleTfidfVectorizer,
    age_relevance,
    book_document,
    get_index,
    invalidate_index,
)

User = get_user_model()


def publish_book(librarian, title, subjects, *, author="Autor", age="10-12",
                 description="", featured=False):
    book = Book.objects.create(
        title=title, recommended_age=age, description=description, featured=featured
    )
    author_obj, _ = Author.objects.get_or_create(name=author)
    book.authors.add(author_obj)
    for name in subjects:
        subject, _ = Subject.objects.get_or_create(name=name)
        book.subjects.add(subject)
    edition = BookEdition.objects.create(book=book, language="ro", is_primary=True)
    BookResource.objects.create(
        edition=edition,
        format=BookResource.Format.EXTERNAL,
        storage_type=BookResource.Storage.EXTERNAL,
        external_url=f"https://example.org/{book.slug}",
        is_primary=True,
        rights_status=RightsStatus.VERIFIED,
    )
    catalog_services.publish(book, librarian)
    return book


class RecommendationBaseTest(TestCase):
    def setUp(self):
        invalidate_index()
        self.librarian = User.objects.create_user(
            "bib", password="x", role=User.Role.LIBRARIAN
        )
        self.student = User.objects.create_user(
            "elev", password="x", role=User.Role.STUDENT
        )
        self.profile = UserProfile.objects.create(user=self.student, age_group="10-12")

        self.dragoni = publish_book(
            self.librarian, "Dragoni și castele", ["Fantasy"],
            author="A. Fantast", description="O poveste cu dragoni, magie și castele."
        )
        self.vrajitori = publish_book(
            self.librarian, "Vrăjitorii din nord", ["Fantasy"],
            author="B. Magic", description="Magie, vrăjitori și castele în nord."
        )
        self.chimie = publish_book(
            self.librarian, "Chimia pe înțelesul tuturor", ["Știință"],
            author="C. Savant", description="Experimente de chimie și laborator.",
            age="13-15"
        )
        self.roboti = publish_book(
            self.librarian, "Roboți și circuite", ["Știință"],
            author="D. Inginer", description="Cum funcționează roboții și circuitele."
        )

    def tearDown(self):
        invalidate_index()


class EngineTest(RecommendationBaseTest):
    def test_indexul_contine_doar_carti_publicate(self):
        draft = Book.objects.create(title="Nepublicată", recommended_age="10-12")
        index = get_index(force=True)
        self.assertEqual(len(index), 4)
        self.assertNotIn(draft.id, index.book_ids)

    def test_indexul_se_reconstruieste_dupa_publicare(self):
        first = get_index()
        publish_book(self.librarian, "Titlu nou", ["Mister"], author="E. Nou")
        second = get_index()
        self.assertNotEqual(first.version, second.version)
        self.assertEqual(len(second), 5)

    def test_apreciere_conduce_la_carti_similare(self):
        reader_services.set_reaction(
            self.student, self.dragoni, UserBookState.Reaction.LIKE
        )
        picks = rec_services.recommendations_for(self.student, limit=3)
        self.assertEqual(picks[0].book, self.vrajitori)

    def test_cartea_respinsa_nu_apare(self):
        reader_services.set_reaction(
            self.student, self.chimie, UserBookState.Reaction.DISLIKE
        )
        picks = rec_services.recommendations_for(self.student, limit=10)
        self.assertNotIn(self.chimie, [p.book for p in picks])

    def test_cartea_terminata_iese_din_descoperire(self):
        reader_services.set_book_state(
            self.student, self.dragoni, UserBookState.Status.FINISHED
        )
        picks = rec_services.recommendations_for(self.student, limit=10)
        self.assertNotIn(self.dragoni, [p.book for p in picks])

    def test_preferintele_de_onboarding_pornesc_recomandarile(self):
        self.profile.preferred_subjects.add(Subject.objects.get(name="Știință"))
        picks = rec_services.recommendations_for(self.student, limit=2)
        self.assertTrue(
            {p.book for p in picks} <= {self.chimie, self.roboti},
            f"Aștept titluri de știință, am primit {[p.book.title for p in picks]}",
        )

    def test_explicatia_mentioneaza_preferinta_aleasa(self):
        self.profile.preferred_subjects.add(Subject.objects.get(name="Fantasy"))
        picks = rec_services.recommendations_for(self.student, limit=4)
        top = picks[0]
        self.assertIn("Fantasy", top.reason)
        self.assertIn("Fantasy", top.matched_subjects)

    def test_personalizarea_dezactivata_nu_foloseste_istoricul(self):
        reader_services.set_reaction(
            self.student, self.dragoni, UserBookState.Reaction.LIKE
        )
        self.profile.personalization_enabled = False
        self.profile.save()
        picks = rec_services.recommendations_for(self.student, limit=4)
        scores = {round(p.score, 6) for p in picks}
        self.assertLessEqual(
            len(scores), 2, "Fără personalizare scorurile nu trebuie să vină din istoric"
        )

    def test_diversificare_maxim_doua_carti_per_autor(self):
        for i in range(4):
            publish_book(
                self.librarian, f"Serie fantasy {i}", ["Fantasy"],
                author="A. Fantast", description="dragoni magie castele"
            )
        reader_services.set_reaction(
            self.student, self.dragoni, UserBookState.Reaction.LIKE
        )
        picks = rec_services.recommendations_for(self.student, limit=4)
        authors = [a.name for p in picks for a in p.book.authors.all()]
        self.assertLessEqual(authors.count("A. Fantast"), 2)

    def test_cold_start_foloseste_selectia_bibliotecarului(self):
        featured = publish_book(
            self.librarian, "Alegerea bibliotecarei", ["Mister"],
            author="F. Curator", featured=True
        )
        picks = rec_services.recommendations_for(self.student, limit=3)
        self.assertEqual(picks[0].book, featured)
        self.assertIn("bibliotecar", picks[0].reason.lower())

    def test_utilizator_anonim_primeste_cold_start(self):
        from django.contrib.auth.models import AnonymousUser

        picks = rec_services.recommendations_for(AnonymousUser(), limit=3)
        self.assertEqual(len(picks), 3)

    def test_catalog_gol_nu_arunca_eroare(self):
        Book.objects.all().delete()
        invalidate_index()
        self.assertEqual(rec_services.recommendations_for(self.student, limit=5), [])

    def test_similar_to_exclude_cartea_curenta(self):
        similar = rec_services.similar_to(self.dragoni, limit=3)
        self.assertNotIn(self.dragoni, [s.book for s in similar])
        self.assertEqual(similar[0].book, self.vrajitori)

    def test_scorul_este_intre_zero_si_unu(self):
        reader_services.set_reaction(
            self.student, self.dragoni, UserBookState.Reaction.LIKE
        )
        for pick in rec_services.recommendations_for(self.student, limit=10):
            self.assertGreaterEqual(pick.score, 0.0)
            self.assertLessEqual(pick.score, 1.0)
            self.assertGreaterEqual(pick.percent, 1)

    def test_relevanta_varstei_scade_cu_distanta(self):
        self.assertEqual(age_relevance("10-12", "10-12"), 1.0)
        self.assertLess(age_relevance("16-18", "10-12"), age_relevance("13-15", "10-12"))
        self.assertEqual(age_relevance("", "10-12"), 0.5)

    def test_documentul_cartii_contine_metadatele(self):
        document = book_document(self.dragoni)
        self.assertIn("Dragoni", document)
        self.assertIn("Fantasy", document)
        self.assertIn("A. Fantast", document)
        self.assertIn("varsta_10-12", document)


class FallbackVectorizerTest(RecommendationBaseTest):
    """Aceleași rezultate fără scikit-learn instalat."""

    def setUp(self):
        super().setUp()
        import apps.recommendations.engine as engine_module

        self._original = engine_module._make_vectorizer
        engine_module._make_vectorizer = lambda: SimpleTfidfVectorizer()
        invalidate_index()

    def tearDown(self):
        import apps.recommendations.engine as engine_module

        engine_module._make_vectorizer = self._original
        invalidate_index()
        super().tearDown()

    def test_recomandarea_functioneaza_fara_sklearn(self):
        reader_services.set_reaction(
            self.student, self.dragoni, UserBookState.Reaction.LIKE
        )
        picks = rec_services.recommendations_for(self.student, limit=3)
        self.assertEqual(picks[0].book, self.vrajitori)

    def test_similar_to_functioneaza_fara_sklearn(self):
        similar = rec_services.similar_to(self.chimie, limit=2)
        self.assertEqual(similar[0].book, self.roboti)

    def test_vectorii_sunt_normalizati(self):
        import math

        index = get_index(force=True)
        row = index.row(self.dragoni.id)
        norm = math.sqrt(sum(v * v for v in row.values()))
        self.assertAlmostEqual(norm, 1.0, places=6)


class EngineSwapTest(RecommendationBaseTest):
    """View-ul nu trebuie să știe ce algoritm rulează."""

    def tearDown(self):
        rec_services.set_engine(ContentBasedRecommendationEngine())
        super().tearDown()

    def test_motorul_poate_fi_inlocuit(self):
        from apps.recommendations.engine import Recommendation, RecommendationEngine

        class AlphabeticalEngine(RecommendationEngine):
            def recommend(self, user, limit=10):
                books = Book.objects.order_by("title")[:limit]
                return [Recommendation(book=b, score=1.0, reason="test") for b in books]

        rec_services.set_engine(AlphabeticalEngine())
        picks = rec_services.recommendations_for(self.student, limit=2)
        self.assertEqual(picks[0].book.title, "Chimia pe înțelesul tuturor")


class RecommendationViewTest(RecommendationBaseTest):
    def test_pagina_pentru_tine_raspunde(self):
        self.client.force_login(self.student)
        response = self.client.get("/recommendations/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pentru tine")

    def test_pagina_arata_explicatia(self):
        self.profile.preferred_subjects.add(Subject.objects.get(name="Fantasy"))
        self.client.force_login(self.student)
        response = self.client.get("/recommendations/")
        self.assertContains(response, "Fantasy")


class TeacherListColdStartTest(RecommendationBaseTest):
    """Fără istoric, listele profesorilor sunt un semnal mai bun decât „recent”."""

    def test_listele_publicate_apar_inaintea_titlurilor_recente(self):
        from apps.reading_lists import services as list_services

        teacher = User.objects.create_user(
            "prof", password="x", role=User.Role.TEACHER
        )
        reading_list = list_services.create_list(teacher, title="Recomandate la clasă")
        list_services.add_book(reading_list, self.chimie, teacher)
        list_services.publish_list(reading_list, teacher)

        fresh = User.objects.create_user("nou", password="x", role=User.Role.STUDENT)
        UserProfile.objects.create(user=fresh)
        picks = rec_services.recommendations_for(fresh, limit=4)
        reasons = {p.book.title: p.reason for p in picks}
        self.assertIn("profesor", reasons["Chimia pe înțelesul tuturor"].lower())

    def test_o_lista_ciorna_nu_influenteaza_recomandarile(self):
        from apps.reading_lists import services as list_services

        teacher = User.objects.create_user(
            "prof", password="x", role=User.Role.TEACHER
        )
        reading_list = list_services.create_list(teacher, title="Ciornă")
        list_services.add_book(reading_list, self.chimie, teacher)

        fresh = User.objects.create_user("nou", password="x", role=User.Role.STUDENT)
        UserProfile.objects.create(user=fresh)
        picks = rec_services.recommendations_for(fresh, limit=4)
        reasons = [p.reason for p in picks]
        self.assertFalse(any("profesor" in r.lower() for r in reasons))


class ColdStartRespectsRejectionTest(RecommendationBaseTest):
    """Un refuz explicit rămâne valabil indiferent ce cale produce lista."""

    def test_cartea_respinsa_nu_reapare_prin_cold_start(self):
        reader_services.set_reaction(
            self.student, self.chimie, UserBookState.Reaction.DISLIKE
        )
        picks = rec_services.cold_start(user=self.student, limit=10)
        self.assertNotIn(self.chimie, [p.book for p in picks])

    def test_cold_start_nu_repeta_cartile_din_raft(self):
        reader_services.set_book_state(
            self.student, self.dragoni, UserBookState.Status.WANT_TO_READ
        )
        picks = rec_services.cold_start(user=self.student, limit=10)
        self.assertNotIn(self.dragoni, [p.book for p in picks])

    def test_utilizator_nou_primeste_justificari_nu_scoruri_inventate(self):
        fresh = User.objects.create_user("proaspat", password="x")
        UserProfile.objects.create(user=fresh)
        picks = rec_services.recommendations_for(fresh, limit=3)
        for pick in picks:
            self.assertTrue(pick.reason, "fiecare recomandare are un motiv")


class ExplanationQualityTest(RecommendationBaseTest):
    """O explicatie generica pentru o alegere motivata induce in eroare."""

    def test_explicatia_face_referire_la_raft_cand_nu_exista_preferinte(self):
        reader_services.set_reaction(
            self.student, self.chimie, UserBookState.Reaction.LIKE
        )
        picks = rec_services.recommendations_for(self.student, limit=5)
        top = picks[0]
        self.assertEqual(top.book, self.roboti)
        self.assertIn("ce ai citit", top.reason)
        self.assertNotIn("Adăugată recent", top.reason)

    def test_cartea_respinsa_nu_contribuie_la_explicatie(self):
        reader_services.set_reaction(
            self.student, self.chimie, UserBookState.Reaction.DISLIKE
        )
        picks = rec_services.recommendations_for(self.student, limit=5)
        for pick in picks:
            self.assertNotIn("Știință", pick.reason)

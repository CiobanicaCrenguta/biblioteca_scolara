from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from apps.catalog import services
from apps.catalog.models import (
    Author,
    Book,
    BookEdition,
    BookResource,
    PublicationStatus,
    RightsStatus,
    Subject,
)
from apps.reader import services as reader_services
from apps.reader.models import ReadingProgress, UserBookState

User = get_user_model()


def make_book(*, complete=True, verified=True):
    book = Book.objects.create(title="Carte test", recommended_age="10-12")
    if complete:
        author, _ = Author.objects.get_or_create(name="Autor Test")
        subject, _ = Subject.objects.get_or_create(name="Aventură")
        book.authors.add(author)
        book.subjects.add(subject)
    edition = BookEdition.objects.create(book=book, language="ro", is_primary=True)
    resource = BookResource.objects.create(
        edition=edition,
        format=BookResource.Format.EXTERNAL,
        storage_type=BookResource.Storage.EXTERNAL,
        external_url="https://example.org/carte",
        is_primary=True,
        rights_status=RightsStatus.VERIFIED if verified else RightsStatus.UNKNOWN,
    )
    return book, resource


class PublicationRulesTest(TestCase):
    def setUp(self):
        self.librarian = User.objects.create_user(
            "bib", password="x", role=User.Role.LIBRARIAN
        )
        self.student = User.objects.create_user(
            "elev", password="x", role=User.Role.STUDENT
        )

    def test_publica_daca_toate_conditiile_sunt_indeplinite(self):
        book, _ = make_book()
        services.publish(book, self.librarian)
        book.refresh_from_db()
        self.assertEqual(book.status, PublicationStatus.PUBLISHED)
        self.assertIsNotNone(book.published_at)

    def test_nu_publica_fara_drepturi_verificate(self):
        book, _ = make_book(verified=False)
        with self.assertRaises(services.PublicationError) as ctx:
            services.publish(book, self.librarian)
        self.assertIn("resursă activă", str(ctx.exception))
        book.refresh_from_db()
        self.assertEqual(book.status, PublicationStatus.DRAFT)

    def test_nu_publica_fara_autor_si_subiect(self):
        book, _ = make_book(complete=False)
        problems = services.validate_for_publication(book)
        self.assertEqual(len(problems), 2)

    def test_studentul_nu_poate_publica(self):
        book, _ = make_book()
        with self.assertRaises(PermissionDenied):
            services.publish(book, self.student)

    def test_dezactivarea_ultimei_resurse_retrage_cartea(self):
        book, resource = make_book()
        services.publish(book, self.librarian)
        services.set_resource_active(resource, False, self.librarian)
        book.refresh_from_db()
        self.assertEqual(book.status, PublicationStatus.READY)

    def test_arhivarea_nu_sterge(self):
        book, _ = make_book()
        services.publish(book, self.librarian)
        services.archive(book, self.librarian)
        self.assertTrue(Book.objects.filter(pk=book.pk).exists())


class ReadingAccessTest(TestCase):
    def setUp(self):
        self.librarian = User.objects.create_user(
            "bib", password="x", role=User.Role.LIBRARIAN
        )
        self.student = User.objects.create_user(
            "elev", password="x", role=User.Role.STUDENT
        )
        self.teacher = User.objects.create_user(
            "prof", password="x", role=User.Role.TEACHER
        )
        self.book, self.resource = make_book()

    def test_toate_rolurile_citesc_o_carte_publicata(self):
        services.publish(self.book, self.librarian)
        for user in (self.student, self.teacher, self.librarian):
            resolved = reader_services.resolve_reading_resource(self.book, user)
            self.assertEqual(resolved, self.resource)

    def test_cartea_nepublicata_nu_se_deschide(self):
        with self.assertRaises(PermissionDenied):
            reader_services.resolve_reading_resource(self.book, self.student)

    def test_progresul_muta_cartea_in_citesc_acum(self):
        services.publish(self.book, self.librarian)
        reader_services.save_progress(self.student, self.resource, 42, 30)
        state = UserBookState.objects.get(user=self.student, book=self.book)
        self.assertEqual(state.status, UserBookState.Status.READING)
        self.assertIsNotNone(state.started_at)
        progress = ReadingProgress.objects.get(user=self.student, resource=self.resource)
        self.assertEqual(progress.location_value, "42")

    def test_progresul_se_actualizeaza_nu_se_dubleaza(self):
        services.publish(self.book, self.librarian)
        reader_services.save_progress(self.student, self.resource, 10, 10)
        reader_services.save_progress(self.student, self.resource, 55, 44)
        self.assertEqual(
            ReadingProgress.objects.filter(user=self.student).count(), 1
        )
        self.assertEqual(
            ReadingProgress.objects.get(user=self.student).location_value, "55"
        )

    def test_procentul_este_limitat(self):
        services.publish(self.book, self.librarian)
        reader_services.save_progress(self.student, self.resource, 1, 3000)
        self.assertEqual(ReadingProgress.objects.get(user=self.student).percentage, 100)

    def test_o_singura_stare_per_carte(self):
        services.publish(self.book, self.librarian)
        reader_services.set_book_state(
            self.student, self.book, UserBookState.Status.WANT_TO_READ
        )
        reader_services.set_book_state(
            self.student, self.book, UserBookState.Status.FINISHED
        )
        self.assertEqual(
            UserBookState.objects.filter(user=self.student, book=self.book).count(), 1
        )


class ViewSmokeTest(TestCase):
    def setUp(self):
        self.librarian = User.objects.create_user(
            "bib", password="parola123", role=User.Role.LIBRARIAN
        )
        self.book, _ = make_book()
        services.publish(self.book, self.librarian)

    def test_catalogul_arata_doar_carti_publicate(self):
        nepublicata, _ = make_book(verified=False)
        nepublicata.title = "Ascunsă"
        nepublicata.save()
        response = self.client.get("/")
        self.assertContains(response, "Carte test")
        self.assertNotContains(response, "Ascunsă")

    def test_lectura_cere_autentificare(self):
        response = self.client.get(f"/books/{self.book.slug}/read/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_publicarea_prin_get_nu_este_permisa(self):
        self.client.login(username="bib", password="parola123")
        response = self.client.get(f"/books/{self.book.slug}/publish/")
        self.assertEqual(response.status_code, 405)

import json

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone

from apps.accounts import privacy
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
from apps.reader.models import InteractionEvent, ReadingProgress, UserBookState
from apps.reader.stats import reading_stats
from apps.reading_lists import services as list_services
from apps.reading_lists.models import ListStatus, ReadingList

User = get_user_model()


def make_published_book(librarian, title, subject="Aventură", author="Autor Unu"):
    book = Book.objects.create(title=title, recommended_age="10-12")
    author_obj, _ = Author.objects.get_or_create(name=author)
    subject_obj, _ = Subject.objects.get_or_create(name=subject)
    book.authors.add(author_obj)
    book.subjects.add(subject_obj)
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


class RolesBaseTest(TestCase):
    def setUp(self):
        self.librarian = User.objects.create_user(
            "bib", password="parola123", role=User.Role.LIBRARIAN
        )
        self.teacher = User.objects.create_user(
            "prof", password="parola123", role=User.Role.TEACHER
        )
        self.other_teacher = User.objects.create_user(
            "prof2", password="parola123", role=User.Role.TEACHER
        )
        self.student = User.objects.create_user(
            "elev", password="parola123", role=User.Role.STUDENT
        )
        for user in (self.librarian, self.teacher, self.other_teacher, self.student):
            UserProfile.objects.get_or_create(user=user)

        self.book = make_published_book(self.librarian, "Insula")
        self.book2 = make_published_book(self.librarian, "Corabia")


class ReadingListRulesTest(RolesBaseTest):
    def test_profesorul_creeaza_lista(self):
        reading_list = list_services.create_list(self.teacher, title="Vara asta citim")
        self.assertEqual(reading_list.owner, self.teacher)
        self.assertEqual(reading_list.status, ListStatus.DRAFT)

    def test_studentul_nu_creeaza_lista(self):
        with self.assertRaises(PermissionDenied):
            list_services.create_list(self.student, title="Lista mea")

    def test_profesorul_nu_modifica_lista_altui_profesor(self):
        reading_list = list_services.create_list(self.teacher, title="A mea")
        with self.assertRaises(PermissionDenied):
            list_services.add_book(reading_list, self.book, self.other_teacher)

    def test_bibliotecarul_poate_corecta_orice_lista(self):
        reading_list = list_services.create_list(self.teacher, title="A profesorului")
        list_services.add_book(reading_list, self.book, self.librarian)
        self.assertEqual(reading_list.items.count(), 1)

    def test_nu_poti_adauga_o_carte_nepublicata(self):
        draft = Book.objects.create(title="Ciornă", recommended_age="10-12")
        reading_list = list_services.create_list(self.teacher, title="Test")
        with self.assertRaises(list_services.ReadingListError):
            list_services.add_book(reading_list, draft, self.teacher)

    def test_aceeasi_carte_nu_intra_de_doua_ori(self):
        reading_list = list_services.create_list(self.teacher, title="Test")
        list_services.add_book(reading_list, self.book, self.teacher)
        with self.assertRaises(list_services.ReadingListError):
            list_services.add_book(reading_list, self.book, self.teacher)

    def test_lista_goala_nu_se_publica(self):
        reading_list = list_services.create_list(self.teacher, title="Goală")
        with self.assertRaises(list_services.ReadingListError):
            list_services.publish_list(reading_list, self.teacher)

    def test_lista_nu_se_publica_daca_o_carte_a_fost_arhivata(self):
        reading_list = list_services.create_list(self.teacher, title="Test")
        list_services.add_book(reading_list, self.book, self.teacher)
        catalog_services.archive(self.book, self.librarian)
        with self.assertRaises(list_services.ReadingListError) as ctx:
            list_services.publish_list(reading_list, self.teacher)
        self.assertIn("Insula", str(ctx.exception))

    def test_pozitiile_raman_consecutive_dupa_stergere(self):
        reading_list = list_services.create_list(self.teacher, title="Test")
        third = make_published_book(self.librarian, "A treia")
        for book in (self.book, self.book2, third):
            list_services.add_book(reading_list, book, self.teacher)
        list_services.remove_book(reading_list, self.book2, self.teacher)
        positions = list(reading_list.items.values_list("position", flat=True))
        self.assertEqual(positions, [1, 2])

    def test_reordonarea_schimba_pozitiile(self):
        reading_list = list_services.create_list(self.teacher, title="Test")
        first = list_services.add_book(reading_list, self.book, self.teacher)
        list_services.add_book(reading_list, self.book2, self.teacher)
        list_services.move_item(reading_list, first.id, "down", self.teacher)
        titles = [item.book.title for item in reading_list.items.all()]
        self.assertEqual(titles, ["Corabia", "Insula"])

    def test_ciorna_nu_este_vizibila_studentului(self):
        reading_list = list_services.create_list(self.teacher, title="Ciornă")
        self.assertFalse(list_services.can_view(reading_list, self.student))
        self.assertTrue(list_services.can_view(reading_list, self.teacher))


class ReadingListViewTest(RolesBaseTest):
    def test_studentul_nu_vede_butonul_de_creare(self):
        self.client.force_login(self.student)
        response = self.client.get("/reading-lists/")
        self.assertNotContains(response, "Listă nouă")

    def test_studentul_nu_poate_accesa_pagina_de_creare(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get("/reading-lists/create/").status_code, 403)

    def test_profesorul_parcurge_tot_fluxul(self):
        self.client.force_login(self.teacher)
        self.client.post(
            "/reading-lists/create/",
            {"title": "Lecturi de vacanță", "description": "", "target_age_group": "10-12"},
        )
        reading_list = ReadingList.objects.get(title="Lecturi de vacanță")
        self.client.post(
            f"/reading-lists/{reading_list.slug}/add/",
            {"book": self.book.id, "note": "Începeți cu asta."},
        )
        self.client.post(f"/reading-lists/{reading_list.slug}/publish/")
        reading_list.refresh_from_db()
        self.assertEqual(reading_list.status, ListStatus.PUBLISHED)

        self.client.force_login(self.student)
        response = self.client.get(f"/reading-lists/{reading_list.slug}/")
        self.assertContains(response, "Începeți cu asta.")

    def test_ciorna_da_404_pentru_student(self):
        reading_list = list_services.create_list(self.teacher, title="Secret")
        self.client.force_login(self.student)
        self.assertEqual(
            self.client.get(f"/reading-lists/{reading_list.slug}/").status_code, 404
        )


class ReaderStatsTest(RolesBaseTest):
    def test_statistici_goale_nu_arunca_eroare(self):
        stats = reading_stats(self.student)
        self.assertFalse(stats["has_data"])
        self.assertEqual(stats["finished"], 0)
        self.assertEqual(stats["level"], "La început de drum")

    def test_statisticile_numara_corect_pe_rafturi(self):
        reader_services.set_book_state(
            self.student, self.book, UserBookState.Status.FINISHED
        )
        reader_services.set_book_state(
            self.student, self.book2, UserBookState.Status.WANT_TO_READ
        )
        stats = reading_stats(self.student)
        self.assertEqual(stats["finished"], 1)
        self.assertEqual(stats["want_to_read"], 1)
        self.assertEqual(stats["total"], 2)

    def test_temele_preferate_vin_din_carti_citite(self):
        reader_services.set_book_state(
            self.student, self.book, UserBookState.Status.FINISHED
        )
        stats = reading_stats(self.student)
        self.assertEqual(stats["top_subjects"][0][0], "Aventură")

    def test_continua_lectura_arata_ultima_pozitie(self):
        resource = BookResource.objects.filter(edition__book=self.book).first()
        reader_services.save_progress(self.student, resource, 88, 45)
        stats = reading_stats(self.student)
        self.assertEqual(stats["continue_reading"]["book"], self.book)
        self.assertEqual(stats["continue_reading"]["location"], "88")
        self.assertEqual(stats["continue_reading"]["percentage"], 45)

    def test_cartea_terminata_nu_apare_la_continua(self):
        resource = BookResource.objects.filter(edition__book=self.book).first()
        reader_services.save_progress(self.student, resource, 200, 100)
        self.assertIsNone(reading_stats(self.student)["continue_reading"])

    def test_nivelul_creste_cu_numarul_de_carti(self):
        for i in range(5):
            book = make_published_book(self.librarian, f"Carte {i}")
            reader_services.set_book_state(
                self.student, book, UserBookState.Status.FINISHED
            )
        self.assertEqual(reading_stats(self.student)["level"], "Cititor constant")

    def test_activitatea_are_sase_luni(self):
        self.assertEqual(len(reading_stats(self.student)["activity"]), 6)

    def test_profilul_afiseaza_statisticile(self):
        reader_services.set_book_state(
            self.student, self.book, UserBookState.Status.FINISHED
        )
        self.client.force_login(self.student)
        response = self.client.get("/accounts/profile/")
        self.assertContains(response, "Cititorul din tine")
        self.assertContains(response, "terminate")


class PrivacyTest(RolesBaseTest):
    def setUp(self):
        super().setUp()
        reader_services.set_book_state(
            self.student, self.book, UserBookState.Status.FINISHED
        )
        resource = BookResource.objects.filter(edition__book=self.book).first()
        reader_services.save_progress(self.student, resource, 12, 20)

    def test_exportul_contine_toate_categoriile(self):
        data = privacy.export_user_data(self.student)
        for key in ("cont", "profil", "raft", "progres_lectura", "evenimente_recomandari"):
            self.assertIn(key, data)
        self.assertEqual(data["cont"]["utilizator"], "elev")
        self.assertTrue(data["raft"])

    def test_exportul_se_descarca_ca_json(self):
        self.client.force_login(self.student)
        response = self.client.get("/accounts/profile/export-data/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload["cont"]["utilizator"], "elev")

    def test_exportul_nu_expune_datele_altcuiva(self):
        data = privacy.export_user_data(self.teacher)
        self.assertEqual(data["raft"], [])

    def test_stergerea_istoricului_pastreaza_contul(self):
        counts = privacy.clear_activity(self.student)
        self.assertGreater(counts["raft"], 0)
        self.assertEqual(UserBookState.objects.filter(user=self.student).count(), 0)
        self.assertEqual(ReadingProgress.objects.filter(user=self.student).count(), 0)
        self.assertTrue(User.objects.filter(username="elev").exists())

    def test_oprirea_profilarii_pastreaza_raftul(self):
        privacy.clear_recommendation_events(self.student)
        self.assertEqual(InteractionEvent.objects.filter(user=self.student).count(), 0)
        self.assertGreater(UserBookState.objects.filter(user=self.student).count(), 0)
        self.student.profile.refresh_from_db()
        self.assertFalse(self.student.profile.personalization_enabled)

    def test_stergerea_contului_cere_confirmare_exacta(self):
        self.client.force_login(self.student)
        self.client.post("/accounts/profile/delete-account/", {"confirm": "gresit"})
        self.assertTrue(User.objects.filter(username="elev").exists())

    def test_stergerea_contului_duce_toate_datele(self):
        self.client.force_login(self.student)
        response = self.client.post(
            "/accounts/profile/delete-account/", {"confirm": "elev"}, follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="elev").exists())
        self.assertEqual(UserBookState.objects.filter(user_id=self.student.id).count(), 0)
        self.assertEqual(ReadingProgress.objects.filter(user_id=self.student.id).count(), 0)

    def test_pagina_de_confidentialitate_raspunde(self):
        self.client.force_login(self.student)
        response = self.client.get("/accounts/profile/privacy/")
        self.assertContains(response, "Ce date păstrăm")

    def test_datele_cer_autentificare(self):
        for url in (
            "/accounts/profile/export-data/",
            "/accounts/profile/clear-history/",
            "/accounts/profile/delete-account/",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)

    def test_salvarea_profilului_inregistreaza_informarea(self):
        self.client.force_login(self.student)
        self.client.post(
            "/accounts/profile/",
            {"age_group": "10-12", "preferred_language": "ro", "personalization_enabled": "on"},
        )
        self.student.profile.refresh_from_db()
        self.assertIsNotNone(self.student.profile.privacy_acknowledged_at)

    def test_profesorul_nu_vede_raftul_elevului(self):
        """Confidențialitatea elevilor: nu există rută care să expună raftul altcuiva."""
        self.client.force_login(self.teacher)
        response = self.client.get("/my-library/")
        self.assertNotContains(response, "Insula")

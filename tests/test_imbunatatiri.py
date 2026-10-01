from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.forms import RegisterForm
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
from apps.reader.stats import _scor_implicare, _serie_zilnica, reading_stats

User = get_user_model()

PAROLA = "ParolaBuna2026!"


def publica(librarian, titlu, *, subiect="Aventură", autor="Autor Unu",
            total_pages=None):
    book = Book.objects.create(title=titlu, recommended_age="10-12")
    a, _ = Author.objects.get_or_create(name=autor)
    s, _ = Subject.objects.get_or_create(name=subiect)
    book.authors.add(a)
    book.subjects.add(s)
    ed = BookEdition.objects.create(book=book, language="ro", is_primary=True)
    res = BookResource.objects.create(
        edition=ed,
        format=BookResource.Format.EXTERNAL,
        storage_type=BookResource.Storage.EXTERNAL,
        external_url=f"https://example.org/{book.slug}",
        is_primary=True,
        rights_status=RightsStatus.VERIFIED,
        total_pages=total_pages,
    )
    catalog_services.publish(book, librarian)
    return book, res


# ==========================================================================
# 1. Formularul de înregistrare
# ==========================================================================


class InregistrareTest(TestCase):
    def test_parola_slaba_este_semnalata_pe_campul_tastat(self):
        """Django atașează eroarea celui de-al doilea câmp. O mutăm pe primul."""
        form = RegisterForm(data={"username": "ana", "email": "",
                                  "password1": "parola123",
                                  "password2": "parola123"})
        self.assertFalse(form.is_valid())
        self.assertTrue(form.errors.get("password1"))
        self.assertFalse(form.errors.get("password2"))

    def test_parolele_diferite_raman_pe_al_doilea_camp(self):
        form = RegisterForm(data={"username": "ana", "email": "",
                                  "password1": PAROLA, "password2": "Altceva9!"})
        self.assertFalse(form.is_valid())
        self.assertTrue(form.errors.get("password2"))

    def test_textul_de_ajutor_al_parolei_nu_mai_contine_html(self):
        ajutor = RegisterForm().fields["password1"].help_text
        self.assertNotIn("<ul>", ajutor)
        self.assertNotIn("<li>", ajutor)
        self.assertIn("8 caractere", ajutor)

    def test_contul_se_creeaza_cu_rol_de_student_si_profil(self):
        form = RegisterForm(data={"username": "elev1", "email": "",
                                  "password1": PAROLA, "password2": PAROLA})
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.role, User.Role.STUDENT)
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_emailul_este_optional_dar_se_salveaza_cand_exista(self):
        f1 = RegisterForm(data={"username": "fara", "email": "",
                                "password1": PAROLA, "password2": PAROLA})
        self.assertTrue(f1.is_valid(), f1.errors)
        self.assertEqual(f1.save().email, "")

        f2 = RegisterForm(data={"username": "cu", "email": "a@scoala.ro",
                                "password1": PAROLA, "password2": PAROLA})
        self.assertTrue(f2.is_valid(), f2.errors)
        self.assertEqual(f2.save().email, "a@scoala.ro")

    def test_rolul_nu_poate_fi_ales_din_formular(self):
        form = RegisterForm(data={"username": "siret", "email": "",
                                  "password1": PAROLA, "password2": PAROLA,
                                  "role": "LIBRARIAN"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().role, User.Role.STUDENT)
        self.assertNotIn("role", form.fields)

    def test_username_duplicat_este_respins(self):
        User.objects.create_user("ocupat", password=PAROLA)
        form = RegisterForm(data={"username": "ocupat", "email": "",
                                  "password1": PAROLA, "password2": PAROLA})
        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_pagina_afiseaza_eroarea_langa_campul_gresit(self):
        raspuns = self.client.post("/accounts/register/",
                                   {"username": "ana", "email": "",
                                    "password1": "parola123",
                                    "password2": "parola123"})
        self.assertEqual(raspuns.status_code, 200)
        html = raspuns.content.decode()
        self.assertIn("field-error", html)
        self.assertIn("field-msg", html)

    def test_inregistrarea_reusita_duce_la_profil(self):
        raspuns = self.client.post("/accounts/register/",
                                   {"username": "elev2", "email": "",
                                    "password1": PAROLA, "password2": PAROLA})
        self.assertEqual(raspuns.status_code, 302)
        self.assertIn("/accounts/profile/", raspuns["Location"])

    def test_pagina_de_autentificare_are_legatura_spre_inregistrare(self):
        html = self.client.get("/accounts/login/").content.decode()
        self.assertIn("/accounts/register/", html)


# ==========================================================================
# 2. Contoare de sesiune
# ==========================================================================


class SesiuniDeLecturaTest(TestCase):
    def setUp(self):
        self.bib = User.objects.create_user("bib", password=PAROLA,
                                            role=User.Role.LIBRARIAN)
        self.elev = User.objects.create_user("elev", password=PAROLA)
        UserProfile.objects.create(user=self.elev)
        self.book, self.res = publica(self.bib, "Insula", total_pages=200)

    def _salveaza(self, momento, pagina, procent):
        with mock.patch("apps.reader.services.timezone.now", return_value=momento):
            reader_services.save_progress(self.elev, self.res, pagina, procent)
        return ReadingProgress.objects.get(user=self.elev, resource=self.res)

    def test_prima_salvare_deschide_o_sesiune(self):
        acum = timezone.now()
        p = self._salveaza(acum, 10, 5)
        self.assertEqual(p.session_count, 1)
        self.assertEqual(p.total_reading_minutes, 0)
        self.assertIsNotNone(p.last_session_at)

    def test_salvarile_apropiate_continua_aceeasi_sesiune(self):
        t0 = timezone.now()
        self._salveaza(t0, 10, 5)
        p = self._salveaza(t0 + timedelta(minutes=12), 40, 20)
        self.assertEqual(p.session_count, 1)
        self.assertEqual(p.total_reading_minutes, 12)

    def test_timpul_se_aduna_pe_parcursul_sesiunii(self):
        t0 = timezone.now()
        self._salveaza(t0, 10, 5)
        self._salveaza(t0 + timedelta(minutes=10), 30, 15)
        p = self._salveaza(t0 + timedelta(minutes=25), 60, 30)
        self.assertEqual(p.session_count, 1)
        self.assertEqual(p.total_reading_minutes, 25)

    def test_o_pauza_lunga_deschide_o_sesiune_noua(self):
        t0 = timezone.now()
        self._salveaza(t0, 10, 5)
        p = self._salveaza(t0 + timedelta(hours=3), 80, 40)
        self.assertEqual(p.session_count, 2)

    def test_pauza_lunga_nu_adauga_timp_de_lectura(self):
        """Nu știm ce a făcut utilizatorul în pauză, deci nu presupunem."""
        t0 = timezone.now()
        self._salveaza(t0, 10, 5)
        self._salveaza(t0 + timedelta(minutes=20), 40, 20)
        p = self._salveaza(t0 + timedelta(hours=5), 90, 45)
        self.assertEqual(p.total_reading_minutes, 20)
        self.assertEqual(p.session_count, 2)

    def test_contoarele_nu_afecteaza_unicitatea_progresului(self):
        t0 = timezone.now()
        for i in range(5):
            self._salveaza(t0 + timedelta(minutes=i * 45), 10 * i + 1, i * 10)
        self.assertEqual(
            ReadingProgress.objects.filter(user=self.elev).count(), 1)
        p = ReadingProgress.objects.get(user=self.elev)
        self.assertEqual(p.session_count, 5)


# ==========================================================================
# 3. Statistici extinse
# ==========================================================================


class StatisticiExtinseTest(TestCase):
    def setUp(self):
        self.bib = User.objects.create_user("bib", password=PAROLA,
                                            role=User.Role.LIBRARIAN)
        self.elev = User.objects.create_user("elev", password=PAROLA)
        UserProfile.objects.create(user=self.elev, age_group="10-12")
        self.b1, self.r1 = publica(self.bib, "Prima", total_pages=100)
        self.b2, self.r2 = publica(self.bib, "A doua", subiect="Fantasy",
                                   autor="Autor Doi")
        self.b3, self.r3 = publica(self.bib, "A treia", subiect="Știință",
                                   autor="Autor Trei")

    def test_lista_cartilor_terminate(self):
        reader_services.set_book_state(self.elev, self.b1,
                                       UserBookState.Status.FINISHED)
        stats = reading_stats(self.elev)
        self.assertEqual(len(stats["finished_books"]), 1)
        intrare = stats["finished_books"][0]
        self.assertEqual(intrare["book"], self.b1)
        self.assertEqual(intrare["percentage"], 100)

    def test_lista_cartilor_in_curs_cu_procentul_real(self):
        reader_services.save_progress(self.elev, self.r1, 42, 42)
        stats = reading_stats(self.elev)
        self.assertEqual(len(stats["reading_books"]), 1)
        self.assertEqual(stats["reading_books"][0]["percentage"], 42)

    def test_procentul_este_cel_mai_avansat_dintre_formate(self):
        """Aceeași operă citită în două formate: contează progresul mai mare."""
        alt = BookResource.objects.create(
            edition=self.b1.editions.first(),
            format=BookResource.Format.PDF,
            storage_type=BookResource.Storage.EXTERNAL,
            external_url="https://example.org/pdf",
            rights_status=RightsStatus.VERIFIED)
        reader_services.save_progress(self.elev, self.r1, 20, 20)
        reader_services.save_progress(self.elev, alt, 70, 70)
        stats = reading_stats(self.elev)
        self.assertEqual(stats["reading_books"][0]["percentage"], 70)

    def test_cartile_in_curs_sunt_ordonate_dupa_progres(self):
        reader_services.save_progress(self.elev, self.r1, 10, 10)
        reader_services.save_progress(self.elev, self.r2, 80, 80)
        stats = reading_stats(self.elev)
        procente = [e["percentage"] for e in stats["reading_books"]]
        self.assertEqual(procente, sorted(procente, reverse=True))

    def test_rata_de_finalizare(self):
        reader_services.set_book_state(self.elev, self.b1,
                                       UserBookState.Status.FINISHED)
        reader_services.set_book_state(self.elev, self.b2,
                                       UserBookState.Status.READING)
        self.assertEqual(reading_stats(self.elev)["completion_rate"], 50)

    def test_rata_de_finalizare_fara_carti_incepute(self):
        reader_services.set_book_state(self.elev, self.b1,
                                       UserBookState.Status.WANT_TO_READ)
        self.assertEqual(reading_stats(self.elev)["completion_rate"], 0)

    def test_numarul_de_sesiuni_si_orele_estimate(self):
        t0 = timezone.now()
        for minute in (0, 15, 30):
            with mock.patch("apps.reader.services.timezone.now",
                            return_value=t0 + timedelta(minutes=minute)):
                reader_services.save_progress(self.elev, self.r1, minute + 1, minute)
        stats = reading_stats(self.elev)
        self.assertEqual(stats["total_sessions"], 1)
        self.assertEqual(stats["total_minutes"], 30)
        self.assertEqual(stats["reading_hours"], 0.5)

    def test_distributia_reactiilor(self):
        reader_services.set_reaction(self.elev, self.b1,
                                     UserBookState.Reaction.LIKE)
        reader_services.set_reaction(self.elev, self.b2,
                                     UserBookState.Reaction.DISLIKE)
        r = reading_stats(self.elev)["books_by_reaction"]
        self.assertEqual(r["liked"], 1)
        self.assertEqual(r["disliked"], 1)
        self.assertEqual(r["neutral"], 0)

    def test_numarul_de_teme_si_autori_distincti(self):
        for carte in (self.b1, self.b2, self.b3):
            reader_services.set_book_state(self.elev, carte,
                                           UserBookState.Status.FINISHED)
        stats = reading_stats(self.elev)
        self.assertEqual(stats["unique_subjects_count"], 3)
        self.assertEqual(stats["unique_authors_count"], 3)

    def test_scorul_de_implicare_este_marginit(self):
        self.assertEqual(_scor_implicare(0, 0, 0), 0)
        self.assertLessEqual(_scor_implicare(500, 500, 100), 100.0)
        self.assertGreater(_scor_implicare(3, 10, 50), _scor_implicare(1, 2, 20))

    def test_statisticile_goale_nu_arunca_eroare(self):
        nou = User.objects.create_user("proaspat", password=PAROLA)
        stats = reading_stats(nou)
        self.assertFalse(stats["has_data"])
        self.assertEqual(stats["finished_books"], [])
        self.assertEqual(stats["reading_books"], [])
        self.assertEqual(stats["total_sessions"], 0)
        self.assertEqual(stats["reading_streak"], 0)


# ==========================================================================
# 4. Seria de zile consecutive
# ==========================================================================


class SerieZilnicaTest(TestCase):
    def test_fara_activitate_seria_este_zero(self):
        self.assertEqual(_serie_zilnica([]), 0)

    def test_trei_zile_consecutive(self):
        azi = timezone.localdate()
        momente = [timezone.now() - timedelta(days=i) for i in range(3)]
        self.assertEqual(_serie_zilnica(momente, azi=azi), 3)

    def test_activitatea_de_ieri_pastreaza_seria(self):
        azi = timezone.localdate()
        momente = [timezone.now() - timedelta(days=i) for i in (1, 2)]
        self.assertEqual(_serie_zilnica(momente, azi=azi), 2)

    def test_o_zi_lipsa_intrerupe_seria(self):
        azi = timezone.localdate()
        momente = [timezone.now(), timezone.now() - timedelta(days=3)]
        self.assertEqual(_serie_zilnica(momente, azi=azi), 1)

    def test_activitatea_veche_nu_conteaza(self):
        azi = timezone.localdate()
        momente = [timezone.now() - timedelta(days=10)]
        self.assertEqual(_serie_zilnica(momente, azi=azi), 0)

    def test_mai_multe_evenimente_in_aceeasi_zi_conteaza_o_data(self):
        azi = timezone.localdate()
        acum = timezone.now()
        momente = [acum, acum - timedelta(hours=2), acum - timedelta(hours=5)]
        self.assertEqual(_serie_zilnica(momente, azi=azi), 1)

    def test_seria_reala_din_evenimente(self):
        bib = User.objects.create_user("bib", password=PAROLA,
                                       role=User.Role.LIBRARIAN)
        elev = User.objects.create_user("elev", password=PAROLA)
        UserProfile.objects.create(user=elev)
        book, _ = publica(bib, "Carte")
        reader_services.set_reaction(elev, book, UserBookState.Reaction.LIKE)
        self.assertTrue(InteractionEvent.objects.filter(user=elev).exists())
        self.assertEqual(reading_stats(elev)["reading_streak"], 1)


# ==========================================================================
# 5. Numărul total de pagini
# ==========================================================================


class TotalPaginiTest(TestCase):
    def setUp(self):
        self.bib = User.objects.create_user("bib", password=PAROLA,
                                            role=User.Role.LIBRARIAN)
        self.elev = User.objects.create_user("elev", password=PAROLA)
        UserProfile.objects.create(user=self.elev)

    def test_campul_este_optional(self):
        _, res = publica(self.bib, "Fara pagini")
        self.assertIsNone(res.total_pages)

    def test_cititorul_afiseaza_totalul_cand_exista(self):
        book, _ = publica(self.bib, "Cu pagini", total_pages=320)
        self.client.force_login(self.elev)
        html = self.client.get(f"/books/{book.slug}/read/").content.decode()
        self.assertIn("din 320", html)
        self.assertIn("const totalPagini = 320", html)

    def test_cititorul_trimite_zero_cand_lipseste(self):
        book, _ = publica(self.bib, "Fara total")
        self.client.force_login(self.elev)
        html = self.client.get(f"/books/{book.slug}/read/").content.decode()
        self.assertIn("const totalPagini = 0", html)


# ==========================================================================
# 6. Cititorul cu salvare automată
# ==========================================================================


class CititorAutomatTest(TestCase):
    def setUp(self):
        self.bib = User.objects.create_user("bib", password=PAROLA,
                                            role=User.Role.LIBRARIAN)
        self.elev = User.objects.create_user("elev", password=PAROLA)
        UserProfile.objects.create(user=self.elev)
        self.book, self.res = publica(self.bib, "Lectura", total_pages=100)
        self.client.force_login(self.elev)

    def test_pagina_contine_salvarea_automata(self):
        html = self.client.get(f"/books/{self.book.slug}/read/").content.decode()
        self.assertIn("setInterval", html)
        self.assertIn("30000", html)

    def test_pagina_salveaza_si_la_parasire(self):
        html = self.client.get(f"/books/{self.book.slug}/read/").content.decode()
        self.assertIn("pagehide", html)
        self.assertIn("sendBeacon", html)

    def test_salvarea_prin_cerere_functioneaza(self):
        raspuns = self.client.post(
            f"/resources/{self.res.pk}/progress/",
            {"book_slug": self.book.slug, "location": "55", "percentage": "55"})
        self.assertEqual(raspuns.status_code, 200)
        p = ReadingProgress.objects.get(user=self.elev, resource=self.res)
        self.assertEqual(p.location_value, "55")
        self.assertEqual(p.session_count, 1)


# ==========================================================================
# 7. Profilul cu secțiunile noi
# ==========================================================================


class ProfilExtinsTest(TestCase):
    def setUp(self):
        self.bib = User.objects.create_user("bib", password=PAROLA,
                                            role=User.Role.LIBRARIAN)
        self.elev = User.objects.create_user("elev", password=PAROLA)
        UserProfile.objects.create(user=self.elev, age_group="10-12")
        self.b1, self.r1 = publica(self.bib, "Terminata")
        self.b2, self.r2 = publica(self.bib, "In curs", autor="Autor Doi")
        self.client.force_login(self.elev)

    def test_sectiunea_carti_citite(self):
        reader_services.set_book_state(self.elev, self.b1,
                                       UserBookState.Status.FINISHED)
        html = self.client.get("/accounts/profile/").content.decode()
        self.assertIn("Cărți citite", html)
        self.assertIn("Terminata", html)

    def test_sectiunea_citesti_acum_cu_buton_de_continuare(self):
        reader_services.save_progress(self.elev, self.r2, 30, 30)
        html = self.client.get("/accounts/profile/").content.decode()
        self.assertIn("Citești acum", html)
        self.assertIn(f"/books/{self.b2.slug}/read/", html)

    def test_indicatorii_avansati_apar(self):
        reader_services.set_book_state(self.elev, self.b1,
                                       UserBookState.Status.FINISHED)
        html = self.client.get("/accounts/profile/").content.decode()
        for eticheta in ("rată de finalizare", "sesiuni de lectură",
                         "zile la rând", "scor de implicare", "teme explorate"):
            self.assertIn(eticheta, html)

    def test_profilul_gol_nu_afiseaza_sectiunile(self):
        html = self.client.get("/accounts/profile/").content.decode()
        self.assertNotIn("Cărți citite", html)
        self.assertNotIn("Citești acum", html)


# ==========================================================================
# 8. Tema administrării și finisajele
# ==========================================================================


class TemaSiFinisajeTest(TestCase):
    def setUp(self):
        self.bib = User.objects.create_superuser("admin", password=PAROLA)
        self.bib.role = User.Role.LIBRARIAN
        self.bib.save()

    def test_administrarea_foloseste_tema_aplicatiei(self):
        self.client.force_login(self.bib)
        html = self.client.get("/admin/").content.decode()
        self.assertIn("css/admin_theme.css", html)
        self.assertIn("Biblioteca școlară", html)

    def test_titlurile_administrarii_sunt_setate(self):
        from django.contrib import admin
        self.assertIn("Biblioteca școlară", admin.site.site_header)
        self.assertEqual(admin.site.site_title, "Biblioteca școlară")

    def test_pagina_are_descriere_si_culoare_de_tema(self):
        html = self.client.get("/").content.decode()
        self.assertIn('name="description"', html)
        self.assertIn('name="theme-color"', html)

    def test_subsolul_arata_confidentialitatea_doar_autentificat(self):
        anonim = self.client.get("/").content.decode()
        self.assertNotIn("/accounts/profile/privacy/", anonim)
        self.client.force_login(self.bib)
        conectat = self.client.get("/").content.decode()
        self.assertIn("/accounts/profile/privacy/", conectat)

    def test_mesajele_au_rol_de_status(self):
        self.client.force_login(self.bib)
        book = Book.objects.create(title="Incompleta", recommended_age="10-12")
        raspuns = self.client.post(f"/books/{book.slug}/publish/", follow=True)
        html = raspuns.content.decode()
        self.assertIn('role="status"', html)
        self.assertIn("msg error", html)

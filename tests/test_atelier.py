import json

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from apps.catalog import workbench
from apps.catalog.forms import FormularCarte
from apps.catalog.models import (
    Author,
    Book,
    BookEdition,
    BookResource,
    PublicationStatus,
    RightsStatus,
    Subject,
)

User = get_user_model()
PAROLA = "ParolaBuna2026!"


def date_carte(**modificari):
    baza = {
        "title": "Insula comorii",
        "autori": "Robert Louis Stevenson",
        "subiecte": "Aventură, Mister",
        "description": "Pirați și o hartă.",
        "recommended_age": "10-12",
        "original_language": "ro",
        "first_publish_year": 1883,
        "featured": False,
        "editie_limba": "ro",
        "editie_editura": "Editura Test",
        "editie_an": 2018,
        "editie_isbn": "9781234567897",
        "editie_coperta": "",
        "resursa_format": BookResource.Format.EXTERNAL,
        "resursa_stocare": BookResource.Storage.EXTERNAL,
        "resursa_link": "https://example.org/insula",
        "resursa_pagini": 290,
        "licenta_nume": "Domeniu public",
        "licenta_url": "",
        "licenta_sursa": "https://example.org/sursa",
        "drepturi_verificate": True,
    }
    baza.update(modificari)
    return baza


class BazaAtelier(TestCase):
    def setUp(self):
        self.bib = User.objects.create_user("bib", password=PAROLA,
                                            role=User.Role.LIBRARIAN)
        self.prof = User.objects.create_user("prof", password=PAROLA,
                                             role=User.Role.TEACHER)
        self.elev = User.objects.create_user("elev", password=PAROLA)


# ==========================================================================
# 1. Numele de autori și teme
# ==========================================================================


class NumeTest(TestCase):
    def test_desparte_si_curata(self):
        self.assertEqual(
            workbench.desparte_nume("  Ion Creangă ,Mihai   Eminescu,  "),
            ["Ion Creangă", "Mihai Eminescu"])

    def test_elimina_duplicatele_indiferent_de_majuscule(self):
        self.assertEqual(
            workbench.desparte_nume("Jules Verne, jules verne, JULES VERNE"),
            ["Jules Verne"])

    def test_textul_gol_nu_produce_nume(self):
        self.assertEqual(workbench.desparte_nume(""), [])
        self.assertEqual(workbench.desparte_nume(None), [])

    def test_autorul_existent_este_refolosit(self):
        existent = Author.objects.create(name="Jules Verne")
        autori, noi = workbench.rezolva_autori(["jules verne"])
        self.assertEqual(autori, [existent])
        self.assertEqual(noi, [])
        self.assertEqual(Author.objects.count(), 1)

    def test_autorul_nou_este_creat_si_raportat(self):
        autori, noi = workbench.rezolva_autori(["Ana Blandiana"])
        self.assertEqual(noi, ["Ana Blandiana"])
        self.assertEqual(autori[0].name, "Ana Blandiana")

    def test_subiectul_existent_este_refolosit(self):
        s = Subject.objects.create(name="Aventură")
        subiecte, noi = workbench.rezolva_subiecte(["aventură"])
        self.assertEqual(subiecte, [s])
        self.assertEqual(noi, [])


# ==========================================================================
# 2. Salvarea într-un singur pas
# ==========================================================================


class SalvareIntrUnPasTest(BazaAtelier):
    def test_o_singura_trimitere_creeaza_tot_lantul(self):
        carte, raport = workbench.salveaza_carte(date_carte(), self.bib)
        self.assertTrue(raport["creata"])
        self.assertEqual(carte.authors.count(), 1)
        self.assertEqual(carte.subjects.count(), 2)
        editie = carte.editions.get(is_primary=True)
        self.assertEqual(editie.publisher, "Editura Test")
        resursa = editie.resources.get(is_primary=True)
        self.assertEqual(resursa.total_pages, 290)
        self.assertEqual(resursa.rights_status, RightsStatus.VERIFIED)

    def test_cartea_devine_publicabila_imediat(self):
        from apps.catalog import services
        carte, _ = workbench.salveaza_carte(date_carte(), self.bib)
        self.assertEqual(services.validate_for_publication(carte), [])

    def test_verificarea_drepturilor_retine_cine_si_cand(self):
        carte, _ = workbench.salveaza_carte(date_carte(), self.bib)
        resursa = BookResource.objects.get(edition__book=carte)
        self.assertEqual(resursa.rights_verified_by, self.bib)
        self.assertIsNotNone(resursa.rights_verified_at)

    def test_fara_bifa_drepturile_raman_neverificate(self):
        carte, _ = workbench.salveaza_carte(
            date_carte(drepturi_verificate=False, licenta_nume=""), self.bib)
        resursa = BookResource.objects.get(edition__book=carte)
        self.assertEqual(resursa.rights_status, RightsStatus.UNKNOWN)
        self.assertIsNone(resursa.rights_verified_by)

    def test_editarea_nu_creeaza_o_a_doua_editie(self):
        carte, _ = workbench.salveaza_carte(date_carte(), self.bib)
        workbench.salveaza_carte(
            date_carte(title="Insula comorii, ediție nouă"), self.bib, carte)
        self.assertEqual(carte.editions.count(), 1)
        self.assertEqual(BookResource.objects.filter(edition__book=carte).count(), 1)

    def test_editarea_inlocuieste_autorii(self):
        carte, _ = workbench.salveaza_carte(date_carte(), self.bib)
        workbench.salveaza_carte(date_carte(autori="Jules Verne"), self.bib, carte)
        self.assertEqual([a.name for a in carte.authors.all()], ["Jules Verne"])

    def test_profesorul_nu_poate_salva(self):
        with self.assertRaises(PermissionDenied):
            workbench.salveaza_carte(date_carte(), self.prof)

    def test_elevul_nu_poate_sterge(self):
        carte, _ = workbench.salveaza_carte(date_carte(), self.bib)
        with self.assertRaises(PermissionDenied):
            workbench.sterge_carte(carte, self.elev)


# ==========================================================================
# 3. Validarea formularului
# ==========================================================================


class FormularCarteTest(TestCase):
    def test_resursa_externa_cere_adresa(self):
        f = FormularCarte(data=date_carte(resursa_link=""))
        self.assertFalse(f.is_valid())
        self.assertIn("resursa_link", f.errors)

    def test_resursa_locala_cere_fisier(self):
        f = FormularCarte(data=date_carte(
            resursa_stocare=BookResource.Storage.LOCAL, resursa_link=""))
        self.assertFalse(f.is_valid())
        self.assertIn("resursa_fisier", f.errors)

    def test_resursa_locala_deja_incarcata_nu_cere_din_nou(self):
        f = FormularCarte(
            data=date_carte(resursa_stocare=BookResource.Storage.LOCAL,
                            resursa_link=""),
            are_fisier=True)
        self.assertTrue(f.is_valid(), f.errors)

    def test_bifa_de_drepturi_cere_licenta(self):
        f = FormularCarte(data=date_carte(licenta_nume=""))
        self.assertFalse(f.is_valid())
        self.assertIn("licenta_nume", f.errors)

    def test_titlul_este_obligatoriu(self):
        f = FormularCarte(data=date_carte(title=""))
        self.assertFalse(f.is_valid())
        self.assertIn("title", f.errors)

    def test_formularul_se_completeaza_din_carte(self):
        bib = User.objects.create_user("b", password=PAROLA,
                                       role=User.Role.LIBRARIAN)
        carte, _ = workbench.salveaza_carte(date_carte(), bib)
        f = FormularCarte.din_carte(carte)
        self.assertEqual(f.initial["title"], "Insula comorii")
        self.assertEqual(f.initial["autori"], "Robert Louis Stevenson")
        self.assertIn("Aventură", f.initial["subiecte"])
        self.assertTrue(f.initial["drepturi_verificate"])


# ==========================================================================
# 4. Starea reală a unei cărți
# ==========================================================================


class SituatieTest(BazaAtelier):
    def test_carte_completa_si_publicata_este_vizibila(self):
        from apps.catalog import services
        carte, _ = workbench.salveaza_carte(date_carte(), self.bib)
        services.publish(carte, self.bib)
        stare = workbench.situatie(carte)
        self.assertEqual(stare["cheie"], "vizibila")
        self.assertTrue(stare["vizibila"])

    def test_publicata_fara_drepturi_este_semnalata_ca_ascunsa(self):
        """Exact cazul care în Django admin arăta ca publicat, deși elevii nu
        vedeau nimic."""
        carte, _ = workbench.salveaza_carte(date_carte(), self.bib)
        Book.objects.filter(pk=carte.pk).update(status=PublicationStatus.PUBLISHED)
        BookResource.objects.filter(edition__book=carte).update(
            rights_status=RightsStatus.UNKNOWN)
        carte.refresh_from_db()
        stare = workbench.situatie(carte)
        self.assertEqual(stare["cheie"], "ascunsa")
        self.assertFalse(stare["vizibila"])
        self.assertTrue(stare["probleme"])

    def test_carte_completa_nepublicata_este_gata(self):
        carte, _ = workbench.salveaza_carte(date_carte(), self.bib)
        self.assertEqual(workbench.situatie(carte)["cheie"], "gata")

    def test_carte_fara_autor_este_incompleta(self):
        carte, _ = workbench.salveaza_carte(
            date_carte(autori="", subiecte=""), self.bib)
        stare = workbench.situatie(carte)
        self.assertEqual(stare["cheie"], "incompleta")
        self.assertGreaterEqual(len(stare["probleme"]), 2)

    def test_carte_arhivata(self):
        from apps.catalog import services
        carte, _ = workbench.salveaza_carte(date_carte(), self.bib)
        services.publish(carte, self.bib)
        services.archive(carte, self.bib)
        self.assertEqual(workbench.situatie(carte)["cheie"], "arhivata")


# ==========================================================================
# 5. Paginile atelierului
# ==========================================================================


class PaginiAtelierTest(BazaAtelier):
    def test_doar_bibliotecarul_intra(self):
        for ruta in ("/gestiune/", "/accounts/gestiune/utilizatori/"):
            self.assertEqual(self.client.get(ruta).status_code, 403, ruta)
            self.client.force_login(self.elev)
            self.assertEqual(self.client.get(ruta).status_code, 403, ruta)
            self.client.force_login(self.prof)
            self.assertEqual(self.client.get(ruta).status_code, 403, ruta)
            self.client.logout()

    def test_atelierul_se_deschide_pentru_bibliotecar(self):
        self.client.force_login(self.bib)
        raspuns = self.client.get("/gestiune/")
        self.assertEqual(raspuns.status_code, 200)
        self.assertContains(raspuns, "Atelierul bibliotecarului")

    def test_o_singura_trimitere_din_pagina_creeaza_cartea(self):
        self.client.force_login(self.bib)
        raspuns = self.client.post("/gestiune/carte/noua/", date_carte(), follow=True)
        self.assertEqual(raspuns.status_code, 200)
        carte = Book.objects.get(title="Insula comorii")
        self.assertEqual(carte.authors.count(), 1)
        self.assertTrue(BookResource.objects.filter(edition__book=carte).exists())

    def test_mesajul_anunta_autorii_nou_creati(self):
        self.client.force_login(self.bib)
        raspuns = self.client.post("/gestiune/carte/noua/",
                                   date_carte(autori="Autor Inventat"), follow=True)
        self.assertContains(raspuns, "Autor Inventat")

    def test_formularul_gresit_nu_pierde_datele(self):
        self.client.force_login(self.bib)
        raspuns = self.client.post("/gestiune/carte/noua/",
                                   date_carte(resursa_link=""))
        self.assertEqual(raspuns.status_code, 200)
        self.assertContains(raspuns, "Insula comorii")
        self.assertFalse(Book.objects.filter(title="Insula comorii").exists())

    def test_lista_arata_starea_reala_nu_campul_status(self):
        carte, _ = workbench.salveaza_carte(date_carte(), self.bib)
        Book.objects.filter(pk=carte.pk).update(status=PublicationStatus.PUBLISHED)
        BookResource.objects.filter(edition__book=carte).update(
            rights_status=RightsStatus.UNKNOWN)
        self.client.force_login(self.bib)
        raspuns = self.client.get("/gestiune/")
        self.assertContains(raspuns, "Publicată, dar invizibilă")

    def test_filtrarea_dupa_stare(self):
        workbench.salveaza_carte(date_carte(), self.bib)
        workbench.salveaza_carte(
            date_carte(title="Fara autor", autori="", subiecte=""), self.bib)
        self.client.force_login(self.bib)
        gata = self.client.get("/gestiune/?stare=gata").content.decode()
        self.assertIn("Insula comorii", gata)
        self.assertNotIn("Fara autor", gata)

    def test_stergerea_cartii(self):
        carte, _ = workbench.salveaza_carte(date_carte(), self.bib)
        self.client.force_login(self.bib)
        self.client.post(f"/gestiune/carte/{carte.slug}/sterge/", follow=True)
        self.assertFalse(Book.objects.filter(pk=carte.pk).exists())

    def test_editarea_incarca_datele_existente(self):
        carte, _ = workbench.salveaza_carte(date_carte(), self.bib)
        self.client.force_login(self.bib)
        html = self.client.get(f"/gestiune/carte/{carte.slug}/").content.decode()
        self.assertIn("Robert Louis Stevenson", html)
        self.assertIn("Editura Test", html)


# ==========================================================================
# 6. Completarea automată
# ==========================================================================


class CompletareAutomataTest(BazaAtelier):
    def setUp(self):
        super().setUp()
        Author.objects.create(name="Jules Verne")
        Author.objects.create(name="Ion Creangă")
        Subject.objects.create(name="Aventură")

    def test_sugestiile_de_autori(self):
        self.client.force_login(self.bib)
        date = json.loads(self.client.get("/gestiune/autori/?q=ver").content)
        self.assertEqual([r["nume"] for r in date["rezultate"]], ["Jules Verne"])

    def test_cautarea_nu_tine_cont_de_majuscule(self):
        self.client.force_login(self.bib)
        date = json.loads(self.client.get("/gestiune/autori/?q=CREANG").content)
        self.assertEqual(len(date["rezultate"]), 1)

    def test_sugestiile_de_teme(self):
        self.client.force_login(self.bib)
        date = json.loads(self.client.get("/gestiune/teme/?q=aven").content)
        self.assertEqual([r["nume"] for r in date["rezultate"]], ["Aventură"])

    def test_sugestiile_sunt_rezervate_bibliotecarului(self):
        self.assertEqual(self.client.get("/gestiune/autori/").status_code, 403)
        self.client.force_login(self.elev)
        self.assertEqual(self.client.get("/gestiune/teme/").status_code, 403)

    def test_interogarea_fara_potrivire_da_lista_goala(self):
        self.client.force_login(self.bib)
        date = json.loads(self.client.get("/gestiune/autori/?q=zzzz").content)
        self.assertEqual(date["rezultate"], [])


# ==========================================================================
# 7. Gestiunea utilizatorilor
# ==========================================================================


class UtilizatoriTest(BazaAtelier):
    def test_pagina_listeaza_conturile(self):
        self.client.force_login(self.bib)
        raspuns = self.client.get("/accounts/gestiune/utilizatori/")
        self.assertContains(raspuns, "elev")
        self.assertContains(raspuns, "prof")

    def test_crearea_unui_cont(self):
        self.client.force_login(self.bib)
        self.client.post("/accounts/gestiune/utilizatori/nou/", {
            "username": "elev.nou", "email": "a@b.ro",
            "first_name": "Ana", "last_name": "Pop",
            "role": User.Role.STUDENT, "is_active": "on",
            "parola": PAROLA}, follow=True)
        u = User.objects.get(username="elev.nou")
        self.assertEqual(u.first_name, "Ana")
        self.assertTrue(u.check_password(PAROLA))
        self.assertTrue(hasattr(u, "profile"))

    def test_contul_nou_cere_parola(self):
        self.client.force_login(self.bib)
        raspuns = self.client.post("/accounts/gestiune/utilizatori/nou/", {
            "username": "fara.parola", "email": "", "first_name": "",
            "last_name": "", "role": User.Role.STUDENT, "is_active": "on",
            "parola": ""})
        self.assertEqual(raspuns.status_code, 200)
        self.assertFalse(User.objects.filter(username="fara.parola").exists())

    def test_editarea_schimba_rolul(self):
        self.client.force_login(self.bib)
        self.client.post(f"/accounts/gestiune/utilizatori/{self.elev.pk}/salveaza/", {
            "username": "elev", "email": "", "first_name": "", "last_name": "",
            "role": User.Role.TEACHER, "is_active": "on", "parola": ""}, follow=True)
        self.elev.refresh_from_db()
        self.assertEqual(self.elev.role, User.Role.TEACHER)

    def test_parola_goala_la_editare_pastreaza_parola_veche(self):
        self.client.force_login(self.bib)
        self.client.post(f"/accounts/gestiune/utilizatori/{self.elev.pk}/salveaza/", {
            "username": "elev", "email": "nou@scoala.ro", "first_name": "",
            "last_name": "", "role": User.Role.STUDENT, "is_active": "on",
            "parola": ""}, follow=True)
        self.elev.refresh_from_db()
        self.assertTrue(self.elev.check_password(PAROLA))
        self.assertEqual(self.elev.email, "nou@scoala.ro")

    def test_dezactivarea_unui_cont(self):
        self.client.force_login(self.bib)
        self.client.post(f"/accounts/gestiune/utilizatori/{self.elev.pk}/salveaza/", {
            "username": "elev", "email": "", "first_name": "", "last_name": "",
            "role": User.Role.STUDENT, "parola": ""}, follow=True)
        self.elev.refresh_from_db()
        self.assertFalse(self.elev.is_active)

    def test_nu_isi_poate_schimba_propriul_rol(self):
        self.client.force_login(self.bib)
        self.client.post(f"/accounts/gestiune/utilizatori/{self.bib.pk}/salveaza/", {
            "username": "bib", "email": "", "first_name": "", "last_name": "",
            "role": User.Role.STUDENT, "is_active": "on", "parola": ""}, follow=True)
        self.bib.refresh_from_db()
        self.assertEqual(self.bib.role, User.Role.LIBRARIAN)

    def test_nu_isi_poate_dezactiva_propriul_cont(self):
        self.client.force_login(self.bib)
        self.client.post(f"/accounts/gestiune/utilizatori/{self.bib.pk}/salveaza/", {
            "username": "bib", "email": "", "first_name": "", "last_name": "",
            "role": User.Role.LIBRARIAN, "parola": ""}, follow=True)
        self.bib.refresh_from_db()
        self.assertTrue(self.bib.is_active)

    def test_nu_se_poate_sterge_pe_sine(self):
        self.client.force_login(self.bib)
        self.client.post(f"/accounts/gestiune/utilizatori/{self.bib.pk}/sterge/",
                         follow=True)
        self.assertTrue(User.objects.filter(pk=self.bib.pk).exists())

    def test_stergerea_altui_cont(self):
        self.client.force_login(self.bib)
        self.client.post(f"/accounts/gestiune/utilizatori/{self.elev.pk}/sterge/",
                         follow=True)
        self.assertFalse(User.objects.filter(pk=self.elev.pk).exists())

    def test_formularul_nu_expune_indicatorii_tehnici(self):
        from apps.accounts.forms import FormularUtilizator
        campuri = set(FormularUtilizator().fields)
        self.assertNotIn("is_superuser", campuri)
        self.assertNotIn("is_staff", campuri)
        self.assertNotIn("user_permissions", campuri)
        self.assertNotIn("groups", campuri)

    def test_filtrarea_dupa_rol(self):
        self.client.force_login(self.bib)
        html = self.client.get(
            "/accounts/gestiune/utilizatori/?rol=TEACHER").content.decode()
        self.assertIn("prof", html)
        self.assertNotIn(">elev<", html)


# ==========================================================================
# 8. Navigarea
# ==========================================================================


class NavigareAtelierTest(BazaAtelier):
    def test_bibliotecarul_vede_ambele_sectiuni(self):
        self.client.force_login(self.bib)
        html = self.client.get("/gestiune/").content.decode()
        self.assertIn("/gestiune/", html)
        self.assertIn("/accounts/gestiune/utilizatori/", html)

    def test_elevul_nu_vede_legaturile(self):
        self.client.force_login(self.elev)
        html = self.client.get("/").content.decode()
        self.assertNotIn("/accounts/gestiune/utilizatori/", html)
        self.assertNotIn('href="/gestiune/"', html)

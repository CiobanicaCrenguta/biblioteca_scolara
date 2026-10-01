# -*- coding: utf-8 -*-
"""Logica atelierului bibliotecarului.

Fișierul acesta este separat de `services.py` tocmai ca regulile de publicare
să rămână neatinse. Aici stă doar ce ține de introducerea datelor dintr-un
singur formular: recunoașterea autorilor, salvarea în lanț a operei, ediției și
resursei, și descrierea sinceră a stării unei cărți.
"""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from . import services
from .models import (
    Author,
    Book,
    BookEdition,
    BookResource,
    PublicationStatus,
    RightsStatus,
    Subject,
)

SEPARATOR = ","


def desparte_nume(text):
    """„Ion Creangă, Mihai Eminescu” devine o listă curată, fără duplicate."""
    if not text:
        return []
    vazute, rezultat = set(), []
    for bucata in text.split(SEPARATOR):
        nume = " ".join(bucata.split())
        if not nume:
            continue
        cheie = nume.casefold()
        if cheie in vazute:
            continue
        vazute.add(cheie)
        rezultat.append(nume)
    return rezultat


def _potriveste(model, nume):
    """Caută fără să țină cont de majuscule, ca să nu apară duplicate."""
    existent = model.objects.filter(name__iexact=nume).first()
    if existent:
        return existent, False
    return model.objects.create(name=nume), True


def rezolva_autori(nume_list):
    autori, create = [], []
    for nume in nume_list:
        autor, nou = _potriveste(Author, nume)
        autori.append(autor)
        if nou:
            create.append(autor.name)
    return autori, create


def rezolva_subiecte(nume_list):
    subiecte, create = [], []
    for nume in nume_list:
        subiect, nou = _potriveste(Subject, nume)
        subiecte.append(subiect)
        if nou:
            create.append(subiect.name)
    return subiecte, create


def cauta(model, interogare, limita=8):
    """Sugestiile pentru completarea automată."""
    interogare = (interogare or "").strip()
    qs = model.objects.all()
    if interogare:
        qs = qs.filter(name__icontains=interogare)
    return list(qs.order_by("name")[:limita])


# --------------------------------------------------------------------------
# Salvarea într-un singur pas
# --------------------------------------------------------------------------


@transaction.atomic
def salveaza_carte(date, actor, carte=None):
    """Creează sau actualizează opera împreună cu ediția și resursa principală.

    Un singur formular acoperă tot lanțul. Fără asta, bibliotecarul ar trebui
    să treacă prin patru pagini diferite ca să adauge o carte.
    """
    if not actor.is_librarian:
        raise PermissionDenied("Doar bibliotecarul administrează catalogul.")

    creata = carte is None
    if creata:
        carte = Book()

    carte.title = date["title"].strip()
    carte.description = date.get("description", "")
    carte.recommended_age = date.get("recommended_age", "")
    carte.original_language = date.get("original_language") or "ro"
    carte.first_publish_year = date.get("first_publish_year")
    carte.featured = bool(date.get("featured"))
    if creata:
        carte.source_name = "manual"
    carte.save()

    autori, autori_noi = rezolva_autori(desparte_nume(date.get("autori", "")))
    subiecte, subiecte_noi = rezolva_subiecte(desparte_nume(date.get("subiecte", "")))
    carte.authors.set(autori)
    carte.subjects.set(subiecte)

    editie = carte.editions.filter(is_primary=True).first() or BookEdition(book=carte)
    editie.book = carte
    editie.language = date.get("editie_limba") or "ro"
    editie.publisher = date.get("editie_editura", "")
    editie.publication_year = date.get("editie_an")
    editie.isbn_13 = date.get("editie_isbn", "")
    editie.cover_url = date.get("editie_coperta", "")
    editie.is_primary = True
    editie.save()

    resursa = editie.resources.filter(is_primary=True).first() or BookResource(edition=editie)
    resursa.edition = editie
    resursa.format = date.get("resursa_format") or BookResource.Format.PDF
    resursa.storage_type = date.get("resursa_stocare") or BookResource.Storage.LOCAL
    if resursa.storage_type == BookResource.Storage.EXTERNAL:
        resursa.external_url = date.get("resursa_link", "")
        resursa.source_url = date.get("resursa_link", "")
    else:
        fisier = date.get("resursa_fisier")
        if fisier:
            resursa.file = fisier
        resursa.external_url = ""
    resursa.total_pages = date.get("resursa_pagini")
    resursa.license_name = date.get("licenta_nume", "")
    resursa.license_url = date.get("licenta_url", "")
    if date.get("licenta_sursa"):
        resursa.source_url = date["licenta_sursa"]
    resursa.is_primary = True
    resursa.is_active = True

    # Verificarea drepturilor rămâne o decizie explicită a bibliotecarului.
    if date.get("drepturi_verificate"):
        if resursa.rights_status != RightsStatus.VERIFIED:
            resursa.rights_status = RightsStatus.VERIFIED
            resursa.rights_verified_at = timezone.now()
            resursa.rights_verified_by = actor
    else:
        resursa.rights_status = RightsStatus.UNKNOWN
        resursa.rights_verified_at = None
        resursa.rights_verified_by = None
    resursa.save()

    return carte, {"autori_noi": autori_noi, "subiecte_noi": subiecte_noi,
                   "creata": creata}


@transaction.atomic
def sterge_carte(carte, actor):
    if not actor.is_librarian:
        raise PermissionDenied("Doar bibliotecarul administrează catalogul.")
    titlu = carte.title
    carte.delete()
    return titlu


# --------------------------------------------------------------------------
# Starea reală a unei cărți
# --------------------------------------------------------------------------

ETICHETE = {
    "vizibila": ("Vizibilă în catalog", "ok"),
    "ascunsa": ("Publicată, dar invizibilă", "alarma"),
    "gata": ("Gata de publicare", "asteptare"),
    "incompleta": ("Incompletă", "neutru"),
    "arhivata": ("Arhivată", "neutru"),
}


def situatie(carte):
    """Ce vede cu adevărat un elev, nu doar ce scrie în câmpul `status`.

    O carte poate avea starea PUBLISHED și totuși să lipsească din catalog,
    dacă resursa ei nu are drepturile verificate. Afișarea stării brute ar
    ascunde exact problema pe care bibliotecarul trebuie să o rezolve.
    """
    probleme = services.validate_for_publication(carte)
    are_continut = services.usable_resources(carte).exists()

    if carte.status == PublicationStatus.ARCHIVED:
        cheie = "arhivata"
    elif carte.status == PublicationStatus.PUBLISHED and are_continut:
        cheie = "vizibila"
    elif carte.status == PublicationStatus.PUBLISHED:
        cheie = "ascunsa"
    elif not probleme:
        cheie = "gata"
    else:
        cheie = "incompleta"

    eticheta, ton = ETICHETE[cheie]
    return {
        "cheie": cheie,
        "eticheta": eticheta,
        "ton": ton,
        "probleme": probleme,
        "vizibila": cheie == "vizibila",
    }

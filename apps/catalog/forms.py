# -*- coding: utf-8 -*-
"""Formularele atelierului bibliotecarului."""

from django import forms

from .models import Book, BookResource


class FormularCarte(forms.Form):
    """Un singur formular pentru operă, ediție și resursă.

    Nu este ModelForm pentru că acoperă trei modele deodată. Validarea
    încrucișată dintre tipul de stocare și conținutul efectiv se face în
    `clean()`.
    """

    title = forms.CharField(
        label="Titlul cărții", max_length=300,
        widget=forms.TextInput(attrs={"placeholder": "Insula comorii"}))
    autori = forms.CharField(
        label="Autori", required=False,
        help_text="Scrie un nume și apasă Enter. Alege din sugestii sau adaugă unul nou.",
        widget=forms.TextInput(attrs={"data-completare": "autori"}))
    subiecte = forms.CharField(
        label="Teme", required=False,
        help_text="Aceleași reguli ca la autori.",
        widget=forms.TextInput(attrs={"data-completare": "subiecte"}))
    description = forms.CharField(
        label="Descriere", required=False,
        widget=forms.Textarea(attrs={"rows": 4}))
    recommended_age = forms.ChoiceField(
        label="Vârsta recomandată", required=False,
        choices=[("", "Nu este stabilită")] + list(Book.AgeGroup.choices))
    original_language = forms.CharField(
        label="Limba operei", required=False, max_length=8, initial="ro")
    first_publish_year = forms.IntegerField(
        label="Anul primei apariții", required=False, min_value=1, max_value=2100)
    featured = forms.BooleanField(
        label="Pune cartea în selecția bibliotecarului", required=False)

    editie_limba = forms.CharField(
        label="Limba ediției", required=False, max_length=8, initial="ro")
    editie_editura = forms.CharField(label="Editura", required=False, max_length=200)
    editie_an = forms.IntegerField(
        label="Anul ediției", required=False, min_value=1, max_value=2100)
    editie_isbn = forms.CharField(label="ISBN", required=False, max_length=13)
    editie_coperta = forms.URLField(label="Adresa copertei", required=False)

    resursa_format = forms.ChoiceField(
        label="Formatul textului", choices=BookResource.Format.choices,
        initial=BookResource.Format.PDF)
    resursa_stocare = forms.ChoiceField(
        label="De unde vine textul", choices=BookResource.Storage.choices,
        initial=BookResource.Storage.LOCAL)
    resursa_fisier = forms.FileField(label="Fișierul cărții", required=False)
    resursa_link = forms.URLField(label="Adresa externă", required=False)
    resursa_pagini = forms.IntegerField(
        label="Număr de pagini", required=False, min_value=1,
        help_text="Completat, cititorul calculează singur procentul.")

    licenta_nume = forms.CharField(
        label="Licența", required=False, max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Domeniu public"}))
    licenta_url = forms.URLField(label="Adresa licenței", required=False)
    licenta_sursa = forms.URLField(label="Sursa textului", required=False)
    drepturi_verificate = forms.BooleanField(
        label="Am verificat că avem dreptul să distribuim acest text",
        required=False,
        help_text="Fără această confirmare, cartea nu poate fi publicată.")

    def __init__(self, *args, **kwargs):
        self.are_fisier = kwargs.pop("are_fisier", False)
        super().__init__(*args, **kwargs)

    def clean(self):
        date = super().clean()
        stocare = date.get("resursa_stocare")

        if stocare == BookResource.Storage.EXTERNAL:
            if not date.get("resursa_link"):
                self.add_error("resursa_link",
                               "Pentru o resursă externă trebuie completată adresa.")
        elif stocare == BookResource.Storage.LOCAL:
            if not date.get("resursa_fisier") and not self.are_fisier:
                self.add_error("resursa_fisier",
                               "Încarcă fișierul sau alege stocarea externă.")

        if date.get("drepturi_verificate") and not date.get("licenta_nume"):
            self.add_error("licenta_nume",
                           "Notează licența pe baza căreia ai verificat drepturile.")
        return date

    @classmethod
    def din_carte(cls, carte):
        """Completează formularul cu datele unei cărți existente."""
        editie = carte.editions.filter(is_primary=True).first()
        resursa = editie.resources.filter(is_primary=True).first() if editie else None
        initial = {
            "title": carte.title,
            "autori": ", ".join(a.name for a in carte.authors.all()),
            "subiecte": ", ".join(s.name for s in carte.subjects.all()),
            "description": carte.description,
            "recommended_age": carte.recommended_age,
            "original_language": carte.original_language,
            "first_publish_year": carte.first_publish_year,
            "featured": carte.featured,
        }
        if editie:
            initial.update({
                "editie_limba": editie.language,
                "editie_editura": editie.publisher,
                "editie_an": editie.publication_year,
                "editie_isbn": editie.isbn_13,
                "editie_coperta": editie.cover_url,
            })
        if resursa:
            initial.update({
                "resursa_format": resursa.format,
                "resursa_stocare": resursa.storage_type,
                "resursa_link": resursa.external_url,
                "resursa_pagini": resursa.total_pages,
                "licenta_nume": resursa.license_name,
                "licenta_url": resursa.license_url,
                "licenta_sursa": resursa.source_url,
                "drepturi_verificate": resursa.rights_status == "VERIFIED",
            })
        return cls(initial=initial, are_fisier=bool(resursa and resursa.file))

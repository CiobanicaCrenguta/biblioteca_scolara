from django.conf import settings
from django.db import models
from django.utils.text import slugify


class PublicationStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    RIGHTS_REVIEW = "RIGHTS_REVIEW", "Verificare drepturi"
    READY = "READY", "Pregătită"
    PUBLISHED = "PUBLISHED", "Publicată"
    ARCHIVED = "ARCHIVED", "Arhivată"


class RightsStatus(models.TextChoices):
    UNKNOWN = "UNKNOWN", "Neverificat"
    VERIFIED = "VERIFIED", "Verificat"
    REJECTED = "REJECTED", "Respins"


class Subject(models.Model):
    """Listă controlată de subiecte. Fără 'science' / 'Științe' / 'stiinta' în paralel."""

    class Kind(models.TextChoices):
        GENRE = "GENRE", "Gen"
        TOPIC = "TOPIC", "Temă"
        EDUCATIONAL = "EDUCATIONAL", "Arie educațională"

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.GENRE)

    class Meta:
        ordering = ["name"]
        verbose_name = "temă"
        verbose_name_plural = "teme"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Author(models.Model):
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=220, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "autor"
        verbose_name_plural = "autori"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:220]
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Book(models.Model):
    """Opera în sens abstract, independent de ediție sau format."""

    class AgeGroup(models.TextChoices):
        A7_9 = "7-9", "7-9 ani"
        A10_12 = "10-12", "10-12 ani"
        A13_15 = "13-15", "13-15 ani"
        A16_18 = "16-18", "16-18 ani"
        ADULT = "ADULT", "Adult"

    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=320, unique=True)
    description = models.TextField(blank=True)
    authors = models.ManyToManyField(Author, related_name="books", blank=True)
    subjects = models.ManyToManyField(Subject, related_name="books", blank=True)
    original_language = models.CharField(max_length=8, default="ro")
    first_publish_year = models.PositiveIntegerField(null=True, blank=True)
    recommended_age = models.CharField(
        max_length=8, choices=AgeGroup.choices, blank=True
    )
    status = models.CharField(
        max_length=16, choices=PublicationStatus.choices, default=PublicationStatus.DRAFT
    )
    featured = models.BooleanField(default=False, help_text="Selecția bibliotecarului")
    source_name = models.CharField(max_length=80, blank=True)
    external_id = models.CharField(max_length=120, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        verbose_name = "carte"
        verbose_name_plural = "cărți"
        constraints = [
            models.UniqueConstraint(
                fields=["source_name", "external_id"],
                condition=~models.Q(external_id=""),
                name="uniq_book_external_source",
            )
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:300] or "carte"
            slug, i = base, 2
            while Book.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def is_published(self) -> bool:
        return self.status == PublicationStatus.PUBLISHED

    @property
    def cover_theme(self) -> int:
        """Gradient determinist pentru cărțile fără copertă. Același titlu,
        aceeași culoare, la fiecare încărcare."""
        return sum(ord(c) for c in self.slug) % 6

    @property
    def cover_url(self) -> str:
        edition = self.editions.filter(cover_url__gt="").first()
        return edition.cover_url if edition else ""

    @property
    def author_names(self) -> str:
        return ", ".join(a.name for a in self.authors.all())

    def __str__(self) -> str:
        return self.title


class BookEdition(models.Model):
    """O anumită ediție sau traducere. Previne duplicarea operei."""

    book = models.ForeignKey(Book, related_name="editions", on_delete=models.CASCADE)
    title = models.CharField(max_length=300, blank=True)
    language = models.CharField(max_length=8, default="ro")
    publisher = models.CharField(max_length=200, blank=True)
    publication_year = models.PositiveIntegerField(null=True, blank=True)
    isbn_10 = models.CharField(max_length=10, blank=True)
    isbn_13 = models.CharField(max_length=13, blank=True)
    cover_url = models.URLField(blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_primary", "publication_year"]
        verbose_name = "ediție"
        verbose_name_plural = "ediții"

    def __str__(self) -> str:
        return f"{self.title or self.book.title} [{self.language}]"


class BookResource(models.Model):
    """Fișierul sau linkul care poate fi citit efectiv."""

    class Format(models.TextChoices):
        PDF = "PDF", "PDF"
        EPUB = "EPUB", "EPUB"
        HTML = "HTML", "HTML"
        TXT = "TXT", "Text"
        EXTERNAL = "EXTERNAL", "Link extern"

    class Storage(models.TextChoices):
        LOCAL = "LOCAL", "Fișier local"
        EXTERNAL = "EXTERNAL", "URL extern"

    edition = models.ForeignKey(
        BookEdition, related_name="resources", on_delete=models.CASCADE
    )
    format = models.CharField(max_length=16, choices=Format.choices)
    storage_type = models.CharField(
        max_length=16, choices=Storage.choices, default=Storage.LOCAL
    )
    file = models.FileField(upload_to="books/", blank=True)
    external_url = models.URLField(blank=True)
    mime_type = models.CharField(max_length=80, blank=True)
    total_pages = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Numărul total de pagini. Permite calculul automat al procentului.",
    )
    file_size = models.PositiveBigIntegerField(null=True, blank=True)
    checksum_sha256 = models.CharField(max_length=64, blank=True)

    is_active = models.BooleanField(default=True)
    is_primary = models.BooleanField(default=False)

    rights_status = models.CharField(
        max_length=16, choices=RightsStatus.choices, default=RightsStatus.UNKNOWN
    )
    license_name = models.CharField(max_length=120, blank=True)
    license_url = models.URLField(blank=True)
    source_url = models.URLField(blank=True)
    rights_verified_at = models.DateTimeField(null=True, blank=True)
    rights_verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="verified_resources",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "id"]
        verbose_name = "resursă"
        verbose_name_plural = "resurse"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(storage_type="LOCAL", external_url="")
                    | models.Q(storage_type="EXTERNAL")
                ),
                name="resource_storage_coherent",
            )
        ]

    @property
    def is_usable(self) -> bool:
        return self.is_active and self.rights_status == RightsStatus.VERIFIED

    @property
    def is_readable_inline(self) -> bool:
        return self.storage_type == self.Storage.LOCAL and bool(self.file)

    def __str__(self) -> str:
        return f"{self.edition} · {self.format}"

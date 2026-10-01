from django.conf import settings
from django.db import models
from django.utils.text import slugify


class ListStatus(models.TextChoices):
    DRAFT = "DRAFT", "Ciornă"
    PUBLISHED = "PUBLISHED", "Publicată"
    ARCHIVED = "ARCHIVED", "Arhivată"


class ReadingList(models.Model):
    """Listă tematică alcătuită de un profesor. Vizibilă tuturor după publicare."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reading_lists",
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    description = models.TextField(blank=True)
    target_age_group = models.CharField(
        max_length=8, choices=[
            ("7-9", "7-9 ani"),
            ("10-12", "10-12 ani"),
            ("13-15", "13-15 ani"),
            ("16-18", "16-18 ani"),
            ("ADULT", "Adult"),
        ],
        blank=True,
    )
    status = models.CharField(
        max_length=16, choices=ListStatus.choices, default=ListStatus.DRAFT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "listă de lectură"
        verbose_name_plural = "liste de lectură"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200] or "lista"
            slug, i = base, 2
            while ReadingList.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def is_published(self) -> bool:
        return self.status == ListStatus.PUBLISHED

    def next_position(self) -> int:
        last = self.items.aggregate(models.Max("position"))["position__max"]
        return (last or 0) + 1

    def __str__(self) -> str:
        return self.title


class ReadingListItem(models.Model):
    reading_list = models.ForeignKey(
        ReadingList, related_name="items", on_delete=models.CASCADE
    )
    book = models.ForeignKey("catalog.Book", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=1)
    teacher_note = models.TextField(blank=True)

    class Meta:
        ordering = ["position"]
        verbose_name = "titlu din listă"
        verbose_name_plural = "titluri din listă"
        constraints = [
            models.UniqueConstraint(
                fields=["reading_list", "book"], name="uniq_list_book"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.position}. {self.book.title}"

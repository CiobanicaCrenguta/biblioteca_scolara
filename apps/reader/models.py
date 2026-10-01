from django.conf import settings
from django.db import models


class UserBookState(models.Model):
    """Relația utilizatorului cu opera. O singură înregistrare per pereche."""

    class Status(models.TextChoices):
        WANT_TO_READ = "WANT_TO_READ", "Vreau să citesc"
        READING = "READING", "Citesc acum"
        FINISHED = "FINISHED", "Terminată"
        ABANDONED = "ABANDONED", "Abandonată"

    class Reaction(models.TextChoices):
        LIKE = "LIKE", "Mi-a plăcut"
        NEUTRAL = "NEUTRAL", "Neutru"
        DISLIKE = "DISLIKE", "Nu mi-a plăcut"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="book_states"
    )
    book = models.ForeignKey(
        "catalog.Book", on_delete=models.CASCADE, related_name="user_states"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.WANT_TO_READ
    )
    reaction = models.CharField(max_length=8, choices=Reaction.choices, blank=True)
    saved_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "stare de lectură"
        verbose_name_plural = "stări de lectură"
        constraints = [
            models.UniqueConstraint(fields=["user", "book"], name="uniq_user_book_state")
        ]

    def __str__(self) -> str:
        return f"{self.user.username} · {self.book.title} · {self.get_status_display()}"


class ReadingProgress(models.Model):
    """Poziția în fișier. Separată de stare: aceeași carte, formate diferite."""

    class LocationType(models.TextChoices):
        PAGE = "page", "Pagină"
        PERCENTAGE = "percentage", "Procent"
        CHAPTER = "chapter", "Capitol"
        CFI = "epubcfi", "EPUB CFI"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="progress"
    )
    resource = models.ForeignKey(
        "catalog.BookResource", on_delete=models.CASCADE, related_name="progress"
    )
    location_type = models.CharField(
        max_length=16, choices=LocationType.choices, default=LocationType.PAGE
    )
    location_value = models.CharField(max_length=120, default="1")
    percentage = models.FloatField(default=0)

    # Contoare de sesiune. Spre deosebire de restul statisticilor, care se
    # calculează la cerere din raft, o sesiune de lectură nu poate fi dedusă
    # ulterior: rândul păstrează doar ultima poziție, nu istoricul salvărilor.
    session_count = models.PositiveIntegerField(
        default=0, help_text="Câte sesiuni distincte de lectură au avut loc.")
    total_reading_minutes = models.PositiveIntegerField(
        default=0, help_text="Minute de lectură estimate din intervalele dintre salvări.")
    last_session_at = models.DateTimeField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "resource"], name="uniq_user_resource_progress"
            ),
            models.CheckConstraint(
                condition=models.Q(percentage__gte=0) & models.Q(percentage__lte=100),
                name="progress_percentage_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} · {self.resource} · {self.percentage:.0f}%"


class InteractionEvent(models.Model):
    """Semnale pentru recomandări. Nu se înregistrează fiecare scroll."""

    class Type(models.TextChoices):
        BOOK_SAVED = "BOOK_SAVED", "Salvată"
        READING_STARTED = "READING_STARTED", "Începută"
        READING_FINISHED = "READING_FINISHED", "Terminată"
        BOOK_LIKED = "BOOK_LIKED", "Apreciată"
        BOOK_DISLIKED = "BOOK_DISLIKED", "Respinsă"
        BOOK_REMOVED = "BOOK_REMOVED", "Scoasă din raft"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="events"
    )
    book = models.ForeignKey("catalog.Book", on_delete=models.CASCADE)
    event_type = models.CharField(max_length=24, choices=Type.choices)
    value = models.FloatField(default=1.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "eveniment de interacțiune"
        verbose_name_plural = "evenimente de interacțiune"
        indexes = [models.Index(fields=["user", "event_type"])]

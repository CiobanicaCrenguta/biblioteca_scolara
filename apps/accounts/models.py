from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = "STUDENT", "Student"
        TEACHER = "TEACHER", "Profesor"
        LIBRARIAN = "LIBRARIAN", "Bibliotecar"

    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STUDENT)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_librarian(self) -> bool:
        return self.role == self.Role.LIBRARIAN or self.is_superuser

    @property
    def can_curate(self) -> bool:
        """Poate crea liste educaționale."""
        return self.role in {self.Role.TEACHER, self.Role.LIBRARIAN} or self.is_superuser

    def __str__(self) -> str:
        return f"{self.username} ({self.get_role_display()})"


class UserProfile(models.Model):
    class AgeGroup(models.TextChoices):
        A7_9 = "7-9", "7-9 ani"
        A10_12 = "10-12", "10-12 ani"
        A13_15 = "13-15", "13-15 ani"
        A16_18 = "16-18", "16-18 ani"
        ADULT = "ADULT", "Adult"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    age_group = models.CharField(
        max_length=8, choices=AgeGroup.choices, blank=True
    )
    preferred_language = models.CharField(max_length=8, default="ro")
    preferred_subjects = models.ManyToManyField(
        "catalog.Subject",
        blank=True,
        related_name="interested_profiles",
        help_text="Selecțiile din onboarding. Semnal de pornire pentru recomandări.",
    )
    onboarding_completed = models.BooleanField(default=False)
    personalization_enabled = models.BooleanField(default=True)
    privacy_acknowledged_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Profil {self.user.username}"

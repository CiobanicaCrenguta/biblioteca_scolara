"""Date de test. Rulează: python manage.py seed_demo"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog import services
from apps.catalog.models import (
    Author,
    Book,
    BookEdition,
    BookResource,
    RightsStatus,
    Subject,
)

User = get_user_model()

SUBJECTS = [
    ("Aventură", Subject.Kind.GENRE),
    ("Fantasy", Subject.Kind.GENRE),
    ("Mister", Subject.Kind.GENRE),
    ("Literatură română", Subject.Kind.EDUCATIONAL),
    ("Mitologie", Subject.Kind.TOPIC),
    ("Știință", Subject.Kind.EDUCATIONAL),
]

BOOKS = [
    {
        "title": "Amintiri din copilărie",
        "pages": 180,
        "author": "Ion Creangă",
        "subjects": ["Literatură română"],
        "age": "10-12",
        "year": 1892,
        "description": "Copilăria la Humulești, povestită de autorul însuși.",
        "url": "https://www.gutenberg.org/ebooks/45638",
        "license": "Domeniu public",
        "verified": True,
    },
    {
        "title": "Alice în Țara Minunilor",
        "pages": 160,
        "author": "Lewis Carroll",
        "subjects": ["Fantasy", "Aventură"],
        "age": "7-9",
        "year": 1865,
        "description": "O fetiță cade într-o vizuină de iepure și ajunge într-o lume absurdă.",
        "url": "https://www.gutenberg.org/ebooks/11",
        "license": "Domeniu public",
        "verified": True,
    },
    {
        "title": "Douăzeci de mii de leghe sub mări",
        "pages": 420,
        "author": "Jules Verne",
        "subjects": ["Aventură", "Știință"],
        "age": "10-12",
        "year": 1870,
        "description": "Expediția submarinului Nautilus, sub comanda căpitanului Nemo.",
        "url": "https://www.gutenberg.org/ebooks/164",
        "license": "Domeniu public",
        "verified": True,
    },
    {
        "title": "Poveşti nemuritoare",
        "pages": 240,
        "author": "Petre Ispirescu",
        "subjects": ["Literatură română", "Mitologie"],
        "age": "7-9",
        "year": 1882,
        "description": "Feți-Frumoși, zmei și tărâmuri de dincolo, adunate din basmele populare.",
        "url": "https://www.gutenberg.org/ebooks/48132",
        "license": "Domeniu public",
        "verified": True,
        "featured": True,
    },
    {
        "title": "Insula comorii",
        "pages": 290,
        "author": "Robert Louis Stevenson",
        "subjects": ["Aventură", "Mister"],
        "age": "10-12",
        "year": 1883,
        "description": "O hartă, o corabie și pirați care caută comoara căpitanului Flint.",
        "url": "https://www.gutenberg.org/ebooks/120",
        "license": "Domeniu public",
        "verified": True,
    },
    {
        "title": "Călătoriile lui Gulliver",
        "pages": 350,
        "author": "Jonathan Swift",
        "subjects": ["Aventură", "Fantasy"],
        "age": "13-15",
        "year": 1726,
        "description": "Naufragii, pitici, uriași și o satiră a societății engleze.",
        "url": "https://www.gutenberg.org/ebooks/829",
        "license": "Domeniu public",
        "verified": True,
    },
    {
        "title": "Originea speciilor",
        "pages": 560,
        "author": "Charles Darwin",
        "subjects": ["Știință"],
        "age": "16-18",
        "year": 1859,
        "description": "Teoria selecției naturale, expusă de autorul ei.",
        "url": "https://www.gutenberg.org/ebooks/1228",
        "license": "Domeniu public",
        "verified": True,
    },
    {
        "title": "Vrăjitorul din Oz",
        "pages": 150,
        "author": "L. Frank Baum",
        "subjects": ["Fantasy", "Aventură"],
        "age": "7-9",
        "year": 1900,
        "description": "Dorothy pornește pe drumul de cărămidă galbenă spre Orașul de Smarald.",
        "url": "https://www.gutenberg.org/ebooks/55",
        "license": "Domeniu public",
        "verified": True,
    },
    {
        # Rămâne nepublicată: resursa nu are drepturile verificate.
        "title": "Manual de fizică, clasa a VIII-a",
        "author": "Colectiv",
        "subjects": ["Știință"],
        "age": "13-15",
        "year": 2021,
        "description": "Exemplu de carte care nu poate fi publicată: drepturi neverificate.",
        "url": "https://example.org/manual-fizica",
        "license": "",
        "verified": False,
    },
]


class Command(BaseCommand):
    help = "Creează utilizatori, subiecte și câteva cărți demonstrative."

    @transaction.atomic
    def handle(self, *args, **options):
        librarian = self._user("bibliotecar", User.Role.LIBRARIAN, staff=True)
        self._user("profesor", User.Role.TEACHER)
        self._user("student", User.Role.STUDENT)

        subjects = {}
        for name, kind in SUBJECTS:
            subject, _ = Subject.objects.get_or_create(name=name, defaults={"kind": kind})
            subjects[name] = subject

        for row in BOOKS:
            author, _ = Author.objects.get_or_create(name=row["author"])
            book, created = Book.objects.get_or_create(
                title=row["title"],
                defaults={
                    "description": row["description"],
                    "first_publish_year": row["year"],
                    "recommended_age": row["age"],
                    "featured": row.get("featured", False),
                    "source_name": "seed",
                },
            )
            book.authors.add(author)
            book.subjects.set([subjects[s] for s in row["subjects"]])

            edition, _ = BookEdition.objects.get_or_create(
                book=book,
                language="ro",
                defaults={"publication_year": row["year"], "is_primary": True},
            )
            resource, _ = BookResource.objects.get_or_create(
                edition=edition,
                format=BookResource.Format.EXTERNAL,
                defaults={
                    "storage_type": BookResource.Storage.EXTERNAL,
                    "external_url": row["url"],
                    "source_url": row["url"],
                    "is_primary": True,
                    "total_pages": row.get("pages"),
                },
            )
            if row["verified"] and resource.rights_status != RightsStatus.VERIFIED:
                services.verify_rights(
                    resource, librarian, license_name=row["license"]
                )

            try:
                services.publish(book, librarian)
                self.stdout.write(self.style.SUCCESS(f"publicat: {book.title}"))
            except services.PublicationError as exc:
                self.stdout.write(
                    self.style.WARNING(f"nepublicat: {book.title} → {exc}")
                )

        self._seed_reading_list(librarian)
        self.stdout.write("\nConturi: bibliotecar / profesor / student, parolă: parola123")

    def _seed_reading_list(self, librarian):
        from apps.reading_lists import services as list_services
        from apps.reading_lists.models import ReadingList

        teacher = User.objects.get(username="profesor")
        if ReadingList.objects.filter(owner=teacher).exists():
            return

        reading_list = list_services.create_list(
            teacher,
            title="Aventuri pentru vacanța de vară",
            description="Cinci titluri care se citesc pe nerăsuflate.",
            target_age_group="10-12",
        )
        notes = {
            "Insula comorii": "Începeți cu asta, are cel mai bun ritm.",
            "Vrăjitorul din Oz": "Scurtă și potrivită pentru cei mai mici.",
            "Douăzeci de mii de leghe sub mări": "Are pasaje lungi, dar merită.",
        }
        for title, note in notes.items():
            book = Book.objects.filter(title=title, status="PUBLISHED").first()
            if book:
                list_services.add_book(reading_list, book, teacher, note=note)
        try:
            list_services.publish_list(reading_list, teacher)
            self.stdout.write(self.style.SUCCESS(f"listă publicată: {reading_list.title}"))
        except list_services.ReadingListError as exc:
            self.stdout.write(self.style.WARNING(str(exc)))

    def _user(self, username, role, staff=False):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"role": role, "is_staff": staff, "is_superuser": staff},
        )
        if created:
            user.set_password("parola123")
            user.save()
        from apps.accounts.models import UserProfile

        UserProfile.objects.get_or_create(user=user)
        return user

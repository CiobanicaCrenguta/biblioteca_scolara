from django.core.management.base import BaseCommand

from apps.recommendations import services


class Command(BaseCommand):
    help = "Reconstruiește matricea TF-IDF a cărților publicate."

    def handle(self, *args, **options):
        count = services.rebuild_index()
        self.stdout.write(self.style.SUCCESS(f"Index reconstruit: {count} cărți."))

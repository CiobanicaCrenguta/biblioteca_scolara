from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import librarian_required

from . import selectors, services
from .models import Book, Subject


def book_list(request):
    query = request.GET.get("q", "").strip()
    subject = request.GET.get("subject", "")
    books = selectors.search_books(query=query, subject_slug=subject)
    return render(
        request,
        "catalog/book_list.html",
        {
            "books": books,
            "query": query,
            "subject": subject,
            "subjects": Subject.objects.all(),
        },
    )


def book_detail(request, slug):
    book = get_object_or_404(
        Book.objects.prefetch_related("authors", "subjects", "editions__resources"),
        slug=slug,
    )
    visible = book.is_published or (
        request.user.is_authenticated and request.user.is_librarian
    )
    if not visible:
        from django.http import Http404

        raise Http404("Carte indisponibilă.")

    from apps.reader.models import UserBookState
    from apps.recommendations import services as rec_services

    state = None
    if request.user.is_authenticated:
        state = UserBookState.objects.filter(user=request.user, book=book).first()

    similar = rec_services.similar_to(book, limit=4) if book.is_published else []

    return render(
        request,
        "catalog/book_detail.html",
        {
            "book": book,
            "state": state,
            "similar": similar,
            "shelf_choices": UserBookState.Status.choices,
            "can_read": services.usable_resources(book).exists() and book.is_published,
            "problems": services.validate_for_publication(book)
            if request.user.is_authenticated and request.user.is_librarian
            else [],
        },
    )


@librarian_required
def review_queue(request):
    """Vechea coadă de publicare. Atelierul o acoperă integral, deci pagina
    rămâne doar ca rută documentată și arată aceeași listă, filtrată."""
    books = selectors.librarian_books().exclude(status="PUBLISHED")
    rows = [(b, services.validate_for_publication(b)) for b in books]
    return render(request, "catalog/review_queue.html", {"rows": rows})


@require_POST
@librarian_required
def publish_book(request, slug):
    book = get_object_or_404(Book, slug=slug)
    try:
        services.publish(book, request.user)
        messages.success(request, f"„{book.title}” a fost publicată.")
    except services.PublicationError as exc:
        for problem in exc.problems:
            messages.error(request, problem)
    return redirect("catalog:book_detail", slug=book.slug)


@require_POST
@librarian_required
def archive_book(request, slug):
    book = get_object_or_404(Book, slug=slug)
    services.archive(book, request.user)
    messages.success(request, f"„{book.title}” a fost arhivată.")
    return redirect("catalog:book_detail", slug=book.slug)


# ==========================================================================
# Atelierul bibliotecarului
# ==========================================================================

from django.core.exceptions import PermissionDenied  # noqa: E402
from django.http import JsonResponse  # noqa: E402

from . import workbench  # noqa: E402
from .forms import FormularCarte  # noqa: E402
from .models import Author, Subject  # noqa: E402


@librarian_required
def atelier(request, slug=None):
    """O singură pagină: lista cărților în stânga, formularul în dreapta."""
    carte = get_object_or_404(Book, slug=slug) if slug else None
    formular = FormularCarte.din_carte(carte) if carte else FormularCarte()
    return render(request, "catalog/atelier.html", _context(request, carte, formular))


def _context(request, carte, formular, filtru=None):
    filtru = filtru if filtru is not None else request.GET.get("stare", "")
    cautare = request.GET.get("q", "").strip()

    carti = selectors.librarian_books().order_by("-updated_at")
    if cautare:
        carti = carti.filter(title__icontains=cautare)

    randuri = []
    numaratoare = {"vizibila": 0, "ascunsa": 0, "gata": 0, "incompleta": 0, "arhivata": 0}
    for b in carti:
        stare = workbench.situatie(b)
        numaratoare[stare["cheie"]] += 1
        if not filtru or stare["cheie"] == filtru:
            randuri.append({"carte": b, "stare": stare})

    return {
        "randuri": randuri,
        "numaratoare": numaratoare,
        "filtru": filtru,
        "cautare": cautare,
        "carte": carte,
        "formular": formular,
        "situatie": workbench.situatie(carte) if carte else None,
        "sectiune": "carti",
    }


@require_POST
@librarian_required
def atelier_salveaza(request, slug=None):
    carte = get_object_or_404(Book, slug=slug) if slug else None
    are_fisier = False
    if carte:
        editie = carte.editions.filter(is_primary=True).first()
        resursa = editie.resources.filter(is_primary=True).first() if editie else None
        are_fisier = bool(resursa and resursa.file)

    formular = FormularCarte(request.POST, request.FILES, are_fisier=are_fisier)
    if not formular.is_valid():
        messages.error(request, "Formularul are câmpuri de corectat.")
        return render(request, "catalog/atelier.html",
                      _context(request, carte, formular))

    carte, raport = workbench.salveaza_carte(formular.cleaned_data, request.user, carte)
    detalii = []
    if raport["autori_noi"]:
        detalii.append("autori noi: " + ", ".join(raport["autori_noi"]))
    if raport["subiecte_noi"]:
        detalii.append("teme noi: " + ", ".join(raport["subiecte_noi"]))
    mesaj = "Cartea „%s” a fost %s." % (
        carte.title, "adăugată" if raport["creata"] else "actualizată")
    if detalii:
        mesaj += " " + "; ".join(detalii).capitalize() + "."
    messages.success(request, mesaj)
    return redirect("catalog:atelier_carte", slug=carte.slug)


@require_POST
@librarian_required
def atelier_sterge(request, slug):
    carte = get_object_or_404(Book, slug=slug)
    titlu = workbench.sterge_carte(carte, request.user)
    messages.success(request, "Cartea „%s” a fost ștearsă definitiv." % titlu)
    return redirect("catalog:atelier")


@librarian_required
def cauta_autori(request):
    nume = workbench.cauta(Author, request.GET.get("q", ""))
    return JsonResponse({"rezultate": [{"id": a.id, "nume": a.name} for a in nume]})


@librarian_required
def cauta_subiecte(request):
    nume = workbench.cauta(Subject, request.GET.get("q", ""))
    return JsonResponse({"rezultate": [{"id": s.id, "nume": s.name} for s in nume]})

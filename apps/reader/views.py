from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.catalog.models import Book

from . import services
from .models import ReadingProgress, UserBookState


@login_required
def read_book(request, slug):
    book = get_object_or_404(Book, slug=slug)
    resource = services.resolve_reading_resource(
        book, request.user, resource_id=request.GET.get("resource")
    )
    progress = ReadingProgress.objects.filter(
        user=request.user, resource=resource
    ).first()
    return render(
        request,
        "reader/read.html",
        {
            "book": book,
            "resource": resource,
            "progress": progress,
            "formats": services.readable_resources(book),
        },
    )


@login_required
def resource_content(request, resource_id):
    """Fișierul trece prin verificare, nu prin MEDIA_URL direct.

    as_attachment=False → browserul afișează fișierul în loc să-l descarce.
    Mime-type-ul se deduce din câmpul format dacă nu e completat explicit în BD.
    """
    _MIME = {
        "PDF":      "application/pdf",
        "EPUB":     "application/epub+zip",
        "HTML":     "text/html; charset=utf-8",
        "TXT":      "text/plain; charset=utf-8",
    }
    resource = services.get_resource_for_download(resource_id, request.user)
    mime = resource.mime_type or _MIME.get(resource.format, "application/octet-stream")
    return FileResponse(
        resource.file.open("rb"),
        content_type=mime,
        as_attachment=False,
    )


@login_required
@require_POST
def save_progress(request, resource_id):
    book = get_object_or_404(Book, slug=request.POST["book_slug"])
    resource = services.resolve_reading_resource(book, request.user, resource_id)
    services.save_progress(
        request.user,
        resource,
        location_value=request.POST.get("location", "1"),
        percentage=request.POST.get("percentage", 0),
        location_type=request.POST.get("location_type", "page"),
    )
    return JsonResponse({"saved": True})


@login_required
@require_POST
def set_state(request, slug):
    book = get_object_or_404(Book, slug=slug)
    services.set_book_state(request.user, book, request.POST["status"])
    return redirect("catalog:book_detail", slug=slug)


@login_required
@require_POST
def set_reaction(request, slug):
    book = get_object_or_404(Book, slug=slug)
    services.set_reaction(request.user, book, request.POST["reaction"])
    return redirect("catalog:book_detail", slug=slug)


@login_required
def my_library(request, shelf=None):
    qs = UserBookState.objects.filter(user=request.user).select_related("book")
    normalised = shelf.upper().replace("-", "_") if shelf else ""
    if normalised:
        if normalised not in UserBookState.Status.values:
            raise Http404("Raft necunoscut.")
        qs = qs.filter(status=normalised)
    return render(
        request,
        "reader/my_library.html",
        {"states": qs, "shelf": normalised, "statuses": UserBookState.Status.choices},
    )

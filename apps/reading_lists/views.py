from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import curator_required
from apps.catalog.models import Book
from apps.catalog.selectors import published_books

from . import selectors, services
from .forms import ReadingListForm
from .models import ReadingList


def list_index(request):
    return render(
        request,
        "reading_lists/index.html",
        {
            "lists": selectors.published_lists(),
            "mine": selectors.lists_owned_by(request.user),
        },
    )


def detail(request, slug):
    reading_list = get_object_or_404(
        ReadingList.objects.select_related("owner").prefetch_related("items__book"),
        slug=slug,
    )
    if not services.can_view(reading_list, request.user):
        raise Http404("Listă indisponibilă.")
    return render(
        request,
        "reading_lists/detail.html",
        {
            "list": reading_list,
            "can_edit": services.can_edit(reading_list, request.user),
        },
    )


@curator_required
def create(request):
    if request.method == "POST":
        form = ReadingListForm(request.POST)
        if form.is_valid():
            reading_list = services.create_list(
                request.user,
                title=form.cleaned_data["title"],
                description=form.cleaned_data["description"],
                target_age_group=form.cleaned_data["target_age_group"],
            )
            messages.success(request, "Listă creată. Adaugă titluri.")
            return redirect("reading_lists:edit", slug=reading_list.slug)
    else:
        form = ReadingListForm()
    return render(request, "reading_lists/form.html", {"form": form})


@curator_required
def edit(request, slug):
    reading_list = get_object_or_404(ReadingList, slug=slug)
    services.assert_can_edit(reading_list, request.user)

    if request.method == "POST":
        form = ReadingListForm(request.POST, instance=reading_list)
        if form.is_valid():
            form.save()
            messages.success(request, "Detaliile listei au fost salvate.")
            return redirect("reading_lists:edit", slug=reading_list.slug)
    else:
        form = ReadingListForm(instance=reading_list)

    chosen = reading_list.items.values_list("book_id", flat=True)
    return render(
        request,
        "reading_lists/edit.html",
        {
            "list": reading_list,
            "form": form,
            "candidates": published_books().exclude(id__in=chosen).order_by("title"),
        },
    )


@require_POST
@curator_required
def add_item(request, slug):
    reading_list = get_object_or_404(ReadingList, slug=slug)
    book = get_object_or_404(Book, pk=request.POST.get("book"))
    try:
        services.add_book(
            reading_list, book, request.user, note=request.POST.get("note", "")
        )
        messages.success(request, f"„{book.title}” a fost adăugată.")
    except services.ReadingListError as exc:
        messages.error(request, str(exc))
    return redirect("reading_lists:edit", slug=slug)


@require_POST
@curator_required
def remove_item(request, slug):
    reading_list = get_object_or_404(ReadingList, slug=slug)
    book = get_object_or_404(Book, pk=request.POST.get("book"))
    services.remove_book(reading_list, book, request.user)
    messages.success(request, f"„{book.title}” a fost scoasă din listă.")
    return redirect("reading_lists:edit", slug=slug)


@require_POST
@curator_required
def move(request, slug):
    reading_list = get_object_or_404(ReadingList, slug=slug)
    services.move_item(
        reading_list,
        int(request.POST["item"]),
        request.POST.get("direction", "up"),
        request.user,
    )
    return redirect("reading_lists:edit", slug=slug)


@require_POST
@curator_required
def publish(request, slug):
    reading_list = get_object_or_404(ReadingList, slug=slug)
    try:
        services.publish_list(reading_list, request.user)
        messages.success(request, "Lista este vizibilă pentru toți.")
    except services.ReadingListError as exc:
        messages.error(request, str(exc))
    return redirect("reading_lists:detail", slug=slug)


@require_POST
@curator_required
def archive(request, slug):
    reading_list = get_object_or_404(ReadingList, slug=slug)
    services.archive_list(reading_list, request.user)
    messages.success(request, "Lista a fost arhivată.")
    return redirect("reading_lists:detail", slug=slug)

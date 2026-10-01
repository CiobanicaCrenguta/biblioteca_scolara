import json

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.reader.stats import reading_stats

from . import privacy
from .forms import ProfileForm, RegisterForm
from .models import UserProfile


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Bine ai venit! Alege câteva teme preferate.")
            return redirect("accounts:profile")
    else:
        form = RegisterForm()
    return render(request, "accounts/register.html", {"form": form})


@login_required
def profile(request):
    user_profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=user_profile)
        if form.is_valid():
            saved = form.save(commit=False)
            saved.onboarding_completed = True
            saved.save()
            form.save_m2m()
            privacy.acknowledge_privacy_notice(saved)
            messages.success(request, "Profilul a fost salvat.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=user_profile)

    return render(
        request,
        "accounts/profile.html",
        {
            "form": form,
            "profile": user_profile,
            "stats": reading_stats(request.user),
        },
    )


@login_required
def privacy_page(request):
    return render(
        request,
        "accounts/privacy.html",
        {"version": privacy.PRIVACY_NOTICE_VERSION, "profile": request.user.profile},
    )


@login_required
def export_data(request):
    """Dreptul de acces: un fișier JSON cu tot ce știe aplicația despre tine."""
    payload = privacy.export_user_data(request.user)
    response = HttpResponse(
        json.dumps(payload, ensure_ascii=False, indent=2),
        content_type="application/json; charset=utf-8",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="datele-mele-{request.user.username}.json"'
    )
    return response


@login_required
def clear_history(request):
    if request.method == "POST":
        counts = privacy.clear_activity(request.user)
        messages.success(
            request,
            "Am șters {raft} intrări din raft, {progres} poziții salvate și "
            "{evenimente} evenimente.".format(**counts),
        )
        return redirect("accounts:profile")
    return render(request, "accounts/confirm_clear.html", {"stats": reading_stats(request.user)})


@login_required
@require_POST
def stop_profiling(request):
    count = privacy.clear_recommendation_events(request.user)
    messages.success(
        request,
        f"Personalizarea a fost oprită și {count} evenimente au fost șterse. "
        "Raftul și progresul au rămas neatinse.",
    )
    return redirect("accounts:profile")


@login_required
def delete_account(request):
    if request.method == "POST":
        if request.POST.get("confirm") != request.user.username:
            messages.error(request, "Scrie exact numele tău de utilizator ca să confirmi.")
            return redirect("accounts:delete_account")
        username = request.user.username
        user = request.user
        logout(request)
        privacy.delete_account(user)
        messages.success(request, f"Contul „{username}” a fost șters definitiv.")
        return redirect("catalog:book_list")
    return render(request, "accounts/confirm_delete.html")


# ==========================================================================
# Gestiunea utilizatorilor, pentru bibliotecar
# ==========================================================================

from django.core.exceptions import PermissionDenied  # noqa: E402
from django.shortcuts import get_object_or_404  # noqa: E402
from django.views.decorators.http import require_POST  # noqa: E402

from .forms import FormularUtilizator  # noqa: E402
from .models import User  # noqa: E402
from .permissions import librarian_required  # noqa: E402


def _context_utilizatori(request, tinta, formular):
    rol = request.GET.get("rol", "")
    cautare = request.GET.get("q", "").strip()

    utilizatori = User.objects.all().order_by("role", "username")
    if rol:
        utilizatori = utilizatori.filter(role=rol)
    if cautare:
        utilizatori = utilizatori.filter(username__icontains=cautare)

    toti = User.objects.all()
    return {
        "utilizatori": utilizatori,
        "numaratoare": {
            "STUDENT": toti.filter(role=User.Role.STUDENT).count(),
            "TEACHER": toti.filter(role=User.Role.TEACHER).count(),
            "LIBRARIAN": toti.filter(role=User.Role.LIBRARIAN).count(),
            "inactivi": toti.filter(is_active=False).count(),
        },
        "rol": rol,
        "cautare": cautare,
        "tinta": tinta,
        "formular": formular,
        "sectiune": "utilizatori",
    }


@librarian_required
def utilizatori(request, pk=None):
    tinta = get_object_or_404(User, pk=pk) if pk else None
    formular = FormularUtilizator(instance=tinta) if tinta else FormularUtilizator()
    return render(request, "accounts/utilizatori.html",
                  _context_utilizatori(request, tinta, formular))


@require_POST
@librarian_required
def utilizator_salveaza(request, pk=None):
    tinta = get_object_or_404(User, pk=pk) if pk else None
    formular = FormularUtilizator(request.POST, instance=tinta)

    if tinta == request.user and request.POST.get("role") != request.user.role:
        messages.error(request, "Nu îți poți schimba propriul rol.")
        return redirect("accounts:utilizator", pk=tinta.pk)
    if tinta == request.user and not request.POST.get("is_active"):
        messages.error(request, "Nu îți poți dezactiva propriul cont.")
        return redirect("accounts:utilizator", pk=tinta.pk)

    if not formular.is_valid():
        messages.error(request, "Formularul are câmpuri de corectat.")
        return render(request, "accounts/utilizatori.html",
                      _context_utilizatori(request, tinta, formular))

    nou = formular.este_nou
    user = formular.save()
    messages.success(request, "Contul „%s” a fost %s." % (
        user.username, "creat" if nou else "actualizat"))
    return redirect("accounts:utilizator", pk=user.pk)


@require_POST
@librarian_required
def utilizator_sterge(request, pk):
    tinta = get_object_or_404(User, pk=pk)
    if tinta == request.user:
        messages.error(request, "Nu îți poți șterge propriul cont de aici.")
        return redirect("accounts:utilizator", pk=pk)
    nume = tinta.username
    tinta.delete()
    messages.success(request, "Contul „%s” a fost șters definitiv." % nume)
    return redirect("accounts:utilizatori")

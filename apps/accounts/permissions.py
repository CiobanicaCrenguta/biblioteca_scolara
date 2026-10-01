from functools import wraps

from django.core.exceptions import PermissionDenied


def librarian_required(view):
    """Autorizarea se verifică în backend, nu prin ascunderea butonului."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_librarian:
            raise PermissionDenied("Acțiune rezervată bibliotecarului.")
        return view(request, *args, **kwargs)

    return wrapper


def curator_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.can_curate:
            raise PermissionDenied("Acțiune rezervată profesorilor și bibliotecarului.")
        return view(request, *args, **kwargs)

    return wrapper

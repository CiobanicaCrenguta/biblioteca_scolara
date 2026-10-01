from .models import ListStatus, ReadingList


def published_lists():
    return (
        ReadingList.objects.filter(status=ListStatus.PUBLISHED)
        .select_related("owner")
        .prefetch_related("items__book")
    )


def lists_owned_by(user):
    if not user.is_authenticated or not user.can_curate:
        return ReadingList.objects.none()
    if user.is_librarian:
        return ReadingList.objects.all().select_related("owner")
    return ReadingList.objects.filter(owner=user).select_related("owner")

from django.shortcuts import render

from . import services


def recommendations(request):
    limit = min(24, max(1, int(request.GET.get("limit", 12))))
    picks = services.recommendations_for(request.user, limit=limit)
    personalized = (
        request.user.is_authenticated
        and getattr(getattr(request.user, "profile", None), "personalization_enabled", True)
    )
    return render(
        request,
        "recommendations/for_you.html",
        {"picks": picks, "personalized": personalized},
    )

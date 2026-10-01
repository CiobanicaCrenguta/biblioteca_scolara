from django.urls import path

from . import views

app_name = "recommendations"

urlpatterns = [
    path("recommendations/", views.recommendations, name="for_you"),
]

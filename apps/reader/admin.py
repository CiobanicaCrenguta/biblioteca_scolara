from django.contrib import admin

from .models import InteractionEvent, ReadingProgress, UserBookState


@admin.register(UserBookState)
class UserBookStateAdmin(admin.ModelAdmin):
    list_display = ("user", "book", "status", "reaction", "updated_at")
    list_filter = ("status", "reaction")


@admin.register(ReadingProgress)
class ReadingProgressAdmin(admin.ModelAdmin):
    list_display = ("user", "resource", "location_value", "percentage", "updated_at")


admin.site.register(InteractionEvent)

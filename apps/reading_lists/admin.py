from django.contrib import admin

from .models import ReadingList, ReadingListItem


class ItemInline(admin.TabularInline):
    model = ReadingListItem
    extra = 1


@admin.register(ReadingList)
class ReadingListAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "status", "target_age_group", "updated_at")
    list_filter = ("status", "target_age_group")
    inlines = [ItemInline]

from django.contrib import admin

from .models import Author, Book, BookEdition, BookResource, Subject


class EditionInline(admin.TabularInline):
    model = BookEdition
    extra = 1


class ResourceInline(admin.TabularInline):
    model = BookResource
    extra = 1


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "recommended_age", "featured", "published_at")
    list_filter = ("status", "recommended_age", "featured")
    search_fields = ("title", "description")
    filter_horizontal = ("authors", "subjects")
    inlines = [EditionInline]


@admin.register(BookEdition)
class EditionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "book", "language", "is_primary")
    inlines = [ResourceInline]


@admin.register(BookResource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ("__str__", "format", "total_pages", "is_active",
                    "rights_status", "is_primary")
    list_filter = ("format", "is_active", "rights_status")


admin.site.register(Author)
admin.site.register(Subject)


admin.site.site_header = "Biblioteca școlară — administrare"
admin.site.site_title = "Biblioteca școlară"
admin.site.index_title = "Panoul bibliotecarului"

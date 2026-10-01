from django.contrib import admin

from .models import Application


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "job",
        "jobseeker",
        "status",
        "created_at",
        "updated_at",
    )
    list_filter = ("status",)
    search_fields = (
        "job__title",
        "jobseeker__user__username",
        "jobseeker__user__email",
        "jobseeker__user__first_name",
        "jobseeker__user__last_name",
    )
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
    raw_id_fields = ("job", "jobseeker", "cv")

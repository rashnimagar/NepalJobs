from django.contrib import admin

from .models import Application, ApplicationStatusHistory, Interview


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


@admin.register(ApplicationStatusHistory)
class ApplicationStatusHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "application",
        "old_status",
        "new_status",
        "changed_by",
        "created_at",
    )
    list_filter = (
        "old_status",
        "new_status",
    )
    search_fields = (
        "application__job__title",
        "application__jobseeker__user__username",
        "application__jobseeker__user__email",
        "application__jobseeker__user__first_name",
        "application__jobseeker__user__last_name",
    )
    readonly_fields = (
        "application",
        "old_status",
        "new_status",
        "changed_by",
        "notes",
        "created_at",
    )
    ordering = ("-created_at",)


@admin.register(Interview)
class InterviewAdmin(admin.ModelAdmin):
    list_display = (
        "application",
        "interview_type",
        "status",
        "scheduled_at",
        "duration_minutes",
        "created_by",
        "created_at",
    )
    list_filter = (
        "status",
        "interview_type",
        "scheduled_at",
    )
    search_fields = (
        "application__job__title",
        "application__jobseeker__user__username",
        "application__jobseeker__user__email",
        "application__jobseeker__user__first_name",
        "application__jobseeker__user__last_name",
        "location_or_link",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "created_by",
    )
    date_hierarchy = "scheduled_at"
    ordering = ("-scheduled_at", "-created_at")
    raw_id_fields = ("application", "created_by")

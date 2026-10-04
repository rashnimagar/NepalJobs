from django.contrib import admin

from .models import Application, ApplicationStatusHistory, Interview


class ApplicationStatusHistoryInline(admin.TabularInline):
    model = ApplicationStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = ("old_status", "new_status", "changed_by", "notes", "created_at")
    fields = ("old_status", "new_status", "changed_by", "notes", "created_at")


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
        "job__employer__company_name",
        "jobseeker__user__username",
        "jobseeker__user__email",
        "jobseeker__user__first_name",
        "jobseeker__user__last_name",
    )
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    raw_id_fields = ("job", "jobseeker", "cv")
    inlines = [ApplicationStatusHistoryInline]
    fieldsets = (
        (
            "Application Information",
            {
                "fields": (
                    "job",
                    "jobseeker",
                    "cv",
                    "status",
                )
            },
        ),
        (
            "Candidate Submission",
            {
                "fields": (
                    "cover_letter",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )


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
        "application__job__employer__company_name",
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
    date_hierarchy = "created_at"
    ordering = ("-created_at",)


@admin.register(Interview)
class InterviewAdmin(admin.ModelAdmin):
    list_display = (
        "get_candidate",
        "get_job",
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
        "created_at",
    )
    search_fields = (
        "application__job__title",
        "application__job__employer__company_name",
        "application__jobseeker__user__username",
        "application__jobseeker__user__email",
        "application__jobseeker__user__first_name",
        "application__jobseeker__user__last_name",
        "location_or_link",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    date_hierarchy = "scheduled_at"
    ordering = ("-scheduled_at", "-created_at")
    raw_id_fields = ("application", "created_by")
    fieldsets = (
        (
            "Interview Details",
            {
                "fields": (
                    "application",
                    "interview_type",
                    "status",
                    "scheduled_at",
                    "duration_minutes",
                    "location_or_link",
                )
            },
        ),
        (
            "Instructions & Notes",
            {
                "fields": (
                    "candidate_instructions",
                    "internal_notes",
                )
            },
        ),
        (
            "Audit & Attribution",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(description="Candidate", ordering="application__jobseeker__user__username")
    def get_candidate(self, obj):
        return obj.application.jobseeker.user.get_full_name() or obj.application.jobseeker.user.username

    @admin.display(description="Job", ordering="application__job__title")
    def get_job(self, obj):
        return obj.application.job.title

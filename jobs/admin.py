from django.contrib import admin

from jobs.models import Category, Job, Location, SavedJob


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("name",)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_remote")
    list_filter = ("is_remote",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("name",)


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "employer",
        "category",
        "location",
        "employment_type",
        "status",
        "application_deadline",
        "is_open",
        "created_at",
    )
    list_filter = (
        "status",
        "employment_type",
        "category",
        "location",
        "is_remote",
        "is_salary_negotiable",
    )
    search_fields = (
        "title",
        "employer__company_name",
        "description",
    )
    raw_id_fields = ("employer",)
    filter_horizontal = ("required_skills",)
    date_hierarchy = "application_deadline"
    ordering = ("-created_at",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "published_at",
        "is_open",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "employer",
                    "title",
                    "category",
                    "location",
                    "is_remote",
                    "employment_type",
                    "vacancies",
                    "application_deadline",
                )
            },
        ),
        (
            "Compensation",
            {
                "fields": (
                    "salary_min",
                    "salary_max",
                    "is_salary_negotiable",
                )
            },
        ),
        (
            "Requirements",
            {
                "fields": (
                    "experience_years_min",
                    "education_level",
                    "required_skills",
                )
            },
        ),
        (
            "Job Details",
            {
                "fields": (
                    "description",
                    "responsibilities",
                )
            },
        ),
        (
            "Status & Lifecycle",
            {
                "fields": (
                    "status",
                    "is_open",
                    "published_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(boolean=True, description="Is open")
    def is_open(self, obj):
        if obj is None or not getattr(obj, "employer_id", None):
            return False
        return obj.is_open


@admin.register(SavedJob)
class SavedJobAdmin(admin.ModelAdmin):
    list_display = ("jobseeker", "job", "created_at")
    list_filter = ("created_at",)
    search_fields = (
        "jobseeker__user__username",
        "jobseeker__user__email",
        "job__title",
        "job__employer__company_name",
    )
    raw_id_fields = ("jobseeker", "job")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

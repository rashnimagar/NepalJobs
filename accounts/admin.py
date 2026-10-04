from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    CV,
    Education,
    EmployerProfile,
    Experience,
    JobseekerProfile,
    Skill,
    User,
)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Role", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Role", {"fields": ("role", "email")}),)
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "role",
        "is_staff",
        "is_active",
        "date_joined",
    )
    list_filter = ("role", "is_staff", "is_superuser", "is_active", "date_joined")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("-date_joined",)


class CVInline(admin.TabularInline):
    model = CV
    extra = 0
    fields = ("title", "original_filename", "is_default", "is_active", "uploaded_at")
    readonly_fields = ("uploaded_at",)


class EducationInline(admin.TabularInline):
    model = Education
    extra = 0
    fields = ("level", "degree", "institution", "start_year", "end_year", "is_ongoing")


class ExperienceInline(admin.TabularInline):
    model = Experience
    extra = 0
    fields = ("job_title", "company", "location", "start_date", "end_date", "is_current")


@admin.register(JobseekerProfile)
class JobseekerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "get_full_name", "get_email", "phone", "location")
    list_filter = ("location",)
    search_fields = (
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
        "location",
        "phone",
    )
    raw_id_fields = ("user",)
    filter_horizontal = ("skills",)
    inlines = [CVInline, EducationInline, ExperienceInline]

    @admin.display(description="Full Name", ordering="user__first_name")
    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    @admin.display(description="Email", ordering="user__email")
    def get_email(self, obj):
        return obj.user.email


@admin.register(EmployerProfile)
class EmployerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "company_name",
        "user",
        "industry",
        "phone",
        "verification_status",
        "reviewed_at",
    )
    list_filter = ("verification_status", "industry")
    search_fields = (
        "company_name",
        "user__username",
        "user__email",
        "industry",
        "phone",
        "address",
    )
    raw_id_fields = ("user",)
    readonly_fields = ("reviewed_at",)
    ordering = ("company_name",)
    fieldsets = (
        (
            "Company Information",
            {
                "fields": (
                    "user",
                    "company_name",
                    "industry",
                    "website",
                    "logo",
                    "description",
                )
            },
        ),
        (
            "Contact Details",
            {
                "fields": (
                    "phone",
                    "address",
                )
            },
        ),
        (
            "Verification & Review",
            {
                "fields": (
                    "verification_status",
                    "verification_document",
                    "reviewed_at",
                    "rejection_reason",
                )
            },
        ),
    )


@admin.register(CV)
class CVAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "profile",
        "original_filename",
        "is_default",
        "is_active",
        "uploaded_at",
    )
    list_filter = ("is_default", "is_active", "uploaded_at")
    search_fields = (
        "title",
        "original_filename",
        "profile__user__username",
        "profile__user__email",
    )
    readonly_fields = ("uploaded_at",)
    raw_id_fields = ("profile",)
    ordering = ("-uploaded_at",)


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Education)
class EducationAdmin(admin.ModelAdmin):
    list_display = (
        "degree",
        "institution",
        "level",
        "profile",
        "start_year",
        "end_year",
        "is_ongoing",
    )
    list_filter = ("level", "is_ongoing")
    search_fields = (
        "degree",
        "institution",
        "field_of_study",
        "profile__user__username",
    )
    raw_id_fields = ("profile",)
    ordering = ("-start_year",)


@admin.register(Experience)
class ExperienceAdmin(admin.ModelAdmin):
    list_display = (
        "job_title",
        "company",
        "location",
        "profile",
        "start_date",
        "end_date",
        "is_current",
    )
    list_filter = ("is_current",)
    search_fields = (
        "job_title",
        "company",
        "location",
        "profile__user__username",
    )
    raw_id_fields = ("profile",)
    ordering = ("-start_date",)
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, JobseekerProfile, EmployerProfile, CV

# Register your models here.
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Role", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Role", {"fields": ("role", "email")}),)
    list_display = ("username", "email", "role", "is_staff")
    list_filter = ("role", "is_staff")

admin.site.register(JobseekerProfile)
admin.site.register(CV)

@admin.register(EmployerProfile)
class EmployerProfileAdmin(admin.ModelAdmin):
    list_display = ("company_name", "user", "verification_status")
    list_filter = ("verification_status",)
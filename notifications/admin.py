from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "recipient",
        "notification_type",
        "title",
        "is_read",
        "created_at",
        "read_at",
    )
    list_filter = (
        "notification_type",
        "is_read",
        "created_at",
    )
    search_fields = (
        "recipient__email",
        "recipient__username",
        "title",
        "message",
    )
    readonly_fields = (
        "created_at",
        "read_at",
    )
    raw_id_fields = (
        "recipient",
        "application",
    )
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

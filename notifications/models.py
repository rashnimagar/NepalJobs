from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        APPLICATION_SUBMITTED = "application_submitted", "Application Submitted"
        APPLICATION_STATUS_CHANGED = "application_status_changed", "Application Status Updated"
        NEW_APPLICANT = "new_applicant", "New Applicant"
        INTERVIEW_SCHEDULED = "interview_scheduled", "Interview Scheduled"
        INTERVIEW_RESCHEDULED = "interview_rescheduled", "Interview Rescheduled"
        INTERVIEW_CANCELLED = "interview_cancelled", "Interview Cancelled"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
        db_index=True,
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    target_url = models.CharField(max_length=255, blank=True)
    application = models.ForeignKey(
        "applications.Application",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "-created_at"]),
            models.Index(fields=["recipient", "-created_at"]),
            models.Index(fields=["notification_type"]),
        ]

    def __str__(self):
        status = "Read" if self.is_read else "Unread"
        return f"{self.recipient} - {self.title} ({status})"

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])

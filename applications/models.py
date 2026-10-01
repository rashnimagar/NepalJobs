from django.db import models


class Application(models.Model):
    class Status(models.TextChoices):
        APPLIED = "applied", "Applied"
        UNDER_REVIEW = "under_review", "Under Review"
        SHORTLISTED = "shortlisted", "Shortlisted"
        INTERVIEW = "interview", "Interview"
        SELECTED = "selected", "Selected"
        REJECTED = "rejected", "Rejected"

    job = models.ForeignKey(
        "jobs.Job",
        on_delete=models.CASCADE,
        related_name="applications",
    )
    jobseeker = models.ForeignKey(
        "accounts.JobseekerProfile",
        on_delete=models.CASCADE,
        related_name="applications",
    )
    cv = models.ForeignKey(
        "accounts.CV",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applications",
    )
    cover_letter = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.APPLIED,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "jobseeker"],
                name="unique_job_application",
            ),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["job", "status"]),
            models.Index(fields=["jobseeker", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.jobseeker} - {self.job.title} ({self.get_status_display()})"

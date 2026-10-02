from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction


class Application(models.Model):
    class Status(models.TextChoices):
        APPLIED = "applied", "Applied"
        UNDER_REVIEW = "under_review", "Under Review"
        SHORTLISTED = "shortlisted", "Shortlisted"
        INTERVIEW = "interview", "Interview"
        SELECTED = "selected", "Selected"
        REJECTED = "rejected", "Rejected"

    VALID_TRANSITIONS = {
        Status.APPLIED: [
            Status.UNDER_REVIEW,
            Status.REJECTED,
        ],
        Status.UNDER_REVIEW: [
            Status.SHORTLISTED,
            Status.REJECTED,
        ],
        Status.SHORTLISTED: [
            Status.INTERVIEW,
            Status.REJECTED,
        ],
        Status.INTERVIEW: [
            Status.SELECTED,
            Status.REJECTED,
        ],
        Status.SELECTED: [],
        Status.REJECTED: [],
    }

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

    @property
    def is_terminal(self):
        return self.status in (self.Status.SELECTED, self.Status.REJECTED)

    def can_transition_to(self, new_status):
        allowed = self.VALID_TRANSITIONS.get(self.status, [])
        return new_status in allowed

    def transition_to(self, new_status, changed_by=None, notes=""):
        if new_status == self.status:
            raise ValidationError(f"Application is already in '{self.get_status_display()}' status.")

        if new_status not in self.Status.values:
            raise ValidationError(f"'{new_status}' is not a valid application status.")

        if not self.can_transition_to(new_status):
            raise ValidationError(
                f"Cannot transition application from '{self.get_status_display()}' to '{self.Status(new_status).label}'."
            )

        with transaction.atomic():
            old_status = self.status
            self.status = new_status
            self.save(update_fields=["status", "updated_at"])
            history = ApplicationStatusHistory.objects.create(
                application=self,
                old_status=old_status,
                new_status=new_status,
                changed_by=changed_by,
                notes=notes or "",
            )
        return history


class ApplicationStatusHistory(models.Model):
    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    old_status = models.CharField(
        max_length=20,
        choices=Application.Status.choices,
    )
    new_status = models.CharField(
        max_length=20,
        choices=Application.Status.choices,
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="application_status_changes",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "Application status histories"

    def __str__(self):
        return f"{self.application_id}: {self.old_status} -> {self.new_status} ({self.created_at})"


class Interview(models.Model):
    class InterviewType(models.TextChoices):
        IN_PERSON = "in_person", "In Person"
        VIDEO = "video", "Video Call"
        PHONE = "phone", "Phone Call"

    class InterviewStatus(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name="interviews",
    )
    interview_type = models.CharField(
        max_length=20,
        choices=InterviewType.choices,
        default=InterviewType.VIDEO,
    )
    status = models.CharField(
        max_length=20,
        choices=InterviewStatus.choices,
        default=InterviewStatus.SCHEDULED,
        db_index=True,
    )
    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=30)
    location_or_link = models.CharField(max_length=500)
    candidate_instructions = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_interviews",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-scheduled_at", "-created_at"]
        indexes = [
            models.Index(fields=["application", "status"]),
            models.Index(fields=["scheduled_at"]),
            models.Index(fields=["status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["application"],
                condition=models.Q(status="scheduled"),
                name="unique_active_scheduled_interview",
            ),
        ]

    def __str__(self):
        scheduled_str = self.scheduled_at.strftime("%Y-%m-%d %H:%M") if self.scheduled_at else "TBD"
        return f"Interview for {self.application_id} ({self.get_interview_type_display()} on {scheduled_str})"

    @property
    def is_scheduled(self):
        return self.status == self.InterviewStatus.SCHEDULED

    @property
    def is_completed(self):
        return self.status == self.InterviewStatus.COMPLETED

    @property
    def is_cancelled(self):
        return self.status == self.InterviewStatus.CANCELLED

    def _scheduled_at_changed(self):
        if not self.pk:
            return True
        original = Interview.objects.filter(pk=self.pk).values_list("scheduled_at", flat=True).first()
        return original != self.scheduled_at

    def clean(self):
        from django.utils import timezone

        super().clean()

        if hasattr(self, "application") and self.application_id:
            app = self.application
            # When creating a new scheduled interview, only SHORTLISTED or INTERVIEW applications are eligible
            if self._state.adding and self.status == self.InterviewStatus.SCHEDULED:
                if app.status not in (Application.Status.SHORTLISTED, Application.Status.INTERVIEW):
                    raise ValidationError(
                        f"Interviews can only be scheduled for applications in 'Shortlisted' or 'Interview' status, not '{app.get_status_display()}'."
                    )

        if self.duration_minutes is not None and self.duration_minutes <= 0:
            raise ValidationError({"duration_minutes": "Duration must be greater than zero minutes."})

        if self.status == self.InterviewStatus.SCHEDULED:
            if self.scheduled_at and self.scheduled_at <= timezone.now():
                if self._state.adding or self._scheduled_at_changed():
                    raise ValidationError({"scheduled_at": "Scheduled interview date and time must be in the future."})

            if hasattr(self, "application") and self.application_id:
                existing_scheduled = Interview.objects.filter(
                    application=self.application,
                    status=self.InterviewStatus.SCHEDULED,
                )
                if self.pk:
                    existing_scheduled = existing_scheduled.exclude(pk=self.pk)
                if existing_scheduled.exists():
                    raise ValidationError(
                        "This application already has an active scheduled interview. Please reschedule or cancel the existing one."
                    )

    def cancel(self):
        if self.status != self.InterviewStatus.SCHEDULED:
            raise ValidationError("Only active scheduled interviews can be cancelled.")
        self.status = self.InterviewStatus.CANCELLED
        self.save(update_fields=["status", "updated_at"])

    def complete(self, outcome_notes=""):
        if self.status != self.InterviewStatus.SCHEDULED:
            raise ValidationError("Only active scheduled interviews can be marked as completed.")
        self.status = self.InterviewStatus.COMPLETED
        cleaned_notes = str(outcome_notes).strip() if outcome_notes else ""
        if cleaned_notes:
            if self.internal_notes:
                self.internal_notes = f"{self.internal_notes}\n\n[Outcome]: {cleaned_notes}"
            else:
                self.internal_notes = f"[Outcome]: {cleaned_notes}"
            self.save(update_fields=["status", "internal_notes", "updated_at"])
        else:
            self.save(update_fields=["status", "updated_at"])

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from accounts.models import Education, EmployerProfile


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name


class Location(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    is_remote = models.BooleanField(
        default=False,
        help_text="Designates whether this location itself represents remote work.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class JobQuerySet(models.QuerySet):
    def open_jobs(self):
        today = timezone.localdate()
        return self.filter(
            status=Job.Status.PUBLISHED,
            application_deadline__gte=today,
            employer__verification_status=EmployerProfile.VerificationStatus.APPROVED,
        )

    def expired_jobs(self):
        today = timezone.localdate()
        return self.filter(
            status=Job.Status.PUBLISHED,
            application_deadline__lt=today,
        )


class Job(models.Model):
    class EmploymentType(models.TextChoices):
        FULL_TIME = "full_time", "Full-time"
        PART_TIME = "part_time", "Part-time"
        CONTRACT = "contract", "Contract"
        INTERNSHIP = "internship", "Internship"
        FREELANCE = "freelance", "Freelance"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        CLOSED = "closed", "Closed"

    employer = models.ForeignKey(
        "accounts.EmployerProfile",
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    responsibilities = models.TextField(blank=True)

    category = models.ForeignKey(
        "jobs.Category",
        on_delete=models.PROTECT,
        related_name="jobs",
    )
    location = models.ForeignKey(
        "jobs.Location",
        on_delete=models.PROTECT,
        related_name="jobs",
    )
    is_remote = models.BooleanField(
        default=False,
        help_text="Check if remote work is permitted for this position.",
    )

    employment_type = models.CharField(
        max_length=20,
        choices=EmploymentType.choices,
        default=EmploymentType.FULL_TIME,
    )

    salary_min = models.PositiveIntegerField(null=True, blank=True)
    salary_max = models.PositiveIntegerField(null=True, blank=True)
    is_salary_negotiable = models.BooleanField(default=False)

    experience_years_min = models.PositiveIntegerField(default=0)
    education_level = models.CharField(
        max_length=20,
        choices=Education.Level.choices,
        blank=True,
    )
    required_skills = models.ManyToManyField(
        "accounts.Skill",
        blank=True,
        related_name="jobs",
    )
    vacancies = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    application_deadline = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    objects = JobQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "application_deadline"]),
            models.Index(fields=["-created_at"]),
            models.Index(fields=["employment_type"]),
        ]

    def __str__(self):
        return f"{self.title} at {self.employer.company_name}"

    def clean(self):
        super().clean()
        errors = {}

        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_max < self.salary_min
        ):
            errors["salary_max"] = "Maximum salary cannot be less than minimum salary."

        if self.vacancies is not None and self.vacancies < 1:
            errors["vacancies"] = "Vacancies must be at least 1."

        if self.status == self.Status.PUBLISHED:
            today = timezone.localdate()
            if self.application_deadline and self.application_deadline < today:
                errors["application_deadline"] = (
                    "Application deadline for published jobs must be today or a future date."
                )

        if errors:
            raise ValidationError(errors)

    @property
    def is_open(self):
        today = timezone.localdate()
        return (
            self.status == self.Status.PUBLISHED
            and self.application_deadline >= today
            and self.employer.is_approved
        )

    @property
    def salary_display(self):
        if self.salary_min and self.salary_max:
            val = f"Rs. {self.salary_min:,} – Rs. {self.salary_max:,}"
        elif self.salary_min:
            val = f"Rs. {self.salary_min:,}+"
        elif self.salary_max:
            val = f"Up to Rs. {self.salary_max:,}"
        elif self.is_salary_negotiable:
            return "Negotiable"
        else:
            return "Not specified"

        if self.is_salary_negotiable:
            val += " (Negotiable)"
        return val

    def publish(self):
        if not self.employer.is_approved:
            raise ValidationError("Only approved employers may publish jobs.")
        today = timezone.localdate()
        if not self.application_deadline or self.application_deadline < today:
            raise ValidationError("Application deadline must be today or a future date.")
        self.status = self.Status.PUBLISHED
        self.published_at = timezone.now()
        self.clean()
        self.save()

    def close(self):
        self.status = self.Status.CLOSED
        self.save()


class SavedJob(models.Model):
    jobseeker = models.ForeignKey(
        "accounts.JobseekerProfile",
        on_delete=models.CASCADE,
        related_name="saved_jobs",
    )
    job = models.ForeignKey(
        "jobs.Job",
        on_delete=models.CASCADE,
        related_name="saved_by_jobseekers",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["jobseeker", "job"],
                name="unique_saved_job",
            ),
        ]
        indexes = [
            models.Index(fields=["jobseeker", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.jobseeker} saved {self.job.title}"

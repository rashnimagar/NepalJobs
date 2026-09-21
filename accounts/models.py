import os
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.validators import FileExtensionValidator
from django.db.models import Q
from django.db import models, transaction
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        JOBSEEKER = "jobseeker", "Jobseeker"
        EMPLOYER = "employer", "Employer"

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.JOBSEEKER)

    @property
    def is_jobseeker(self):
        return self.role == self.Role.JOBSEEKER

    @property
    def is_employer(self):
        return self.role == self.Role.EMPLOYER

class JobseekerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="jobseeker_profile")
    phone = models.CharField(max_length=20, blank=True)
    location = models.CharField(max_length=100, blank=True)
    summary = models.TextField(blank=True)
    skills = models.ManyToManyField("Skill", blank=True, related_name="jobseekers")

    def __str__(self):
        return  self.user.get_full_name() or self.user.username

MAX_LOGO_SIZE_MB = 2
MAX_VERIFICATION_DOC_SIZE_MB = 10


def validate_logo_size(file):
    if file.size > MAX_LOGO_SIZE_MB * 1024 * 1024:
        raise ValidationError(f"Logo must be {MAX_LOGO_SIZE_MB} MB or smaller.")


def validate_verification_doc_size(file):
    if file.size > MAX_VERIFICATION_DOC_SIZE_MB * 1024 * 1024:
        raise ValidationError(
            f"Verification document must be {MAX_VERIFICATION_DOC_SIZE_MB} MB or smaller."
        )


def logo_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"logos/employer_{instance.user_id}/{uuid.uuid4().hex}{ext}"


def verification_doc_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"verification_docs/employer_{instance.user_id}/{uuid.uuid4().hex}{ext}"


def private_verification_storage():
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)


class EmployerProfile(models.Model):
    class VerificationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="employer_profile")
    company_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    # Step 5 additions
    logo = models.ImageField(
        upload_to=logo_upload_path,
        blank=True,
        validators=[
            FileExtensionValidator(["jpg", "jpeg", "png", "webp"]),
            validate_logo_size,
        ],
        help_text="Optional. JPG, PNG or WebP, up to 2 MB.",
    )
    industry = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    verification_document = models.FileField(
        upload_to=verification_doc_upload_path,
        storage=private_verification_storage,
        blank=True,
        validators=[
            FileExtensionValidator(["pdf", "jpg", "jpeg", "png"]),
            validate_verification_doc_size,
        ],
        help_text="PDF or image, up to 10 MB. Kept private.",
    )
    rejection_reason = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    verification_status = models.CharField(
        max_length=10, choices=VerificationStatus.choices, default=VerificationStatus.PENDING
    )

    @property
    def is_approved(self):
        return self.verification_status == self.VerificationStatus.APPROVED

    @property
    def is_pending(self):
        return self.verification_status == self.VerificationStatus.PENDING

    @property
    def is_rejected(self):
        return self.verification_status == self.VerificationStatus.REJECTED

    def submit_for_verification(self):
        """Move Rejected → Pending. Only callable from Rejected state."""
        if self.verification_status != self.VerificationStatus.REJECTED:
            raise ValueError("Only rejected employers may resubmit for verification.")
        self.verification_status = self.VerificationStatus.PENDING
        self.rejection_reason = ""
        self.reviewed_at = None
        self.save(update_fields=["verification_status", "rejection_reason", "reviewed_at"])

    def __str__(self):
        return self.company_name


MAX_ACTIVE_CVS = 5
MAX_CV_SIZE_MB = 5


def private_storage():
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)


def cv_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"cvs/user_{instance.profile.user_id}/{uuid.uuid4().hex}{ext}"


def validate_cv_size(file):
    if file.size > MAX_CV_SIZE_MB * 1024 * 1024:
        raise ValidationError(f"CV must be {MAX_CV_SIZE_MB} MB or smaller.")


class CV(models.Model):
    profile = models.ForeignKey(JobseekerProfile, on_delete=models.CASCADE, related_name="cvs")
    title = models.CharField(max_length=100)
    file = models.FileField(
        upload_to=cv_upload_path,
        storage=private_storage,
        validators=[FileExtensionValidator(["pdf", "doc", "docx"]), validate_cv_size],
    )
    original_filename = models.CharField(max_length=255)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "CV"
        constraints = [
            models.UniqueConstraint(
                fields=["profile"],
                condition=Q(is_default=True, is_active=True),
                name="one_default_cv_per_profile",
            )
        ]

    def __str__(self):
        return f"{self.title} ({self.profile})"

    def make_default(self):
        with transaction.atomic():
            CV.objects.filter(profile=self.profile, is_default=True).update(is_default=False)
            self.is_default = True
            self.save(update_fields=["is_default"])

    def deactivate(self):
        was_default = self.is_default
        self.is_active = False
        self.is_default = False
        self.save(update_fields=["is_active", "is_default"])
        if was_default:
            replacement = CV.objects.filter(profile=self.profile, is_active=True).first()
            if replacement:
                replacement.make_default()


MAX_SKILLS = 20


class Skill(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.name = " ".join(self.name.split()).lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Education(models.Model):
    class Level(models.TextChoices):
        SEE = "see", "SEE"
        PLUS_TWO = "plus2", "+2 / High School"
        DIPLOMA = "diploma", "Diploma"
        BACHELOR = "bachelor", "Bachelor's"
        MASTER = "master", "Master's"
        PHD = "phd", "PhD"
        OTHER = "other", "Other"

    profile = models.ForeignKey(JobseekerProfile, on_delete=models.CASCADE, related_name="educations")
    level = models.CharField(max_length=10, choices=Level.choices)
    degree = models.CharField(max_length=150)
    institution = models.CharField(max_length=200)
    field_of_study = models.CharField(max_length=150, blank=True)
    start_year = models.PositiveSmallIntegerField()
    end_year = models.PositiveSmallIntegerField(null=True, blank=True)
    is_ongoing = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_ongoing", "-end_year", "-start_year"]

    def __str__(self):
        return f"{self.degree} - {self.institution}"

    def clean(self):
        errors = {}
        this_year = timezone.localdate().year
        if self.start_year and not (1950 <= self.start_year <= this_year):
            errors["start_year"] = "Enter a valid start year."
        if self.is_ongoing:
            self.end_year = None
        elif not self.end_year:
            errors["end_year"] = "Enter the end year, or tick 'I'm currently studying here'."
        elif self.start_year and self.end_year < self.start_year:
            errors["end_year"] = "End year cannot be before the start year."
        if errors:
            raise ValidationError(errors)


class Experience(models.Model):
    profile = models.ForeignKey(JobseekerProfile, on_delete=models.CASCADE, related_name="experiences")
    job_title = models.CharField(max_length=150)
    company = models.CharField(max_length=200)
    location = models.CharField(max_length=100, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["-is_current", "-start_date"]

    def __str__(self):
        return f"{self.job_title} at {self.company}"

    def clean(self):
        errors = {}
        today = timezone.localdate()
        if self.start_date and self.start_date > today:
            errors["start_date"] = "Start date cannot be in the future."
        if self.is_current:
            self.end_date = None
        elif not self.end_date:
            errors["end_date"] = "Enter the end date, or tick 'I currently work here'."
        elif self.start_date and self.end_date < self.start_date:
            errors["end_date"] = "End date cannot be before the start date."
        elif self.end_date > today:
            errors["end_date"] = "End date cannot be in the future."
        if errors:
            raise ValidationError(errors)
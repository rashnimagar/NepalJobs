import os
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.validators import FileExtensionValidator
from django.db.models import Q
from django.db import models, transaction


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

    def __str__(self):
        return  self.user.get_full_name() or self.user.username

class EmployerProfile(models.Model):
    class VerificationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="employer_profile")
    company_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    verification_status = models.CharField(
        max_length=10, choices=VerificationStatus.choices, default=VerificationStatus.PENDING
    )

    @property
    def is_approved(self):
        return self.verification_status == self.VerificationStatus.APPROVED

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
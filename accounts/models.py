from django.contrib.auth.models import AbstractUser
from django.db import models


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
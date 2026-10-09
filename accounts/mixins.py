from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied

from .models import User


class JobseekerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """CBV mixin requiring an authenticated user with the jobseeker role.

    Equivalent to the @jobseeker_required decorator:
    - Anonymous users redirect to the standard login URL with `next` query parameter.
    - Authenticated users whose role is not User.Role.JOBSEEKER receive HTTP 403 / PermissionDenied.
    """

    def test_func(self):
        user = self.request.user
        return bool(user.is_authenticated and user.role == User.Role.JOBSEEKER)


class EmployerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """CBV mixin requiring an authenticated user with the employer role.

    Equivalent to the @employer_required decorator:
    - Anonymous users redirect to the standard login URL with `next` query parameter.
    - Authenticated users whose role is not User.Role.EMPLOYER receive HTTP 403 / PermissionDenied.
    - Reachable across all employer verification states (pending, approved, rejected).
    """

    def test_func(self):
        user = self.request.user
        return bool(user.is_authenticated and user.role == User.Role.EMPLOYER)


class ApprovedEmployerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """CBV mixin requiring an authenticated user with the employer role and an approved EmployerProfile.

    Equivalent to the @approved_employer_required decorator:
    - Anonymous users redirect to the standard login URL with `next` query parameter.
    - Authenticated non-employers receive HTTP 403 / PermissionDenied.
    - Authenticated employers without an EmployerProfile receive HTTP 403 / PermissionDenied.
    - Authenticated employers with pending or rejected verification status receive HTTP 403 / PermissionDenied.
    - Authenticated employers with approved verification status are granted access.
    """

    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.role != User.Role.EMPLOYER:
            return False
        try:
            profile = user.employer_profile
        except Exception:
            return False
        return bool(profile and profile.is_approved)


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """CBV mixin requiring an authenticated user who is staff or superuser.

    Equivalent to administrative access guards (e.g. verification document download):
    - Anonymous users redirect to the standard login URL with `next` query parameter.
    - Authenticated non-staff/non-superuser users receive HTTP 403 / PermissionDenied.
    - Staff members and superusers are granted access.
    """

    def test_func(self):
        user = self.request.user
        return bool(user.is_authenticated and (user.is_staff or user.is_superuser))

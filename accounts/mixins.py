from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.http import QueryDict

from .models import User


class AsViewCacheMixin:
    """CBV mixin that caches the result of .as_view() when called without arguments.

    Ensures that calling as_view() returns a cached view function instance so that:
    - resolve(url).func is <callable_alias>
    - resolve(url).func.view_class is <CBVClass>
    """

    _cached_as_view = None
    _view_func = None

    @classmethod
    def as_view(cls, **initkwargs):
        if not initkwargs:
            cached = cls.__dict__.get("_cached_as_view") or cls.__dict__.get("_view_func")
            if cached is None:
                cached = super().as_view(**initkwargs)
                cls._cached_as_view = cached
                cls._view_func = cached
            return cached
        return super().as_view(**initkwargs)


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


def get_pagination_query_string(request, page_param="page"):
    """
    Return a URL-encoded query string preserving all GET parameters except the pagination parameter.
    Accepts an HttpRequest object, a QueryDict, a dictionary, or a query string.
    """
    if not request:
        return ""
    query_dict = getattr(request, "GET", request)
    if isinstance(query_dict, QueryDict):
        query_params = query_dict.copy()
    elif isinstance(query_dict, dict) or hasattr(query_dict, "items"):
        query_params = QueryDict(mutable=True)
        for k, v in query_dict.items():
            if isinstance(v, (list, tuple)):
                for item in v:
                    query_params.appendlist(k, str(item))
            else:
                query_params[k] = str(v)
    elif isinstance(query_dict, str):
        query_params = QueryDict(query_dict, mutable=True)
    else:
        return ""

    if page_param in query_params:
        del query_params[page_param]

    return query_params.urlencode()

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import User


def role_required(role):
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.user.role != role:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


jobseeker_required = role_required(User.Role.JOBSEEKER)
employer_required = role_required(User.Role.EMPLOYER)


def approved_employer_required(view_func):
    """Requires: authenticated + employer role + EmployerProfile approved.
    Pending/rejected employers hit 403. Anonymous users redirect to login.
    employer_required is deliberately separate so dashboard/profile pages
    remain reachable for all employer verification states.
    """
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.role != User.Role.EMPLOYER:
            raise PermissionDenied
        try:
            profile = request.user.employer_profile
        except Exception:
            raise PermissionDenied
        if not profile.is_approved:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapper
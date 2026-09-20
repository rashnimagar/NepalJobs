from django.urls import path
from django.contrib.auth import views as auth_views

from . import views
from .forms import StyledAuthenticationForm

urlpatterns = [
    path("register/", views.register_choice, name="register"),
    path("register/jobseeker/", views.register_jobseeker, name="register_jobseeker"),
    path("register/employer/", views.register_employer, name="register_employer"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=StyledAuthenticationForm,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/jobseeker/", views.jobseeker_dashboard, name="jobseeker_dashboard"),
    path("dashboard/employer/", views.employer_dashboard, name="employer_dashboard"),
]
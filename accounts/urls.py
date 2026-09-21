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
        path("profile/", views.profile_edit, name="profile_edit"),
    path("cvs/", views.cv_list, name="cv_list"),
    path("cvs/<int:pk>/download/", views.cv_download, name="cv_download"),
    path("cvs/<int:pk>/default/", views.cv_set_default, name="cv_set_default"),
    path("cvs/<int:pk>/delete/", views.cv_delete, name="cv_delete"),
]
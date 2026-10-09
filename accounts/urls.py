from django.urls import path
from django.contrib.auth import views as auth_views

from . import views
from .forms import StyledAuthenticationForm

urlpatterns = [
    path("register/", views.RegisterChoiceView.as_view(), name="register"),
    path("register/jobseeker/", views.RegisterJobseekerView.as_view(), name="register_jobseeker"),
    path("register/employer/", views.RegisterEmployerView.as_view(), name="register_employer"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=StyledAuthenticationForm,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("dashboard/jobseeker/", views.JobseekerDashboardView.as_view(), name="jobseeker_dashboard"),
    path("dashboard/employer/", views.EmployerDashboardView.as_view(), name="employer_dashboard"),
    # Employer profile & verification
    path("employer/profile/", views.EmployerProfileView.as_view(), name="employer_profile"),
    path("employer/profile/edit/", views.EmployerProfileEditView.as_view(), name="employer_profile_edit"),
    path("employer/verification/", views.EmployerVerificationSubmitView.as_view(), name="employer_verification_submit"),
    path("employer/verification/<int:pk>/download/", views.VerificationDocumentDownloadView.as_view(), name="verification_document_download"),
    # Public company profile
    path("companies/<int:pk>/", views.CompanyDetailView.as_view(), name="company_detail"),
    # CV management
    path("cvs/", views.CVListView.as_view(), name="cv_list"),
    path("cvs/<int:pk>/download/", views.CVDownloadView.as_view(), name="cv_download"),
    path("cvs/<int:pk>/default/", views.CVSetDefaultView.as_view(), name="cv_set_default"),
    path("cvs/<int:pk>/delete/", views.CVDeleteView.as_view(), name="cv_delete"),
    # Profile – read-only view and edit are separate URLs
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("profile/edit/", views.ProfileEditView.as_view(), name="profile_edit"),
    path("profile/skills/", views.SkillsEditView.as_view(), name="skills_edit"),
    path("profile/education/add/", views.EducationCreateView.as_view(), name="education_add"),
    path("profile/education/<int:pk>/edit/", views.EducationUpdateView.as_view(), name="education_edit"),
    path("profile/education/<int:pk>/delete/", views.EducationDeleteView.as_view(), name="education_delete"),
    path("profile/experience/add/", views.ExperienceCreateView.as_view(), name="experience_add"),
    path("profile/experience/<int:pk>/edit/", views.ExperienceUpdateView.as_view(), name="experience_edit"),
    path("profile/experience/<int:pk>/delete/", views.ExperienceDeleteView.as_view(), name="experience_delete"),
]

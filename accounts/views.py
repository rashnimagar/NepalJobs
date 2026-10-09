import os

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    FormView,
    TemplateView,
    UpdateView,
)

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .decorators import employer_required, jobseeker_required
from .mixins import (
    EmployerRequiredMixin,
    JobseekerRequiredMixin,
    StaffRequiredMixin,
)
from .forms import (
    CVUploadForm,
    EducationForm,
    EmployerProfileForm,
    EmployerSignUpForm,
    EmployerVerificationForm,
    ExperienceForm,
    JobseekerProfileForm,
    JobseekerSignUpForm,
    SkillsForm,
)
from .models import (
    CV,
    MAX_ACTIVE_CVS,
    Education,
    EmployerProfile,
    Experience,
    JobseekerProfile,
    Skill,
)
from django.db.models import Count, Q
from django.utils import timezone

from applications.models import Application, Interview
from jobs.models import Job


class AsViewCacheMixin:
    """
    Ensures that calling as_view() without arguments returns a cached view function
    instance so that resolve().func matches module-level callable aliases.
    """

    _view_func = None

    @classmethod
    def as_view(cls, **initkwargs):
        if not initkwargs:
            if cls._view_func is None:
                cls._view_func = super().as_view(**initkwargs)
            return cls._view_func
        return super().as_view(**initkwargs)


class RegisterChoiceView(AsViewCacheMixin, TemplateView):
    """
    Renders the public account type selection landing page (jobseeker vs employer).
    """

    template_name = "accounts/register_choice.html"


class RegisterJobseekerView(AsViewCacheMixin, FormView):
    """
    Handles jobseeker account registration.
    Redirects authenticated users to dashboard.
    Creates user and jobseeker profile, logs the user in, and displays welcome message.
    """

    form_class = JobseekerSignUpForm
    template_name = "accounts/register_jobseeker.html"
    success_url = reverse_lazy("dashboard")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        messages.success(self.request, "Account created. Welcome to NepalJobs!")
        return redirect("dashboard")


class RegisterEmployerView(AsViewCacheMixin, FormView):
    """
    Handles employer account registration.
    Redirects authenticated users to dashboard.
    Creates user and employer profile (pending verification), logs the user in, and displays status message.
    """

    form_class = EmployerSignUpForm
    template_name = "accounts/register_employer.html"
    success_url = reverse_lazy("dashboard")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        messages.success(
            self.request, "Company account created. It is pending admin approval."
        )
        return redirect("dashboard")


# Backward-compatible function aliases for registration views
register_choice = RegisterChoiceView.as_view()
register_jobseeker = RegisterJobseekerView.as_view()
register_employer = RegisterEmployerView.as_view()


class DashboardView(AsViewCacheMixin, LoginRequiredMixin, View):
    """
    Central routing view that dispatches authenticated users to their role-specific dashboard:
    - Staff / superusers -> admin:index
    - Employers -> employer_dashboard
    - Jobseekers / others -> jobseeker_dashboard
    """

    def get(self, request, *args, **kwargs):
        if request.user.is_staff:
            return redirect("admin:index")
        if request.user.is_employer:
            return redirect("employer_dashboard")
        return redirect("jobseeker_dashboard")


class JobseekerDashboardView(AsViewCacheMixin, JobseekerRequiredMixin, TemplateView):
    """
    Candidate dashboard displaying profile completion steps, application metrics,
    recent applications, upcoming interviews, and saved jobs.
    """

    template_name = "accounts/jobseeker_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = self.request.user.jobseeker_profile
        steps = [
            (
                "Add your contact details and summary",
                bool(profile.phone and profile.location and profile.summary),
                "profile_edit",
            ),
            ("Add your education", profile.educations.exists(), "education_add"),
            ("Add your skills", profile.skills.exists(), "skills_edit"),
            (
                "Add your work experience",
                profile.experiences.exists(),
                "experience_add",
            ),
            ("Upload a CV", profile.cvs.filter(is_active=True).exists(), "cv_list"),
        ]
        done = sum(1 for _, ok, _ in steps if ok)

        # Application metrics scoped strictly to authenticated jobseeker
        app_metrics = profile.applications.aggregate(
            total=Count("id"),
            under_review=Count("id", filter=Q(status=Application.Status.UNDER_REVIEW)),
            interview=Count("id", filter=Q(status=Application.Status.INTERVIEW)),
            selected=Count("id", filter=Q(status=Application.Status.SELECTED)),
        )

        # 3-5 most recent applications
        recent_applications = (
            profile.applications.select_related("job", "job__employer", "job__location")
            .order_by("-created_at")[:5]
        )

        # Upcoming scheduled interviews for candidate
        upcoming_interviews = (
            Interview.objects.filter(
                application__jobseeker=profile,
                status=Interview.InterviewStatus.SCHEDULED,
                scheduled_at__gte=timezone.now(),
            )
            .select_related(
                "application__job",
                "application__job__employer",
                "application__job__location",
            )
            .order_by("scheduled_at")[:5]
        )

        # Saved jobs for candidate
        saved_jobs_count = profile.saved_jobs.count()
        recent_saved_jobs = (
            profile.saved_jobs.select_related("job", "job__employer", "job__location")
            .order_by("-created_at")[:3]
        )

        context.update(
            {
                "steps": steps,
                "done": done,
                "total": len(steps),
                "percent": int(done * 100 / len(steps)),
                "app_metrics": app_metrics,
                "total_applications": app_metrics["total"],
                "under_review_count": app_metrics["under_review"],
                "interview_count": app_metrics["interview"],
                "selected_count": app_metrics["selected"],
                "recent_applications": recent_applications,
                "upcoming_interviews": upcoming_interviews,
                "saved_jobs_count": saved_jobs_count,
                "recent_saved_jobs": recent_saved_jobs,
                "today": timezone.localdate(),
            }
        )
        return context


class EmployerDashboardView(AsViewCacheMixin, EmployerRequiredMixin, TemplateView):
    """
    Employer dashboard displaying verification status, pipeline metrics,
    upcoming scheduled interviews, and recent applicants.
    """

    template_name = "accounts/employer_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = self.request.user.employer_profile
        is_approved = profile.is_approved
        jobs_count = profile.jobs.count() if is_approved else 0
        active_jobs_count = profile.jobs.open_jobs().count() if is_approved else 0

        # Pipeline metrics scoped strictly to current employer
        pipeline_metrics = Application.objects.filter(job__employer=profile).aggregate(
            total=Count("id"),
            needs_review=Count("id", filter=Q(status=Application.Status.APPLIED)),
            screening=Count(
                "id",
                filter=Q(
                    status__in=[
                        Application.Status.UNDER_REVIEW,
                        Application.Status.SHORTLISTED,
                    ]
                ),
            ),
            interview=Count("id", filter=Q(status=Application.Status.INTERVIEW)),
            hired=Count("id", filter=Q(status=Application.Status.SELECTED)),
        )

        # Upcoming scheduled interviews (next 5)
        upcoming_interviews = (
            Interview.objects.filter(
                application__job__employer=profile,
                status=Interview.InterviewStatus.SCHEDULED,
                scheduled_at__gte=timezone.now(),
            )
            .select_related(
                "application__job",
                "application__jobseeker__user",
                "application__jobseeker",
            )
            .order_by("scheduled_at")[:5]
        )

        # Recent applicants across employer's jobs (latest 6)
        recent_applicants = (
            Application.objects.filter(job__employer=profile)
            .select_related("job", "jobseeker__user", "jobseeker")
            .order_by("-created_at")[:6]
        )

        context.update(
            {
                "profile": profile,
                "employer_profile": profile,
                "verification_status": profile.verification_status,
                "is_approved": is_approved,
                "is_pending": profile.is_pending,
                "is_rejected": profile.is_rejected,
                "rejection_reason": profile.rejection_reason,
                "has_verification_document": bool(profile.verification_document),
                "can_post_jobs": is_approved,
                "jobs_count": jobs_count,
                "active_jobs_count": active_jobs_count,
                "pipeline_metrics": pipeline_metrics,
                "total_applicants": pipeline_metrics["total"],
                "needs_review_count": pipeline_metrics["needs_review"],
                "screening_count": pipeline_metrics["screening"],
                "interview_count": pipeline_metrics["interview"],
                "hired_count": pipeline_metrics["hired"],
                "upcoming_interviews": upcoming_interviews,
                "recent_applicants": recent_applicants,
            }
        )
        return context


class EmployerProfileView(AsViewCacheMixin, EmployerRequiredMixin, TemplateView):
    """
    Read-only view for the authenticated employer's company profile.
    """

    template_name = "accounts/employer_profile_view.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["profile"] = self.request.user.employer_profile
        return context


class EmployerProfileEditView(AsViewCacheMixin, EmployerRequiredMixin, UpdateView):
    """
    Handles editing of the authenticated employer's company profile.
    """

    model = EmployerProfile
    form_class = EmployerProfileForm
    template_name = "accounts/employer_profile_edit.html"
    context_object_name = "profile"

    def get_object(self, queryset=None):
        return self.request.user.employer_profile

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Company profile updated.")
        return redirect("employer_profile")


# Backward-compatible function aliases for dashboard and employer profile views
dashboard = DashboardView.as_view()
jobseeker_dashboard = JobseekerDashboardView.as_view()
employer_dashboard = EmployerDashboardView.as_view()
employer_profile = EmployerProfileView.as_view()
employer_profile_edit = EmployerProfileEditView.as_view()


class EmployerVerificationSubmitView(AsViewCacheMixin, EmployerRequiredMixin, UpdateView):
    """
    Handles submission and resubmission of employer verification documents.
    Approved employers are informed and redirected to employer_dashboard.
    """

    model = EmployerProfile
    form_class = EmployerVerificationForm
    template_name = "accounts/employer_verification.html"
    context_object_name = "profile"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and getattr(request.user, "is_employer", False):
            profile = getattr(request.user, "employer_profile", None)
            if profile and profile.is_approved:
                messages.info(request, "Your company is already verified.")
                return redirect("employer_dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        return self.request.user.employer_profile

    def form_valid(self, form):
        profile = form.save()
        if profile.is_rejected:
            profile.submit_for_verification()
        messages.success(
            self.request,
            "Verification document submitted. Your account is pending review.",
        )
        return redirect("employer_dashboard")


# Backward-compatible function alias for employer verification submit view
employer_verification_submit = EmployerVerificationSubmitView.as_view()


class CompanyDetailView(AsViewCacheMixin, DetailView):
    """
    Public company profile displaying approved employer information and paginated open jobs.
    Unapproved or non-existent companies return HTTP 404.
    """

    model = EmployerProfile
    template_name = "accounts/company_detail.html"
    context_object_name = "company"

    def get_queryset(self):
        return EmployerProfile.objects.filter(
            verification_status=EmployerProfile.VerificationStatus.APPROVED
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.object
        open_jobs_qs = (
            company.jobs.open_jobs()
            .select_related("category", "location")
            .order_by("-created_at")
        )
        paginator = Paginator(open_jobs_qs, 10)
        page_number = self.request.GET.get("page")
        page_obj = paginator.get_page(page_number)

        saved_job_ids = set()
        user = self.request.user
        if user.is_authenticated and getattr(user, "is_jobseeker", False):
            profile = getattr(user, "jobseeker_profile", None)
            if profile:
                page_job_ids = [j.pk for j in page_obj.object_list]
                saved_job_ids = set(
                    profile.saved_jobs.filter(job_id__in=page_job_ids).values_list(
                        "job_id", flat=True
                    )
                )

        context.update(
            {
                "page_obj": page_obj,
                "jobs": page_obj.object_list,
                "open_jobs_count": paginator.count,
                "saved_job_ids": saved_job_ids,
            }
        )
        return context


# Backward-compatible function alias for company detail view
company_detail = CompanyDetailView.as_view()


class VerificationDocumentDownloadView(AsViewCacheMixin, StaffRequiredMixin, View):
    """
    Allows staff members and superusers to download private employer verification documents.
    """

    def get(self, request, pk, *args, **kwargs):
        profile = get_object_or_404(EmployerProfile, pk=pk)
        if not profile.verification_document:
            raise Http404("No verification document uploaded.")
        try:
            file_obj = profile.verification_document.open("rb")
        except (FileNotFoundError, ValueError):
            raise Http404("Verification document file missing.")
        filename = os.path.basename(profile.verification_document.name)
        return FileResponse(file_obj, filename=filename)


# Backward-compatible function alias for verification document download view
verification_document_download = VerificationDocumentDownloadView.as_view()


class ProfileView(AsViewCacheMixin, JobseekerRequiredMixin, TemplateView):
    """
    Read-only view for the authenticated jobseeker's profile, including
    profile details, education, experience, skills, and default CV.
    """

    template_name = "accounts/profile_view.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = self.request.user.jobseeker_profile
        context["profile"] = profile
        context["default_cv"] = profile.cvs.filter(is_active=True, is_default=True).first()
        return context


class ProfileEditView(AsViewCacheMixin, JobseekerRequiredMixin, UpdateView):
    """
    Handles editing of the authenticated jobseeker's profile.
    """

    model = JobseekerProfile
    form_class = JobseekerProfileForm
    template_name = "accounts/profile_edit.html"
    context_object_name = "profile"

    def get_object(self, queryset=None):
        return self.request.user.jobseeker_profile

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Profile updated.")
        return redirect("profile")


# Backward-compatible function aliases for jobseeker profile views
profile_view = ProfileView.as_view()
profile_edit = ProfileEditView.as_view()


class CVListView(AsViewCacheMixin, JobseekerRequiredMixin, View):
    """
    Lists active CVs for the authenticated jobseeker and handles new CV uploads.
    """

    template_name = "accounts/cv_list.html"

    def get(self, request, *args, **kwargs):
        profile = request.user.jobseeker_profile
        cvs = profile.cvs.filter(is_active=True)
        form = CVUploadForm()
        return render(
            request,
            self.template_name,
            {"form": form, "cvs": cvs, "max_cvs": MAX_ACTIVE_CVS},
        )

    def post(self, request, *args, **kwargs):
        profile = request.user.jobseeker_profile
        cvs = profile.cvs.filter(is_active=True)
        form = CVUploadForm(request.POST, request.FILES)
        if cvs.count() >= MAX_ACTIVE_CVS:
            messages.error(
                request,
                f"You can keep up to {MAX_ACTIVE_CVS} CVs. Delete one first.",
            )
        elif form.is_valid():
            cv = form.save(commit=False)
            cv.profile = profile
            cv.original_filename = form.cleaned_data["file"].name
            cv.save()
            if not profile.cvs.filter(is_active=True, is_default=True).exists():
                cv.make_default()
            messages.success(request, "CV uploaded.")
            return redirect("cv_list")
        return render(
            request,
            self.template_name,
            {"form": form, "cvs": cvs, "max_cvs": MAX_ACTIVE_CVS},
        )


class CVSetDefaultView(AsViewCacheMixin, JobseekerRequiredMixin, View):
    """
    POST-only view to set a jobseeker's active CV as the default.
    """

    http_method_names = ["post"]

    def post(self, request, pk, *args, **kwargs):
        cv = get_object_or_404(
            CV, pk=pk, profile=request.user.jobseeker_profile, is_active=True
        )
        cv.make_default()
        messages.success(request, f'"{cv.title}" is now your default CV.')
        return redirect("cv_list")


class CVDeleteView(AsViewCacheMixin, JobseekerRequiredMixin, View):
    """
    POST-only view to soft-delete (deactivate) a jobseeker's active CV.
    """

    http_method_names = ["post"]

    def post(self, request, pk, *args, **kwargs):
        cv = get_object_or_404(
            CV, pk=pk, profile=request.user.jobseeker_profile, is_active=True
        )
        cv.deactivate()
        messages.success(request, "CV deleted.")
        return redirect("cv_list")


class CVDownloadView(AsViewCacheMixin, LoginRequiredMixin, View):
    """
    Secure file streaming for CV documents.
    Access is strictly limited to:
    1. The jobseeker who owns the CV.
    2. Staff / superusers.
    3. An approved employer with an active job application linking this CV.
    """

    def get(self, request, pk, *args, **kwargs):
        cv = get_object_or_404(CV, pk=pk)
        is_owner = (
            request.user.is_jobseeker
            and hasattr(request.user, "jobseeker_profile")
            and cv.profile.user_id == request.user.id
        )
        is_staff = request.user.is_staff or request.user.is_superuser
        is_authorized_employer = (
            request.user.is_employer
            and hasattr(request.user, "employer_profile")
            and request.user.employer_profile.is_approved
            and cv.applications.filter(
                job__employer=request.user.employer_profile
            ).exists()
        )
        if not (is_owner or is_staff or is_authorized_employer):
            raise PermissionDenied
        try:
            file_obj = cv.file.open("rb")
        except (FileNotFoundError, ValueError):
            raise Http404("CV file missing.")
        return FileResponse(file_obj, filename=cv.original_filename)


# Backward-compatible function aliases for CV management views
cv_list = CVListView.as_view()
cv_set_default = CVSetDefaultView.as_view()
cv_delete = CVDeleteView.as_view()
cv_download = CVDownloadView.as_view()

class SkillsEditView(AsViewCacheMixin, JobseekerRequiredMixin, FormView):
    """
    Handles editing comma-separated skills for the authenticated jobseeker.
    """

    form_class = SkillsForm
    template_name = "accounts/skills_edit.html"
    success_url = reverse_lazy("profile")

    def get_initial(self):
        initial = super().get_initial()
        profile = self.request.user.jobseeker_profile
        initial["skills"] = ", ".join(profile.skills.values_list("name", flat=True))
        return initial

    def form_valid(self, form):
        profile = self.request.user.jobseeker_profile
        skills = [
            Skill.objects.get_or_create(name=name)[0]
            for name in form.cleaned_data["skills"]
        ]
        profile.skills.set(skills)
        messages.success(self.request, "Skills updated.")
        return redirect("profile")


# Backward-compatible function alias for skills edit view
skills_edit = SkillsEditView.as_view()


class ProfileSectionMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Jobseekers only, and only ever the logged-in user's own entries."""
    section_name = ""
    success_url = reverse_lazy("profile")

    def test_func(self):
        return self.request.user.is_jobseeker

    def get_queryset(self):
        return self.model.objects.filter(profile=self.request.user.jobseeker_profile)


class SectionCreateView(ProfileSectionMixin, CreateView):
    template_name = "accounts/section_form.html"

    def form_valid(self, form):
        form.instance.profile = self.request.user.jobseeker_profile
        messages.success(self.request, f"{self.section_name} added.")
        return super().form_valid(form)


class SectionUpdateView(ProfileSectionMixin, UpdateView):
    template_name = "accounts/section_form.html"

    def form_valid(self, form):
        messages.success(self.request, f"{self.section_name} updated.")
        return super().form_valid(form)


class SectionDeleteView(ProfileSectionMixin, DeleteView):
    http_method_names = ["post"]

    def form_valid(self, form):
        messages.success(self.request, f"{self.section_name} entry removed.")
        return super().form_valid(form)


class EducationCreateView(SectionCreateView):
    model, form_class, section_name = Education, EducationForm, "Education"


class EducationUpdateView(SectionUpdateView):
    model, form_class, section_name = Education, EducationForm, "Education"


class EducationDeleteView(SectionDeleteView):
    model, section_name = Education, "Education"


class ExperienceCreateView(SectionCreateView):
    model, form_class, section_name = Experience, ExperienceForm, "Experience"


class ExperienceUpdateView(SectionUpdateView):
    model, form_class, section_name = Experience, ExperienceForm, "Experience"


class ExperienceDeleteView(SectionDeleteView):
    model, section_name = Experience, "Experience"
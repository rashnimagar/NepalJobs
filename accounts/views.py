import os

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, UpdateView

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .decorators import employer_required, jobseeker_required
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
from .models import CV, MAX_ACTIVE_CVS, Education, EmployerProfile, Experience, Skill
from django.db.models import Count, Q
from django.utils import timezone

from applications.models import Application, Interview
from jobs.models import Job


def register_choice(request):
    return render(request, "accounts/register_choice.html")


def register_jobseeker(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = JobseekerSignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Account created. Welcome to NepalJobs!")
        return redirect("dashboard")
    return render(request, "accounts/register_jobseeker.html", {"form": form})


def register_employer(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = EmployerSignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Company account created. It is pending admin approval.")
        return redirect("dashboard")
    return render(request, "accounts/register_employer.html", {"form": form})


@login_required
def dashboard(request):
    if request.user.is_staff:
        return redirect("admin:index")
    if request.user.is_employer:
        return redirect("employer_dashboard")
    return redirect("jobseeker_dashboard")


@jobseeker_required
def jobseeker_dashboard(request):
    profile = request.user.jobseeker_profile
    steps = [
        ("Add your contact details and summary",
         bool(profile.phone and profile.location and profile.summary), "profile_edit"),
        ("Add your education", profile.educations.exists(), "education_add"),
        ("Add your skills", profile.skills.exists(), "skills_edit"),
        ("Add your work experience", profile.experiences.exists(), "experience_add"),
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
        .select_related("application__job", "application__job__employer", "application__job__location")
        .order_by("scheduled_at")[:5]
    )

    return render(request, "accounts/jobseeker_dashboard.html", {
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
    })



@employer_required
def employer_dashboard(request):
    profile = request.user.employer_profile
    is_approved = profile.is_approved
    jobs_count = profile.jobs.count() if is_approved else 0
    active_jobs_count = profile.jobs.open_jobs().count() if is_approved else 0

    # Pipeline metrics scoped strictly to current employer
    pipeline_metrics = Application.objects.filter(job__employer=profile).aggregate(
        total=Count("id"),
        needs_review=Count("id", filter=Q(status=Application.Status.APPLIED)),
        screening=Count(
            "id",
            filter=Q(status__in=[Application.Status.UNDER_REVIEW, Application.Status.SHORTLISTED]),
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

    return render(
        request,
        "accounts/employer_dashboard.html",
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
        },
    )


@employer_required
def employer_profile(request):
    profile = request.user.employer_profile
    return render(
        request,
        "accounts/employer_profile_view.html",
        {
            "profile": profile,
        },
    )


@employer_required
def employer_profile_edit(request):
    profile = request.user.employer_profile
    form = EmployerProfileForm(
        request.POST or None, request.FILES or None, instance=profile
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Company profile updated.")
        return redirect("employer_profile")
    return render(
        request,
        "accounts/employer_profile_edit.html",
        {
            "form": form,
            "profile": profile,
        },
    )


@employer_required
def employer_verification_submit(request):
    profile = request.user.employer_profile
    if profile.is_approved:
        messages.info(request, "Your company is already verified.")
        return redirect("employer_dashboard")

    form = EmployerVerificationForm(
        request.POST or None, request.FILES or None, instance=profile
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        if profile.is_rejected:
            profile.submit_for_verification()
        messages.success(
            request, "Verification document submitted. Your account is pending review."
        )
        return redirect("employer_dashboard")

    return render(
        request,
        "accounts/employer_verification.html",
        {
            "form": form,
            "profile": profile,
        },
    )


def company_detail(request, pk):
    company = get_object_or_404(
        EmployerProfile,
        pk=pk,
        verification_status=EmployerProfile.VerificationStatus.APPROVED,
    )
    return render(
        request,
        "accounts/company_detail.html",
        {
            "company": company,
        },
    )


@login_required
def verification_document_download(request, pk):
    if not (request.user.is_staff or request.user.is_superuser):
        raise PermissionDenied
    profile = get_object_or_404(EmployerProfile, pk=pk)
    if not profile.verification_document:
        raise Http404("No verification document uploaded.")
    try:
        file_obj = profile.verification_document.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404("Verification document file missing.")
    filename = os.path.basename(profile.verification_document.name)
    return FileResponse(file_obj, filename=filename)


@jobseeker_required
def profile_view(request):
    profile = request.user.jobseeker_profile
    return render(request, "accounts/profile_view.html", {
        "profile": profile,
        "default_cv": profile.cvs.filter(is_active=True, is_default=True).first(),
    })


@jobseeker_required
def profile_edit(request):
    profile = request.user.jobseeker_profile
    form = JobseekerProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("profile")
    return render(request, "accounts/profile_edit.html", {"form": form})


@jobseeker_required
def cv_list(request):
    profile = request.user.jobseeker_profile
    cvs = profile.cvs.filter(is_active=True)
    form = CVUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if cvs.count() >= MAX_ACTIVE_CVS:
            messages.error(request, f"You can keep up to {MAX_ACTIVE_CVS} CVs. Delete one first.")
        elif form.is_valid():
            cv = form.save(commit=False)
            cv.profile = profile
            cv.original_filename = form.cleaned_data["file"].name
            cv.save()
            if not profile.cvs.filter(is_active=True, is_default=True).exists():
                cv.make_default()
            messages.success(request, "CV uploaded.")
            return redirect("cv_list")
    return render(request, "accounts/cv_list.html", {"form": form, "cvs": cvs, "max_cvs": MAX_ACTIVE_CVS})


@jobseeker_required
@require_POST
def cv_set_default(request, pk):
    cv = get_object_or_404(CV, pk=pk, profile=request.user.jobseeker_profile, is_active=True)
    cv.make_default()
    messages.success(request, f'"{cv.title}" is now your default CV.')
    return redirect("cv_list")


@jobseeker_required
@require_POST
def cv_delete(request, pk):
    cv = get_object_or_404(CV, pk=pk, profile=request.user.jobseeker_profile, is_active=True)
    cv.deactivate()
    messages.success(request, "CV deleted.")
    return redirect("cv_list")


@login_required
def cv_download(request, pk):
    cv = get_object_or_404(CV, pk=pk)
    is_owner = request.user.is_jobseeker and hasattr(request.user, "jobseeker_profile") and cv.profile.user_id == request.user.id
    is_staff = request.user.is_staff or request.user.is_superuser
    is_authorized_employer = (
        request.user.is_employer
        and hasattr(request.user, "employer_profile")
        and request.user.employer_profile.is_approved
        and cv.applications.filter(job__employer=request.user.employer_profile).exists()
    )
    if not (is_owner or is_staff or is_authorized_employer):
        raise PermissionDenied
    try:
        file_obj = cv.file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404("CV file missing.")
    return FileResponse(file_obj, filename=cv.original_filename)

@jobseeker_required
def skills_edit(request):
    profile = request.user.jobseeker_profile
    initial = {"skills": ", ".join(profile.skills.values_list("name", flat=True))}
    form = SkillsForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        skills = [Skill.objects.get_or_create(name=name)[0] for name in form.cleaned_data["skills"]]
        profile.skills.set(skills)
        messages.success(request, "Skills updated.")
        return redirect("profile")
    return render(request, "accounts/skills_edit.html", {"form": form})


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
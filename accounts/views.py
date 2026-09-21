from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, UpdateView

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .decorators import employer_required, jobseeker_required
from .forms import (CVUploadForm, EducationForm, EmployerSignUpForm, ExperienceForm, JobseekerProfileForm, JobseekerSignUpForm, SkillsForm)
from .models import CV, MAX_ACTIVE_CVS, Education, Experience, Skill


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
    return render(request, "accounts/jobseeker_dashboard.html", {
        "steps": steps,
        "done": done,
        "total": len(steps),
        "percent": int(done * 100 / len(steps)),
    })



@employer_required
def employer_dashboard(request):
    profile = request.user.employer_profile
    return render(request, "accounts/employer_dashboard.html", {"profile": profile})

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
    # Only the owner for now. Employers get access in the applications step,
    # and only for CVs submitted to their own jobs.
    if not (request.user.is_jobseeker and cv.profile.user_id == request.user.id):
        raise PermissionDenied
    return FileResponse(cv.file.open("rb"), filename=cv.original_filename)

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
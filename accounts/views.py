from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .decorators import employer_required, jobseeker_required
from .forms import CVUploadForm, EmployerSignUpForm, JobseekerProfileForm, JobseekerSignUpForm
from .models import CV, MAX_ACTIVE_CVS


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
    return render(request, "accounts/jobseeker_dashboard.html")


@employer_required
def employer_dashboard(request):
    profile = request.user.employer_profile
    return render(request, "accounts/employer_dashboard.html", {"profile": profile})

@jobseeker_required
def profile_edit(request):
    profile = request.user.jobseeker_profile
    form = JobseekerProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("profile_edit")
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
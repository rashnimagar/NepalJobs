from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .decorators import employer_required, jobseeker_required
from .forms import EmployerSignUpForm, JobseekerSignUpForm


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
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import approved_employer_required
from jobs.forms import JobForm
from jobs.models import Job


def home(request):
    return render(request, "home.html")


@approved_employer_required
def employer_job_list(request):
    employer = request.user.employer_profile
    jobs = employer.jobs.all().order_by("-created_at")
    return render(
        request,
        "jobs/employer_job_list.html",
        {
            "jobs": jobs,
            "employer": employer,
        },
    )


@approved_employer_required
def employer_job_create(request):
    employer = request.user.employer_profile
    form = JobForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        job = form.save(commit=False)
        job.employer = employer
        job.status = Job.Status.DRAFT
        job.save()
        form.save_m2m()
        messages.success(request, f'Job "{job.title}" created successfully as a draft.')
        return redirect("employer_job_detail", pk=job.pk)

    return render(
        request,
        "jobs/employer_job_form.html",
        {
            "form": form,
            "action": "create",
        },
    )


@approved_employer_required
def employer_job_detail(request, pk):
    employer = request.user.employer_profile
    job = get_object_or_404(Job, pk=pk, employer=employer)
    return render(
        request,
        "jobs/employer_job_detail.html",
        {
            "job": job,
        },
    )


@approved_employer_required
def employer_job_edit(request, pk):
    employer = request.user.employer_profile
    job = get_object_or_404(Job, pk=pk, employer=employer)
    form = JobForm(request.POST or None, instance=job)
    if request.method == "POST" and form.is_valid():
        updated_job = form.save(commit=False)
        # Protect server-side fields from tampering
        updated_job.employer = employer
        updated_job.status = job.status
        updated_job.published_at = job.published_at
        updated_job.save()
        form.save_m2m()
        messages.success(request, f'Job "{updated_job.title}" updated successfully.')
        return redirect("employer_job_detail", pk=job.pk)

    return render(
        request,
        "jobs/employer_job_form.html",
        {
            "form": form,
            "job": job,
            "action": "edit",
        },
    )
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import approved_employer_required, jobseeker_required
from jobs.models import Job
from .forms import JobApplicationForm
from .models import Application


@jobseeker_required
def apply_job(request, job_pk):
    job = get_object_or_404(
        Job.objects.select_related("employer", "category", "location"),
        pk=job_pk,
    )
    if not job.is_open:
        messages.error(request, "This job is closed or has expired and is no longer accepting applications.")
        return redirect("job_list")

    profile = request.user.jobseeker_profile

    # Check for existing application
    existing_application = Application.objects.filter(job=job, jobseeker=profile).first()
    if existing_application:
        messages.info(request, "You have already applied for this job.")
        return redirect("jobseeker_application_detail", pk=existing_application.pk)

    # Candidate must have at least one active CV
    if not profile.cvs.filter(is_active=True).exists():
        messages.warning(
            request,
            "You need an active CV uploaded before you can apply for jobs. Please upload a CV first.",
        )
        return redirect("cv_list")

    if request.method == "POST":
        job.refresh_from_db()
        if not job.is_open:
            messages.error(request, "This job has closed and is no longer accepting applications.")
            return redirect("job_list")

        form = JobApplicationForm(request.POST, jobseeker=profile)
        if form.is_valid():
            try:
                with transaction.atomic():
                    if Application.objects.filter(job=job, jobseeker=profile).exists():
                        messages.warning(request, "You have already applied for this job.")
                        existing = Application.objects.get(job=job, jobseeker=profile)
                        return redirect("jobseeker_application_detail", pk=existing.pk)

                    application = form.save(commit=False)
                    application.job = job
                    application.jobseeker = profile
                    application.status = Application.Status.APPLIED
                    application.save()
            except IntegrityError:
                messages.warning(request, "You have already applied for this job.")
                existing = Application.objects.filter(job=job, jobseeker=profile).first()
                if existing:
                    return redirect("jobseeker_application_detail", pk=existing.pk)
                return redirect("job_list")

            messages.success(request, f"Your application for '{job.title}' was submitted successfully.")
            return redirect("jobseeker_application_detail", pk=application.pk)
    else:
        form = JobApplicationForm(jobseeker=profile)

    return render(
        request,
        "applications/apply_form.html",
        {
            "form": form,
            "job": job,
        },
    )


@jobseeker_required
def jobseeker_application_list(request):
    profile = request.user.jobseeker_profile
    applications = (
        profile.applications.select_related("job", "job__employer", "job__location", "cv")
        .order_by("-created_at")
    )
    return render(
        request,
        "applications/jobseeker_application_list.html",
        {
            "applications": applications,
        },
    )


@jobseeker_required
def jobseeker_application_detail(request, pk):
    profile = request.user.jobseeker_profile
    application = get_object_or_404(
        Application.objects.select_related(
            "job",
            "job__employer",
            "job__location",
            "job__category",
            "cv",
        ),
        pk=pk,
        jobseeker=profile,
    )
    return render(
        request,
        "applications/jobseeker_application_detail.html",
        {
            "application": application,
        },
    )


@approved_employer_required
def employer_job_applicants(request, job_pk):
    employer = request.user.employer_profile
    job = get_object_or_404(Job, pk=job_pk, employer=employer)
    applicants = (
        job.applications.select_related("jobseeker", "jobseeker__user", "cv")
        .order_by("-created_at")
    )
    return render(
        request,
        "applications/employer_applicant_list.html",
        {
            "job": job,
            "applicants": applicants,
        },
    )

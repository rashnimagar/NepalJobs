from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import approved_employer_required, jobseeker_required
from jobs.models import Job
from .forms import ApplicationStatusUpdateForm, InterviewScheduleForm, JobApplicationForm
from .models import Application, Interview


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
    all_applications = (
        profile.applications.select_related("job", "job__employer", "job__location", "cv")
        .order_by("-created_at")
    )

    # Compute status counts in a single aggregation query
    status_counts = all_applications.aggregate(
        total=Count("id"),
        applied=Count("id", filter=Q(status=Application.Status.APPLIED)),
        under_review=Count("id", filter=Q(status=Application.Status.UNDER_REVIEW)),
        shortlisted=Count("id", filter=Q(status=Application.Status.SHORTLISTED)),
        interview=Count("id", filter=Q(status=Application.Status.INTERVIEW)),
        selected=Count("id", filter=Q(status=Application.Status.SELECTED)),
        rejected=Count("id", filter=Q(status=Application.Status.REJECTED)),
    )
    status_counts["all"] = status_counts["total"]

    # Status filtering
    current_status = request.GET.get("status", "").strip().lower()
    if current_status in Application.Status.values:
        filtered_applications = all_applications.filter(status=current_status)
    else:
        current_status = "all"
        filtered_applications = all_applications

    # Pagination: 10 applications per page
    paginator = Paginator(filtered_applications, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    status_display_map = dict(Application.Status.choices)
    current_status_display = status_display_map.get(current_status, "All")

    return render(
        request,
        "applications/jobseeker_application_list.html",
        {
            "applications": page_obj,
            "page_obj": page_obj,
            "current_status": current_status,
            "current_status_display": current_status_display,
            "status_counts": status_counts,
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
        ).prefetch_related("status_history", "interviews"),
        pk=pk,
        jobseeker=profile,
    )

    # Canonical recruitment stages for candidate progress stepper
    pipeline_stages = [
        {"key": Application.Status.APPLIED, "label": "Applied", "step": 1},
        {"key": Application.Status.UNDER_REVIEW, "label": "Under Review", "step": 2},
        {"key": Application.Status.SHORTLISTED, "label": "Shortlisted", "step": 3},
        {"key": Application.Status.INTERVIEW, "label": "Interview", "step": 4},
        {"key": Application.Status.SELECTED, "label": "Selected", "step": 5},
    ]

    stage_order = {
        Application.Status.APPLIED: 1,
        Application.Status.UNDER_REVIEW: 2,
        Application.Status.SHORTLISTED: 3,
        Application.Status.INTERVIEW: 4,
        Application.Status.SELECTED: 5,
    }

    current_step = stage_order.get(application.status, 0)
    is_rejected = application.status == Application.Status.REJECTED

    NEXT_STEPS_GUIDANCE = {
        Application.Status.APPLIED: "Your application was received and is pending employer review.",
        Application.Status.UNDER_REVIEW: "The recruitment team is evaluating your CV and qualifications.",
        Application.Status.SHORTLISTED: "You have been shortlisted. The employer is reviewing candidates for the next stage.",
        Application.Status.INTERVIEW: "You have reached the interview stage. The employer will provide interview details through the appropriate recruitment process.",
        Application.Status.SELECTED: "You have been selected for this role. The hiring team will be in touch regarding next steps.",
        Application.Status.REJECTED: "Your application was not selected for this opportunity. We encourage you to continue exploring other roles.",
    }

    status_display_map = dict(Application.Status.choices)

    # Build candidate-safe progression timeline:
    # Initial "Applied" timeline event always comes from application.created_at
    timeline_events = [
        {
            "status": Application.Status.APPLIED,
            "status_display": status_display_map.get(Application.Status.APPLIED, "Applied"),
            "timestamp": application.created_at,
        }
    ]

    # Append actual status history records in chronological order, exposing ONLY safe fields
    for history in application.status_history.order_by("created_at"):
        if history.new_status == Application.Status.APPLIED and len(timeline_events) == 1:
            continue
        timeline_events.append(
            {
                "status": history.new_status,
                "status_display": status_display_map.get(history.new_status, history.new_status.title()),
                "timestamp": history.created_at,
            }
        )

    # Fetch interview information and expose ONLY candidate-safe fields
    active_interview = application.interviews.filter(status=Interview.InterviewStatus.SCHEDULED).first()
    historical_interviews = application.interviews.exclude(status=Interview.InterviewStatus.SCHEDULED).order_by("-scheduled_at", "-created_at")

    candidate_active_interview = None
    if active_interview:
        candidate_active_interview = {
            "scheduled_at": active_interview.scheduled_at,
            "duration_minutes": active_interview.duration_minutes,
            "interview_type_display": active_interview.get_interview_type_display(),
            "interview_type": active_interview.interview_type,
            "location_or_link": active_interview.location_or_link,
            "candidate_instructions": active_interview.candidate_instructions,
            "status": active_interview.status,
            "status_display": active_interview.get_status_display(),
        }

    candidate_historical_interviews = []
    for h_int in historical_interviews:
        candidate_historical_interviews.append({
            "scheduled_at": h_int.scheduled_at,
            "duration_minutes": h_int.duration_minutes,
            "interview_type_display": h_int.get_interview_type_display(),
            "interview_type": h_int.interview_type,
            "location_or_link": h_int.location_or_link,
            "candidate_instructions": h_int.candidate_instructions,
            "status": h_int.status,
            "status_display": h_int.get_status_display(),
        })

    return render(
        request,
        "applications/jobseeker_application_detail.html",
        {
            "application": application,
            "pipeline_stages": pipeline_stages,
            "current_step": current_step,
            "is_rejected": is_rejected,
            "next_steps_guidance": NEXT_STEPS_GUIDANCE.get(application.status, ""),
            "timeline_events": timeline_events,
            "candidate_active_interview": candidate_active_interview,
            "candidate_historical_interviews": candidate_historical_interviews,
        },
    )


@approved_employer_required
def employer_job_applicants(request, job_pk):
    employer = request.user.employer_profile
    job = get_object_or_404(
        Job.objects.select_related("employer", "category", "location"),
        pk=job_pk,
        employer=employer,
    )

    all_applicants = (
        job.applications.select_related("jobseeker", "jobseeker__user", "cv")
        .order_by("-created_at")
    )

    # Status counts for filter pills
    status_counts = {
        "all": all_applicants.count(),
        Application.Status.APPLIED: all_applicants.filter(status=Application.Status.APPLIED).count(),
        Application.Status.UNDER_REVIEW: all_applicants.filter(status=Application.Status.UNDER_REVIEW).count(),
        Application.Status.SHORTLISTED: all_applicants.filter(status=Application.Status.SHORTLISTED).count(),
        Application.Status.INTERVIEW: all_applicants.filter(status=Application.Status.INTERVIEW).count(),
        Application.Status.SELECTED: all_applicants.filter(status=Application.Status.SELECTED).count(),
        Application.Status.REJECTED: all_applicants.filter(status=Application.Status.REJECTED).count(),
    }

    # Query param filtering
    current_status = request.GET.get("status", "").strip().lower()
    if current_status in Application.Status.values:
        applicants = all_applicants.filter(status=current_status)
    else:
        current_status = "all"
        applicants = all_applicants

    return render(
        request,
        "applications/employer_applicant_list.html",
        {
            "job": job,
            "applicants": applicants,
            "current_status": current_status,
            "status_counts": status_counts,
        },
    )


@approved_employer_required
def employer_application_detail(request, pk):
    employer = request.user.employer_profile
    application = get_object_or_404(
        Application.objects.select_related(
            "job",
            "job__employer",
            "jobseeker",
            "jobseeker__user",
            "cv",
        ).prefetch_related(
            "jobseeker__skills",
            "jobseeker__educations",
            "jobseeker__experiences",
            "status_history",
            "status_history__changed_by",
            "interviews",
            "interviews__created_by",
        ),
        pk=pk,
        job__employer=employer,
    )

    if request.method == "POST":
        if application.is_terminal:
            messages.error(request, "This application has reached a terminal status and cannot be modified.")
            return redirect("employer_application_detail", pk=application.pk)

        form = ApplicationStatusUpdateForm(request.POST, instance=application)
        if form.is_valid():
            new_status = form.cleaned_data["status"]
            notes = form.cleaned_data.get("notes", "")
            try:
                application.transition_to(new_status, changed_by=request.user, notes=notes)
                messages.success(
                    request,
                    f"Candidate application status updated to '{application.get_status_display()}'.",
                )
                return redirect("employer_application_detail", pk=application.pk)
            except ValidationError as e:
                form.add_error(None, e)
    else:
        form = ApplicationStatusUpdateForm(instance=application)

    history = application.status_history.select_related("changed_by").order_by("-created_at")

    active_interview = application.interviews.filter(status=Interview.InterviewStatus.SCHEDULED).first()
    historical_interviews = application.interviews.exclude(status=Interview.InterviewStatus.SCHEDULED).order_by("-scheduled_at", "-created_at")
    can_schedule_interview = (
        not active_interview
        and application.status in (Application.Status.SHORTLISTED, Application.Status.INTERVIEW)
    )
    schedule_interview_form = InterviewScheduleForm() if can_schedule_interview else None

    return render(
        request,
        "applications/employer_application_detail.html",
        {
            "application": application,
            "form": form,
            "history": history,
            "can_change_status": not application.is_terminal,
            "active_interview": active_interview,
            "historical_interviews": historical_interviews,
            "can_schedule_interview": can_schedule_interview,
            "schedule_interview_form": schedule_interview_form,
        },
    )


@approved_employer_required
def employer_schedule_interview(request, pk):
    employer = request.user.employer_profile
    application = get_object_or_404(
        Application.objects.select_related("job", "job__employer", "jobseeker__user"),
        pk=pk,
        job__employer=employer,
    )

    if application.status not in (Application.Status.SHORTLISTED, Application.Status.INTERVIEW):
        messages.error(
            request,
            f"Interviews can only be scheduled for applications in 'Shortlisted' or 'Interview' stage, not '{application.get_status_display()}'.",
        )
        return redirect("employer_application_detail", pk=application.pk)

    if application.interviews.filter(status=Interview.InterviewStatus.SCHEDULED).exists():
        messages.warning(
            request,
            "This application already has an active scheduled interview. Please reschedule or cancel it instead.",
        )
        return redirect("employer_application_detail", pk=application.pk)

    if request.method == "POST":
        form = InterviewScheduleForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    if application.status == Application.Status.SHORTLISTED:
                        application.transition_to(
                            Application.Status.INTERVIEW,
                            changed_by=request.user,
                            notes="Interview scheduled.",
                        )
                    interview = form.save(commit=False)
                    interview.application = application
                    interview.status = Interview.InterviewStatus.SCHEDULED
                    interview.created_by = request.user
                    interview.full_clean()
                    interview.save()

                messages.success(
                    request,
                    f"Interview scheduled for {interview.scheduled_at.strftime('%b %d, %Y at %I:%M %p')}.",
                )
                return redirect("employer_application_detail", pk=application.pk)
            except ValidationError as e:
                form.add_error(None, e)
    else:
        form = InterviewScheduleForm()

    return render(
        request,
        "applications/employer_interview_form.html",
        {
            "form": form,
            "application": application,
            "action": "schedule",
        },
    )


@approved_employer_required
def employer_edit_interview(request, pk):
    employer = request.user.employer_profile
    interview = get_object_or_404(
        Interview.objects.select_related("application", "application__job", "application__jobseeker__user"),
        pk=pk,
        application__job__employer=employer,
    )

    if interview.status != Interview.InterviewStatus.SCHEDULED:
        messages.error(request, "Only active scheduled interviews can be rescheduled.")
        return redirect("employer_application_detail", pk=interview.application.pk)

    if request.method == "POST":
        form = InterviewScheduleForm(request.POST, instance=interview)
        if form.is_valid():
            try:
                updated_interview = form.save(commit=False)
                updated_interview.full_clean()
                updated_interview.save()
                messages.success(
                    request,
                    f"Interview rescheduled to {updated_interview.scheduled_at.strftime('%b %d, %Y at %I:%M %p')}.",
                )
                return redirect("employer_application_detail", pk=interview.application.pk)
            except ValidationError as e:
                form.add_error(None, e)
    else:
        form = InterviewScheduleForm(instance=interview)

    return render(
        request,
        "applications/employer_interview_form.html",
        {
            "form": form,
            "application": interview.application,
            "interview": interview,
            "action": "reschedule",
        },
    )


@approved_employer_required
@require_POST
def employer_cancel_interview(request, pk):
    employer = request.user.employer_profile
    interview = get_object_or_404(
        Interview.objects.select_related("application"),
        pk=pk,
        application__job__employer=employer,
    )

    if interview.status != Interview.InterviewStatus.SCHEDULED:
        messages.error(request, "Only active scheduled interviews can be cancelled.")
        return redirect("employer_application_detail", pk=interview.application.pk)

    interview.cancel()
    messages.success(request, "The interview has been cancelled.")
    return redirect("employer_application_detail", pk=interview.application.pk)

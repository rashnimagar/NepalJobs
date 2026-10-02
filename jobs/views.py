from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import approved_employer_required, jobseeker_required
from accounts.models import EmployerProfile
from jobs.forms import JobForm
from jobs.models import Category, Job, Location, SavedJob

PAGE_SIZE = 10


def home(request):
    return render(request, "home.html")


def job_list(request):
    queryset = (
        Job.objects.open_jobs()
        .select_related("employer", "category", "location")
        .prefetch_related("required_skills")
    )

    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(responsibilities__icontains=q)
            | Q(category__name__icontains=q)
            | Q(location__name__icontains=q)
            | Q(required_skills__name__icontains=q)
        ).distinct()

    category_slug = request.GET.get("category", "").strip()
    if category_slug:
        queryset = queryset.filter(category__slug=category_slug)

    location_slug = request.GET.get("location", "").strip()
    if location_slug:
        queryset = queryset.filter(location__slug=location_slug)

    employment_type = request.GET.get("employment_type", "").strip()
    if employment_type:
        queryset = queryset.filter(employment_type=employment_type)

    remote = request.GET.get("remote", "").strip().lower()
    if remote == "remote":
        queryset = queryset.filter(is_remote=True)
    elif remote == "onsite":
        queryset = queryset.filter(is_remote=False)

    sort = request.GET.get("sort", "newest").strip().lower()
    if sort == "deadline":
        queryset = queryset.order_by("application_deadline", "-created_at")
    else:
        sort = "newest"
        queryset = queryset.order_by("-created_at")

    paginator = Paginator(queryset, PAGE_SIZE)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    categories = Category.objects.filter(is_active=True)
    locations = Location.objects.all()
    employment_types = Job.EmploymentType.choices

    query_params = request.GET.copy()
    if "page" in query_params:
        del query_params["page"]
    query_string = query_params.urlencode()

    has_filters = bool(
        q
        or category_slug
        or location_slug
        or employment_type
        or (remote in ("remote", "onsite"))
        or (sort and sort != "newest")
    )

    saved_job_ids = set()
    if request.user.is_authenticated and getattr(request.user, "is_jobseeker", False):
        profile = getattr(request.user, "jobseeker_profile", None)
        if profile:
            page_job_ids = [j.pk for j in page_obj.object_list]
            saved_job_ids = set(
                profile.saved_jobs.filter(job_id__in=page_job_ids).values_list("job_id", flat=True)
            )

    return render(
        request,
        "jobs/job_list.html",
        {
            "page_obj": page_obj,
            "jobs": page_obj.object_list,
            "categories": categories,
            "locations": locations,
            "employment_types": employment_types,
            "current_q": q,
            "current_category": category_slug,
            "current_location": location_slug,
            "current_employment_type": employment_type,
            "current_remote": remote,
            "current_sort": sort,
            "query_string": query_string,
            "has_filters": has_filters,
            "total_count": paginator.count,
            "saved_job_ids": saved_job_ids,
        },
    )


def job_detail(request, pk):
    job = get_object_or_404(
        Job.objects.open_jobs()
        .select_related("employer", "category", "location")
        .prefetch_related("required_skills"),
        pk=pk,
    )
    user_application = None
    has_active_cv = False
    is_saved = False
    if request.user.is_authenticated and getattr(request.user, "is_jobseeker", False):
        profile = getattr(request.user, "jobseeker_profile", None)
        if profile:
            user_application = profile.applications.filter(job=job).first()
            has_active_cv = profile.cvs.filter(is_active=True).exists()
            is_saved = profile.saved_jobs.filter(job=job).exists()

    return render(
        request,
        "jobs/job_detail.html",
        {
            "job": job,
            "user_application": user_application,
            "has_active_cv": has_active_cv,
            "is_saved": is_saved,
        },
    )


@jobseeker_required
@require_POST
def toggle_save_job(request, pk):
    job = get_object_or_404(Job, pk=pk)
    profile = request.user.jobseeker_profile

    saved_job = profile.saved_jobs.filter(job=job).first()
    if saved_job:
        saved_job.delete()
        messages.info(request, f"'{job.title}' has been removed from your saved jobs.")
    else:
        profile.saved_jobs.get_or_create(job=job)
        messages.success(request, f"'{job.title}' has been added to your saved jobs.")

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    if job.is_open:
        return redirect("job_detail", pk=job.pk)
    return redirect("saved_job_list")


@jobseeker_required
def saved_job_list(request):
    profile = request.user.jobseeker_profile
    today = timezone.localdate()

    open_q = Q(
        job__status=Job.Status.PUBLISHED,
        job__application_deadline__gte=today,
        job__employer__verification_status=EmployerProfile.VerificationStatus.APPROVED,
    )

    filter_counts = profile.saved_jobs.aggregate(
        total=Count("id"),
        open=Count("id", filter=open_q),
        closed=Count("id", filter=~open_q),
    )

    status_filter = request.GET.get("status", "all").strip().lower()
    saved_qs = (
        profile.saved_jobs.select_related(
            "job",
            "job__employer",
            "job__location",
            "job__category",
        )
        .prefetch_related("job__required_skills")
        .order_by("-created_at")
    )

    if status_filter == "open":
        saved_qs = saved_qs.filter(open_q)
    elif status_filter in ("closed", "expired", "closed_expired"):
        status_filter = "closed"
        saved_qs = saved_qs.filter(~open_q)
    else:
        status_filter = "all"

    paginator = Paginator(saved_qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    page_job_ids = [sj.job_id for sj in page_obj.object_list]
    applied_apps = {
        app.job_id: app.pk
        for app in profile.applications.filter(job_id__in=page_job_ids)
    }
    for sj in page_obj.object_list:
        sj.user_application_pk = applied_apps.get(sj.job_id)

    query_params = request.GET.copy()
    if "page" in query_params:
        del query_params["page"]
    query_string = query_params.urlencode()

    return render(
        request,
        "jobs/saved_job_list.html",
        {
            "page_obj": page_obj,
            "saved_jobs": page_obj.object_list,
            "applied_apps": applied_apps,
            "current_status": status_filter,
            "filter_counts": filter_counts,
            "total_count": filter_counts["total"],
            "query_string": query_string,
            "today": today,
        },
    )



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


@approved_employer_required
@require_POST
def employer_job_publish(request, pk):
    employer = request.user.employer_profile
    job = get_object_or_404(Job, pk=pk, employer=employer)
    try:
        job.publish()
        messages.success(request, f'Job "{job.title}" has been published.')
    except ValidationError as e:
        if hasattr(e, "message_dict"):
            error_msg = "; ".join(f"{k}: {', '.join(v)}" for k, v in e.message_dict.items())
        elif hasattr(e, "messages"):
            error_msg = "; ".join(e.messages)
        else:
            error_msg = str(e)
        messages.error(request, f"Unable to publish job: {error_msg}")
    return redirect("employer_job_detail", pk=job.pk)


@approved_employer_required
@require_POST
def employer_job_close(request, pk):
    employer = request.user.employer_profile
    job = get_object_or_404(Job, pk=pk, employer=employer)
    try:
        job.close()
        messages.success(request, f'Job "{job.title}" has been closed.')
    except ValidationError as e:
        if hasattr(e, "message_dict"):
            error_msg = "; ".join(f"{k}: {', '.join(v)}" for k, v in e.message_dict.items())
        elif hasattr(e, "messages"):
            error_msg = "; ".join(e.messages)
        else:
            error_msg = str(e)
        messages.error(request, f"Unable to close job: {error_msg}")
    return redirect("employer_job_detail", pk=job.pk)
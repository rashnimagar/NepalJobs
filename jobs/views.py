from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import approved_employer_required
from jobs.forms import JobForm
from jobs.models import Category, Job, Location

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
    if request.user.is_authenticated and getattr(request.user, "is_jobseeker", False):
        profile = getattr(request.user, "jobseeker_profile", None)
        if profile:
            user_application = profile.applications.filter(job=job).first()
            has_active_cv = profile.cvs.filter(is_active=True).exists()

    return render(
        request,
        "jobs/job_detail.html",
        {
            "job": job,
            "user_application": user_application,
            "has_active_cv": has_active_cv,
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
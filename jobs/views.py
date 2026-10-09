from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from accounts.mixins import ApprovedEmployerRequiredMixin, JobseekerRequiredMixin
from accounts.models import EmployerProfile, JobseekerProfile
from jobs.forms import JobForm
from jobs.models import Category, Job, Location, SavedJob

PAGE_SIZE = 10


class HomeView(TemplateView):
    template_name = "home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()

        categories = (
            Category.objects.filter(is_active=True)
            .annotate(
                open_jobs_count=Count(
                    "jobs",
                    filter=Q(
                        jobs__status=Job.Status.PUBLISHED,
                        jobs__application_deadline__gte=today,
                        jobs__employer__verification_status=EmployerProfile.VerificationStatus.APPROVED,
                    ),
                )
            )
            .order_by("-open_jobs_count", "name")[:8]
        )

        recent_jobs = (
            Job.objects.open_jobs()
            .select_related("employer", "category", "location")
            .prefetch_related("required_skills")
            .order_by("-published_at", "-created_at")[:6]
        )

        stats = {
            "open_jobs": Job.objects.open_jobs().count(),
            "companies": EmployerProfile.objects.filter(
                verification_status=EmployerProfile.VerificationStatus.APPROVED
            ).count(),
            "categories": Category.objects.filter(is_active=True).count(),
            "jobseekers": JobseekerProfile.objects.count(),
        }

        context.update(
            {
                "categories": categories,
                "recent_jobs": recent_jobs,
                "stats": stats,
            }
        )
        return context


class JobListView(ListView):
    model = Job
    template_name = "jobs/job_list.html"
    context_object_name = "jobs"
    paginate_by = PAGE_SIZE

    def paginate_queryset(self, queryset, page_size):
        paginator = self.get_paginator(queryset, page_size)
        page_number = self.request.GET.get("page")
        page_obj = paginator.get_page(page_number)
        return (paginator, page_obj, page_obj.object_list, page_obj.has_other_pages())

    def get_queryset(self):
        queryset = (
            Job.objects.open_jobs()
            .select_related("employer", "category", "location")
            .prefetch_related("required_skills")
        )

        self.q = self.request.GET.get("q", "").strip()
        if self.q:
            queryset = queryset.filter(
                Q(title__icontains=self.q)
                | Q(description__icontains=self.q)
                | Q(responsibilities__icontains=self.q)
                | Q(category__name__icontains=self.q)
                | Q(location__name__icontains=self.q)
                | Q(required_skills__name__icontains=self.q)
            ).distinct()

        self.category_slug = self.request.GET.get("category", "").strip()
        if self.category_slug:
            queryset = queryset.filter(category__slug=self.category_slug)

        self.location_slug = self.request.GET.get("location", "").strip()
        if self.location_slug:
            queryset = queryset.filter(location__slug=self.location_slug)

        self.employment_type = self.request.GET.get("employment_type", "").strip()
        if self.employment_type:
            queryset = queryset.filter(employment_type=self.employment_type)

        self.remote = self.request.GET.get("remote", "").strip().lower()
        if self.remote == "remote":
            queryset = queryset.filter(is_remote=True)
        elif self.remote == "onsite":
            queryset = queryset.filter(is_remote=False)

        self.sort = self.request.GET.get("sort", "newest").strip().lower()
        if self.sort == "deadline":
            queryset = queryset.order_by("application_deadline", "-created_at")
        else:
            self.sort = "newest"
            queryset = queryset.order_by("-created_at")

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        page_obj = context["page_obj"]
        request = self.request

        categories = Category.objects.filter(is_active=True)
        locations = Location.objects.all()
        employment_types = Job.EmploymentType.choices

        query_params = request.GET.copy()
        if "page" in query_params:
            del query_params["page"]
        query_string = query_params.urlencode()

        has_filters = bool(
            self.q
            or self.category_slug
            or self.location_slug
            or self.employment_type
            or (self.remote in ("remote", "onsite"))
            or (self.sort and self.sort != "newest")
        )

        saved_job_ids = set()
        if request.user.is_authenticated and getattr(request.user, "is_jobseeker", False):
            profile = getattr(request.user, "jobseeker_profile", None)
            if profile:
                page_job_ids = [j.pk for j in page_obj.object_list]
                saved_job_ids = set(
                    profile.saved_jobs.filter(job_id__in=page_job_ids).values_list(
                        "job_id", flat=True
                    )
                )

        context.update(
            {
                "categories": categories,
                "locations": locations,
                "employment_types": employment_types,
                "current_q": self.q,
                "current_category": self.category_slug,
                "current_location": self.location_slug,
                "current_employment_type": self.employment_type,
                "current_remote": self.remote,
                "current_sort": self.sort,
                "query_string": query_string,
                "has_filters": has_filters,
                "total_count": context["paginator"].count,
                "saved_job_ids": saved_job_ids,
            }
        )
        return context


class JobDetailView(DetailView):
    model = Job
    template_name = "jobs/job_detail.html"
    context_object_name = "job"

    def get_queryset(self):
        return (
            Job.objects.open_jobs()
            .select_related("employer", "category", "location")
            .prefetch_related("required_skills")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        job = self.object
        request = self.request
        user_application = None
        has_active_cv = False
        is_saved = False
        if request.user.is_authenticated and getattr(request.user, "is_jobseeker", False):
            profile = getattr(request.user, "jobseeker_profile", None)
            if profile:
                user_application = profile.applications.filter(job=job).first()
                has_active_cv = profile.cvs.filter(is_active=True).exists()
                is_saved = profile.saved_jobs.filter(job=job).exists()

        context.update(
            {
                "user_application": user_application,
                "has_active_cv": has_active_cv,
                "is_saved": is_saved,
            }
        )
        return context


class ToggleSaveJobView(JobseekerRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk, *args, **kwargs):
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


class SavedJobListView(JobseekerRequiredMixin, ListView):
    model = SavedJob
    template_name = "jobs/saved_job_list.html"
    context_object_name = "saved_jobs"
    paginate_by = 10

    def paginate_queryset(self, queryset, page_size):
        paginator = self.get_paginator(queryset, page_size)
        page_number = self.request.GET.get("page")
        page_obj = paginator.get_page(page_number)
        return (paginator, page_obj, page_obj.object_list, page_obj.has_other_pages())

    def get_queryset(self):
        profile = self.request.user.jobseeker_profile
        today = timezone.localdate()
        self.today = today

        self.open_q = Q(
            job__status=Job.Status.PUBLISHED,
            job__application_deadline__gte=today,
            job__employer__verification_status=EmployerProfile.VerificationStatus.APPROVED,
        )

        self.filter_counts = profile.saved_jobs.aggregate(
            total=Count("id"),
            open=Count("id", filter=self.open_q),
            closed=Count("id", filter=~self.open_q),
        )

        status_filter = self.request.GET.get("status", "all").strip().lower()
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
            saved_qs = saved_qs.filter(self.open_q)
        elif status_filter in ("closed", "expired", "closed_expired"):
            status_filter = "closed"
            saved_qs = saved_qs.filter(~self.open_q)
        else:
            status_filter = "all"

        self.current_status = status_filter
        return saved_qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        page_obj = context["page_obj"]
        profile = self.request.user.jobseeker_profile

        page_job_ids = [sj.job_id for sj in page_obj.object_list]
        applied_apps = {
            app.job_id: app.pk
            for app in profile.applications.filter(job_id__in=page_job_ids)
        }
        for sj in page_obj.object_list:
            sj.user_application_pk = applied_apps.get(sj.job_id)

        query_params = self.request.GET.copy()
        if "page" in query_params:
            del query_params["page"]
        query_string = query_params.urlencode()

        context.update(
            {
                "applied_apps": applied_apps,
                "current_status": self.current_status,
                "filter_counts": self.filter_counts,
                "total_count": self.filter_counts["total"],
                "query_string": query_string,
                "today": self.today,
            }
        )
        return context


# Backward-compatible function aliases
home = HomeView.as_view()
job_list = JobListView.as_view()
job_detail = JobDetailView.as_view()
toggle_save_job = ToggleSaveJobView.as_view()
saved_job_list = SavedJobListView.as_view()



class EmployerJobListView(ApprovedEmployerRequiredMixin, ListView):
    """
    Displays the list of jobs created by the authenticated approved employer,
    ordered newest first.
    """

    model = Job
    template_name = "jobs/employer_job_list.html"
    context_object_name = "jobs"

    def get_queryset(self):
        return self.request.user.employer_profile.jobs.all().order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["employer"] = self.request.user.employer_profile
        return context


class EmployerJobCreateView(ApprovedEmployerRequiredMixin, CreateView):
    """
    Handles creation of a new job post by the authenticated approved employer.
    Always initializes as draft and sets employer server-side.
    """

    model = Job
    form_class = JobForm
    template_name = "jobs/employer_job_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["action"] = "create"
        return context

    def form_valid(self, form):
        job = form.save(commit=False)
        job.employer = self.request.user.employer_profile
        job.status = Job.Status.DRAFT
        job.save()
        form.save_m2m()
        self.object = job
        messages.success(
            self.request, f'Job "{job.title}" created successfully as a draft.'
        )
        return redirect("employer_job_detail", pk=job.pk)


class EmployerJobDetailView(ApprovedEmployerRequiredMixin, DetailView):
    """
    Displays details and management options for a job owned by the authenticated approved employer.
    """

    model = Job
    template_name = "jobs/employer_job_detail.html"
    context_object_name = "job"

    def get_queryset(self):
        return self.request.user.employer_profile.jobs.all()


class EmployerJobEditView(ApprovedEmployerRequiredMixin, UpdateView):
    """
    Handles editing of an existing job owned by the authenticated approved employer.
    Server-side fields (employer, status, published_at) are protected from tampering.
    """

    model = Job
    form_class = JobForm
    template_name = "jobs/employer_job_form.html"
    context_object_name = "job"

    def get_queryset(self):
        return self.request.user.employer_profile.jobs.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["action"] = "edit"
        return context

    def form_valid(self, form):
        employer = self.request.user.employer_profile
        job = self.get_object()
        updated_job = form.save(commit=False)
        # Protect server-side fields from tampering
        updated_job.employer = employer
        updated_job.status = job.status
        updated_job.published_at = job.published_at
        updated_job.save()
        form.save_m2m()
        self.object = updated_job
        messages.success(
            self.request, f'Job "{updated_job.title}" updated successfully.'
        )
        return redirect("employer_job_detail", pk=job.pk)


class EmployerJobPublishView(ApprovedEmployerRequiredMixin, View):
    """
    Publishes an owned draft or closed job. Requires POST method.
    """

    http_method_names = ["post"]

    def post(self, request, pk, *args, **kwargs):
        employer = request.user.employer_profile
        job = get_object_or_404(Job, pk=pk, employer=employer)
        try:
            job.publish()
            messages.success(request, f'Job "{job.title}" has been published.')
        except ValidationError as e:
            if hasattr(e, "message_dict"):
                error_msg = "; ".join(
                    f"{k}: {', '.join(v)}" for k, v in e.message_dict.items()
                )
            elif hasattr(e, "messages"):
                error_msg = "; ".join(e.messages)
            else:
                error_msg = str(e)
            messages.error(request, f"Unable to publish job: {error_msg}")
        return redirect("employer_job_detail", pk=job.pk)


class EmployerJobCloseView(ApprovedEmployerRequiredMixin, View):
    """
    Closes an owned published job. Requires POST method.
    """

    http_method_names = ["post"]

    def post(self, request, pk, *args, **kwargs):
        employer = request.user.employer_profile
        job = get_object_or_404(Job, pk=pk, employer=employer)
        try:
            job.close()
            messages.success(request, f'Job "{job.title}" has been closed.')
        except ValidationError as e:
            if hasattr(e, "message_dict"):
                error_msg = "; ".join(
                    f"{k}: {', '.join(v)}" for k, v in e.message_dict.items()
                )
            elif hasattr(e, "messages"):
                error_msg = "; ".join(e.messages)
            else:
                error_msg = str(e)
            messages.error(request, f"Unable to close job: {error_msg}")
        return redirect("employer_job_detail", pk=job.pk)


# Backward-compatible function aliases for employer job views
employer_job_list = EmployerJobListView.as_view()
employer_job_create = EmployerJobCreateView.as_view()
employer_job_detail = EmployerJobDetailView.as_view()
employer_job_edit = EmployerJobEditView.as_view()
employer_job_publish = EmployerJobPublishView.as_view()
employer_job_close = EmployerJobCloseView.as_view()
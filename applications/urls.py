from django.urls import path

from . import views

urlpatterns = [
    path("apply/<int:job_pk>/", views.apply_job, name="apply_job"),
    path("my-applications/", views.jobseeker_application_list, name="jobseeker_application_list"),
    path("my-applications/<int:pk>/", views.jobseeker_application_detail, name="jobseeker_application_detail"),
    path("jobs/<int:job_pk>/applicants/", views.employer_job_applicants, name="employer_job_applicants"),
]

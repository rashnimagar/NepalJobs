from django.urls import path

from . import views

urlpatterns = [
    path("apply/<int:job_pk>/", views.apply_job, name="apply_job"),
    path("my-applications/", views.jobseeker_application_list, name="jobseeker_application_list"),
    path("my-applications/<int:pk>/", views.jobseeker_application_detail, name="jobseeker_application_detail"),
    path("jobs/<int:job_pk>/applicants/", views.employer_job_applicants, name="employer_job_applicants"),
    path("employer/applicants/", views.employer_all_applicants, name="employer_all_applicants"),
    path("employer/applications/<int:pk>/", views.employer_application_detail, name="employer_application_detail"),
    path("employer/applications/<int:pk>/schedule-interview/", views.employer_schedule_interview, name="employer_schedule_interview"),
    path("employer/interviews/<int:pk>/edit/", views.employer_edit_interview, name="employer_edit_interview"),
    path("employer/interviews/<int:pk>/cancel/", views.employer_cancel_interview, name="employer_cancel_interview"),
    path("employer/interviews/<int:pk>/complete/", views.employer_complete_interview, name="employer_complete_interview"),
]

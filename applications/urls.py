from django.urls import path

from . import views

urlpatterns = [
    path("apply/<int:job_pk>/", views.ApplyJobView.as_view(), name="apply_job"),
    path("my-applications/", views.JobseekerApplicationListView.as_view(), name="jobseeker_application_list"),
    path("my-applications/<int:pk>/", views.JobseekerApplicationDetailView.as_view(), name="jobseeker_application_detail"),
    path("jobs/<int:job_pk>/applicants/", views.EmployerJobApplicantsView.as_view(), name="employer_job_applicants"),
    path("employer/applicants/", views.EmployerAllApplicantsView.as_view(), name="employer_all_applicants"),
    path("employer/applications/<int:pk>/", views.EmployerApplicationDetailView.as_view(), name="employer_application_detail"),
    path("employer/applications/<int:pk>/schedule-interview/", views.EmployerScheduleInterviewView.as_view(), name="employer_schedule_interview"),
    path("employer/interviews/<int:pk>/edit/", views.EmployerEditInterviewView.as_view(), name="employer_edit_interview"),
    path("employer/interviews/<int:pk>/cancel/", views.EmployerCancelInterviewView.as_view(), name="employer_cancel_interview"),
    path("employer/interviews/<int:pk>/complete/", views.EmployerCompleteInterviewView.as_view(), name="employer_complete_interview"),
]

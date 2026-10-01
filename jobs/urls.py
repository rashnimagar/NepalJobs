from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("jobs/", views.job_list, name="job_list"),
    path("jobs/employer/", views.employer_job_list, name="employer_job_list"),
    path("jobs/employer/create/", views.employer_job_create, name="employer_job_create"),
    path("jobs/employer/<int:pk>/", views.employer_job_detail, name="employer_job_detail"),
    path("jobs/employer/<int:pk>/edit/", views.employer_job_edit, name="employer_job_edit"),
    path("jobs/employer/<int:pk>/publish/", views.employer_job_publish, name="employer_job_publish"),
    path("jobs/employer/<int:pk>/close/", views.employer_job_close, name="employer_job_close"),
    path("jobs/<int:pk>/", views.job_detail, name="job_detail"),
]
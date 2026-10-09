from django.urls import path

from . import views

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("jobs/", views.JobListView.as_view(), name="job_list"),
    path("jobs/employer/", views.EmployerJobListView.as_view(), name="employer_job_list"),
    path("jobs/employer/create/", views.EmployerJobCreateView.as_view(), name="employer_job_create"),
    path("jobs/employer/<int:pk>/", views.EmployerJobDetailView.as_view(), name="employer_job_detail"),
    path("jobs/employer/<int:pk>/edit/", views.EmployerJobEditView.as_view(), name="employer_job_edit"),
    path("jobs/employer/<int:pk>/publish/", views.EmployerJobPublishView.as_view(), name="employer_job_publish"),
    path("jobs/employer/<int:pk>/close/", views.EmployerJobCloseView.as_view(), name="employer_job_close"),
    path("jobs/saved/", views.SavedJobListView.as_view(), name="saved_job_list"),
    path("jobs/<int:pk>/save/", views.ToggleSaveJobView.as_view(), name="toggle_save_job"),
    path("jobs/<int:pk>/", views.JobDetailView.as_view(), name="job_detail"),
]
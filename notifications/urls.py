from django.urls import path

from . import views

urlpatterns = [
    path("", views.notification_list, name="notification_list"),
    path("<int:pk>/go/", views.notification_read_and_redirect, name="notification_read_and_redirect"),
    path("mark-all-read/", views.notification_mark_all_read, name="notification_mark_all_read"),
]

from django.urls import path

from .views import (
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationReadAndRedirectView,
)

urlpatterns = [
    path("", NotificationListView.as_view(), name="notification_list"),
    path("<int:pk>/go/", NotificationReadAndRedirectView.as_view(), name="notification_read_and_redirect"),
    path("mark-all-read/", NotificationMarkAllReadView.as_view(), name="notification_mark_all_read"),
]

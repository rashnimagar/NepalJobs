from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from .models import Notification

PAGE_SIZE = 15


def is_safe_internal_url(url):
    """
    Ensure the URL is a relative path starting with / and not a scheme or protocol-relative URL.
    """
    if not url or not isinstance(url, str):
        return False
    # Avoid protocol-relative URLs like '//example.com'
    if url.startswith("//"):
        return False
    if not url.startswith("/"):
        return False
    parsed = urlsplit(url)
    return not parsed.scheme and not parsed.netloc


class NotificationListView(LoginRequiredMixin, ListView):
    """
    Displays the authenticated user's notifications, ordered newest first with pagination.
    """

    model = Notification
    template_name = "notifications/notification_list.html"
    context_object_name = "notifications"
    paginate_by = PAGE_SIZE

    def get_queryset(self):
        return (
            self.request.user.notifications
            .select_related("application", "application__job")
            .order_by("-created_at")
        )

    def paginate_queryset(self, queryset, page_size):
        paginator = self.get_paginator(
            queryset,
            page_size,
            orphans=self.get_paginate_orphans(),
            allow_empty_first_page=self.get_allow_empty(),
        )
        page_kwarg = self.page_kwarg
        page_number = self.kwargs.get(page_kwarg) or self.request.GET.get(page_kwarg)
        page = paginator.get_page(page_number)
        return (paginator, page, page.object_list, page.has_other_pages())


class NotificationReadAndRedirectView(LoginRequiredMixin, View):
    """
    Marks the notification as read and redirects safely to its internal target URL.
    Scoped strictly to the authenticated recipient.
    """

    def get(self, request, pk, *args, **kwargs):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        notification.mark_as_read()

        target_url = notification.target_url
        if is_safe_internal_url(target_url):
            return redirect(target_url)

        return redirect("notification_list")


class NotificationMarkAllReadView(LoginRequiredMixin, View):
    """
    Marks all unread notifications for the authenticated user as read.
    """

    def post(self, request, *args, **kwargs):
        request.user.notifications.filter(is_read=False).update(
            is_read=True,
            read_at=timezone.now(),
        )
        messages.success(request, "All notifications marked as read.")
        return redirect("notification_list")


# Backward-compatible function aliases
notification_list = NotificationListView.as_view()
notification_read_and_redirect = NotificationReadAndRedirectView.as_view()
notification_mark_all_read = NotificationMarkAllReadView.as_view()

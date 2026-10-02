from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

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


@login_required
def notification_list(request):
    """
    Displays the authenticated user's notifications, ordered newest first with pagination.
    """
    notifications_qs = request.user.notifications.select_related("application", "application__job").order_by("-created_at")

    paginator = Paginator(notifications_qs, PAGE_SIZE)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "notifications/notification_list.html",
        {
            "page_obj": page_obj,
            "notifications": page_obj.object_list,
        },
    )


@login_required
def notification_read_and_redirect(request, pk):
    """
    Marks the notification as read and redirects safely to its internal target URL.
    Scoped strictly to the authenticated recipient.
    """
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.mark_as_read()

    target_url = notification.target_url
    if is_safe_internal_url(target_url):
        return redirect(target_url)

    return redirect("notification_list")


@login_required
@require_POST
def notification_mark_all_read(request):
    """
    Marks all unread notifications for the authenticated user as read.
    """
    request.user.notifications.filter(is_read=False).update(
        is_read=True,
        read_at=timezone.now(),
    )
    messages.success(request, "All notifications marked as read.")
    return redirect("notification_list")

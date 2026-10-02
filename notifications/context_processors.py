def unread_notifications_count(request):
    """
    Context processor to provide the unread notification count for the authenticated user.
    """
    if getattr(request, "user", None) and request.user.is_authenticated:
        count = request.user.notifications.filter(is_read=False).count()
    else:
        count = 0
    return {"unread_notifications_count": count}

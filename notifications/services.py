from django.urls import reverse
from applications.models import Application
from notifications.models import Notification


def notify_application_submitted(application):
    """
    Explicitly create notifications for candidate and employer when a new application is submitted.
    """
    job = application.job
    jobseeker_user = application.jobseeker.user
    employer_user = job.employer.user

    candidate_target = reverse("jobseeker_application_detail", kwargs={"pk": application.pk})
    candidate_notification = Notification.objects.create(
        recipient=jobseeker_user,
        notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
        title="Application Submitted",
        message=f'Your application for "{job.title}" at {job.employer.company_name} was received successfully.',
        target_url=candidate_target,
        application=application,
    )

    employer_target = reverse("employer_application_detail", kwargs={"pk": application.pk})
    employer_notification = Notification.objects.create(
        recipient=employer_user,
        notification_type=Notification.NotificationType.NEW_APPLICANT,
        title="New Applicant",
        message=f'A new candidate applied for "{job.title}".',
        target_url=employer_target,
        application=application,
    )

    return candidate_notification, employer_notification


def notify_application_status_changed(application, old_status, new_status):
    """
    Explicitly create notification for candidate when their application status transitions.
    Only notifies for valid forward/terminal statuses: UNDER_REVIEW, SHORTLISTED, SELECTED, REJECTED.
    """
    if old_status == new_status:
        return None

    valid_notify_statuses = (
        Application.Status.UNDER_REVIEW,
        Application.Status.SHORTLISTED,
        Application.Status.SELECTED,
        Application.Status.REJECTED,
    )
    if new_status not in valid_notify_statuses:
        return None

    status_display = application.get_status_display()
    target_url = reverse("jobseeker_application_detail", kwargs={"pk": application.pk})

    return Notification.objects.create(
        recipient=application.jobseeker.user,
        notification_type=Notification.NotificationType.APPLICATION_STATUS_CHANGED,
        title="Application Status Updated",
        message=f'Your application for "{application.job.title}" has moved to {status_display}.',
        target_url=target_url,
        application=application,
    )


def notify_interview_scheduled(interview):
    """
    Explicitly create notification for candidate when an interview is scheduled.
    """
    application = interview.application
    formatted_dt = interview.scheduled_at.strftime("%b %d, %Y at %I:%M %p")
    target_url = reverse("jobseeker_application_detail", kwargs={"pk": application.pk})

    return Notification.objects.create(
        recipient=application.jobseeker.user,
        notification_type=Notification.NotificationType.INTERVIEW_SCHEDULED,
        title="Interview Scheduled",
        message=f'An interview for "{application.job.title}" has been scheduled for {formatted_dt}.',
        target_url=target_url,
        application=application,
    )


def notify_interview_rescheduled(interview):
    """
    Explicitly create notification for candidate when an interview is rescheduled.
    """
    application = interview.application
    formatted_dt = interview.scheduled_at.strftime("%b %d, %Y at %I:%M %p")
    target_url = reverse("jobseeker_application_detail", kwargs={"pk": application.pk})

    return Notification.objects.create(
        recipient=application.jobseeker.user,
        notification_type=Notification.NotificationType.INTERVIEW_RESCHEDULED,
        title="Interview Rescheduled",
        message=f'Your interview for "{application.job.title}" has been rescheduled to {formatted_dt}.',
        target_url=target_url,
        application=application,
    )


def notify_interview_cancelled(interview):
    """
    Explicitly create notification for candidate when an interview is cancelled.
    """
    application = interview.application
    target_url = reverse("jobseeker_application_detail", kwargs={"pk": application.pk})

    return Notification.objects.create(
        recipient=application.jobseeker.user,
        notification_type=Notification.NotificationType.INTERVIEW_CANCELLED,
        title="Interview Cancelled",
        message=f'Your scheduled interview for "{application.job.title}" has been cancelled.',
        target_url=target_url,
        application=application,
    )

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CV, EmployerProfile, JobseekerProfile
from applications.models import Application, Interview
from jobs.models import Category, Job, Location
from notifications.context_processors import unread_notifications_count
from notifications.models import Notification
from notifications.services import (
    notify_application_status_changed,
    notify_application_submitted,
    notify_interview_cancelled,
    notify_interview_rescheduled,
    notify_interview_scheduled,
)

User = get_user_model()


def make_jobseeker(username="candidate1", email="cand1@example.com", password="Testpass123!"):
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        role=User.Role.JOBSEEKER,
        first_name="Jane",
        last_name="Doe",
    )
    JobseekerProfile.objects.get_or_create(user=user)
    return user


def make_employer(
    username="employer1",
    email="emp1@example.com",
    company_name="Acme Corp",
    verification_status=EmployerProfile.VerificationStatus.APPROVED,
    password="Testpass123!",
):
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        role=User.Role.EMPLOYER,
    )
    EmployerProfile.objects.get_or_create(
        user=user,
        defaults={
            "company_name": company_name,
            "verification_status": verification_status,
        },
    )
    return user


def make_category(name="Engineering", slug="engineering"):
    return Category.objects.create(name=name, slug=slug)


def make_location(name="Kathmandu", slug="kathmandu"):
    return Location.objects.create(name=name, slug=slug)


def create_job(
    employer_profile,
    title="Software Engineer",
    status=Job.Status.PUBLISHED,
    days_to_deadline=14,
    category=None,
    location=None,
):
    if category is None:
        category, _ = Category.objects.get_or_create(name="IT", defaults={"slug": "it"})
    if location is None:
        location, _ = Location.objects.get_or_create(name="Kathmandu", defaults={"slug": "ktm"})

    deadline = timezone.localdate() + timedelta(days=days_to_deadline)
    return Job.objects.create(
        employer=employer_profile,
        title=title,
        description="A great engineering opportunity in Kathmandu.",
        category=category,
        location=location,
        status=status,
        application_deadline=deadline,
    )


def make_cv(jobseeker_profile, name="resume.pdf"):
    fake_file = SimpleUploadedFile(name, b"%PDF-1.4 test content", content_type="application/pdf")
    return CV.objects.create(
        profile=jobseeker_profile,
        title="My Resume",
        original_filename=name,
        file=fake_file,
        is_active=True,
        is_default=True,
    )


class NotificationModelTests(TestCase):
    def setUp(self):
        self.user = make_jobseeker()
        self.employer = make_employer()
        self.job = create_job(self.employer.employer_profile)
        self.cv = make_cv(self.user.jobseeker_profile)
        self.application = Application.objects.create(
            job=self.job,
            jobseeker=self.user.jobseeker_profile,
            cv=self.cv,
            status=Application.Status.APPLIED,
        )

    def test_notification_creation_and_defaults(self):
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
            title="Application Submitted",
            message="Your application was received.",
            target_url="/applications/my-applications/1/",
            application=self.application,
        )
        self.assertFalse(notification.is_read)
        self.assertIsNone(notification.read_at)
        self.assertIsNotNone(notification.created_at)
        self.assertEqual(notification.recipient, self.user)
        self.assertEqual(notification.application, self.application)

    def test_notification_str_representation(self):
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
            title="Application Submitted",
            message="Your application was received.",
        )
        self.assertIn(str(self.user), str(notification))
        self.assertIn("Application Submitted", str(notification))
        self.assertIn("Unread", str(notification))

        notification.mark_as_read()
        self.assertIn("Read", str(notification))

    def test_mark_as_read_updates_status_and_timestamp(self):
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
            title="Application Submitted",
            message="Your application was received.",
        )
        self.assertFalse(notification.is_read)
        self.assertIsNone(notification.read_at)

        notification.mark_as_read()
        notification.refresh_from_db()

        self.assertTrue(notification.is_read)
        self.assertIsNotNone(notification.read_at)

    def test_repeated_mark_as_read_is_idempotent(self):
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
            title="Application Submitted",
            message="Your application was received.",
        )
        notification.mark_as_read()
        original_read_at = notification.read_at

        # Call again
        notification.mark_as_read()
        notification.refresh_from_db()

        self.assertEqual(notification.read_at, original_read_at)

    def test_user_deletion_cascades_notifications(self):
        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
            title="Application Submitted",
            message="Your application was received.",
        )
        self.assertEqual(Notification.objects.filter(recipient=self.user).count(), 1)

        self.user.delete()
        self.assertEqual(Notification.objects.count(), 0)

    def test_application_deletion_cascades_application_linked_notifications(self):
        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
            title="Application Submitted",
            message="Your application was received.",
            application=self.application,
        )
        self.assertEqual(Notification.objects.filter(application=self.application).count(), 1)

        self.application.delete()
        self.assertEqual(Notification.objects.count(), 0)

    def test_ordering_newest_first(self):
        n1 = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
            title="First",
            message="First message",
        )
        n2 = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.APPLICATION_STATUS_CHANGED,
            title="Second",
            message="Second message",
        )
        notifications = list(Notification.objects.filter(recipient=self.user))
        self.assertEqual(notifications, [n2, n1])


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.candidate = make_jobseeker()
        self.employer = make_employer()
        self.job = create_job(self.employer.employer_profile)
        self.cv = make_cv(self.candidate.jobseeker_profile)
        self.application = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate.jobseeker_profile,
            cv=self.cv,
            status=Application.Status.APPLIED,
        )

    def test_notify_application_submitted(self):
        c_notif, e_notif = notify_application_submitted(self.application)

        self.assertEqual(c_notif.recipient, self.candidate)
        self.assertEqual(c_notif.notification_type, Notification.NotificationType.APPLICATION_SUBMITTED)
        self.assertIn("Application Submitted", c_notif.title)
        self.assertIn(self.job.title, c_notif.message)
        self.assertIn(self.employer.employer_profile.company_name, c_notif.message)
        self.assertEqual(c_notif.target_url, reverse("jobseeker_application_detail", kwargs={"pk": self.application.pk}))

        self.assertEqual(e_notif.recipient, self.employer)
        self.assertEqual(e_notif.notification_type, Notification.NotificationType.NEW_APPLICANT)
        self.assertIn("New Applicant", e_notif.title)
        self.assertIn(self.job.title, e_notif.message)
        self.assertEqual(e_notif.target_url, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))

    def test_notify_application_status_changed_valid_transitions(self):
        statuses = [
            Application.Status.UNDER_REVIEW,
            Application.Status.SHORTLISTED,
            Application.Status.SELECTED,
            Application.Status.REJECTED,
        ]
        for s in statuses:
            self.application.status = s
            self.application.save()
            notif = notify_application_status_changed(self.application, Application.Status.APPLIED, s)
            self.assertIsNotNone(notif)
            self.assertEqual(notif.recipient, self.candidate)
            self.assertEqual(notif.notification_type, Notification.NotificationType.APPLICATION_STATUS_CHANGED)
            self.assertIn(self.application.get_status_display(), notif.message)
            self.assertEqual(notif.target_url, reverse("jobseeker_application_detail", kwargs={"pk": self.application.pk}))

    def test_notify_application_status_changed_ignores_identical_status(self):
        notif = notify_application_status_changed(
            self.application,
            Application.Status.APPLIED,
            Application.Status.APPLIED,
        )
        self.assertIsNone(notif)
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_interview_scheduled(self):
        scheduled_time = timezone.now() + timedelta(days=2)
        interview = Interview.objects.create(
            application=self.application,
            interview_type=Interview.InterviewType.VIDEO,
            status=Interview.InterviewStatus.SCHEDULED,
            scheduled_at=scheduled_time,
            location_or_link="https://meet.google.com/abc-xyz",
            candidate_instructions="Prepare portfolio",
            internal_notes="Internal confidential note",
        )
        notif = notify_interview_scheduled(interview)
        self.assertEqual(notif.recipient, self.candidate)
        self.assertEqual(notif.notification_type, Notification.NotificationType.INTERVIEW_SCHEDULED)
        self.assertIn("Interview Scheduled", notif.title)
        self.assertIn(self.job.title, notif.message)
        # Verify internal notes are excluded
        self.assertNotIn("Internal confidential note", notif.message)
        self.assertNotIn("confidential", notif.message)

    def test_notify_interview_rescheduled(self):
        new_time = timezone.now() + timedelta(days=3)
        interview = Interview.objects.create(
            application=self.application,
            interview_type=Interview.InterviewType.VIDEO,
            status=Interview.InterviewStatus.SCHEDULED,
            scheduled_at=new_time,
        )
        notif = notify_interview_rescheduled(interview)
        self.assertEqual(notif.recipient, self.candidate)
        self.assertEqual(notif.notification_type, Notification.NotificationType.INTERVIEW_RESCHEDULED)
        self.assertIn("Interview Rescheduled", notif.title)
        self.assertIn(self.job.title, notif.message)

    def test_notify_interview_cancelled(self):
        interview = Interview.objects.create(
            application=self.application,
            interview_type=Interview.InterviewType.VIDEO,
            status=Interview.InterviewStatus.CANCELLED,
            scheduled_at=timezone.now() + timedelta(days=2),
        )
        notif = notify_interview_cancelled(interview)
        self.assertEqual(notif.recipient, self.candidate)
        self.assertEqual(notif.notification_type, Notification.NotificationType.INTERVIEW_CANCELLED)
        self.assertIn("Interview Cancelled", notif.title)
        self.assertIn("cancelled", notif.message.lower())


class NotificationWorkflowIntegrationTests(TestCase):
    def setUp(self):
        self.candidate = make_jobseeker()
        self.employer = make_employer()
        self.job = create_job(self.employer.employer_profile)
        self.cv = make_cv(self.candidate.jobseeker_profile)

    def test_apply_job_workflow_creates_notifications(self):
        self.client.login(username="candidate1", password="Testpass123!")
        url = reverse("apply_job", kwargs={"job_pk": self.job.pk})
        response = self.client.post(url, {"cv": self.cv.pk, "cover_letter": "Excited to apply!"})
        self.assertEqual(response.status_code, 302)

        # Candidate and employer notifications created
        self.assertEqual(Notification.objects.filter(recipient=self.candidate).count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.employer).count(), 1)

    def test_duplicate_apply_job_creates_no_extra_notifications(self):
        self.client.login(username="candidate1", password="Testpass123!")
        url = reverse("apply_job", kwargs={"job_pk": self.job.pk})

        # First application
        self.client.post(url, {"cv": self.cv.pk, "cover_letter": "First"})
        self.assertEqual(Notification.objects.count(), 2)

        # Duplicate attempt
        self.client.post(url, {"cv": self.cv.pk, "cover_letter": "Second"})
        self.assertEqual(Notification.objects.count(), 2)

    def test_apply_to_closed_job_creates_no_notifications(self):
        self.job.status = Job.Status.CLOSED
        self.job.save()

        self.client.login(username="candidate1", password="Testpass123!")
        url = reverse("apply_job", kwargs={"job_pk": self.job.pk})
        response = self.client.post(url, {"cv": self.cv.pk, "cover_letter": "Try applying"})
        self.assertEqual(response.status_code, 302)

        self.assertEqual(Notification.objects.count(), 0)

    def test_employer_status_change_workflow_creates_candidate_notification(self):
        app = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate.jobseeker_profile,
            cv=self.cv,
            status=Application.Status.APPLIED,
        )

        self.client.login(username="employer1", password="Testpass123!")
        url = reverse("employer_application_detail", kwargs={"pk": app.pk})
        response = self.client.post(url, {"status": Application.Status.UNDER_REVIEW, "notes": "Looks promising."})
        self.assertEqual(response.status_code, 302)

        app.refresh_from_db()
        self.assertEqual(app.status, Application.Status.UNDER_REVIEW)

        # Candidate receives notification; employer receives none
        c_notifs = Notification.objects.filter(recipient=self.candidate)
        self.assertEqual(c_notifs.count(), 1)
        self.assertEqual(c_notifs.first().notification_type, Notification.NotificationType.APPLICATION_STATUS_CHANGED)
        self.assertNotIn("Looks promising", c_notifs.first().message)
        self.assertEqual(Notification.objects.filter(recipient=self.employer).count(), 0)

    def test_employer_invalid_status_change_creates_no_notification(self):
        app = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate.jobseeker_profile,
            cv=self.cv,
            status=Application.Status.APPLIED,
        )

        self.client.login(username="employer1", password="Testpass123!")
        url = reverse("employer_application_detail", kwargs={"pk": app.pk})
        # APPLIED -> SELECTED is an invalid direct transition
        response = self.client.post(url, {"status": Application.Status.SELECTED, "notes": "Invalid jump"})
        self.assertEqual(response.status_code, 200)

        app.refresh_from_db()
        self.assertEqual(app.status, Application.Status.APPLIED)
        self.assertEqual(Notification.objects.count(), 0)

    def test_employer_schedule_interview_workflow_creates_candidate_notification(self):
        app = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate.jobseeker_profile,
            cv=self.cv,
            status=Application.Status.SHORTLISTED,
        )

        self.client.login(username="employer1", password="Testpass123!")
        url = reverse("employer_schedule_interview", kwargs={"pk": app.pk})
        scheduled_time = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
        post_data = {
            "interview_type": Interview.InterviewType.VIDEO,
            "scheduled_at": scheduled_time,
            "duration_minutes": 45,
            "location_or_link": "https://meet.example.com/test",
            "candidate_instructions": "Check your webcam",
            "internal_notes": "Confidential hiring manager notes",
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        # Candidate receives INTERVIEW_SCHEDULED notification
        c_notifs = Notification.objects.filter(recipient=self.candidate)
        self.assertEqual(c_notifs.count(), 1)
        self.assertEqual(c_notifs.first().notification_type, Notification.NotificationType.INTERVIEW_SCHEDULED)
        self.assertNotIn("Confidential", c_notifs.first().message)

    def test_employer_reschedule_interview_workflow_creates_candidate_notification(self):
        app = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate.jobseeker_profile,
            cv=self.cv,
            status=Application.Status.INTERVIEW,
        )
        scheduled_time = timezone.now() + timedelta(days=2)
        interview = Interview.objects.create(
            application=app,
            interview_type=Interview.InterviewType.VIDEO,
            status=Interview.InterviewStatus.SCHEDULED,
            scheduled_at=scheduled_time,
            location_or_link="https://meet.example.com/test",
        )

        self.client.login(username="employer1", password="Testpass123!")
        url = reverse("employer_edit_interview", kwargs={"pk": interview.pk})
        new_time = (timezone.now() + timedelta(days=4)).strftime("%Y-%m-%d %H:%M")
        post_data = {
            "interview_type": Interview.InterviewType.VIDEO,
            "scheduled_at": new_time,
            "duration_minutes": 30,
            "location_or_link": "https://meet.example.com/test-new",
            "candidate_instructions": "Updated instructions",
            "internal_notes": "Reschedule notes",
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        c_notifs = Notification.objects.filter(recipient=self.candidate)
        self.assertEqual(c_notifs.count(), 1)
        self.assertEqual(c_notifs.first().notification_type, Notification.NotificationType.INTERVIEW_RESCHEDULED)

    def test_employer_cancel_interview_workflow_creates_candidate_notification(self):
        app = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate.jobseeker_profile,
            cv=self.cv,
            status=Application.Status.INTERVIEW,
        )
        scheduled_time = timezone.now() + timedelta(days=2)
        interview = Interview.objects.create(
            application=app,
            interview_type=Interview.InterviewType.VIDEO,
            status=Interview.InterviewStatus.SCHEDULED,
            scheduled_at=scheduled_time,
            location_or_link="https://meet.example.com/test",
        )

        self.client.login(username="employer1", password="Testpass123!")
        url = reverse("employer_cancel_interview", kwargs={"pk": interview.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        interview.refresh_from_db()
        self.assertEqual(interview.status, Interview.InterviewStatus.CANCELLED)

        c_notifs = Notification.objects.filter(recipient=self.candidate)
        self.assertEqual(c_notifs.count(), 1)
        self.assertEqual(c_notifs.first().notification_type, Notification.NotificationType.INTERVIEW_CANCELLED)

        # Repeated cancellation attempt creates no additional notification
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Notification.objects.filter(recipient=self.candidate).count(), 1)


class NotificationTransactionTests(TestCase):
    def setUp(self):
        self.candidate = make_jobseeker()
        self.employer = make_employer()
        self.job = create_job(self.employer.employer_profile)
        self.cv = make_cv(self.candidate.jobseeker_profile)
        self.application = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate.jobseeker_profile,
            cv=self.cv,
            status=Application.Status.SHORTLISTED,
        )

    def test_rolled_back_interview_scheduling_persists_no_notification(self):
        # Simulate a transaction rollback during interview scheduling
        self.client.login(username="employer1", password="Testpass123!")
        url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})

        with patch("applications.models.Interview.full_clean", side_effect=Exception("Database failure")):
            scheduled_time = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
            post_data = {
                "interview_type": Interview.InterviewType.VIDEO,
                "scheduled_at": scheduled_time,
                "duration_minutes": 30,
                "location_or_link": "https://meet.example.com",
            }
            with self.assertRaises(Exception):
                self.client.post(url, post_data)

        # Verify application status did NOT change and NO notifications were persisted
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.SHORTLISTED)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(Interview.objects.count(), 0)


class NotificationSecurityTests(TestCase):
    def setUp(self):
        self.candidate1 = make_jobseeker("candidate1", "cand1@example.com")
        self.candidate2 = make_jobseeker("candidate2", "cand2@example.com")
        self.employer = make_employer("employer1", "emp1@example.com")

        self.notif_cand1 = Notification.objects.create(
            recipient=self.candidate1,
            notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
            title="Candidate 1 Notification",
            message="Private message for candidate 1",
            target_url="/applications/my-applications/1/",
        )
        self.notif_emp = Notification.objects.create(
            recipient=self.employer,
            notification_type=Notification.NotificationType.NEW_APPLICANT,
            title="Employer Notification",
            message="Private message for employer",
            target_url="/applications/employer/applications/1/",
        )

    def test_anonymous_access_redirects_to_login(self):
        url = reverse("notification_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_user_cannot_view_another_users_notifications(self):
        self.client.login(username="candidate2", password="Testpass123!")
        url = reverse("notification_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Candidate 1 Notification")
        self.assertNotContains(response, "Employer Notification")

    def test_user_cannot_click_through_another_users_notification(self):
        self.client.login(username="candidate2", password="Testpass123!")
        url = reverse("notification_read_and_redirect", kwargs={"pk": self.notif_cand1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
        self.notif_cand1.refresh_from_db()
        self.assertFalse(self.notif_cand1.is_read)

    def test_candidate_cannot_access_employer_notification(self):
        self.client.login(username="candidate1", password="Testpass123!")
        url = reverse("notification_read_and_redirect", kwargs={"pk": self.notif_emp.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
        self.notif_emp.refresh_from_db()
        self.assertFalse(self.notif_emp.is_read)

    def test_employer_cannot_access_candidate_notification(self):
        self.client.login(username="employer1", password="Testpass123!")
        url = reverse("notification_read_and_redirect", kwargs={"pk": self.notif_cand1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
        self.notif_cand1.refresh_from_db()
        self.assertFalse(self.notif_cand1.is_read)

    def test_mark_all_read_does_not_affect_other_users(self):
        self.client.login(username="candidate1", password="Testpass123!")
        url = reverse("notification_mark_all_read")
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        self.notif_cand1.refresh_from_db()
        self.assertTrue(self.notif_cand1.is_read)

        self.notif_emp.refresh_from_db()
        self.assertFalse(self.notif_emp.is_read)

    def test_destination_view_authorization_remains_enforced(self):
        # Even if a user attempts to visit the target URL of another user's notification directly,
        # the target view blocks them.
        self.client.login(username="candidate1", password="Testpass123!")
        # Trying to access employer application detail as candidate
        response = self.client.get(self.notif_emp.target_url)
        # @approved_employer_required rejects candidate with 403 Forbidden
        self.assertEqual(response.status_code, 403)


class NotificationCenterUITests(TestCase):
    def setUp(self):
        self.user = make_jobseeker()
        self.employer = make_employer()
        self.job = create_job(self.employer.employer_profile)
        self.cv = make_cv(self.user.jobseeker_profile)
        self.application = Application.objects.create(
            job=self.job,
            jobseeker=self.user.jobseeker_profile,
            cv=self.cv,
            status=Application.Status.APPLIED,
        )

    def test_notification_list_renders_empty_state(self):
        self.client.login(username="candidate1", password="Testpass123!")
        url = reverse("notification_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No notifications yet")

    def test_notification_list_renders_read_and_unread_states(self):
        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
            title="Unread Notice",
            message="This is unread",
            is_read=False,
        )
        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.APPLICATION_STATUS_CHANGED,
            title="Read Notice",
            message="This is read",
            is_read=True,
            read_at=timezone.now(),
        )

        self.client.login(username="candidate1", password="Testpass123!")
        url = reverse("notification_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unread Notice")
        self.assertContains(response, "Read Notice")
        self.assertContains(response, "New")
        self.assertContains(response, "Mark all as read")

    def test_unread_count_context_processor(self):
        class DummyRequest:
            def __init__(self, user):
                self.user = user

        # Anonymous request
        from django.contrib.auth.models import AnonymousUser
        anon_req = DummyRequest(AnonymousUser())
        self.assertEqual(unread_notifications_count(anon_req), {"unread_notifications_count": 0})

        # Authenticated user with 2 unread notifications
        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
            title="Notice 1",
            message="Msg 1",
            is_read=False,
        )
        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
            title="Notice 2",
            message="Msg 2",
            is_read=False,
        )
        auth_req = DummyRequest(self.user)
        self.assertEqual(unread_notifications_count(auth_req), {"unread_notifications_count": 2})

    def test_mark_all_read_action(self):
        Notification.objects.create(recipient=self.user, notification_type="application_submitted", title="1", message="1")
        Notification.objects.create(recipient=self.user, notification_type="application_submitted", title="2", message="2")
        self.assertEqual(Notification.objects.filter(recipient=self.user, is_read=False).count(), 2)

        self.client.login(username="candidate1", password="Testpass123!")
        url = reverse("notification_mark_all_read")
        response = self.client.post(url)
        self.assertRedirects(response, reverse("notification_list"))

        self.assertEqual(Notification.objects.filter(recipient=self.user, is_read=False).count(), 0)

    def test_mark_all_read_get_rejected(self):
        self.client.login(username="candidate1", password="Testpass123!")
        url = reverse("notification_mark_all_read")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_click_through_marks_read_and_redirects_to_valid_target(self):
        target = reverse("jobseeker_application_detail", kwargs={"pk": self.application.pk})
        notif = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
            title="Test Notice",
            message="Test Msg",
            target_url=target,
            is_read=False,
        )
        self.client.login(username="candidate1", password="Testpass123!")
        url = reverse("notification_read_and_redirect", kwargs={"pk": notif.pk})
        response = self.client.get(url)
        self.assertRedirects(response, target)

        notif.refresh_from_db()
        self.assertTrue(notif.is_read)
        self.assertIsNotNone(notif.read_at)

    def test_click_through_unsafe_or_external_target_falls_back_to_list(self):
        unsafe_targets = [
            "https://evil.com/phish",
            "//evil.com/phish",
            "javascript:alert(1)",
            "",
        ]
        self.client.login(username="candidate1", password="Testpass123!")

        for target in unsafe_targets:
            notif = Notification.objects.create(
                recipient=self.user,
                notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
                title="Test Notice",
                message="Test Msg",
                target_url=target,
                is_read=False,
            )
            url = reverse("notification_read_and_redirect", kwargs={"pk": notif.pk})
            response = self.client.get(url)
            self.assertRedirects(response, reverse("notification_list"))
            notif.refresh_from_db()
            self.assertTrue(notif.is_read)

    def test_pagination_when_exceeding_page_size(self):
        for i in range(20):
            Notification.objects.create(
                recipient=self.user,
                notification_type=Notification.NotificationType.APPLICATION_SUBMITTED,
                title=f"Notification {i}",
                message=f"Message {i}",
            )

        self.client.login(username="candidate1", password="Testpass123!")
        url = reverse("notification_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # Should contain page 1 of 2
        self.assertContains(response, "Page 1 of 2")
        self.assertEqual(len(response.context["notifications"]), 15)

        # Page 2
        response2 = self.client.get(url + "?page=2")
        self.assertEqual(response2.status_code, 200)
        self.assertContains(response2, "Page 2 of 2")
        self.assertEqual(len(response2.context["notifications"]), 5)

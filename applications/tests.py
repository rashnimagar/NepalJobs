import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    CV,
    Education,
    EmployerProfile,
    Experience,
    JobseekerProfile,
    Skill,
)
from applications.admin import (
    ApplicationAdmin,
    ApplicationStatusHistoryAdmin,
    InterviewAdmin,
)
from applications.forms import (
    ApplicationStatusUpdateForm,
    InterviewScheduleForm,
    JobApplicationForm,
)
from applications.models import Application, ApplicationStatusHistory, Interview
from jobs.models import Category, Job, Location

User = get_user_model()


def make_pdf(name="resume.pdf", size_bytes=1024):
    return SimpleUploadedFile(
        name, b"%PDF-1.4 " + b"x" * max(0, size_bytes - 10), content_type="application/pdf"
    )


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
        category, _ = Category.objects.get_or_create(name="Tech", defaults={"slug": "tech"})
    if location is None:
        location, _ = Location.objects.get_or_create(name="Patan", defaults={"slug": "patan"})
    return Job.objects.create(
        employer=employer_profile,
        category=category,
        location=location,
        title=title,
        description="A great engineering opportunity.",
        application_deadline=timezone.localdate() + timedelta(days=days_to_deadline),
        status=status,
        published_at=timezone.now() if status == Job.Status.PUBLISHED else None,
    )


class ApplicationModelTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer()
        self.candidate_user = make_jobseeker()
        self.job = create_job(self.employer_user.employer_profile)
        self.profile = self.candidate_user.jobseeker_profile

    def test_application_creation_and_defaults(self):
        app = Application.objects.create(
            job=self.job,
            jobseeker=self.profile,
            cover_letter="I am very excited about this role.",
        )
        self.assertEqual(app.status, Application.Status.APPLIED)
        self.assertEqual(app.status, "applied")
        self.assertIsNotNone(app.created_at)
        self.assertIsNotNone(app.updated_at)
        self.assertIn(self.job.title, str(app))
        self.assertIn("Applied", str(app))

    def test_all_status_choices(self):
        statuses = [
            Application.Status.APPLIED,
            Application.Status.UNDER_REVIEW,
            Application.Status.SHORTLISTED,
            Application.Status.INTERVIEW,
            Application.Status.SELECTED,
            Application.Status.REJECTED,
        ]
        app = Application.objects.create(
            job=self.job,
            jobseeker=self.profile,
        )
        for st in statuses:
            app.status = st
            app.save()
            app.refresh_from_db()
            self.assertEqual(app.status, st)

    def test_unique_job_application_constraint(self):
        Application.objects.create(
            job=self.job,
            jobseeker=self.profile,
        )
        with self.assertRaises(IntegrityError):
            Application.objects.create(
                job=self.job,
                jobseeker=self.profile,
            )

    def test_ordering_is_newest_first(self):
        job2 = create_job(self.employer_user.employer_profile, title="DevOps Engineer")
        cand2_user = make_jobseeker(username="cand2", email="cand2@example.com")

        app1 = Application.objects.create(job=self.job, jobseeker=self.profile)
        app2 = Application.objects.create(job=job2, jobseeker=cand2_user.jobseeker_profile)

        apps = list(Application.objects.all())
        self.assertEqual(apps[0], app2)
        self.assertEqual(apps[1], app1)

    def test_cascade_delete_job(self):
        Application.objects.create(job=self.job, jobseeker=self.profile)
        self.assertEqual(Application.objects.count(), 1)
        self.job.delete()
        self.assertEqual(Application.objects.count(), 0)

    def test_cascade_delete_jobseeker(self):
        Application.objects.create(job=self.job, jobseeker=self.profile)
        self.assertEqual(Application.objects.count(), 1)
        self.candidate_user.delete()
        self.assertEqual(Application.objects.count(), 0)

    def test_set_null_on_cv_delete(self):
        cv = CV.objects.create(
            profile=self.profile,
            title="Standard CV",
            original_filename="standard.pdf",
            file=make_pdf(),
        )
        app = Application.objects.create(job=self.job, jobseeker=self.profile, cv=cv)
        self.assertEqual(app.cv, cv)
        cv.delete()
        app.refresh_from_db()
        self.assertIsNone(app.cv)


class TempMediaTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.temp_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)
        super().tearDownClass()


class ApplicationTransitionModelTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer()
        self.candidate_user = make_jobseeker()
        self.job = create_job(self.employer_user.employer_profile)
        self.profile = self.candidate_user.jobseeker_profile
        self.application = Application.objects.create(
            job=self.job,
            jobseeker=self.profile,
            status=Application.Status.APPLIED,
        )

    def test_valid_transitions(self):
        # 1. Applied -> Under Review
        self.assertTrue(self.application.can_transition_to(Application.Status.UNDER_REVIEW))
        h1 = self.application.transition_to(
            Application.Status.UNDER_REVIEW,
            changed_by=self.employer_user,
            notes="Reviewed candidate portfolio.",
        )
        self.assertEqual(self.application.status, Application.Status.UNDER_REVIEW)
        self.assertEqual(h1.old_status, Application.Status.APPLIED)
        self.assertEqual(h1.new_status, Application.Status.UNDER_REVIEW)
        self.assertEqual(h1.changed_by, self.employer_user)
        self.assertEqual(h1.notes, "Reviewed candidate portfolio.")

        # 2. Under Review -> Shortlisted
        self.assertTrue(self.application.can_transition_to(Application.Status.SHORTLISTED))
        h2 = self.application.transition_to(
            Application.Status.SHORTLISTED,
            changed_by=self.employer_user,
            notes="Shortlisted for technical round.",
        )
        self.assertEqual(self.application.status, Application.Status.SHORTLISTED)
        self.assertEqual(h2.old_status, Application.Status.UNDER_REVIEW)
        self.assertEqual(h2.new_status, Application.Status.SHORTLISTED)

        # 3. Shortlisted -> Interview
        self.assertTrue(self.application.can_transition_to(Application.Status.INTERVIEW))
        h3 = self.application.transition_to(
            Application.Status.INTERVIEW,
            changed_by=self.employer_user,
            notes="Invited to technical interview.",
        )
        self.assertEqual(self.application.status, Application.Status.INTERVIEW)
        self.assertEqual(h3.old_status, Application.Status.SHORTLISTED)
        self.assertEqual(h3.new_status, Application.Status.INTERVIEW)

        # 4. Interview -> Selected
        self.assertTrue(self.application.can_transition_to(Application.Status.SELECTED))
        h4 = self.application.transition_to(
            Application.Status.SELECTED,
            changed_by=self.employer_user,
            notes="Offer extended and accepted.",
        )
        self.assertEqual(self.application.status, Application.Status.SELECTED)
        self.assertEqual(h4.old_status, Application.Status.INTERVIEW)
        self.assertEqual(h4.new_status, Application.Status.SELECTED)
        self.assertTrue(self.application.is_terminal)

    def test_rejection_from_any_active_stage(self):
        stages = [
            Application.Status.APPLIED,
            Application.Status.UNDER_REVIEW,
            Application.Status.SHORTLISTED,
            Application.Status.INTERVIEW,
        ]
        for stage in stages:
            app = Application.objects.create(
                job=create_job(self.employer_user.employer_profile, title=f"Job {stage}"),
                jobseeker=make_jobseeker(username=f"user_{stage}", email=f"user_{stage}@example.com").jobseeker_profile,
                status=stage,
            )
            self.assertTrue(app.can_transition_to(Application.Status.REJECTED))
            h = app.transition_to(
                Application.Status.REJECTED,
                changed_by=self.employer_user,
                notes="Candidate not a match.",
            )
            self.assertEqual(app.status, Application.Status.REJECTED)
            self.assertEqual(h.old_status, stage)
            self.assertEqual(h.new_status, Application.Status.REJECTED)
            self.assertTrue(app.is_terminal)

    def test_illegal_status_jumps_raise_validation_error(self):
        illegal_transitions = [
            (Application.Status.APPLIED, Application.Status.SHORTLISTED),
            (Application.Status.APPLIED, Application.Status.INTERVIEW),
            (Application.Status.APPLIED, Application.Status.SELECTED),
            (Application.Status.UNDER_REVIEW, Application.Status.INTERVIEW),
            (Application.Status.UNDER_REVIEW, Application.Status.SELECTED),
            (Application.Status.SHORTLISTED, Application.Status.SELECTED),
            (Application.Status.INTERVIEW, Application.Status.UNDER_REVIEW),
            (Application.Status.INTERVIEW, Application.Status.SHORTLISTED),
        ]
        for current, target in illegal_transitions:
            self.application.status = current
            self.application.save()
            self.assertFalse(self.application.can_transition_to(target))
            with self.assertRaises(ValidationError):
                self.application.transition_to(target)

    def test_terminal_states_cannot_transition(self):
        for terminal_status in [Application.Status.SELECTED, Application.Status.REJECTED]:
            self.application.status = terminal_status
            self.application.save()
            self.assertTrue(self.application.is_terminal)
            for any_status in Application.Status.values:
                self.assertFalse(self.application.can_transition_to(any_status))
                with self.assertRaises(ValidationError):
                    self.application.transition_to(any_status)

    def test_transition_to_same_status_raises_validation_error(self):
        self.application.status = Application.Status.APPLIED
        self.application.save()
        with self.assertRaises(ValidationError):
            self.application.transition_to(Application.Status.APPLIED)

    def test_transition_to_unknown_status_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            self.application.transition_to("non_existent_status")

    def test_atomic_rollback_on_history_failure(self):
        initial_status = self.application.status
        with patch.object(ApplicationStatusHistory.objects, "create", side_effect=Exception("DB Error")):
            with self.assertRaises(Exception):
                self.application.transition_to(Application.Status.UNDER_REVIEW)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, initial_status)
        self.assertEqual(self.application.status_history.count(), 0)


class ApplicationStatusUpdateFormTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer()
        self.candidate_user = make_jobseeker()
        self.job = create_job(self.employer_user.employer_profile)
        self.profile = self.candidate_user.jobseeker_profile
        self.app_applied = Application.objects.create(
            job=self.job,
            jobseeker=self.profile,
            status=Application.Status.APPLIED,
        )

    def test_form_choices_for_applied_status(self):
        form = ApplicationStatusUpdateForm(instance=self.app_applied)
        expected_choices = [
            ("under_review", "Under Review"),
            ("rejected", "Rejected"),
        ]
        self.assertEqual(form.fields["status"].choices, expected_choices)

    def test_form_choices_for_under_review_status(self):
        app = Application.objects.create(
            job=self.job,
            jobseeker=make_jobseeker(username="u_rev", email="rev@example.com").jobseeker_profile,
            status=Application.Status.UNDER_REVIEW,
        )
        form = ApplicationStatusUpdateForm(instance=app)
        expected_choices = [
            ("shortlisted", "Shortlisted"),
            ("rejected", "Rejected"),
        ]
        self.assertEqual(form.fields["status"].choices, expected_choices)

    def test_form_choices_for_shortlisted_status(self):
        app = Application.objects.create(
            job=self.job,
            jobseeker=make_jobseeker(username="u_short", email="short@example.com").jobseeker_profile,
            status=Application.Status.SHORTLISTED,
        )
        form = ApplicationStatusUpdateForm(instance=app)
        expected_choices = [
            ("interview", "Interview"),
            ("rejected", "Rejected"),
        ]
        self.assertEqual(form.fields["status"].choices, expected_choices)

    def test_form_choices_for_interview_status(self):
        app = Application.objects.create(
            job=self.job,
            jobseeker=make_jobseeker(username="u_int", email="int@example.com").jobseeker_profile,
            status=Application.Status.INTERVIEW,
        )
        form = ApplicationStatusUpdateForm(instance=app)
        expected_choices = [
            ("selected", "Selected"),
            ("rejected", "Rejected"),
        ]
        self.assertEqual(form.fields["status"].choices, expected_choices)

    def test_form_disabled_for_terminal_status(self):
        for terminal in [Application.Status.SELECTED, Application.Status.REJECTED]:
            app = Application.objects.create(
                job=self.job,
                jobseeker=make_jobseeker(username=f"u_{terminal}", email=f"{terminal}@example.com").jobseeker_profile,
                status=terminal,
            )
            form = ApplicationStatusUpdateForm(instance=app)
            self.assertTrue(form.fields["status"].disabled)
            self.assertEqual(form.fields["status"].choices, [])

    def test_submitting_illegal_jump_fails_validation(self):
        form = ApplicationStatusUpdateForm(
            data={"status": Application.Status.SELECTED, "notes": "Hacking the pipeline"},
            instance=self.app_applied,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("status", form.errors)

    def test_submitting_valid_status_succeeds(self):
        form = ApplicationStatusUpdateForm(
            data={"status": Application.Status.UNDER_REVIEW, "notes": "Screening now"},
            instance=self.app_applied,
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["status"], Application.Status.UNDER_REVIEW)
        self.assertEqual(form.cleaned_data["notes"], "Screening now")


class EmployerRecruitmentManagementTests(TempMediaTestCase):
    def setUp(self):
        self.temp_settings = override_settings(PRIVATE_MEDIA_ROOT=self.temp_dir)
        self.temp_settings.enable()

        self.employer_a_user = make_employer(username="emp_a_rec", email="emp_a_rec@example.com")
        self.employer_b_user = make_employer(username="emp_b_rec", email="emp_b_rec@example.com")

        self.job_a = create_job(self.employer_a_user.employer_profile, title="Backend Developer")
        self.job_b = create_job(self.employer_b_user.employer_profile, title="Frontend Developer")

        self.candidate_user = make_jobseeker(username="candidate_rec", email="cand_rec@example.com")
        self.profile = self.candidate_user.jobseeker_profile

        self.cv = CV.objects.create(
            profile=self.profile,
            title="Senior Resume",
            original_filename="resume_senior.pdf",
            file=make_pdf(),
            is_active=True,
            is_default=True,
        )

        self.app_a = Application.objects.create(
            job=self.job_a,
            jobseeker=self.profile,
            cv=self.cv,
            cover_letter="Cover letter for Job A",
            status=Application.Status.APPLIED,
        )
        self.app_b = Application.objects.create(
            job=self.job_b,
            jobseeker=self.profile,
            cv=self.cv,
            cover_letter="Cover letter for Job B",
            status=Application.Status.APPLIED,
        )

    def tearDown(self):
        self.temp_settings.disable()
        super().tearDown()

    def test_anonymous_access_redirects_to_login(self):
        response = self.client.get(reverse("employer_application_detail", args=[self.app_a.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_jobseeker_access_denied(self):
        self.client.force_login(self.candidate_user)
        response = self.client.get(reverse("employer_application_detail", args=[self.app_a.pk]))
        self.assertEqual(response.status_code, 403)

    def test_pending_employer_access_denied(self):
        pending_emp = make_employer(
            username="pending_rec",
            email="pending_rec@example.com",
            verification_status=EmployerProfile.VerificationStatus.PENDING,
        )
        self.client.force_login(pending_emp)
        response = self.client.get(reverse("employer_application_detail", args=[self.app_a.pk]))
        self.assertEqual(response.status_code, 403)

    def test_rejected_employer_access_denied(self):
        rejected_emp = make_employer(
            username="rejected_rec",
            email="rejected_rec@example.com",
            verification_status=EmployerProfile.VerificationStatus.REJECTED,
        )
        self.client.force_login(rejected_emp)
        response = self.client.get(reverse("employer_application_detail", args=[self.app_a.pk]))
        self.assertEqual(response.status_code, 403)

    def test_approved_employer_can_view_own_application_detail(self):
        self.client.force_login(self.employer_a_user)
        response = self.client.get(reverse("employer_application_detail", args=[self.app_a.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "applications/employer_application_detail.html")
        content = response.content.decode()
        self.assertIn("Jane Doe", content)
        self.assertIn("Backend Developer", content)
        self.assertIn("Cover letter for Job A", content)
        self.assertIn("resume_senior.pdf", content)

    def test_cross_employer_idor_get_returns_404(self):
        self.client.force_login(self.employer_a_user)
        # Attempting to access Employer B's application returns 404
        response = self.client.get(reverse("employer_application_detail", args=[self.app_b.pk]))
        self.assertEqual(response.status_code, 404)

    def test_cross_employer_idor_post_returns_404(self):
        self.client.force_login(self.employer_a_user)
        # Attempting to POST status change to Employer B's application returns 404
        response = self.client.post(
            reverse("employer_application_detail", args=[self.app_b.pk]),
            {"status": Application.Status.UNDER_REVIEW, "notes": "Hacked status"},
        )
        self.assertEqual(response.status_code, 404)
        self.app_b.refresh_from_db()
        self.assertEqual(self.app_b.status, Application.Status.APPLIED)

    def test_approved_employer_successful_status_update(self):
        self.client.force_login(self.employer_a_user)
        response = self.client.post(
            reverse("employer_application_detail", args=[self.app_a.pk]),
            {"status": Application.Status.UNDER_REVIEW, "notes": "Looks promising."},
        )
        self.assertRedirects(response, reverse("employer_application_detail", args=[self.app_a.pk]))
        self.app_a.refresh_from_db()
        self.assertEqual(self.app_a.status, Application.Status.UNDER_REVIEW)
        self.assertEqual(self.app_a.status_history.count(), 1)
        history = self.app_a.status_history.first()
        self.assertEqual(history.old_status, Application.Status.APPLIED)
        self.assertEqual(history.new_status, Application.Status.UNDER_REVIEW)
        self.assertEqual(history.changed_by, self.employer_a_user)
        self.assertEqual(history.notes, "Looks promising.")

    def test_illegal_status_jump_post_fails_validation(self):
        self.client.force_login(self.employer_a_user)
        response = self.client.post(
            reverse("employer_application_detail", args=[self.app_a.pk]),
            {"status": Application.Status.SELECTED, "notes": "Skipping screening"},
        )
        self.assertEqual(response.status_code, 200)
        self.app_a.refresh_from_db()
        self.assertEqual(self.app_a.status, Application.Status.APPLIED)
        self.assertEqual(self.app_a.status_history.count(), 0)

    def test_terminal_application_cannot_be_updated_via_post(self):
        self.app_a.status = Application.Status.REJECTED
        self.app_a.save()
        self.client.force_login(self.employer_a_user)
        response = self.client.post(
            reverse("employer_application_detail", args=[self.app_a.pk]),
            {"status": Application.Status.UNDER_REVIEW, "notes": "Reopen"},
        )
        self.assertRedirects(response, reverse("employer_application_detail", args=[self.app_a.pk]))
        self.app_a.refresh_from_db()
        self.assertEqual(self.app_a.status, Application.Status.REJECTED)


class ClosedAndExpiredJobRecruitmentTests(TempMediaTestCase):
    def setUp(self):
        self.temp_settings = override_settings(PRIVATE_MEDIA_ROOT=self.temp_dir)
        self.temp_settings.enable()

        self.employer_user = make_employer()
        self.candidate_user = make_jobseeker()
        self.profile = self.candidate_user.jobseeker_profile

        self.closed_job = create_job(
            self.employer_user.employer_profile,
            title="Closed Job Position",
            status=Job.Status.CLOSED,
        )
        self.expired_job = create_job(
            self.employer_user.employer_profile,
            title="Expired Job Position",
            status=Job.Status.PUBLISHED,
            days_to_deadline=-5,
        )

        self.app_closed = Application.objects.create(
            job=self.closed_job,
            jobseeker=self.profile,
            status=Application.Status.APPLIED,
        )
        self.app_expired = Application.objects.create(
            job=self.expired_job,
            jobseeker=self.profile,
            status=Application.Status.APPLIED,
        )

    def tearDown(self):
        self.temp_settings.disable()
        super().tearDown()

    def test_employer_can_view_and_process_applications_for_closed_job(self):
        self.client.force_login(self.employer_user)
        # GET applicant list
        response_list = self.client.get(reverse("employer_job_applicants", args=[self.closed_job.pk]))
        self.assertEqual(response_list.status_code, 200)

        # GET application detail
        response_detail = self.client.get(reverse("employer_application_detail", args=[self.app_closed.pk]))
        self.assertEqual(response_detail.status_code, 200)

        # POST status update on closed job
        response_post = self.client.post(
            reverse("employer_application_detail", args=[self.app_closed.pk]),
            {"status": Application.Status.UNDER_REVIEW, "notes": "Reviewing applicant after job closure."},
        )
        self.assertRedirects(response_post, reverse("employer_application_detail", args=[self.app_closed.pk]))
        self.app_closed.refresh_from_db()
        self.assertEqual(self.app_closed.status, Application.Status.UNDER_REVIEW)

    def test_employer_can_view_and_process_applications_for_expired_job(self):
        self.client.force_login(self.employer_user)
        # GET application detail
        response_detail = self.client.get(reverse("employer_application_detail", args=[self.app_expired.pk]))
        self.assertEqual(response_detail.status_code, 200)

        # POST status update on expired job
        response_post = self.client.post(
            reverse("employer_application_detail", args=[self.app_expired.pk]),
            {"status": Application.Status.UNDER_REVIEW, "notes": "Reviewing after deadline passed."},
        )
        self.assertRedirects(response_post, reverse("employer_application_detail", args=[self.app_expired.pk]))
        self.app_expired.refresh_from_db()
        self.assertEqual(self.app_expired.status, Application.Status.UNDER_REVIEW)

    def test_candidates_still_blocked_from_new_applications_to_closed_or_expired_jobs(self):
        cv = CV.objects.create(profile=self.profile, title="Resume", file=make_pdf())
        cand2 = make_jobseeker(username="cand2_test", email="c2@example.com")
        CV.objects.create(profile=cand2.jobseeker_profile, title="C2 Resume", file=make_pdf())
        self.client.force_login(cand2)

        # Blocked on closed job
        resp_closed = self.client.post(reverse("apply_job", args=[self.closed_job.pk]), {"cv": cv.pk})
        self.assertRedirects(resp_closed, reverse("job_list"))

        # Blocked on expired job
        resp_expired = self.client.post(reverse("apply_job", args=[self.expired_job.pk]), {"cv": cv.pk})
        self.assertRedirects(resp_expired, reverse("job_list"))


class CandidateStatusVisibilityTests(TempMediaTestCase):
    def setUp(self):
        self.temp_settings = override_settings(PRIVATE_MEDIA_ROOT=self.temp_dir)
        self.temp_settings.enable()

        self.employer_user = make_employer()
        self.candidate_user = make_jobseeker()
        self.profile = self.candidate_user.jobseeker_profile
        self.job = create_job(self.employer_user.employer_profile, title="Senior Fullstack Dev")

        self.application = Application.objects.create(
            job=self.job,
            jobseeker=self.profile,
            status=Application.Status.APPLIED,
        )

    def tearDown(self):
        self.temp_settings.disable()
        super().tearDown()

    def test_candidate_sees_active_pipeline_stepper(self):
        self.client.force_login(self.candidate_user)
        response = self.client.get(reverse("jobseeker_application_detail", args=[self.application.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Recruitment Progress", content)
        self.assertIn("Applied", content)
        self.assertIn("Under Review", content)
        self.assertIn("Shortlisted", content)
        self.assertIn("Interview", content)
        self.assertIn("Selected", content)
        self.assertIn("Current", content)

    def test_candidate_sees_rejected_banner(self):
        self.application.status = Application.Status.REJECTED
        self.application.save()
        self.client.force_login(self.candidate_user)
        response = self.client.get(reverse("jobseeker_application_detail", args=[self.application.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Application Status: Not Selected", content)
        self.assertIn("decided to proceed with other candidates", content)

    def test_internal_employer_notes_never_appear_in_candidate_html(self):
        secret_notes = "CONFIDENTIAL: Internal hiring committee notes candidate salary demands are too high."
        self.application.transition_to(
            Application.Status.UNDER_REVIEW,
            changed_by=self.employer_user,
            notes=secret_notes,
        )
        self.client.force_login(self.candidate_user)
        response = self.client.get(reverse("jobseeker_application_detail", args=[self.application.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(secret_notes, content)
        self.assertNotIn("CONFIDENTIAL", content)

    def test_candidate_view_has_no_status_form(self):
        self.client.force_login(self.candidate_user)
        response = self.client.get(reverse("jobseeker_application_detail", args=[self.application.pk]))
        content = response.content.decode()
        self.assertNotIn("Update Status", content)
        self.assertNotIn("<select name=\"status\"", content)

    def test_last_updated_rendered(self):
        self.client.force_login(self.candidate_user)
        response = self.client.get(reverse("jobseeker_application_detail", args=[self.application.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Last updated:", response.content.decode())

    def test_guidance_for_all_canonical_statuses(self):
        self.client.force_login(self.candidate_user)
        expected_guidance = {
            Application.Status.APPLIED: "Your application was received and is pending employer review.",
            Application.Status.UNDER_REVIEW: "The recruitment team is evaluating your CV and qualifications.",
            Application.Status.SHORTLISTED: "You have been shortlisted. The employer is reviewing candidates for the next stage.",
            Application.Status.INTERVIEW: "You have reached the interview stage. The employer will provide interview details through the appropriate recruitment process.",
            Application.Status.SELECTED: "You have been selected for this role. The hiring team will be in touch regarding next steps.",
            Application.Status.REJECTED: "Your application was not selected for this opportunity. We encourage you to continue exploring other roles.",
        }
        for st, expected_text in expected_guidance.items():
            self.application.status = st
            self.application.save()
            response = self.client.get(reverse("jobseeker_application_detail", args=[self.application.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertIn(expected_text, response.content.decode())

    def test_applied_timeline_event_from_created_at(self):
        self.client.force_login(self.candidate_user)
        response = self.client.get(reverse("jobseeker_application_detail", args=[self.application.pk]))
        self.assertEqual(response.status_code, 200)
        timeline = response.context["timeline_events"]
        self.assertGreaterEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["status"], Application.Status.APPLIED)
        self.assertEqual(timeline[0]["timestamp"], self.application.created_at)

    def test_transition_history_dates_and_stages_displayed(self):
        self.application.transition_to(
            Application.Status.UNDER_REVIEW,
            changed_by=self.employer_user,
            notes="Reviewing resume",
        )
        self.client.force_login(self.candidate_user)
        response = self.client.get(reverse("jobseeker_application_detail", args=[self.application.pk]))
        self.assertEqual(response.status_code, 200)
        timeline = response.context["timeline_events"]
        self.assertEqual(len(timeline), 2)
        self.assertEqual(timeline[1]["status"], Application.Status.UNDER_REVIEW)
        self.assertIn("Status Timeline", response.content.decode())
        self.assertIn("Under Review", response.content.decode())

    def test_changed_by_and_notes_never_rendered_even_with_history(self):
        reviewer_name = "secret_reviewer_99"
        reviewer_user = make_employer(username=reviewer_name, email="secret_rev@example.com")
        secret_notes = "INTERNAL ONLY: Candidate scored 85% on coding test."
        self.application.transition_to(
            Application.Status.UNDER_REVIEW,
            changed_by=reviewer_user,
            notes=secret_notes,
        )
        self.client.force_login(self.candidate_user)
        response = self.client.get(reverse("jobseeker_application_detail", args=[self.application.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(reviewer_name, content)
        self.assertNotIn(secret_notes, content)
        self.assertNotIn("INTERNAL ONLY", content)

    def test_candidate_detail_post_method_is_read_only(self):
        self.client.force_login(self.candidate_user)
        response = self.client.post(
            reverse("jobseeker_application_detail", args=[self.application.pk]),
            {"status": Application.Status.SELECTED},
        )
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.APPLIED)


class CandidateApplicationListEnhancementTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer(username="emp_enh_list", email="emp_enh_list@example.com")
        self.employer = self.employer_user.employer_profile
        self.candidate = make_jobseeker(username="cand_list_enh", email="cand_list@example.com")
        self.other_candidate = make_jobseeker(username="other_cand_list", email="other_cand_list@example.com")

        # Create 15 jobs and applications across different statuses
        self.jobs = [
            create_job(self.employer, title=f"Job {i}") for i in range(15)
        ]
        statuses = [
            Application.Status.APPLIED,
            Application.Status.UNDER_REVIEW,
            Application.Status.SHORTLISTED,
            Application.Status.INTERVIEW,
            Application.Status.SELECTED,
            Application.Status.REJECTED,
        ]
        self.apps = []
        for i, job in enumerate(self.jobs):
            st = statuses[i % len(statuses)]
            app = Application.objects.create(
                job=job,
                jobseeker=self.candidate.jobseeker_profile,
                status=st,
            )
            self.apps.append(app)

        # Other candidate application
        self.other_app = Application.objects.create(
            job=self.jobs[0],
            jobseeker=self.other_candidate.jobseeker_profile,
            status=Application.Status.APPLIED,
        )

    def test_candidate_list_all_applications(self):
        self.client.force_login(self.candidate)
        response = self.client.get(reverse("jobseeker_application_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["status_counts"]["total"], 15)
        self.assertEqual(response.context["current_status"], "all")
        # Page size is 10
        self.assertEqual(len(response.context["applications"]), 10)
        self.assertNotIn(self.other_app, response.context["applications"])

    def test_candidate_list_status_filter_each_status(self):
        self.client.force_login(self.candidate)
        for st in Application.Status.values:
            response = self.client.get(f"{reverse('jobseeker_application_list')}?status={st}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["current_status"], st)
            for app in response.context["applications"]:
                self.assertEqual(app.status, st)

    def test_candidate_list_invalid_status_falls_back_to_all(self):
        self.client.force_login(self.candidate)
        response = self.client.get(f"{reverse('jobseeker_application_list')}?status=invalid_status_xyz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_status"], "all")
        self.assertEqual(response.context["status_counts"]["total"], 15)

    def test_candidate_list_status_counts(self):
        self.client.force_login(self.candidate)
        response = self.client.get(reverse("jobseeker_application_list"))
        counts = response.context["status_counts"]
        self.assertEqual(counts["total"], 15)
        self.assertEqual(
            counts["applied"] + counts["under_review"] + counts["shortlisted"] +
            counts["interview"] + counts["selected"] + counts["rejected"],
            15
        )

    def test_candidate_list_pagination_first_and_second_page(self):
        self.client.force_login(self.candidate)
        response_p1 = self.client.get(reverse("jobseeker_application_list"))
        self.assertEqual(len(response_p1.context["applications"]), 10)
        self.assertTrue(response_p1.context["page_obj"].has_next())

        response_p2 = self.client.get(f"{reverse('jobseeker_application_list')}?page=2")
        self.assertEqual(len(response_p2.context["applications"]), 5)
        self.assertFalse(response_p2.context["page_obj"].has_next())

    def test_candidate_list_out_of_range_page_handled_safely(self):
        self.client.force_login(self.candidate)
        # Out of range returns last page
        response = self.client.get(f"{reverse('jobseeker_application_list')}?page=999")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 2)

        # Invalid page returns first page
        response_invalid = self.client.get(f"{reverse('jobseeker_application_list')}?page=abc")
        self.assertEqual(response_invalid.status_code, 200)
        self.assertEqual(response_invalid.context["page_obj"].number, 1)

    def test_candidate_list_status_filter_preserved_in_pagination(self):
        # Create 12 applications with status 'applied'
        more_jobs = [create_job(self.employer, title=f"Extra Job {i}") for i in range(12)]
        for job in more_jobs:
            Application.objects.create(
                job=job,
                jobseeker=self.candidate.jobseeker_profile,
                status=Application.Status.APPLIED,
            )
        self.client.force_login(self.candidate)
        response = self.client.get(f"{reverse('jobseeker_application_list')}?status=applied&page=1")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("status=applied", content)
        self.assertIn("page=2", content)

    def test_candidate_list_strictly_scoped_to_authenticated_candidate(self):
        self.client.force_login(self.candidate)
        response = self.client.get(reverse("jobseeker_application_list"))
        apps = list(response.context["applications"])
        self.assertNotIn(self.other_app, apps)


class ApplicantListStatusFilterTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer()
        self.job = create_job(self.employer_user.employer_profile, title="Data Engineer")

        # Create applicants across various statuses
        self.apps = {}
        for st in Application.Status.values:
            u = make_jobseeker(username=f"filter_user_{st}", email=f"f_{st}@example.com")
            self.apps[st] = Application.objects.create(
                job=self.job,
                jobseeker=u.jobseeker_profile,
                status=st,
            )

    def test_filter_all_returns_all_applicants(self):
        self.client.force_login(self.employer_user)
        response = self.client.get(reverse("employer_job_applicants", args=[self.job.pk]))
        self.assertEqual(response.status_code, 200)
        applicants = list(response.context["applicants"])
        self.assertEqual(len(applicants), len(Application.Status.values))
        self.assertEqual(response.context["status_counts"]["all"], len(Application.Status.values))

    def test_filter_by_individual_status(self):
        self.client.force_login(self.employer_user)
        for st in Application.Status.values:
            response = self.client.get(f"{reverse('employer_job_applicants', args=[self.job.pk])}?status={st}")
            self.assertEqual(response.status_code, 200)
            applicants = list(response.context["applicants"])
            self.assertEqual(len(applicants), 1)
            self.assertEqual(applicants[0].status, st)
            self.assertEqual(response.context["current_status"], st)

    def test_filter_by_invalid_status_falls_back_to_all(self):
        self.client.force_login(self.employer_user)
        response = self.client.get(f"{reverse('employer_job_applicants', args=[self.job.pk])}?status=invalid_xyz")
        self.assertEqual(response.status_code, 200)
        applicants = list(response.context["applicants"])
        self.assertEqual(len(applicants), len(Application.Status.values))
        self.assertEqual(response.context["current_status"], "all")


class CandidateApplicationFlowTests(TempMediaTestCase):
    def setUp(self):
        self.temp_settings = override_settings(PRIVATE_MEDIA_ROOT=self.temp_dir)
        self.temp_settings.enable()

        self.employer_user = make_employer()
        self.employer = self.employer_user.employer_profile
        self.job = create_job(self.employer, title="Senior Python Developer")

        self.candidate_user = make_jobseeker()
        self.profile = self.candidate_user.jobseeker_profile

        self.cv = CV.objects.create(
            profile=self.profile,
            title="Backend Resume",
            original_filename="resume_backend.pdf",
            file=make_pdf(),
            is_active=True,
            is_default=True,
        )

    def tearDown(self):
        self.temp_settings.disable()
        super().tearDown()

    def test_anonymous_apply_redirects_to_login(self):
        response = self.client.get(reverse("apply_job", args=[self.job.pk]))
        self.assertEqual(response.status_code, 302)
        expected_url = f"{reverse('login')}?next={reverse('apply_job', args=[self.job.pk])}"
        self.assertRedirects(response, expected_url)

    def test_employer_cannot_apply(self):
        self.client.force_login(self.employer_user)
        response = self.client.get(reverse("apply_job", args=[self.job.pk]))
        self.assertEqual(response.status_code, 403)

    def test_jobseeker_can_access_apply_page(self):
        self.client.force_login(self.candidate_user)
        response = self.client.get(reverse("apply_job", args=[self.job.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "applications/apply_form.html")
        self.assertEqual(response.context["job"], self.job)

    def test_jobseeker_without_cv_cannot_access_apply_form(self):
        cand_no_cv = make_jobseeker(username="nocv_user", email="nocv@example.com")
        self.client.force_login(cand_no_cv)
        response = self.client.get(reverse("apply_job", args=[self.job.pk]))
        self.assertRedirects(response, reverse("cv_list"))

    def test_default_cv_is_preselected(self):
        cv2 = CV.objects.create(
            profile=self.profile,
            title="Other Resume",
            original_filename="other.pdf",
            file=make_pdf(),
            is_active=True,
            is_default=False,
        )
        self.client.force_login(self.candidate_user)
        response = self.client.get(reverse("apply_job", args=[self.job.pk]))
        form = response.context["form"]
        self.assertEqual(form.initial.get("cv"), self.cv.pk)

    def test_active_cv_is_selectable_and_inactive_cv_is_excluded(self):
        inactive_cv = CV.objects.create(
            profile=self.profile,
            title="Old Resume",
            original_filename="old.pdf",
            file=make_pdf(),
            is_active=False,
        )
        form = JobApplicationForm(jobseeker=self.profile)
        selectable_cvs = list(form.fields["cv"].queryset)
        self.assertIn(self.cv, selectable_cvs)
        self.assertNotIn(inactive_cv, selectable_cvs)

    def test_submitting_inactive_cv_fails_validation(self):
        inactive_cv = CV.objects.create(
            profile=self.profile,
            title="Inactive CV",
            original_filename="inactive.pdf",
            file=make_pdf(),
            is_active=False,
        )
        form = JobApplicationForm(
            data={"cv": inactive_cv.pk, "cover_letter": "Hello"},
            jobseeker=self.profile,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("cv", form.errors)

    def test_submitting_another_candidates_cv_fails_validation(self):
        other_user = make_jobseeker(username="other_cand", email="other_cand@example.com")
        other_cv = CV.objects.create(
            profile=other_user.jobseeker_profile,
            title="Other's CV",
            original_filename="other.pdf",
            file=make_pdf(),
            is_active=True,
        )
        form = JobApplicationForm(
            data={"cv": other_cv.pk, "cover_letter": "Hello"},
            jobseeker=self.profile,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("cv", form.errors)

    def test_successful_application(self):
        self.client.force_login(self.candidate_user)
        post_data = {
            "cv": self.cv.pk,
            "cover_letter": "I have 5 years of Django experience and would love to join Acme Corp.",
        }
        response = self.client.post(reverse("apply_job", args=[self.job.pk]), post_data)
        self.assertEqual(Application.objects.count(), 1)
        app = Application.objects.first()
        self.assertEqual(app.job, self.job)
        self.assertEqual(app.jobseeker, self.profile)
        self.assertEqual(app.cv, self.cv)
        self.assertEqual(app.status, Application.Status.APPLIED)
        self.assertEqual(app.cover_letter, post_data["cover_letter"])
        self.assertRedirects(response, reverse("jobseeker_application_detail", args=[app.pk]))

    def test_duplicate_application_blocked_via_view_and_redirects(self):
        self.client.force_login(self.candidate_user)
        app = Application.objects.create(
            job=self.job,
            jobseeker=self.profile,
            cv=self.cv,
        )
        response_get = self.client.get(reverse("apply_job", args=[self.job.pk]))
        self.assertRedirects(response_get, reverse("jobseeker_application_detail", args=[app.pk]))

        response_post = self.client.post(
            reverse("apply_job", args=[self.job.pk]),
            {"cv": self.cv.pk, "cover_letter": "Duplicate attempt"},
        )
        self.assertEqual(Application.objects.count(), 1)
        self.assertRedirects(response_post, reverse("jobseeker_application_detail", args=[app.pk]))

    def test_closed_job_blocked(self):
        closed_job = create_job(self.employer, title="Closed Position", status=Job.Status.CLOSED)
        self.client.force_login(self.candidate_user)
        response_get = self.client.get(reverse("apply_job", args=[closed_job.pk]))
        self.assertRedirects(response_get, reverse("job_list"))

        response_post = self.client.post(
            reverse("apply_job", args=[closed_job.pk]),
            {"cv": self.cv.pk, "cover_letter": "Should fail"},
        )
        self.assertEqual(Application.objects.count(), 0)
        self.assertRedirects(response_post, reverse("job_list"))

    def test_expired_job_blocked(self):
        expired_job = create_job(
            self.employer,
            title="Expired Position",
            status=Job.Status.PUBLISHED,
            days_to_deadline=-2,
        )
        self.client.force_login(self.candidate_user)
        response_get = self.client.get(reverse("apply_job", args=[expired_job.pk]))
        self.assertRedirects(response_get, reverse("job_list"))

        response_post = self.client.post(
            reverse("apply_job", args=[expired_job.pk]),
            {"cv": self.cv.pk, "cover_letter": "Should fail"},
        )
        self.assertEqual(Application.objects.count(), 0)
        self.assertRedirects(response_post, reverse("job_list"))

    def test_draft_job_blocked(self):
        draft_job = create_job(self.employer, title="Draft Position", status=Job.Status.DRAFT)
        self.client.force_login(self.candidate_user)
        response_get = self.client.get(reverse("apply_job", args=[draft_job.pk]))
        self.assertRedirects(response_get, reverse("job_list"))

        response_post = self.client.post(
            reverse("apply_job", args=[draft_job.pk]),
            {"cv": self.cv.pk, "cover_letter": "Should fail"},
        )
        self.assertEqual(Application.objects.count(), 0)
        self.assertRedirects(response_post, reverse("job_list"))

    def test_unapproved_employer_job_blocked(self):
        pending_emp_user = make_employer(
            username="pending_emp",
            email="pending@example.com",
            verification_status=EmployerProfile.VerificationStatus.PENDING,
        )
        unapproved_job = create_job(
            pending_emp_user.employer_profile,
            title="Unapproved Job",
            status=Job.Status.PUBLISHED,
        )
        self.client.force_login(self.candidate_user)
        response_get = self.client.get(reverse("apply_job", args=[unapproved_job.pk]))
        self.assertRedirects(response_get, reverse("job_list"))

        response_post = self.client.post(
            reverse("apply_job", args=[unapproved_job.pk]),
            {"cv": self.cv.pk, "cover_letter": "Should fail"},
        )
        self.assertEqual(Application.objects.count(), 0)
        self.assertRedirects(response_post, reverse("job_list"))


class CandidateOwnershipTests(TempMediaTestCase):
    def setUp(self):
        self.temp_settings = override_settings(PRIVATE_MEDIA_ROOT=self.temp_dir)
        self.temp_settings.enable()

        self.employer_user = make_employer()
        self.job1 = create_job(self.employer_user.employer_profile, title="Job 1")
        self.job2 = create_job(self.employer_user.employer_profile, title="Job 2")

        self.user1 = make_jobseeker(username="user1", email="u1@example.com")
        self.user2 = make_jobseeker(username="user2", email="u2@example.com")

        self.cv1 = CV.objects.create(
            profile=self.user1.jobseeker_profile,
            title="User 1 CV",
            original_filename="u1.pdf",
            file=make_pdf(),
            is_active=True,
        )
        self.cv2 = CV.objects.create(
            profile=self.user2.jobseeker_profile,
            title="User 2 CV",
            original_filename="u2.pdf",
            file=make_pdf(),
            is_active=True,
        )

        self.app1 = Application.objects.create(
            job=self.job1,
            jobseeker=self.user1.jobseeker_profile,
            cv=self.cv1,
            cover_letter="Cover letter 1",
        )
        self.app2 = Application.objects.create(
            job=self.job2,
            jobseeker=self.user2.jobseeker_profile,
            cv=self.cv2,
            cover_letter="Cover letter 2",
        )

    def tearDown(self):
        self.temp_settings.disable()
        super().tearDown()

    def test_candidate_sees_only_own_applications_in_list(self):
        self.client.force_login(self.user1)
        response = self.client.get(reverse("jobseeker_application_list"))
        self.assertEqual(response.status_code, 200)
        apps = list(response.context["applications"])
        self.assertIn(self.app1, apps)
        self.assertNotIn(self.app2, apps)

    def test_candidate_cannot_access_another_candidates_application_detail(self):
        self.client.force_login(self.user1)
        response = self.client.get(reverse("jobseeker_application_detail", args=[self.app2.pk]))
        self.assertEqual(response.status_code, 404)

    def test_candidate_can_access_own_application_detail(self):
        self.client.force_login(self.user1)
        response = self.client.get(reverse("jobseeker_application_detail", args=[self.app1.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["application"], self.app1)
        content = response.content.decode()
        self.assertIn(self.job1.title, content)
        self.assertIn(self.cv1.original_filename, content)
        self.assertIn("Cover letter 1", content)


class JobDetailUITests(TempMediaTestCase):
    def setUp(self):
        self.temp_settings = override_settings(PRIVATE_MEDIA_ROOT=self.temp_dir)
        self.temp_settings.enable()

        self.employer_user = make_employer()
        self.job = create_job(self.employer_user.employer_profile, title="Frontend React Engineer")

        self.candidate_with_cv = make_jobseeker(username="with_cv", email="with_cv@example.com")
        self.cv = CV.objects.create(
            profile=self.candidate_with_cv.jobseeker_profile,
            title="React Resume",
            original_filename="react_resume.pdf",
            file=make_pdf(),
            is_active=True,
            is_default=True,
        )
        self.candidate_no_cv = make_jobseeker(username="no_cv", email="no_cv@example.com")

    def tearDown(self):
        self.temp_settings.disable()
        super().tearDown()

    def test_anonymous_sees_login_to_apply(self):
        response = self.client.get(reverse("job_detail", args=[self.job.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Login to Apply", content)
        self.assertIn(reverse("apply_job", args=[self.job.pk]), content)

    def test_eligible_jobseeker_sees_apply_now(self):
        self.client.force_login(self.candidate_with_cv)
        response = self.client.get(reverse("job_detail", args=[self.job.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Apply Now", content)
        self.assertIn(reverse("apply_job", args=[self.job.pk]), content)

    def test_no_cv_jobseeker_sees_cv_requirement(self):
        self.client.force_login(self.candidate_no_cv)
        response = self.client.get(reverse("job_detail", args=[self.job.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("CV Required", content)
        self.assertIn(reverse("cv_list"), content)
        self.assertNotIn("Apply Now", content)

    def test_already_applied_jobseeker_sees_already_applied_badge_and_link(self):
        app = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate_with_cv.jobseeker_profile,
            cv=self.cv,
        )
        self.client.force_login(self.candidate_with_cv)
        response = self.client.get(reverse("job_detail", args=[self.job.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Already Applied", content)
        self.assertIn(reverse("jobseeker_application_detail", args=[app.pk]), content)

    def test_employer_sees_employer_restriction(self):
        self.client.force_login(self.employer_user)
        response = self.client.get(reverse("job_detail", args=[self.job.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Employers cannot apply to jobs", content)
        self.assertNotIn("Apply Now", content)


class EmployerVisibilityTests(TempMediaTestCase):
    def setUp(self):
        self.temp_settings = override_settings(PRIVATE_MEDIA_ROOT=self.temp_dir)
        self.temp_settings.enable()

        self.employer_a_user = make_employer(username="emp_a", email="emp_a@example.com")
        self.employer_b_user = make_employer(username="emp_b", email="emp_b@example.com")

        self.job_a = create_job(self.employer_a_user.employer_profile, title="Job at Acme A")
        self.job_b = create_job(self.employer_b_user.employer_profile, title="Job at Beta B")

        self.candidate = make_jobseeker()
        self.cv = CV.objects.create(
            profile=self.candidate.jobseeker_profile,
            title="Candidate CV",
            original_filename="cv.pdf",
            file=make_pdf(),
            is_active=True,
        )

        self.app_a = Application.objects.create(
            job=self.job_a,
            jobseeker=self.candidate.jobseeker_profile,
            cv=self.cv,
            cover_letter="Application for A",
        )
        self.app_b = Application.objects.create(
            job=self.job_b,
            jobseeker=self.candidate.jobseeker_profile,
            cv=self.cv,
            cover_letter="Application for B",
        )

    def tearDown(self):
        self.temp_settings.disable()
        super().tearDown()

    def test_approved_employer_can_view_applicants_for_own_job(self):
        self.client.force_login(self.employer_a_user)
        response = self.client.get(reverse("employer_job_applicants", args=[self.job_a.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "applications/employer_applicant_list.html")
        applicants = list(response.context["applicants"])
        self.assertIn(self.app_a, applicants)
        self.assertNotIn(self.app_b, applicants)

    def test_employer_cannot_view_applicants_for_another_employers_job(self):
        self.client.force_login(self.employer_a_user)
        response = self.client.get(reverse("employer_job_applicants", args=[self.job_b.pk]))
        self.assertEqual(response.status_code, 404)

    def test_pending_employer_denied_access(self):
        pending_emp_user = make_employer(
            username="pending_emp_test",
            email="pending_test@example.com",
            verification_status=EmployerProfile.VerificationStatus.PENDING,
        )
        job_pending = create_job(pending_emp_user.employer_profile, title="Pending Job")
        self.client.force_login(pending_emp_user)
        response = self.client.get(reverse("employer_job_applicants", args=[job_pending.pk]))
        self.assertEqual(response.status_code, 403)

    def test_rejected_employer_denied_access(self):
        rejected_emp_user = make_employer(
            username="rejected_emp_test",
            email="rejected_test@example.com",
            verification_status=EmployerProfile.VerificationStatus.REJECTED,
        )
        job_rejected = create_job(rejected_emp_user.employer_profile, title="Rejected Job")
        self.client.force_login(rejected_emp_user)
        response = self.client.get(reverse("employer_job_applicants", args=[job_rejected.pk]))
        self.assertEqual(response.status_code, 403)


class CVSecurityTests(TempMediaTestCase):
    def setUp(self):
        self.temp_settings = override_settings(PRIVATE_MEDIA_ROOT=self.temp_dir)
        self.temp_settings.enable()

        self.employer_a_user = make_employer(username="emp_sec_a", email="emp_sec_a@example.com")
        self.employer_b_user = make_employer(username="emp_sec_b", email="emp_sec_b@example.com")

        self.job_a = create_job(self.employer_a_user.employer_profile, title="Job at A")
        self.job_b = create_job(self.employer_b_user.employer_profile, title="Job at B")

        self.candidate1 = make_jobseeker(username="cand_sec1", email="cand_sec1@example.com")
        self.candidate2 = make_jobseeker(username="cand_sec2", email="cand_sec2@example.com")

        self.cv1 = CV.objects.create(
            profile=self.candidate1.jobseeker_profile,
            title="Candidate 1 Resume",
            original_filename="resume1.pdf",
            file=make_pdf("resume1.pdf"),
            is_active=True,
        )
        self.cv2 = CV.objects.create(
            profile=self.candidate2.jobseeker_profile,
            title="Candidate 2 Resume",
            original_filename="resume2.pdf",
            file=make_pdf("resume2.pdf"),
            is_active=True,
        )

        self.app1 = Application.objects.create(
            job=self.job_a,
            jobseeker=self.candidate1.jobseeker_profile,
            cv=self.cv1,
        )

    def tearDown(self):
        self.temp_settings.disable()
        super().tearDown()

    def test_cv_owner_can_download_cv(self):
        self.client.force_login(self.candidate1)
        response = self.client.get(reverse("cv_download", args=[self.cv1.pk]))
        self.assertEqual(response.status_code, 200)

    def test_approved_employer_can_download_cv_submitted_to_their_job(self):
        self.client.force_login(self.employer_a_user)
        response = self.client.get(reverse("cv_download", args=[self.cv1.pk]))
        self.assertEqual(response.status_code, 200)

    def test_approved_employer_cannot_download_unrelated_cv(self):
        self.client.force_login(self.employer_b_user)
        response = self.client.get(reverse("cv_download", args=[self.cv1.pk]))
        self.assertEqual(response.status_code, 403)

    def test_employer_cannot_download_unsubmitted_cv_even_knowing_id(self):
        self.client.force_login(self.employer_a_user)
        response = self.client.get(reverse("cv_download", args=[self.cv2.pk]))
        self.assertEqual(response.status_code, 403)

    def test_other_candidate_cannot_download_cv(self):
        self.client.force_login(self.candidate2)
        response = self.client.get(reverse("cv_download", args=[self.cv1.pk]))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirected_on_cv_download(self):
        response = self.client.get(reverse("cv_download", args=[self.cv1.pk]))
        self.assertEqual(response.status_code, 302)


class ApplicationAdminTests(TestCase):
    def test_admin_registration(self):
        self.assertIn(Application, admin.site._registry)
        admin_instance = admin.site._registry[Application]
        self.assertIsInstance(admin_instance, ApplicationAdmin)
        self.assertEqual(
            admin_instance.list_display,
            (
                "job",
                "jobseeker",
                "status",
                "created_at",
                "updated_at",
            ),
        )
        self.assertEqual(admin_instance.list_filter, ("status",))
        self.assertIn("job__title", admin_instance.search_fields)
        self.assertEqual(admin_instance.readonly_fields, ("created_at", "updated_at"))
        self.assertEqual(admin_instance.ordering, ("-created_at",))

    def test_history_admin_registration(self):
        self.assertIn(ApplicationStatusHistory, admin.site._registry)
        history_admin = admin.site._registry[ApplicationStatusHistory]
        self.assertIsInstance(history_admin, ApplicationStatusHistoryAdmin)
        self.assertEqual(
            history_admin.list_display,
            (
                "application",
                "old_status",
                "new_status",
                "changed_by",
                "created_at",
            ),
        )
        self.assertEqual(
            history_admin.list_filter,
            (
                "old_status",
                "new_status",
            ),
        )
        self.assertIn("application__job__title", history_admin.search_fields)
        self.assertEqual(history_admin.ordering, ("-created_at",))


class CandidateDashboardApplicationIntegrationTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer(username="emp_dash", email="emp_dash@example.com")
        self.employer = self.employer_user.employer_profile
        self.candidate = make_jobseeker(username="cand_dash", email="cand_dash@example.com")
        self.other_candidate = make_jobseeker(username="cand_dash_other", email="cand_dash_other@example.com")

        self.jobs = [create_job(self.employer, title=f"Dash Job {i}") for i in range(6)]

    def test_dashboard_empty_state_when_no_applications(self):
        self.client.force_login(self.candidate)
        response = self.client.get(reverse("jobseeker_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_applications"], 0)
        self.assertEqual(response.context["under_review_count"], 0)
        self.assertEqual(response.context["interview_count"], 0)
        self.assertEqual(response.context["selected_count"], 0)
        self.assertEqual(list(response.context["recent_applications"]), [])
        self.assertIn("haven't submitted any job applications yet", response.content.decode())

    def test_dashboard_application_metrics_and_recent_applications(self):
        # Create applications for candidate
        Application.objects.create(job=self.jobs[0], jobseeker=self.candidate.jobseeker_profile, status=Application.Status.APPLIED)
        Application.objects.create(job=self.jobs[1], jobseeker=self.candidate.jobseeker_profile, status=Application.Status.UNDER_REVIEW)
        Application.objects.create(job=self.jobs[2], jobseeker=self.candidate.jobseeker_profile, status=Application.Status.UNDER_REVIEW)
        Application.objects.create(job=self.jobs[3], jobseeker=self.candidate.jobseeker_profile, status=Application.Status.INTERVIEW)
        Application.objects.create(job=self.jobs[4], jobseeker=self.candidate.jobseeker_profile, status=Application.Status.SELECTED)
        Application.objects.create(job=self.jobs[5], jobseeker=self.candidate.jobseeker_profile, status=Application.Status.REJECTED)

        self.client.force_login(self.candidate)
        response = self.client.get(reverse("jobseeker_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_applications"], 6)
        self.assertEqual(response.context["under_review_count"], 2)
        self.assertEqual(response.context["interview_count"], 1)
        self.assertEqual(response.context["selected_count"], 1)

        # Recent applications limited to at most 5
        recent = list(response.context["recent_applications"])
        self.assertEqual(len(recent), 5)
        # Verify rendered content
        content = response.content.decode()
        self.assertIn("Recent Applications", content)
        self.assertIn(self.jobs[5].title, content)

    def test_dashboard_metrics_only_include_current_candidate(self):
        # Create applications for current candidate
        Application.objects.create(job=self.jobs[0], jobseeker=self.candidate.jobseeker_profile, status=Application.Status.APPLIED)
        # Create applications for other candidate
        Application.objects.create(job=self.jobs[1], jobseeker=self.other_candidate.jobseeker_profile, status=Application.Status.INTERVIEW)
        Application.objects.create(job=self.jobs[2], jobseeker=self.other_candidate.jobseeker_profile, status=Application.Status.SELECTED)

        self.client.force_login(self.candidate)
        response = self.client.get(reverse("jobseeker_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_applications"], 1)
        self.assertEqual(response.context["interview_count"], 0)
        self.assertEqual(response.context["selected_count"], 0)


class InterviewModelTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer()
        self.candidate_user = make_jobseeker()
        self.job = create_job(self.employer_user.employer_profile)
        self.application = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate_user.jobseeker_profile,
            status=Application.Status.SHORTLISTED,
        )

    def test_valid_interview_creation(self):
        scheduled_time = timezone.now() + timedelta(days=2)
        interview = Interview.objects.create(
            application=self.application,
            interview_type=Interview.InterviewType.VIDEO,
            status=Interview.InterviewStatus.SCHEDULED,
            scheduled_at=scheduled_time,
            duration_minutes=45,
            location_or_link="https://meet.google.com/abc-defg-hij",
            candidate_instructions="Bring your ID and prepare portfolio.",
            internal_notes="Focus on database indexing and system design.",
            created_by=self.employer_user,
        )
        self.assertEqual(interview.status, Interview.InterviewStatus.SCHEDULED)
        self.assertEqual(interview.interview_type, Interview.InterviewType.VIDEO)
        self.assertEqual(interview.duration_minutes, 45)
        self.assertTrue(interview.is_scheduled)
        self.assertFalse(interview.is_completed)
        self.assertFalse(interview.is_cancelled)
        self.assertIn("Interview for", str(interview))
        self.assertIsNotNone(interview.created_at)
        self.assertIsNotNone(interview.updated_at)

    def test_interview_type_choices(self):
        for itype in [
            Interview.InterviewType.IN_PERSON,
            Interview.InterviewType.VIDEO,
            Interview.InterviewType.PHONE,
        ]:
            interview = Interview(
                application=self.application,
                interview_type=itype,
                scheduled_at=timezone.now() + timedelta(days=1),
                location_or_link="Office Kathmandu",
            )
            interview.full_clean()
            self.assertEqual(interview.interview_type, itype)

    def test_interview_status_choices(self):
        for istatus in [
            Interview.InterviewStatus.SCHEDULED,
            Interview.InterviewStatus.COMPLETED,
            Interview.InterviewStatus.CANCELLED,
        ]:
            interview = Interview(
                application=self.application,
                status=istatus,
                scheduled_at=timezone.now() + timedelta(days=1),
                location_or_link="Office Kathmandu",
            )
            interview.full_clean()
            self.assertEqual(interview.status, istatus)

    def test_positive_duration_validation(self):
        interview = Interview(
            application=self.application,
            scheduled_at=timezone.now() + timedelta(days=1),
            duration_minutes=0,
            location_or_link="Test",
        )
        with self.assertRaises(ValidationError) as ctx:
            interview.full_clean()
        self.assertIn("duration_minutes", ctx.exception.message_dict)

        interview.duration_minutes = -15
        with self.assertRaises(ValidationError) as ctx:
            interview.full_clean()
        self.assertIn("duration_minutes", ctx.exception.message_dict)

    def test_future_scheduled_time_validation(self):
        interview = Interview(
            application=self.application,
            scheduled_at=timezone.now() - timedelta(hours=1),
            location_or_link="Test",
            status=Interview.InterviewStatus.SCHEDULED,
        )
        with self.assertRaises(ValidationError) as ctx:
            interview.full_clean()
        self.assertIn("scheduled_at", ctx.exception.message_dict)

    def test_historical_completed_interview_with_past_date_allowed(self):
        interview = Interview(
            application=self.application,
            scheduled_at=timezone.now() - timedelta(days=10),
            location_or_link="Past Office Meeting",
            status=Interview.InterviewStatus.COMPLETED,
        )
        interview.full_clean()
        interview.save()
        self.assertTrue(interview.is_completed)

    def test_historical_cancelled_interview_with_past_date_allowed(self):
        interview = Interview(
            application=self.application,
            scheduled_at=timezone.now() - timedelta(days=5),
            location_or_link="Cancelled Call",
            status=Interview.InterviewStatus.CANCELLED,
        )
        interview.full_clean()
        interview.save()
        self.assertTrue(interview.is_cancelled)

    def test_cascade_deletion_when_application_is_deleted(self):
        Interview.objects.create(
            application=self.application,
            scheduled_at=timezone.now() + timedelta(days=1),
            location_or_link="https://meet.google.com/test",
        )
        self.assertEqual(Interview.objects.count(), 1)
        self.application.delete()
        self.assertEqual(Interview.objects.count(), 0)

    def test_only_shortlisted_or_interview_application_can_have_new_interview(self):
        for disallowed_status in [
            Application.Status.APPLIED,
            Application.Status.UNDER_REVIEW,
            Application.Status.SELECTED,
            Application.Status.REJECTED,
        ]:
            app = Application.objects.create(
                job=self.job,
                jobseeker=make_jobseeker(
                    username=f"cand_{disallowed_status}",
                    email=f"cand_{disallowed_status}@example.com",
                ).jobseeker_profile,
                status=disallowed_status,
            )
            interview = Interview(
                application=app,
                scheduled_at=timezone.now() + timedelta(days=1),
                location_or_link="Kathmandu",
            )
            with self.assertRaises(ValidationError):
                interview.full_clean()

    def test_duplicate_active_scheduled_interview_rejected(self):
        Interview.objects.create(
            application=self.application,
            scheduled_at=timezone.now() + timedelta(days=1),
            location_or_link="https://zoom.us/j/123",
            status=Interview.InterviewStatus.SCHEDULED,
        )
        second_interview = Interview(
            application=self.application,
            scheduled_at=timezone.now() + timedelta(days=2),
            location_or_link="https://zoom.us/j/456",
            status=Interview.InterviewStatus.SCHEDULED,
        )
        with self.assertRaises(ValidationError):
            second_interview.full_clean()


class EmployerInterviewSchedulingTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer()
        self.candidate_user = make_jobseeker()
        self.job = create_job(self.employer_user.employer_profile)
        self.application = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate_user.jobseeker_profile,
            status=Application.Status.SHORTLISTED,
        )
        self.client.force_login(self.employer_user)

    def test_approved_employer_can_schedule_for_shortlisted_applicant(self):
        scheduled_time = timezone.now() + timedelta(days=3)
        post_data = {
            "interview_type": Interview.InterviewType.VIDEO,
            "scheduled_at": scheduled_time.strftime("%Y-%m-%dT%H:%M"),
            "duration_minutes": 45,
            "location_or_link": "https://meet.google.com/abc-xyz",
            "candidate_instructions": "Review our codebase beforehand.",
            "internal_notes": "Evaluate architectural depth.",
        }
        url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.INTERVIEW)

        histories = list(self.application.status_history.all())
        self.assertEqual(len(histories), 1)
        self.assertEqual(histories[0].old_status, Application.Status.SHORTLISTED)
        self.assertEqual(histories[0].new_status, Application.Status.INTERVIEW)
        self.assertEqual(histories[0].changed_by, self.employer_user)

        interviews = list(self.application.interviews.all())
        self.assertEqual(len(interviews), 1)
        self.assertEqual(interviews[0].location_or_link, "https://meet.google.com/abc-xyz")
        self.assertEqual(interviews[0].created_by, self.employer_user)
        self.assertEqual(interviews[0].status, Interview.InterviewStatus.SCHEDULED)

    def test_approved_employer_can_schedule_for_existing_interview_stage_applicant(self):
        self.application.status = Application.Status.INTERVIEW
        self.application.save()

        scheduled_time = timezone.now() + timedelta(days=2)
        post_data = {
            "interview_type": Interview.InterviewType.IN_PERSON,
            "scheduled_at": scheduled_time.strftime("%Y-%m-%dT%H:%M"),
            "duration_minutes": 60,
            "location_or_link": "Floor 3, Acme Tower, Kathmandu",
            "candidate_instructions": "Bring original certificates.",
            "internal_notes": "Second round technical interview.",
        }
        url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.INTERVIEW)
        self.assertEqual(self.application.status_history.count(), 0)
        self.assertEqual(self.application.interviews.count(), 1)

    def test_cannot_schedule_for_applied_status(self):
        self.application.status = Application.Status.APPLIED
        self.application.save()

        post_data = {
            "interview_type": Interview.InterviewType.PHONE,
            "scheduled_at": (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
            "duration_minutes": 30,
            "location_or_link": "+977-9800000000",
        }
        url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))
        self.assertEqual(self.application.interviews.count(), 0)

    def test_cannot_schedule_for_under_review_status(self):
        self.application.status = Application.Status.UNDER_REVIEW
        self.application.save()

        post_data = {
            "interview_type": Interview.InterviewType.PHONE,
            "scheduled_at": (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
            "duration_minutes": 30,
            "location_or_link": "+977-9800000000",
        }
        url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))
        self.assertEqual(self.application.interviews.count(), 0)

    def test_cannot_schedule_for_selected_terminal_status(self):
        self.application.status = Application.Status.SELECTED
        self.application.save()

        post_data = {
            "interview_type": Interview.InterviewType.PHONE,
            "scheduled_at": (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
            "duration_minutes": 30,
            "location_or_link": "+977-9800000000",
        }
        url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))
        self.assertEqual(self.application.interviews.count(), 0)

    def test_cannot_schedule_for_rejected_terminal_status(self):
        self.application.status = Application.Status.REJECTED
        self.application.save()

        post_data = {
            "interview_type": Interview.InterviewType.PHONE,
            "scheduled_at": (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
            "duration_minutes": 30,
            "location_or_link": "+977-9800000000",
        }
        url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))
        self.assertEqual(self.application.interviews.count(), 0)

    def test_duplicate_active_scheduled_interview_rejected(self):
        Interview.objects.create(
            application=self.application,
            scheduled_at=timezone.now() + timedelta(days=2),
            location_or_link="Office",
            status=Interview.InterviewStatus.SCHEDULED,
        )
        post_data = {
            "interview_type": Interview.InterviewType.VIDEO,
            "scheduled_at": (timezone.now() + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M"),
            "duration_minutes": 30,
            "location_or_link": "https://meet.google.com/test",
        }
        url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))
        self.assertEqual(self.application.interviews.count(), 1)


class InterviewAuthorizationTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer()
        self.other_employer_user = make_employer(username="other_emp", email="other_emp@example.com")
        self.candidate_user = make_jobseeker()
        self.job = create_job(self.employer_user.employer_profile)
        self.application = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate_user.jobseeker_profile,
            status=Application.Status.SHORTLISTED,
        )
        self.interview = Interview.objects.create(
            application=self.application,
            scheduled_at=timezone.now() + timedelta(days=2),
            location_or_link="Kathmandu",
            status=Interview.InterviewStatus.SCHEDULED,
        )

    def test_anonymous_redirected_to_login(self):
        schedule_url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})
        edit_url = reverse("employer_edit_interview", kwargs={"pk": self.interview.pk})
        cancel_url = reverse("employer_cancel_interview", kwargs={"pk": self.interview.pk})

        for url in [schedule_url, edit_url, cancel_url]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("login"), response["Location"])

    def test_jobseeker_denied_employer_scheduling(self):
        self.client.force_login(self.candidate_user)
        schedule_url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})
        response = self.client.get(schedule_url)
        self.assertEqual(response.status_code, 403)

    def test_pending_employer_denied(self):
        pending_emp = make_employer(
            username="pending_emp",
            email="pending@example.com",
            verification_status=EmployerProfile.VerificationStatus.PENDING,
        )
        self.client.force_login(pending_emp)
        schedule_url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})
        response = self.client.get(schedule_url)
        self.assertEqual(response.status_code, 403)

    def test_rejected_employer_denied(self):
        rejected_emp = make_employer(
            username="rejected_emp",
            email="rejected@example.com",
            verification_status=EmployerProfile.VerificationStatus.REJECTED,
        )
        self.client.force_login(rejected_emp)
        schedule_url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})
        response = self.client.get(schedule_url)
        self.assertEqual(response.status_code, 403)

    def test_unrelated_approved_employer_gets_404(self):
        self.client.force_login(self.other_employer_user)
        schedule_url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})
        edit_url = reverse("employer_edit_interview", kwargs={"pk": self.interview.pk})
        cancel_url = reverse("employer_cancel_interview", kwargs={"pk": self.interview.pk})

        self.assertEqual(self.client.get(schedule_url).status_code, 404)
        self.assertEqual(self.client.get(edit_url).status_code, 404)
        self.assertEqual(self.client.post(cancel_url).status_code, 404)


class EmployerInterviewRescheduleTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer()
        self.candidate_user = make_jobseeker()
        self.job = create_job(self.employer_user.employer_profile)
        self.application = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate_user.jobseeker_profile,
            status=Application.Status.INTERVIEW,
        )
        self.interview = Interview.objects.create(
            application=self.application,
            interview_type=Interview.InterviewType.PHONE,
            scheduled_at=timezone.now() + timedelta(days=2),
            duration_minutes=30,
            location_or_link="+977-9811111111",
            candidate_instructions="Initial instructions",
            internal_notes="Initial notes",
            created_by=self.employer_user,
        )
        self.client.force_login(self.employer_user)

    def test_reschedule_active_interview_success(self):
        new_time = timezone.now() + timedelta(days=5)
        post_data = {
            "interview_type": Interview.InterviewType.VIDEO,
            "scheduled_at": new_time.strftime("%Y-%m-%dT%H:%M"),
            "duration_minutes": 60,
            "location_or_link": "https://meet.google.com/updated-link",
            "candidate_instructions": "Updated instructions.",
            "internal_notes": "Updated internal notes.",
        }
        url = reverse("employer_edit_interview", kwargs={"pk": self.interview.pk})
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))

        self.interview.refresh_from_db()
        self.assertEqual(self.interview.interview_type, Interview.InterviewType.VIDEO)
        self.assertEqual(self.interview.duration_minutes, 60)
        self.assertEqual(self.interview.location_or_link, "https://meet.google.com/updated-link")
        self.assertEqual(self.interview.candidate_instructions, "Updated instructions.")
        self.assertEqual(self.interview.internal_notes, "Updated internal notes.")
        self.assertEqual(self.interview.created_by, self.employer_user)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.INTERVIEW)

    def test_cannot_reschedule_cancelled_interview(self):
        self.interview.status = Interview.InterviewStatus.CANCELLED
        self.interview.save()

        url = reverse("employer_edit_interview", kwargs={"pk": self.interview.pk})
        response = self.client.get(url)
        self.assertRedirects(response, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))

    def test_reschedule_validation_failure_with_past_date(self):
        past_time = timezone.now() - timedelta(days=1)
        post_data = {
            "interview_type": Interview.InterviewType.VIDEO,
            "scheduled_at": past_time.strftime("%Y-%m-%dT%H:%M"),
            "duration_minutes": 30,
            "location_or_link": "https://meet.google.com/test",
        }
        url = reverse("employer_edit_interview", kwargs={"pk": self.interview.pk})
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "scheduled_at", "Scheduled interview date and time must be in the future.")


class EmployerInterviewCancellationTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer()
        self.candidate_user = make_jobseeker()
        self.job = create_job(self.employer_user.employer_profile)
        self.application = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate_user.jobseeker_profile,
            status=Application.Status.INTERVIEW,
        )
        self.interview = Interview.objects.create(
            application=self.application,
            scheduled_at=timezone.now() + timedelta(days=2),
            location_or_link="Kathmandu",
            status=Interview.InterviewStatus.SCHEDULED,
        )
        self.client.force_login(self.employer_user)

    def test_employer_can_cancel_scheduled_interview(self):
        url = reverse("employer_cancel_interview", kwargs={"pk": self.interview.pk})
        response = self.client.post(url)
        self.assertRedirects(response, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))

        self.interview.refresh_from_db()
        self.assertEqual(self.interview.status, Interview.InterviewStatus.CANCELLED)
        self.assertTrue(self.interview.is_cancelled)
        self.assertEqual(self.application.interviews.count(), 1)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.INTERVIEW)

    def test_second_cancellation_rejected(self):
        self.interview.status = Interview.InterviewStatus.CANCELLED
        self.interview.save()

        url = reverse("employer_cancel_interview", kwargs={"pk": self.interview.pk})
        response = self.client.post(url)
        self.assertRedirects(response, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))

    def test_cancellation_requires_post(self):
        url = reverse("employer_cancel_interview", kwargs={"pk": self.interview.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)


class CandidateInterviewVisibilityTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer()
        self.candidate_user = make_jobseeker()
        self.other_candidate_user = make_jobseeker(username="other_cand", email="other_cand@example.com")
        self.job = create_job(self.employer_user.employer_profile)
        self.application = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate_user.jobseeker_profile,
            status=Application.Status.INTERVIEW,
        )
        self.interview = Interview.objects.create(
            application=self.application,
            interview_type=Interview.InterviewType.VIDEO,
            scheduled_at=timezone.now() + timedelta(days=3),
            duration_minutes=45,
            location_or_link="https://meet.google.com/secret-interview-link",
            candidate_instructions="Candidate preparation instructions: review Python asyncio.",
            internal_notes="PRIVATE_INTERNAL_NOTE: Candidate expected salary is 120k.",
            created_by=self.employer_user,
        )
        self.client.force_login(self.candidate_user)

    def test_candidate_sees_own_scheduled_interview_details(self):
        url = reverse("jobseeker_application_detail", kwargs={"pk": self.application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode()
        self.assertIn("Upcoming Interview", content)
        self.assertIn("45 minutes", content)
        self.assertIn("Video Call", content)
        self.assertIn("https://meet.google.com/secret-interview-link", content)
        self.assertIn("Candidate preparation instructions: review Python asyncio.", content)

    def test_candidate_never_sees_internal_notes_or_created_by(self):
        url = reverse("jobseeker_application_detail", kwargs={"pk": self.application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode()
        self.assertNotIn("PRIVATE_INTERNAL_NOTE", content)
        self.assertNotIn("Candidate expected salary is 120k", content)
        self.assertNotIn(self.employer_user.username, content)

    def test_unrelated_candidate_gets_404(self):
        self.client.force_login(self.other_candidate_user)
        url = reverse("jobseeker_application_detail", kwargs={"pk": self.application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_candidate_cannot_mutate_or_cancel_interview(self):
        cancel_url = reverse("employer_cancel_interview", kwargs={"pk": self.interview.pk})
        edit_url = reverse("employer_edit_interview", kwargs={"pk": self.interview.pk})
        schedule_url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})

        self.assertEqual(self.client.post(cancel_url).status_code, 403)
        self.assertEqual(self.client.post(edit_url, {}).status_code, 403)
        self.assertEqual(self.client.post(schedule_url, {}).status_code, 403)

    def test_candidate_sees_safe_historical_interviews(self):
        self.interview.status = Interview.InterviewStatus.CANCELLED
        self.interview.save()

        url = reverse("jobseeker_application_detail", kwargs={"pk": self.application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode()
        self.assertIn("Interview History", content)
        self.assertIn("Cancelled", content)
        self.assertNotIn("PRIVATE_INTERNAL_NOTE", content)


class InterviewIntegrationFlowTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer()
        self.candidate_user = make_jobseeker()
        self.job = create_job(self.employer_user.employer_profile)
        self.application = Application.objects.create(
            job=self.job,
            jobseeker=self.candidate_user.jobseeker_profile,
            status=Application.Status.SHORTLISTED,
        )

    def test_full_interview_lifecycle(self):
        # 1. Employer schedules interview for SHORTLISTED applicant
        self.client.force_login(self.employer_user)
        schedule_time = timezone.now() + timedelta(days=2)
        schedule_url = reverse("employer_schedule_interview", kwargs={"pk": self.application.pk})
        response = self.client.post(
            schedule_url,
            {
                "interview_type": Interview.InterviewType.VIDEO,
                "scheduled_at": schedule_time.strftime("%Y-%m-%dT%H:%M"),
                "duration_minutes": 30,
                "location_or_link": "https://meet.google.com/round-1",
                "candidate_instructions": "Prepare design presentation.",
                "internal_notes": "Internal note round 1.",
            },
        )
        self.assertRedirects(response, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.INTERVIEW)
        interview = self.application.interviews.first()
        self.assertIsNotNone(interview)
        self.assertEqual(interview.status, Interview.InterviewStatus.SCHEDULED)

        # 2. Candidate logs in and views their application detail
        self.client.force_login(self.candidate_user)
        candidate_url = reverse("jobseeker_application_detail", kwargs={"pk": self.application.pk})
        cand_resp = self.client.get(candidate_url)
        self.assertEqual(cand_resp.status_code, 200)
        cand_html = cand_resp.content.decode()
        self.assertIn("Upcoming Interview", cand_html)
        self.assertIn("https://meet.google.com/round-1", cand_html)
        self.assertIn("Prepare design presentation.", cand_html)
        self.assertNotIn("Internal note round 1.", cand_html)

        # 3. Employer reschedules the interview
        self.client.force_login(self.employer_user)
        reschedule_time = timezone.now() + timedelta(days=4)
        edit_url = reverse("employer_edit_interview", kwargs={"pk": interview.pk})
        edit_resp = self.client.post(
            edit_url,
            {
                "interview_type": Interview.InterviewType.VIDEO,
                "scheduled_at": reschedule_time.strftime("%Y-%m-%dT%H:%M"),
                "duration_minutes": 45,
                "location_or_link": "https://meet.google.com/round-1-rescheduled",
                "candidate_instructions": "Time changed to 45 mins.",
                "internal_notes": "Internal note rescheduled.",
            },
        )
        self.assertRedirects(edit_resp, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))
        interview.refresh_from_db()
        self.assertEqual(interview.location_or_link, "https://meet.google.com/round-1-rescheduled")
        self.assertEqual(interview.duration_minutes, 45)

        # 4. Candidate sees the updated schedule
        self.client.force_login(self.candidate_user)
        cand_resp = self.client.get(candidate_url)
        cand_html = cand_resp.content.decode()
        self.assertIn("https://meet.google.com/round-1-rescheduled", cand_html)
        self.assertIn("Time changed to 45 mins.", cand_html)
        self.assertNotIn("Internal note rescheduled.", cand_html)

        # 5. Employer cancels the interview
        self.client.force_login(self.employer_user)
        cancel_url = reverse("employer_cancel_interview", kwargs={"pk": interview.pk})
        cancel_resp = self.client.post(cancel_url)
        self.assertRedirects(cancel_resp, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))
        interview.refresh_from_db()
        self.assertTrue(interview.is_cancelled)

        # 6. Candidate sees interview in history, no longer as active
        self.client.force_login(self.candidate_user)
        cand_resp = self.client.get(candidate_url)
        cand_html = cand_resp.content.decode()
        self.assertNotIn("Scheduled</span>", cand_html)
        self.assertIn("Interview History", cand_html)
        self.assertIn("Cancelled", cand_html)

        # 7. Employer schedules a replacement interview
        self.client.force_login(self.employer_user)
        new_time = timezone.now() + timedelta(days=6)
        rep_resp = self.client.post(
            schedule_url,
            {
                "interview_type": Interview.InterviewType.IN_PERSON,
                "scheduled_at": new_time.strftime("%Y-%m-%dT%H:%M"),
                "duration_minutes": 60,
                "location_or_link": "Office Kathmandu",
                "candidate_instructions": "Replacement in-person interview.",
                "internal_notes": "Replacement interview notes.",
            },
        )
        self.assertRedirects(rep_resp, reverse("employer_application_detail", kwargs={"pk": self.application.pk}))
        self.assertEqual(self.application.interviews.count(), 2)
        new_interview = self.application.interviews.filter(status=Interview.InterviewStatus.SCHEDULED).first()
        self.assertIsNotNone(new_interview)
        self.assertEqual(new_interview.location_or_link, "Office Kathmandu")


class InterviewAdminTests(TestCase):
    def test_admin_registration(self):
        self.assertIn(Interview, admin.site._registry)
        model_admin = admin.site._registry[Interview]
        self.assertIsInstance(model_admin, InterviewAdmin)
        self.assertIn("scheduled_at", model_admin.list_display)
        self.assertIn("status", model_admin.list_filter)
        self.assertIn("created_at", model_admin.readonly_fields)
        self.assertIn("application", model_admin.raw_id_fields)

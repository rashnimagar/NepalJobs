import shutil
import tempfile
from datetime import timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CV, EmployerProfile, JobseekerProfile
from applications.admin import ApplicationAdmin
from applications.forms import ApplicationStatusUpdateForm, JobApplicationForm
from applications.models import Application
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
        # Attempting GET to apply_job redirects with info message
        response_get = self.client.get(reverse("apply_job", args=[self.job.pk]))
        self.assertRedirects(response_get, reverse("jobseeker_application_detail", args=[app.pk]))

        # Attempting POST to apply_job redirects and does not create a duplicate
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
        # Attempt to access job_b applicants
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

        # Candidate 1 applied only to Employer A's job
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
        # Employer B received no application with cv1
        self.client.force_login(self.employer_b_user)
        response = self.client.get(reverse("cv_download", args=[self.cv1.pk]))
        self.assertEqual(response.status_code, 403)

    def test_employer_cannot_download_unsubmitted_cv_even_knowing_id(self):
        # cv2 was never submitted to any job
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


class ApplicationStatusUpdateFormTests(TestCase):
    def test_status_update_form_valid_choices(self):
        form = ApplicationStatusUpdateForm(data={"status": Application.Status.SHORTLISTED})
        self.assertTrue(form.is_valid())

    def test_status_update_form_invalid_choice(self):
        form = ApplicationStatusUpdateForm(data={"status": "invalid_status"})
        self.assertFalse(form.is_valid())

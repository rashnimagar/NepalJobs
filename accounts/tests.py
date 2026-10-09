"""
accounts/tests.py
-----------------
Test suite for Steps 1–4: User model, registration, authentication, role
access control, jobseeker profile, CV management, skills, education,
experience, dashboard checklist, and URL routing regression tests.

Run with:  python manage.py test accounts
"""

import io
import os
import shutil
import tempfile

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import FileResponse
from django.test import TestCase, override_settings
from django.urls import reverse, resolve
from django.views import View
from django.views.generic import DetailView, FormView, TemplateView, UpdateView

from .forms import EmployerProfileForm, EmployerVerificationForm
from .views import (
    CVDeleteView,
    CVDownloadView,
    CVListView,
    CVSetDefaultView,
    CompanyDetailView,
    DashboardView,
    EmployerDashboardView,
    EmployerProfileEditView,
    EmployerProfileView,
    EmployerVerificationSubmitView,
    JobseekerDashboardView,
    ProfileEditView,
    ProfileView,
    RegisterChoiceView,
    RegisterEmployerView,
    RegisterJobseekerView,
    SkillsEditView,
    VerificationDocumentDownloadView,
    company_detail,
    cv_delete,
    cv_download,
    cv_list,
    cv_set_default,
    dashboard,
    employer_dashboard,
    employer_profile,
    employer_profile_edit,
    employer_verification_submit,
    jobseeker_dashboard,
    profile_edit,
    profile_view,
    register_choice,
    register_employer,
    register_jobseeker,
    skills_edit,
    verification_document_download,
)
from .models import (
    CV,
    MAX_ACTIVE_CVS,
    MAX_SKILLS,
    Education,
    EmployerProfile,
    Experience,
    JobseekerProfile,
    Skill,
)

User = get_user_model()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_jobseeker(username="jobseeker1", email="js1@example.com", password="Testpass123!"):
    user = User.objects.create_user(
        username=username, email=email, password=password,
        role=User.Role.JOBSEEKER,
    )
    JobseekerProfile.objects.get_or_create(user=user)
    return user


def make_employer(username="employer1", email="em1@example.com", password="Testpass123!"):
    user = User.objects.create_user(
        username=username, email=email, password=password,
        role=User.Role.EMPLOYER,
    )
    EmployerProfile.objects.get_or_create(user=user, defaults={"company_name": "Acme Ltd"})
    return user


def make_pdf(name="resume.pdf", size_bytes=1024):
    """Return a SimpleUploadedFile that passes extension validation."""
    return SimpleUploadedFile(
        name, b"%PDF-1.4 " + b"x" * max(0, size_bytes - 10), content_type="application/pdf"
    )


def make_image(name="logo.png", size_bytes=1024, format="PNG"):
    """Return a valid SimpleUploadedFile image."""
    buf = io.BytesIO()
    if size_bytes > 2 * 1024 * 1024:
        img = Image.frombytes("RGB", (1000, 1000), b"\x00" * 3000000)
        img.save(buf, format="PNG", compress_level=0)
    else:
        img = Image.new("RGB", (100, 100), color="blue")
        img.save(buf, format=format)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=f"image/{format.lower()}")


# ---------------------------------------------------------------------------
# 1. User Model Tests
# ---------------------------------------------------------------------------

class UserModelTests(TestCase):

    def test_jobseeker_role_default(self):
        user = User(username="u1", email="u1@example.com", role=User.Role.JOBSEEKER)
        self.assertEqual(user.role, User.Role.JOBSEEKER)

    def test_employer_role(self):
        user = User(username="u2", email="u2@example.com", role=User.Role.EMPLOYER)
        self.assertEqual(user.role, User.Role.EMPLOYER)

    def test_is_jobseeker_property_true(self):
        user = make_jobseeker()
        self.assertTrue(user.is_jobseeker)
        self.assertFalse(user.is_employer)

    def test_is_employer_property_true(self):
        user = make_employer()
        self.assertTrue(user.is_employer)
        self.assertFalse(user.is_jobseeker)

    def test_email_must_be_unique(self):
        make_jobseeker(email="dup@example.com")
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                username="other", email="dup@example.com", password="pass"
            )


# ---------------------------------------------------------------------------
# 2. Registration Tests
# ---------------------------------------------------------------------------

class JobseekerRegistrationTests(TestCase):

    def _post(self, data):
        return self.client.post(reverse("register_jobseeker"), data)

    def _valid_data(self, **overrides):
        base = {
            "username": "newuser",
            "first_name": "New",
            "last_name": "User",
            "email": "new@example.com",
            "password1": "Testpass123!",
            "password2": "Testpass123!",
        }
        base.update(overrides)
        return base

    def test_creates_user(self):
        self._post(self._valid_data())
        self.assertTrue(User.objects.filter(username="newuser").exists())

    def test_creates_jobseeker_profile(self):
        self._post(self._valid_data())
        user = User.objects.get(username="newuser")
        self.assertTrue(hasattr(user, "jobseeker_profile"))

    def test_user_has_jobseeker_role(self):
        self._post(self._valid_data())
        user = User.objects.get(username="newuser")
        self.assertTrue(user.is_jobseeker)

    def test_redirects_to_dashboard_after_register(self):
        response = self._post(self._valid_data())
        # Registration redirects to dashboard; dashboard itself redirects further
        # (to jobseeker_dashboard), so we check the initial redirect only.
        self.assertRedirects(
            response, reverse("dashboard"), fetch_redirect_response=False
        )

    def test_duplicate_email_rejected(self):
        make_jobseeker(email="taken@example.com")
        response = self._post(self._valid_data(email="taken@example.com"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_duplicate_username_rejected(self):
        make_jobseeker(username="newuser")
        response = self._post(self._valid_data())
        self.assertEqual(response.status_code, 200)
        # Only one user with that username should exist (the pre-existing one)
        self.assertEqual(User.objects.filter(username="newuser").count(), 1)

    def test_password_mismatch_rejected(self):
        data = self._valid_data(password2="DifferentPass99!")
        response = self._post(data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())


class EmployerRegistrationTests(TestCase):

    def _post(self, data):
        return self.client.post(reverse("register_employer"), data)

    def _valid_data(self, **overrides):
        base = {
            "username": "newemployer",
            "email": "emp@example.com",
            "company_name": "NepalCorp",
            "phone": "9800000000",
            "address": "Kathmandu",
            "password1": "Testpass123!",
            "password2": "Testpass123!",
        }
        base.update(overrides)
        return base

    def test_creates_user(self):
        self._post(self._valid_data())
        self.assertTrue(User.objects.filter(username="newemployer").exists())

    def test_creates_employer_profile(self):
        self._post(self._valid_data())
        user = User.objects.get(username="newemployer")
        self.assertTrue(hasattr(user, "employer_profile"))
        self.assertEqual(user.employer_profile.company_name, "NepalCorp")

    def test_user_has_employer_role(self):
        self._post(self._valid_data())
        user = User.objects.get(username="newemployer")
        self.assertTrue(user.is_employer)

    def test_employer_starts_pending(self):
        self._post(self._valid_data())
        user = User.objects.get(username="newemployer")
        self.assertEqual(
            user.employer_profile.verification_status,
            EmployerProfile.VerificationStatus.PENDING,
        )

    def test_duplicate_email_rejected(self):
        make_jobseeker(email="taken@example.com")
        response = self._post(self._valid_data(email="taken@example.com"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newemployer").exists())


# ---------------------------------------------------------------------------
# 3. Authentication Tests
# ---------------------------------------------------------------------------

class AuthenticationTests(TestCase):

    def setUp(self):
        self.js = make_jobseeker()
        self.em = make_employer()

    def test_login_success(self):
        response = self.client.post(reverse("login"), {
            "username": "jobseeker1",
            "password": "Testpass123!",
        })
        # Django's LoginView redirects on success
        self.assertEqual(response.status_code, 302)

    def test_login_wrong_password_fails(self):
        response = self.client.post(reverse("login"), {
            "username": "jobseeker1",
            "password": "wrongpassword",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_logout(self):
        self.client.force_login(self.js)
        self.client.post(reverse("logout"))
        response = self.client.get(reverse("home"))
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_jobseeker_dashboard_redirect(self):
        self.client.force_login(self.js)
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("jobseeker_dashboard"))

    def test_employer_dashboard_redirect(self):
        self.client.force_login(self.em)
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("employer_dashboard"))

    def test_anonymous_profile_redirects_to_login(self):
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_anonymous_cv_list_redirects_to_login(self):
        response = self.client.get(reverse("cv_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_anonymous_dashboard_redirects_to_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])


# ---------------------------------------------------------------------------
# 4. Role Permission Tests
# ---------------------------------------------------------------------------

class RolePermissionTests(TestCase):

    def setUp(self):
        self.js = make_jobseeker()
        self.em = make_employer()

    def test_employer_cannot_view_jobseeker_profile(self):
        self.client.force_login(self.em)
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 403)

    def test_employer_cannot_access_jobseeker_dashboard(self):
        self.client.force_login(self.em)
        response = self.client.get(reverse("jobseeker_dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_employer_cannot_access_cv_list(self):
        self.client.force_login(self.em)
        response = self.client.get(reverse("cv_list"))
        self.assertEqual(response.status_code, 403)

    def test_employer_cannot_access_skills_edit(self):
        self.client.force_login(self.em)
        response = self.client.get(reverse("skills_edit"))
        self.assertEqual(response.status_code, 403)

    def test_employer_cannot_add_education(self):
        self.client.force_login(self.em)
        response = self.client.get(reverse("education_add"))
        self.assertEqual(response.status_code, 403)

    def test_jobseeker_cannot_access_employer_dashboard(self):
        self.client.force_login(self.js)
        response = self.client.get(reverse("employer_dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_gets_login_redirect_not_403(self):
        """Anonymous users should be redirected to login, not receive a 403."""
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# 5. Profile Tests
# ---------------------------------------------------------------------------

class ProfileTests(TestCase):

    def setUp(self):
        self.user = make_jobseeker()
        self.client.force_login(self.user)

    def test_profile_view_is_accessible(self):
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)

    def test_profile_edit_is_accessible(self):
        response = self.client.get(reverse("profile_edit"))
        self.assertEqual(response.status_code, 200)

    def test_profile_edit_updates_data(self):
        self.client.post(reverse("profile_edit"), {
            "first_name": "Rama",
            "last_name": "Sharma",
            "email": self.user.email,
            "phone": "9800000001",
            "location": "Kathmandu",
            "summary": "Experienced developer.",
        })
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Rama")
        profile = self.user.jobseeker_profile
        profile.refresh_from_db()
        self.assertEqual(profile.phone, "9800000001")
        self.assertEqual(profile.location, "Kathmandu")

    def test_profile_update_redirects_to_profile_view(self):
        response = self.client.post(reverse("profile_edit"), {
            "first_name": "Test",
            "last_name": "User",
            "email": self.user.email,
            "phone": "9800000002",
            "location": "Pokhara",
            "summary": "Hi.",
        })
        self.assertRedirects(response, reverse("profile"))

    def test_email_change_uniqueness_enforced(self):
        other = make_jobseeker(username="other", email="other@example.com")
        response = self.client.post(reverse("profile_edit"), {
            "first_name": "Test",
            "last_name": "User",
            "email": "other@example.com",  # already taken
            "phone": "9800000000",
            "location": "Lalitpur",
            "summary": "Summary.",
        })
        self.assertEqual(response.status_code, 200)  # form invalid — re-renders
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.email, "other@example.com")


# ---------------------------------------------------------------------------
# 6. CV Tests
# ---------------------------------------------------------------------------

@override_settings(PRIVATE_MEDIA_ROOT="/tmp/nepaljobs_test_private_media")
class CVTests(TestCase):

    def setUp(self):
        self.user = make_jobseeker()
        self.other = make_jobseeker(username="other", email="other@example.com")
        self.client.force_login(self.user)
        self.profile = self.user.jobseeker_profile

    def _upload(self, title="My CV", filename="resume.pdf", size_bytes=1024):
        return self.client.post(reverse("cv_list"), {
            "title": title,
            "file": make_pdf(filename, size_bytes),
        })

    def test_valid_cv_upload(self):
        self._upload()
        self.assertEqual(self.profile.cvs.filter(is_active=True).count(), 1)

    def test_invalid_extension_rejected(self):
        bad_file = SimpleUploadedFile("resume.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        self.client.post(reverse("cv_list"), {"title": "Hack", "file": bad_file})
        self.assertEqual(self.profile.cvs.filter(is_active=True).count(), 0)

    def test_max_cvs_enforced(self):
        # Upload MAX_ACTIVE_CVS CVs
        for i in range(MAX_ACTIVE_CVS):
            self._upload(title=f"CV {i}", filename=f"resume{i}.pdf")
        count_before = self.profile.cvs.filter(is_active=True).count()
        # Attempt one more
        self._upload(title="One Too Many", filename="extra.pdf")
        count_after = self.profile.cvs.filter(is_active=True).count()
        self.assertEqual(count_before, MAX_ACTIVE_CVS)
        self.assertEqual(count_after, MAX_ACTIVE_CVS)

    def test_first_uploaded_cv_becomes_default(self):
        self._upload()
        cv = self.profile.cvs.filter(is_active=True).first()
        self.assertTrue(cv.is_default)

    def test_set_default_cv(self):
        self._upload(title="CV 1", filename="cv1.pdf")
        self._upload(title="CV 2", filename="cv2.pdf")
        cvs = list(self.profile.cvs.filter(is_active=True))
        non_default = next(c for c in cvs if not c.is_default)
        self.client.post(reverse("cv_set_default", args=[non_default.pk]))
        non_default.refresh_from_db()
        self.assertTrue(non_default.is_default)

    def test_deactivate_default_promotes_next(self):
        self._upload(title="CV 1", filename="cv1.pdf")
        self._upload(title="CV 2", filename="cv2.pdf")
        default_cv = self.profile.cvs.filter(is_active=True, is_default=True).first()
        default_cv.deactivate()
        # Another CV should now be default
        remaining = self.profile.cvs.filter(is_active=True)
        self.assertTrue(remaining.filter(is_default=True).exists())

    def test_owner_can_download_cv(self):
        self._upload()
        cv = self.profile.cvs.filter(is_active=True).first()
        response = self.client.get(reverse("cv_download", args=[cv.pk]))
        # FileResponse returns 200 with the file content
        self.assertEqual(response.status_code, 200)

    def test_other_user_cannot_download_cv(self):
        self._upload()
        cv = self.profile.cvs.filter(is_active=True).first()
        # Log in as the other user
        self.client.force_login(self.other)
        response = self.client.get(reverse("cv_download", args=[cv.pk]))
        self.assertEqual(response.status_code, 403)

    def test_other_user_cannot_delete_cv(self):
        self._upload()
        cv = self.profile.cvs.filter(is_active=True).first()
        self.client.force_login(self.other)
        # other is a jobseeker, but cv belongs to self.user
        response = self.client.post(reverse("cv_delete", args=[cv.pk]))
        self.assertEqual(response.status_code, 404)
        cv.refresh_from_db()
        self.assertTrue(cv.is_active)  # untouched

    def test_other_user_cannot_set_default_on_foreign_cv(self):
        self._upload()
        cv = self.profile.cvs.filter(is_active=True).first()
        self.client.force_login(self.other)
        response = self.client.post(reverse("cv_set_default", args=[cv.pk]))
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# 7. Skill Tests
# ---------------------------------------------------------------------------

class SkillModelTests(TestCase):

    def test_skill_name_normalised_on_save(self):
        skill = Skill.objects.create(name="  Python  ")
        self.assertEqual(skill.name, "python")

    def test_duplicate_skill_case_insensitive(self):
        Skill.objects.create(name="django")
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            Skill.objects.create(name="django")

    def test_skill_whitespace_collapsed(self):
        skill = Skill.objects.create(name="machine   learning")
        self.assertEqual(skill.name, "machine learning")


class SkillsViewTests(TestCase):

    def setUp(self):
        self.user = make_jobseeker()
        self.client.force_login(self.user)

    def _post_skills(self, skills_str):
        return self.client.post(reverse("skills_edit"), {"skills": skills_str})

    def test_add_skills(self):
        self._post_skills("python, django, sql")
        profile = self.user.jobseeker_profile
        self.assertEqual(profile.skills.count(), 3)

    def test_skills_normalised(self):
        self._post_skills("Python, DJANGO")
        profile = self.user.jobseeker_profile
        names = list(profile.skills.values_list("name", flat=True))
        self.assertIn("python", names)
        self.assertIn("django", names)

    def test_remove_skills(self):
        self._post_skills("python, django")
        self._post_skills("python")  # remove django
        profile = self.user.jobseeker_profile
        self.assertEqual(profile.skills.count(), 1)
        self.assertEqual(profile.skills.first().name, "python")

    def test_max_skill_limit_rejected(self):
        # MAX_SKILLS + 1 skills
        skills = ", ".join([f"skill{i}" for i in range(MAX_SKILLS + 1)])
        response = self._post_skills(skills)
        self.assertEqual(response.status_code, 200)  # form invalid, re-renders
        profile = self.user.jobseeker_profile
        self.assertEqual(profile.skills.count(), 0)

    def test_duplicate_skills_deduplicated(self):
        self._post_skills("python, python, python")
        profile = self.user.jobseeker_profile
        self.assertEqual(profile.skills.count(), 1)

    def test_empty_skills_clears_all(self):
        self._post_skills("python, django")
        self._post_skills("")
        profile = self.user.jobseeker_profile
        self.assertEqual(profile.skills.count(), 0)


# ---------------------------------------------------------------------------
# 8. Education Tests
# ---------------------------------------------------------------------------

class EducationTests(TestCase):

    def setUp(self):
        self.user_a = make_jobseeker(username="user_a", email="a@example.com")
        self.user_b = make_jobseeker(username="user_b", email="b@example.com")
        self.client.force_login(self.user_a)

    def _add_education(self, **overrides):
        data = {
            "level": "bachelor",
            "degree": "BCA",
            "institution": "PU",
            "field_of_study": "",
            "start_year": 2018,
            "end_year": 2022,
            "is_ongoing": False,
        }
        data.update(overrides)
        return self.client.post(reverse("education_add"), data)

    def test_create_education(self):
        self._add_education()
        self.assertEqual(self.user_a.jobseeker_profile.educations.count(), 1)

    def test_create_education_redirects_to_profile(self):
        response = self._add_education()
        self.assertRedirects(response, reverse("profile"))

    def test_update_education(self):
        self._add_education()
        edu = self.user_a.jobseeker_profile.educations.first()
        self.client.post(reverse("education_edit", args=[edu.pk]), {
            "level": "master",
            "degree": "MCA",
            "institution": "TU",
            "field_of_study": "",
            "start_year": 2022,
            "end_year": 2024,
            "is_ongoing": False,
        })
        edu.refresh_from_db()
        self.assertEqual(edu.degree, "MCA")

    def test_delete_education(self):
        self._add_education()
        edu = self.user_a.jobseeker_profile.educations.first()
        self.client.post(reverse("education_delete", args=[edu.pk]))
        self.assertEqual(self.user_a.jobseeker_profile.educations.count(), 0)

    def test_ongoing_education_no_end_year_required(self):
        response = self._add_education(is_ongoing=True, end_year="")
        # Should succeed — ongoing entries don't need end_year
        self.assertEqual(self.user_a.jobseeker_profile.educations.count(), 1)

    def test_end_year_before_start_year_rejected(self):
        response = self._add_education(start_year=2022, end_year=2020)
        self.assertEqual(response.status_code, 200)  # form re-renders with error
        self.assertEqual(self.user_a.jobseeker_profile.educations.count(), 0)

    def test_missing_end_year_non_ongoing_rejected(self):
        response = self._add_education(end_year="", is_ongoing=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user_a.jobseeker_profile.educations.count(), 0)

    # --- Ownership protection ---

    def test_user_b_cannot_edit_user_a_education(self):
        self._add_education()
        edu = self.user_a.jobseeker_profile.educations.first()
        # Log in as user B
        self.client.force_login(self.user_b)
        response = self.client.post(reverse("education_edit", args=[edu.pk]), {
            "level": "master",
            "degree": "HACKED",
            "institution": "Evil Corp",
            "field_of_study": "",
            "start_year": 2022,
            "end_year": 2024,
            "is_ongoing": False,
        })
        # get_queryset filters by profile, so edu is not found → 404
        self.assertEqual(response.status_code, 404)
        edu.refresh_from_db()
        self.assertNotEqual(edu.degree, "HACKED")

    def test_user_b_cannot_delete_user_a_education(self):
        self._add_education()
        edu = self.user_a.jobseeker_profile.educations.first()
        self.client.force_login(self.user_b)
        response = self.client.post(reverse("education_delete", args=[edu.pk]))
        self.assertEqual(response.status_code, 404)
        # Record still exists
        self.assertEqual(self.user_a.jobseeker_profile.educations.count(), 1)

    def test_employer_cannot_add_education(self):
        employer = make_employer()
        self.client.force_login(employer)
        response = self.client.get(reverse("education_add"))
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# 9. Experience Tests
# ---------------------------------------------------------------------------

class ExperienceTests(TestCase):

    def setUp(self):
        self.user_a = make_jobseeker(username="exp_a", email="expa@example.com")
        self.user_b = make_jobseeker(username="exp_b", email="expb@example.com")
        self.client.force_login(self.user_a)

    def _add_experience(self, **overrides):
        data = {
            "job_title": "Developer",
            "company": "Acme",
            "location": "Kathmandu",
            "start_date": "2020-01-01",
            "end_date": "2022-12-31",
            "is_current": False,
            "description": "",
        }
        data.update(overrides)
        return self.client.post(reverse("experience_add"), data)

    def test_create_experience(self):
        self._add_experience()
        self.assertEqual(self.user_a.jobseeker_profile.experiences.count(), 1)

    def test_create_experience_redirects_to_profile(self):
        response = self._add_experience()
        self.assertRedirects(response, reverse("profile"))

    def test_update_experience(self):
        self._add_experience()
        exp = self.user_a.jobseeker_profile.experiences.first()
        self.client.post(reverse("experience_edit", args=[exp.pk]), {
            "job_title": "Senior Developer",
            "company": "NewCorp",
            "location": "Pokhara",
            "start_date": "2020-01-01",
            "end_date": "2023-06-30",
            "is_current": False,
            "description": "",
        })
        exp.refresh_from_db()
        self.assertEqual(exp.job_title, "Senior Developer")

    def test_delete_experience(self):
        self._add_experience()
        exp = self.user_a.jobseeker_profile.experiences.first()
        self.client.post(reverse("experience_delete", args=[exp.pk]))
        self.assertEqual(self.user_a.jobseeker_profile.experiences.count(), 0)

    def test_current_experience_no_end_date_required(self):
        self._add_experience(is_current=True, end_date="")
        self.assertEqual(self.user_a.jobseeker_profile.experiences.count(), 1)

    def test_future_start_date_rejected(self):
        response = self._add_experience(start_date="2099-01-01", end_date="2099-06-01")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user_a.jobseeker_profile.experiences.count(), 0)

    def test_end_date_before_start_date_rejected(self):
        response = self._add_experience(start_date="2020-06-01", end_date="2020-01-01")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user_a.jobseeker_profile.experiences.count(), 0)

    def test_missing_end_date_non_current_rejected(self):
        response = self._add_experience(end_date="", is_current=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user_a.jobseeker_profile.experiences.count(), 0)

    # --- Ownership protection ---

    def test_user_b_cannot_edit_user_a_experience(self):
        self._add_experience()
        exp = self.user_a.jobseeker_profile.experiences.first()
        self.client.force_login(self.user_b)
        response = self.client.post(reverse("experience_edit", args=[exp.pk]), {
            "job_title": "HACKED",
            "company": "Evil",
            "location": "",
            "start_date": "2020-01-01",
            "end_date": "2022-01-01",
            "is_current": False,
            "description": "",
        })
        self.assertEqual(response.status_code, 404)
        exp.refresh_from_db()
        self.assertNotEqual(exp.job_title, "HACKED")

    def test_user_b_cannot_delete_user_a_experience(self):
        self._add_experience()
        exp = self.user_a.jobseeker_profile.experiences.first()
        self.client.force_login(self.user_b)
        response = self.client.post(reverse("experience_delete", args=[exp.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.user_a.jobseeker_profile.experiences.count(), 1)

    def test_employer_cannot_add_experience(self):
        employer = make_employer()
        self.client.force_login(employer)
        response = self.client.get(reverse("experience_add"))
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# 10. URL Regression Tests
# ---------------------------------------------------------------------------

class URLRegressionTests(TestCase):
    """
    Regression tests for the profile URL collision (audit finding TD-1).
    These tests will FAIL if the duplicate `path("profile/", ...)` returns.
    """

    def test_profile_and_profile_edit_resolve_to_different_urls(self):
        profile_url = reverse("profile")
        edit_url = reverse("profile_edit")
        self.assertNotEqual(
            profile_url, edit_url,
            "REGRESSION: 'profile' and 'profile_edit' must resolve to different URLs",
        )

    def test_profile_url_is_read_only_view(self):
        """GET /accounts/profile/ must call profile_view, not profile_edit."""
        match = resolve("/accounts/profile/")
        from accounts import views
        self.assertEqual(match.func, views.profile_view)

    def test_profile_edit_url_is_edit_view(self):
        """GET /accounts/profile/edit/ must call profile_edit."""
        match = resolve("/accounts/profile/edit/")
        from accounts import views
        self.assertEqual(match.func, views.profile_edit)

    def test_profile_url_value(self):
        self.assertEqual(reverse("profile"), "/accounts/profile/")

    def test_profile_edit_url_value(self):
        self.assertEqual(reverse("profile_edit"), "/accounts/profile/edit/")

    def test_get_profile_url_returns_200_for_jobseeker(self):
        user = make_jobseeker()
        self.client.force_login(user)
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)

    def test_get_profile_url_renders_profile_view_template(self):
        user = make_jobseeker()
        self.client.force_login(user)
        response = self.client.get(reverse("profile"))
        self.assertTemplateUsed(response, "accounts/profile_view.html")

    def test_get_profile_edit_url_renders_edit_template(self):
        user = make_jobseeker()
        self.client.force_login(user)
        response = self.client.get(reverse("profile_edit"))
        self.assertTemplateUsed(response, "accounts/profile_edit.html")


# ---------------------------------------------------------------------------
# 11. Dashboard Tests
# ---------------------------------------------------------------------------

class DashboardTests(TestCase):

    def setUp(self):
        self.user = make_jobseeker()
        self.client.force_login(self.user)
        self.profile = self.user.jobseeker_profile

    def _get_dashboard(self):
        return self.client.get(reverse("jobseeker_dashboard"))

    def test_dashboard_accessible(self):
        response = self._get_dashboard()
        self.assertEqual(response.status_code, 200)

    def test_dashboard_has_five_steps(self):
        response = self._get_dashboard()
        steps = response.context["steps"]
        self.assertEqual(len(steps), 5, "Dashboard must have exactly 5 checklist items")

    def test_dashboard_initial_progress_is_zero(self):
        response = self._get_dashboard()
        self.assertEqual(response.context["done"], 0)
        self.assertEqual(response.context["percent"], 0)

    def test_experience_step_in_dashboard(self):
        response = self._get_dashboard()
        steps = response.context["steps"]
        labels = [label for label, _, _ in steps]
        experience_step = any("experience" in label.lower() for label in labels)
        self.assertTrue(experience_step, "Experience step must appear in the dashboard checklist")

    def test_cv_step_in_dashboard(self):
        response = self._get_dashboard()
        steps = response.context["steps"]
        labels = [label for label, _, _ in steps]
        cv_step = any("cv" in label.lower() for label in labels)
        self.assertTrue(cv_step, "CV upload step must appear in dashboard checklist")

    def test_skills_completion_increases_progress(self):
        Skill.objects.create(name="python")
        self.profile.skills.add(Skill.objects.get(name="python"))
        response = self._get_dashboard()
        done_after = response.context["done"]
        self.assertGreater(done_after, 0)

    def test_education_completion_increases_progress(self):
        Education.objects.create(
            profile=self.profile,
            level="bachelor",
            degree="BCA",
            institution="PU",
            start_year=2018,
            end_year=2022,
            is_ongoing=False,
        )
        response = self._get_dashboard()
        self.assertGreater(response.context["done"], 0)

    def test_experience_completion_increases_progress(self):
        from django.utils import timezone
        import datetime
        Experience.objects.create(
            profile=self.profile,
            job_title="Dev",
            company="Acme",
            start_date=datetime.date(2020, 1, 1),
            end_date=datetime.date(2022, 1, 1),
            is_current=False,
        )
        response = self._get_dashboard()
        steps = response.context["steps"]
        # Find the experience step and confirm it is marked done
        experience_done = any(
            ok for label, ok, _ in steps if "experience" in label.lower()
        )
        self.assertTrue(experience_done)

    def test_total_is_five(self):
        response = self._get_dashboard()
        self.assertEqual(response.context["total"], 5)

    def test_percent_calculation_with_one_step_done(self):
        Education.objects.create(
            profile=self.profile,
            level="bachelor",
            degree="BCA",
            institution="PU",
            start_year=2018,
            end_year=2022,
            is_ongoing=False,
        )
        response = self._get_dashboard()
        # 1 out of 5 = 20%
        self.assertEqual(response.context["percent"], 20)

    def test_dashboard_empty_application_state(self):
        response = self._get_dashboard()
        self.assertEqual(response.context["total_applications"], 0)
        self.assertEqual(response.context["under_review_count"], 0)
        self.assertEqual(response.context["interview_count"], 0)
        self.assertEqual(response.context["selected_count"], 0)
        self.assertEqual(list(response.context["recent_applications"]), [])
        self.assertIn("haven't submitted any job applications yet", response.content.decode())

    def test_dashboard_application_metric_context_and_recent_applications(self):
        import datetime
        from applications.models import Application
        from jobs.models import Category, Job, Location
        employer_user = make_employer(username="dash_emp_acc", email="dash_emp_acc@example.com")
        cat = Category.objects.create(name="Design", slug="design")
        loc = Location.objects.create(name="Lalitpur", slug="lalitpur")
        job1 = Job.objects.create(
            employer=employer_user.employer_profile,
            category=cat,
            location=loc,
            title="UI Designer",
            description="Design great interfaces",
            application_deadline=datetime.date.today() + datetime.timedelta(days=10),
            status=Job.Status.PUBLISHED,
        )
        job2 = Job.objects.create(
            employer=employer_user.employer_profile,
            category=cat,
            location=loc,
            title="UX Researcher",
            description="Research user needs",
            application_deadline=datetime.date.today() + datetime.timedelta(days=10),
            status=Job.Status.PUBLISHED,
        )
        Application.objects.create(
            job=job1,
            jobseeker=self.profile,
            status=Application.Status.UNDER_REVIEW,
        )
        Application.objects.create(
            job=job2,
            jobseeker=self.profile,
            status=Application.Status.INTERVIEW,
        )
        response = self._get_dashboard()
        self.assertEqual(response.context["total_applications"], 2)
        self.assertEqual(response.context["under_review_count"], 1)
        self.assertEqual(response.context["interview_count"], 1)
        self.assertEqual(response.context["selected_count"], 0)
        recent = list(response.context["recent_applications"])
        self.assertEqual(len(recent), 2)
        content = response.content.decode()
        self.assertIn("Recent Applications", content)
        self.assertIn("UI Designer", content)
        self.assertIn("UX Researcher", content)


# ---------------------------------------------------------------------------
# 12. Step 5.1 Employer Form Tests
# ---------------------------------------------------------------------------

class EmployerProfileFormTests(TestCase):

    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.settings_override = self.settings(MEDIA_ROOT=self.temp_media)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def test_valid_company_information_accepted(self):
        logo = make_image("logo.png")
        data = {
            "company_name": "Kathmandu Tech Solutions",
            "phone": "+977-1-4200000",
            "address": "Tinkune, Kathmandu",
            "industry": "Information Technology",
            "website": "https://ktmtech.example.com",
            "description": "Leading software company in Nepal.",
        }
        form = EmployerProfileForm(data=data, files={"logo": logo})
        self.assertTrue(form.is_valid(), form.errors)
        employer = make_employer()
        profile = employer.employer_profile
        form = EmployerProfileForm(data=data, files={"logo": logo}, instance=profile)
        saved = form.save()
        self.assertEqual(saved.company_name, "Kathmandu Tech Solutions")
        self.assertEqual(saved.industry, "Information Technology")
        self.assertTrue(saved.logo.name.startswith("logos/employer_"))

    def test_invalid_website_rejected(self):
        data = {
            "company_name": "Kathmandu Tech Solutions",
            "website": "not-a-valid-url",
        }
        form = EmployerProfileForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("website", form.errors)

    def test_oversized_logo_rejected(self):
        big_logo = make_image("big_logo.png", size_bytes=3 * 1024 * 1024)
        data = {"company_name": "Big Logo Ltd"}
        form = EmployerProfileForm(data=data, files={"logo": big_logo})
        self.assertFalse(form.is_valid())
        self.assertIn("logo", form.errors)
        self.assertTrue(any("2 MB" in err for err in form.errors["logo"]))

    def test_unsupported_logo_format_rejected(self):
        gif_logo = make_image("logo.gif", format="GIF")
        data = {"company_name": "Gif Logo Ltd"}
        form = EmployerProfileForm(data=data, files={"logo": gif_logo})
        self.assertFalse(form.is_valid())
        self.assertIn("logo", form.errors)

    def test_non_editable_fields_not_present(self):
        form = EmployerProfileForm()
        excluded_fields = [
            "verification_status",
            "rejection_reason",
            "reviewed_at",
            "verification_document",
            "user",
        ]
        for field in excluded_fields:
            self.assertNotIn(field, form.fields)


class EmployerVerificationFormTests(TestCase):

    def setUp(self):
        self.temp_private = tempfile.mkdtemp()
        self.settings_override = self.settings(PRIVATE_MEDIA_ROOT=self.temp_private)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.temp_private, ignore_errors=True)

    def test_valid_verification_document_accepted(self):
        valid_pdf = make_pdf("pan_card.pdf", size_bytes=2048)
        form = EmployerVerificationForm(data={}, files={"verification_document": valid_pdf})
        self.assertTrue(form.is_valid(), form.errors)

    def test_valid_image_verification_document_accepted(self):
        valid_image = make_image("registration.jpg", format="JPEG")
        form = EmployerVerificationForm(data={}, files={"verification_document": valid_image})
        self.assertTrue(form.is_valid(), form.errors)

    def test_oversized_document_rejected(self):
        big_doc = make_pdf("huge_audit.pdf", size_bytes=11 * 1024 * 1024)
        form = EmployerVerificationForm(data={}, files={"verification_document": big_doc})
        self.assertFalse(form.is_valid())
        self.assertIn("verification_document", form.errors)
        self.assertTrue(any("10 MB" in err for err in form.errors["verification_document"]))

    def test_unsupported_document_format_rejected(self):
        bad_doc = SimpleUploadedFile("doc.docx", b"word doc content", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        form = EmployerVerificationForm(data={}, files={"verification_document": bad_doc})
        self.assertFalse(form.is_valid())
        self.assertIn("verification_document", form.errors)

    def test_only_verification_document_field_exposed(self):
        form = EmployerVerificationForm()
        self.assertEqual(list(form.fields.keys()), ["verification_document"])
        self.assertTrue(form.fields["verification_document"].required)
        empty_form = EmployerVerificationForm(data={}, files={})
        self.assertFalse(empty_form.is_valid())
        self.assertIn("verification_document", empty_form.errors)


# ---------------------------------------------------------------------------
# 13. Step 5.2 Employer Views & URL Routing Tests
# ---------------------------------------------------------------------------

class Step5ViewsBaseTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.temp_private = tempfile.mkdtemp()
        self.temp_media = tempfile.mkdtemp()
        self.storage_override = self.settings(
            PRIVATE_MEDIA_ROOT=self.temp_private,
            MEDIA_ROOT=self.temp_media,
        )
        self.storage_override.enable()

    def tearDown(self):
        super().tearDown()
        self.storage_override.disable()
        shutil.rmtree(self.temp_private, ignore_errors=True)
        shutil.rmtree(self.temp_media, ignore_errors=True)



class EmployerProfileViewTests(Step5ViewsBaseTestCase):

    def setUp(self):
        super().setUp()
        self.employer = make_employer("emp_view", "emp_view@example.com")
        self.other_employer = make_employer("emp_other", "emp_other@example.com")
        self.jobseeker = make_jobseeker("js_view", "js_view@example.com")

    def test_employer_can_view_own_profile(self):
        self.client.force_login(self.employer)
        response = self.client.get(reverse("employer_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["profile"], self.employer.employer_profile)

    def test_employer_can_edit_own_profile(self):
        self.client.force_login(self.employer)
        response = self.client.get(reverse("employer_profile_edit"))
        self.assertEqual(response.status_code, 200)

        logo = make_image("new_logo.png")
        post_data = {
            "company_name": "Updated Corp",
            "phone": "+977-1-5555555",
            "address": "Lalitpur",
            "industry": "FinTech",
            "website": "https://updatedcorp.example.com",
            "description": "Updated company description.",
            "logo": logo,
        }
        post_response = self.client.post(reverse("employer_profile_edit"), post_data)
        self.assertRedirects(post_response, reverse("employer_profile"))
        self.employer.employer_profile.refresh_from_db()
        self.assertEqual(self.employer.employer_profile.company_name, "Updated Corp")
        self.assertEqual(self.employer.employer_profile.industry, "FinTech")

    def test_jobseeker_denied_employer_profile_views(self):
        self.client.force_login(self.jobseeker)
        res_view = self.client.get(reverse("employer_profile"))
        self.assertEqual(res_view.status_code, 403)
        res_edit = self.client.get(reverse("employer_profile_edit"))
        self.assertEqual(res_edit.status_code, 403)

    def test_another_employer_cannot_access_other_private_profile(self):
        # Views retrieve request.user.employer_profile; they take no ID parameter.
        self.client.force_login(self.other_employer)
        response = self.client.get(reverse("employer_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["profile"], self.other_employer.employer_profile)
        self.assertNotEqual(response.context["profile"], self.employer.employer_profile)


class EmployerVerificationViewTests(Step5ViewsBaseTestCase):

    def setUp(self):
        super().setUp()
        self.employer = make_employer("emp_ver", "emp_ver@example.com")
        self.profile = self.employer.employer_profile

    def test_employer_can_submit_valid_verification_document(self):
        self.client.force_login(self.employer)
        pdf = make_pdf("company_doc.pdf")
        response = self.client.post(
            reverse("employer_verification_submit"),
            {"verification_document": pdf},
        )
        self.assertRedirects(response, reverse("employer_dashboard"))
        self.profile.refresh_from_db()
        self.assertTrue(bool(self.profile.verification_document))
        self.assertEqual(self.profile.verification_status, EmployerProfile.VerificationStatus.PENDING)

    def test_rejected_employer_can_resubmit_and_reason_cleared(self):
        self.profile.verification_status = EmployerProfile.VerificationStatus.REJECTED
        self.profile.rejection_reason = "Document unclear or missing stamp."
        self.profile.save()

        self.client.force_login(self.employer)
        pdf = make_pdf("corrected_doc.pdf")
        response = self.client.post(
            reverse("employer_verification_submit"),
            {"verification_document": pdf},
        )
        self.assertRedirects(response, reverse("employer_dashboard"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_status, EmployerProfile.VerificationStatus.PENDING)
        self.assertEqual(self.profile.rejection_reason, "")
        self.assertIsNone(self.profile.reviewed_at)

    def test_approved_employer_cannot_reset_approval(self):
        self.profile.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.profile.save()

        self.client.force_login(self.employer)
        pdf = make_pdf("extra_doc.pdf")
        response = self.client.post(
            reverse("employer_verification_submit"),
            {"verification_document": pdf},
        )
        self.assertRedirects(response, reverse("employer_dashboard"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_status, EmployerProfile.VerificationStatus.APPROVED)

    def test_invalid_upload_does_not_change_verification_state(self):
        self.profile.verification_status = EmployerProfile.VerificationStatus.REJECTED
        self.profile.rejection_reason = "Fix required."
        self.profile.save()

        self.client.force_login(self.employer)
        bad_doc = SimpleUploadedFile("invalid.exe", b"binary", content_type="application/octet-stream")
        response = self.client.post(
            reverse("employer_verification_submit"),
            {"verification_document": bad_doc},
        )
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_status, EmployerProfile.VerificationStatus.REJECTED)
        self.assertEqual(self.profile.rejection_reason, "Fix required.")


class PublicCompanyProfileViewTests(Step5ViewsBaseTestCase):

    def setUp(self):
        super().setUp()
        self.approved_user = make_employer("emp_appr", "emp_appr@example.com")
        self.approved_profile = self.approved_user.employer_profile
        self.approved_profile.company_name = "Approved Co"
        self.approved_profile.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.approved_profile.verification_document = make_pdf("private_secret.pdf")
        self.approved_profile.save()

        self.pending_user = make_employer("emp_pend", "emp_pend@example.com")
        self.pending_profile = self.pending_user.employer_profile
        self.pending_profile.verification_status = EmployerProfile.VerificationStatus.PENDING
        self.pending_profile.save()

        self.rejected_user = make_employer("emp_rej", "emp_rej@example.com")
        self.rejected_profile = self.rejected_user.employer_profile
        self.rejected_profile.verification_status = EmployerProfile.VerificationStatus.REJECTED
        self.rejected_profile.save()

    def test_approved_employer_public_profile_returns_200(self):
        response = self.client.get(reverse("company_detail", args=[self.approved_profile.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["company"], self.approved_profile)

    def test_pending_employer_public_profile_returns_404(self):
        response = self.client.get(reverse("company_detail", args=[self.pending_profile.pk]))
        self.assertEqual(response.status_code, 404)

    def test_rejected_employer_public_profile_returns_404(self):
        response = self.client.get(reverse("company_detail", args=[self.rejected_profile.pk]))
        self.assertEqual(response.status_code, 404)

    def test_private_verification_document_not_in_public_response(self):
        response = self.client.get(reverse("company_detail", args=[self.approved_profile.pk]))
        content = response.content.decode()
        self.assertNotIn("private_secret.pdf", content)
        self.assertNotIn(self.approved_profile.verification_document.name, content)


class VerificationDocumentDownloadViewTests(Step5ViewsBaseTestCase):

    def setUp(self):
        super().setUp()
        self.staff_user = User.objects.create_user("staff_member", "staff@example.com", "Pass123!", is_staff=True)
        self.employer_user = make_employer("emp_file", "emp_file@example.com")
        self.profile_with_doc = self.employer_user.employer_profile
        self.profile_with_doc.verification_document = SimpleUploadedFile("tax_cert.pdf", b"%PDF-1.4 file content", content_type="application/pdf")
        self.profile_with_doc.save()

        self.employer_no_doc = make_employer("emp_nofile", "emp_nofile@example.com").employer_profile
        self.jobseeker_user = make_jobseeker("seeker_file", "seeker_file@example.com")

    def test_guest_denied_document_download(self):
        response = self.client.get(reverse("verification_document_download", args=[self.profile_with_doc.pk]))
        self.assertEqual(response.status_code, 302)

    def test_jobseeker_denied_document_download(self):
        self.client.force_login(self.jobseeker_user)
        response = self.client.get(reverse("verification_document_download", args=[self.profile_with_doc.pk]))
        self.assertEqual(response.status_code, 403)

    def test_normal_employer_denied_document_download(self):
        self.client.force_login(self.employer_user)
        response = self.client.get(reverse("verification_document_download", args=[self.profile_with_doc.pk]))
        self.assertEqual(response.status_code, 403)

    def test_staff_can_access_document(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("verification_document_download", args=[self.profile_with_doc.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response, FileResponse)

    def test_missing_document_returns_404(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("verification_document_download", args=[self.employer_no_doc.pk]))
        self.assertEqual(response.status_code, 404)


class EmployerDashboardContextTests(TestCase):

    def setUp(self):
        self.employer = make_employer("emp_dash", "emp_dash@example.com")
        self.profile = self.employer.employer_profile
        self.client.force_login(self.employer)

    def test_pending_employer_dashboard_context(self):
        self.profile.verification_status = EmployerProfile.VerificationStatus.PENDING
        self.profile.save()
        response = self.client.get(reverse("employer_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_pending"])
        self.assertFalse(response.context["is_approved"])
        self.assertFalse(response.context["is_rejected"])
        self.assertFalse(response.context["can_post_jobs"])

    def test_approved_employer_dashboard_context(self):
        self.profile.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.profile.save()
        response = self.client.get(reverse("employer_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_approved"])
        self.assertFalse(response.context["is_pending"])
        self.assertTrue(response.context["can_post_jobs"])

    def test_rejected_employer_dashboard_context(self):
        self.profile.verification_status = EmployerProfile.VerificationStatus.REJECTED
        self.profile.rejection_reason = "Registration invalid"
        self.profile.save()
        response = self.client.get(reverse("employer_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_rejected"])
        self.assertEqual(response.context["rejection_reason"], "Registration invalid")
        self.assertFalse(response.context["can_post_jobs"])

    def test_dashboard_context_has_verification_document_flag(self):
        self.assertFalse(self.profile.verification_document)
        response = self.client.get(reverse("employer_dashboard"))
        self.assertFalse(response.context["has_verification_document"])

        self.profile.verification_document = SimpleUploadedFile("cert.pdf", b"%PDF-1.4 data", content_type="application/pdf")
        self.profile.save()
        response = self.client.get(reverse("employer_dashboard"))
        self.assertTrue(response.context["has_verification_document"])


# ---------------------------------------------------------------------------
# 14. Step 5.3 Employer UI & Template Rendering Tests
# ---------------------------------------------------------------------------

class Step5EmployerTemplateRenderTests(Step5ViewsBaseTestCase):

    def setUp(self):
        super().setUp()
        self.employer = make_employer("tpl_emp", "tpl_emp@example.com")
        self.profile = self.employer.employer_profile
        self.profile.company_name = "TechSphere Nepal"
        self.profile.industry = "Software & IT"
        self.profile.website = "https://techsphere.example.com"
        self.profile.phone = "+977-1-4444444"
        self.profile.address = "Tinkune, Kathmandu"
        self.profile.description = "Leading software engineering consultancy in Nepal."
        self.profile.save()

    def test_approved_employer_dashboard_renders_approved_state(self):
        self.profile.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.profile.save()
        self.client.force_login(self.employer)
        response = self.client.get(reverse("employer_dashboard"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Company Verified", content)
        self.assertIn("Verified", content)
        self.assertIn("TechSphere Nepal", content)
        self.assertIn(reverse("company_detail", args=[self.profile.pk]), content)
        self.assertNotIn("Verification Pending", content)
        self.assertNotIn("Action Required", content)

    def test_pending_employer_dashboard_renders_pending_state(self):
        self.profile.verification_status = EmployerProfile.VerificationStatus.PENDING
        self.profile.save()
        self.client.force_login(self.employer)
        response = self.client.get(reverse("employer_dashboard"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Verification Pending", content)
        self.assertIn("Under Review", content)
        self.assertNotIn("Company Verified", content)
        self.assertNotIn("Verification Not Approved", content)

    def test_rejected_employer_dashboard_renders_rejection_reason(self):
        self.profile.verification_status = EmployerProfile.VerificationStatus.REJECTED
        self.profile.rejection_reason = "PAN certificate blurred and illegible."
        self.profile.save()
        self.client.force_login(self.employer)
        response = self.client.get(reverse("employer_dashboard"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Verification Not Approved", content)
        self.assertIn("Action Required", content)
        self.assertIn("PAN certificate blurred and illegible.", content)
        self.assertIn(reverse("employer_verification_submit"), content)

    def test_employer_profile_view_renders_company_info(self):
        self.client.force_login(self.employer)
        response = self.client.get(reverse("employer_profile"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("TechSphere Nepal", content)
        self.assertIn("Software &amp; IT", content)
        self.assertIn("https://techsphere.example.com", content)
        self.assertIn("+977-1-4444444", content)
        self.assertIn("Tinkune, Kathmandu", content)
        self.assertIn("Leading software engineering consultancy in Nepal.", content)
        self.assertIn(reverse("employer_profile_edit"), content)
        self.assertNotIn("private_media", content)

    def test_employer_profile_edit_renders_expected_form(self):
        self.client.force_login(self.employer)
        response = self.client.get(reverse("employer_profile_edit"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('enctype="multipart/form-data"', content)
        self.assertIn("Edit Company Profile", content)
        self.assertIn('name="company_name"', content)
        self.assertIn('name="industry"', content)
        self.assertIn('name="website"', content)
        self.assertIn('name="logo"', content)
        self.assertIn("Save Changes", content)

    def test_employer_verification_page_renders_form_and_guidelines(self):
        self.client.force_login(self.employer)
        response = self.client.get(reverse("employer_verification_submit"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('enctype="multipart/form-data"', content)
        self.assertIn("10 MB", content)
        self.assertIn("PDF", content)
        self.assertIn("Company Verification", content)
        self.assertIn('name="verification_document"', content)

    def test_rejected_employer_verification_page_renders_feedback(self):
        self.profile.verification_status = EmployerProfile.VerificationStatus.REJECTED
        self.profile.rejection_reason = "Official stamp is missing from the submitted document."
        self.profile.save()
        self.client.force_login(self.employer)
        response = self.client.get(reverse("employer_verification_submit"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Official stamp is missing from the submitted document.", content)
        self.assertIn("Resubmit Verification", content)

    def test_public_company_page_renders_expected_public_fields(self):
        self.profile.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.profile.save()
        response = self.client.get(reverse("company_detail", args=[self.profile.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("TechSphere Nepal", content)
        self.assertIn("Verified Company", content)
        self.assertIn("Software &amp; IT", content)
        self.assertIn("https://techsphere.example.com", content)
        self.assertIn("Leading software engineering consultancy in Nepal.", content)

    def test_public_company_page_does_not_expose_private_document_or_rejection(self):
        self.profile.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.profile.verification_document = SimpleUploadedFile("secret_biz_reg.pdf", b"%PDF-1.4 sample", content_type="application/pdf")
        self.profile.rejection_reason = "Internal admin note that should never be shown."
        self.profile.save()
        response = self.client.get(reverse("company_detail", args=[self.profile.pk]))
        content = response.content.decode()
        self.assertNotIn("secret_biz_reg.pdf", content)
        self.assertNotIn(self.profile.verification_document.name, content)
        self.assertNotIn("Internal admin note that should never be shown.", content)
        self.assertNotIn("private_media", content)

    def test_logo_rendering_and_fallback(self):
        # Without logo, placeholder monogram is shown
        self.profile.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.profile.save()
        response = self.client.get(reverse("company_detail", args=[self.profile.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("company-logo-hero-placeholder", content)
        self.assertIn("T", content)

        # With logo uploaded
        self.profile.logo = make_image("brand_logo.png")
        self.profile.save()
        response2 = self.client.get(reverse("company_detail", args=[self.profile.pk]))
        self.assertEqual(response2.status_code, 200)
        content2 = response2.content.decode()
        self.assertIn(self.profile.logo.url, content2)
        self.assertIn("company-logo-hero", content2)


# ===========================================================================
# Step 6.11 — Recruitment Dashboards & Interview Lifecycle Tests
# ===========================================================================

from datetime import timedelta
from django.utils import timezone
from applications.models import Application, Interview
from jobs.models import Category, Job, Location


class Step611EmployerRecruitmentDashboardTests(TestCase):
    def setUp(self):
        self.employer_a_user = make_employer(username="dash_emp_a", email="dash_emp_a@example.com")
        self.employer_b_user = make_employer(username="dash_emp_b", email="dash_emp_b@example.com")
        self.profile_a = self.employer_a_user.employer_profile
        self.profile_a.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.profile_a.save()

        self.profile_b = self.employer_b_user.employer_profile
        self.profile_b.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.profile_b.save()

        self.category = Category.objects.create(name="IT", slug="it-dash")
        self.location = Location.objects.create(name="Kathmandu", slug="ktm-dash")

        # Jobs for Employer A (2 published, 1 draft)
        self.job_a1 = Job.objects.create(
            employer=self.profile_a,
            title="Senior Python Dev",
            description="Desc",
            category=self.category,
            location=self.location,
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.PUBLISHED,
        )
        self.job_a2 = Job.objects.create(
            employer=self.profile_a,
            title="UI Designer",
            description="Desc",
            category=self.category,
            location=self.location,
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.PUBLISHED,
        )
        self.job_a3 = Job.objects.create(
            employer=self.profile_a,
            title="Draft QA Role",
            description="Desc",
            category=self.category,
            location=self.location,
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.DRAFT,
        )

        # Job for Employer B
        self.job_b = Job.objects.create(
            employer=self.profile_b,
            title="Data Scientist",
            description="Desc",
            category=self.category,
            location=self.location,
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.PUBLISHED,
        )

        # Create Candidates
        self.cands = [
            make_jobseeker(username=f"dash_cand_{i}", email=f"dash_cand_{i}@example.com")
            for i in range(7)
        ]

        # Applications for Employer A across stages
        self.app_applied = Application.objects.create(
            job=self.job_a1,
            jobseeker=self.cands[0].jobseeker_profile,
            status=Application.Status.APPLIED,
        )
        self.app_review = Application.objects.create(
            job=self.job_a1,
            jobseeker=self.cands[1].jobseeker_profile,
            status=Application.Status.UNDER_REVIEW,
        )
        self.app_shortlisted = Application.objects.create(
            job=self.job_a2,
            jobseeker=self.cands[2].jobseeker_profile,
            status=Application.Status.SHORTLISTED,
        )
        self.app_interview = Application.objects.create(
            job=self.job_a2,
            jobseeker=self.cands[3].jobseeker_profile,
            status=Application.Status.INTERVIEW,
        )
        self.app_selected = Application.objects.create(
            job=self.job_a1,
            jobseeker=self.cands[4].jobseeker_profile,
            status=Application.Status.SELECTED,
        )
        self.app_rejected = Application.objects.create(
            job=self.job_a2,
            jobseeker=self.cands[5].jobseeker_profile,
            status=Application.Status.REJECTED,
        )

        # Application for Employer B
        self.app_b = Application.objects.create(
            job=self.job_b,
            jobseeker=self.cands[6].jobseeker_profile,
            status=Application.Status.APPLIED,
        )

        # Interviews for Employer A
        self.int_future = Interview.objects.create(
            application=self.app_interview,
            created_by=self.employer_a_user,
            interview_type=Interview.InterviewType.VIDEO,
            scheduled_at=timezone.now() + timedelta(days=2),
            duration_minutes=45,
            location_or_link="https://meet.google.com/upcoming-a",
            status=Interview.InterviewStatus.SCHEDULED,
        )
        self.int_past = Interview.objects.create(
            application=self.app_shortlisted,
            created_by=self.employer_a_user,
            interview_type=Interview.InterviewType.IN_PERSON,
            scheduled_at=timezone.now() - timedelta(days=2),
            duration_minutes=30,
            location_or_link="Office KTM",
            status=Interview.InterviewStatus.SCHEDULED,
        )
        self.int_cancelled = Interview.objects.create(
            application=self.app_review,
            created_by=self.employer_a_user,
            interview_type=Interview.InterviewType.PHONE,
            scheduled_at=timezone.now() + timedelta(days=3),
            duration_minutes=15,
            status=Interview.InterviewStatus.CANCELLED,
        )
        self.int_completed = Interview.objects.create(
            application=self.app_selected,
            created_by=self.employer_a_user,
            interview_type=Interview.InterviewType.IN_PERSON,
            scheduled_at=timezone.now() - timedelta(days=1),
            duration_minutes=60,
            status=Interview.InterviewStatus.COMPLETED,
        )

        # Interview for Employer B
        self.int_b = Interview.objects.create(
            application=self.app_b,
            created_by=self.employer_b_user,
            interview_type=Interview.InterviewType.VIDEO,
            scheduled_at=timezone.now() + timedelta(days=1),
            duration_minutes=45,
            location_or_link="https://meet.google.com/upcoming-b",
            status=Interview.InterviewStatus.SCHEDULED,
        )

        self.dash_url = reverse("employer_dashboard")

    def test_dashboard_active_jobs_count(self):
        self.client.force_login(self.employer_a_user)
        response = self.client.get(self.dash_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["jobs_count"], 3)
        self.assertEqual(response.context["active_jobs_count"], 2)

    def test_dashboard_active_jobs_excludes_expired_closed_and_draft_jobs(self):
        user = make_employer(username="active_jobs_emp", email="active_jobs@example.com")
        profile = user.employer_profile
        profile.verification_status = EmployerProfile.VerificationStatus.APPROVED
        profile.save()

        # 1. Published future deadline (should be counted)
        Job.objects.create(
            employer=profile,
            category=self.category,
            location=self.location,
            title="Open Future Job",
            description="Desc",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
        )
        # 2. Published expired deadline (must be excluded)
        Job.objects.create(
            employer=profile,
            category=self.category,
            location=self.location,
            title="Expired Published Job",
            description="Desc",
            application_deadline=timezone.localdate() - timedelta(days=1),
            status=Job.Status.PUBLISHED,
        )
        # 3. Draft job with future deadline (must be excluded)
        Job.objects.create(
            employer=profile,
            category=self.category,
            location=self.location,
            title="Draft Job",
            description="Desc",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.DRAFT,
        )
        # 4. Closed job with future deadline (must be excluded)
        Job.objects.create(
            employer=profile,
            category=self.category,
            location=self.location,
            title="Closed Job",
            description="Desc",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.CLOSED,
        )

        self.client.force_login(user)
        response = self.client.get(self.dash_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["jobs_count"], 4)
        self.assertEqual(response.context["active_jobs_count"], 1)

    def test_dashboard_pipeline_metrics(self):
        self.client.force_login(self.employer_a_user)
        response = self.client.get(self.dash_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_applicants"], 6)
        self.assertEqual(response.context["needs_review_count"], 1)  # APPLIED
        self.assertEqual(response.context["screening_count"], 2)     # UNDER_REVIEW (1) + SHORTLISTED (1)
        self.assertEqual(response.context["interview_count"], 1)     # INTERVIEW
        self.assertEqual(response.context["hired_count"], 1)         # SELECTED

    def test_dashboard_employer_isolation(self):
        self.client.force_login(self.employer_b_user)
        response = self.client.get(self.dash_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["jobs_count"], 1)
        self.assertEqual(response.context["active_jobs_count"], 1)
        self.assertEqual(response.context["total_applicants"], 1)
        self.assertEqual(response.context["needs_review_count"], 1)
        self.assertEqual(response.context["screening_count"], 0)
        self.assertEqual(response.context["interview_count"], 0)
        self.assertEqual(response.context["hired_count"], 0)

    def test_dashboard_upcoming_interviews_filtering(self):
        self.client.force_login(self.employer_a_user)
        response = self.client.get(self.dash_url)
        self.assertEqual(response.status_code, 200)
        upcoming = list(response.context["upcoming_interviews"])
        # Only future scheduled interview should appear
        self.assertIn(self.int_future, upcoming)
        self.assertNotIn(self.int_past, upcoming)
        self.assertNotIn(self.int_cancelled, upcoming)
        self.assertNotIn(self.int_completed, upcoming)
        self.assertNotIn(self.int_b, upcoming)

    def test_dashboard_recent_applicants_ordering_and_isolation(self):
        self.client.force_login(self.employer_a_user)
        response = self.client.get(self.dash_url)
        self.assertEqual(response.status_code, 200)
        recent = list(response.context["recent_applicants"])
        self.assertEqual(len(recent), 6)
        # B's applicant is excluded
        self.assertNotIn(self.app_b, recent)
        # First item is the most recently created
        self.assertEqual(recent[0], self.app_rejected)

    def test_dashboard_quick_actions_rendered(self):
        self.client.force_login(self.employer_a_user)
        response = self.client.get(self.dash_url)
        content = response.content.decode()
        self.assertIn(reverse("employer_job_create"), content)
        self.assertIn(reverse("employer_job_list"), content)
        self.assertIn(reverse("employer_all_applicants"), content)

    def test_unapproved_employer_metrics_safe(self):
        pending_emp = make_employer(
            username="pending_dash_emp",
            email="pending_dash@example.com",
        )
        self.client.force_login(pending_emp)
        response = self.client.get(self.dash_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["jobs_count"], 0)
        self.assertEqual(response.context["active_jobs_count"], 0)


class Step611CandidateUpcomingInterviewsTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer(username="cand_dash_emp", email="cand_dash_emp@example.com")
        self.employer_user.employer_profile.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.employer_user.employer_profile.save()

        self.cand1 = make_jobseeker(username="cand_dash_1", email="cand_dash_1@example.com")
        self.cand2 = make_jobseeker(username="cand_dash_2", email="cand_dash_2@example.com")

        self.category = Category.objects.create(name="Design", slug="design-cand")
        self.location = Location.objects.create(name="Lalitpur", slug="lalitpur-cand")

        self.job = Job.objects.create(
            employer=self.employer_user.employer_profile,
            title="Product Designer",
            description="Design modern apps",
            category=self.category,
            location=self.location,
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.PUBLISHED,
        )
        self.job2 = Job.objects.create(
            employer=self.employer_user.employer_profile,
            title="UX Researcher",
            description="UX Research",
            category=self.category,
            location=self.location,
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.PUBLISHED,
        )

        self.app1 = Application.objects.create(
            job=self.job,
            jobseeker=self.cand1.jobseeker_profile,
            status=Application.Status.INTERVIEW,
        )
        self.app1_second = Application.objects.create(
            job=self.job2,
            jobseeker=self.cand1.jobseeker_profile,
            status=Application.Status.INTERVIEW,
        )
        self.app2 = Application.objects.create(
            job=self.job,
            jobseeker=self.cand2.jobseeker_profile,
            status=Application.Status.INTERVIEW,
        )

        # Cand 1 interviews
        self.int_future = Interview.objects.create(
            application=self.app1,
            created_by=self.employer_user,
            interview_type=Interview.InterviewType.VIDEO,
            scheduled_at=timezone.now() + timedelta(days=3),
            duration_minutes=45,
            location_or_link="https://meet.google.com/cand1-future",
            candidate_instructions="Review our design system",
            internal_notes="Confidential: check portfolio depth",
            status=Interview.InterviewStatus.SCHEDULED,
        )
        self.int_past = Interview.objects.create(
            application=self.app1_second,
            created_by=self.employer_user,
            interview_type=Interview.InterviewType.IN_PERSON,
            scheduled_at=timezone.now() - timedelta(days=2),
            duration_minutes=30,
            status=Interview.InterviewStatus.SCHEDULED,
        )
        self.int_cancelled = Interview.objects.create(
            application=self.app1,
            created_by=self.employer_user,
            interview_type=Interview.InterviewType.PHONE,
            scheduled_at=timezone.now() + timedelta(days=5),
            duration_minutes=15,
            status=Interview.InterviewStatus.CANCELLED,
        )
        self.int_completed = Interview.objects.create(
            application=self.app1,
            created_by=self.employer_user,
            interview_type=Interview.InterviewType.IN_PERSON,
            scheduled_at=timezone.now() - timedelta(days=1),
            duration_minutes=60,
            status=Interview.InterviewStatus.COMPLETED,
        )

        # Cand 2 interview
        self.int_cand2 = Interview.objects.create(
            application=self.app2,
            created_by=self.employer_user,
            interview_type=Interview.InterviewType.VIDEO,
            scheduled_at=timezone.now() + timedelta(days=4),
            duration_minutes=45,
            status=Interview.InterviewStatus.SCHEDULED,
        )

        self.dash_url = reverse("jobseeker_dashboard")

    def test_candidate_dashboard_shows_upcoming_interviews(self):
        self.client.force_login(self.cand1)
        response = self.client.get(self.dash_url)
        self.assertEqual(response.status_code, 200)
        upcoming = list(response.context["upcoming_interviews"])
        self.assertIn(self.int_future, upcoming)
        self.assertNotIn(self.int_past, upcoming)
        self.assertNotIn(self.int_cancelled, upcoming)
        self.assertNotIn(self.int_completed, upcoming)
        self.assertNotIn(self.int_cand2, upcoming)

        content = response.content.decode()
        self.assertIn("Upcoming Scheduled Interviews", content)
        self.assertIn("Product Designer", content)
        self.assertIn("https://meet.google.com/cand1-future", content)
        self.assertIn("Review our design system", content)
        self.assertIn(reverse("jobseeker_application_detail", args=[self.app1.pk]), content)

    def test_candidate_dashboard_does_not_leak_internal_notes(self):
        self.client.force_login(self.cand1)
        response = self.client.get(self.dash_url)
        content = response.content.decode()
        self.assertNotIn("Confidential: check portfolio depth", content)
        self.assertNotIn("internal_notes", content)

    def test_candidate_isolation(self):
        self.client.force_login(self.cand2)
        response = self.client.get(self.dash_url)
        self.assertEqual(response.status_code, 200)
        upcoming = list(response.context["upcoming_interviews"])
        self.assertIn(self.int_cand2, upcoming)
        self.assertNotIn(self.int_future, upcoming)


class Step612CandidateDashboardSavedJobsTests(TestCase):
    def setUp(self):
        self.employer_user = make_employer(username="dash_emp", email="dash_emp@example.com")
        self.employer = self.employer_user.employer_profile
        self.employer.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.employer.save()

        from jobs.models import Category, Location, Job
        self.cat = Category.objects.create(name="Dash Cat", slug="dash-cat")
        self.loc = Location.objects.create(name="Dash Loc", slug="dash-loc")

        self.cand1 = make_jobseeker(username="dash_cand1", email="dash_cand1@example.com")
        self.cand2 = make_jobseeker(username="dash_cand2", email="dash_cand2@example.com")

        today = timezone.localdate()
        self.jobs = []
        for i in range(5):
            j = Job.objects.create(
                employer=self.employer,
                category=self.cat,
                location=self.loc,
                title=f"Dash Position {i}",
                description="Dashboard test role.",
                application_deadline=today + timedelta(days=10 + i),
                status=Job.Status.PUBLISHED,
                published_at=timezone.now(),
            )
            self.jobs.append(j)

        self.dash_url = reverse("jobseeker_dashboard")

    def test_candidate_dashboard_saved_jobs_count_and_recent_3(self):
        from jobs.models import SavedJob
        # Save 4 jobs for cand1
        for j in self.jobs[:4]:
            SavedJob.objects.create(jobseeker=self.cand1.jobseeker_profile, job=j)

        self.client.force_login(self.cand1)
        response = self.client.get(self.dash_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["saved_jobs_count"], 4)
        recent = list(response.context["recent_saved_jobs"])
        self.assertEqual(len(recent), 3)

        content = response.content.decode()
        self.assertIn("Saved Jobs", content)
        self.assertIn("View All Saved Jobs (4)", content)
        self.assertIn(reverse("saved_job_list"), content)

    def test_candidate_dashboard_saved_jobs_candidate_isolation(self):
        from jobs.models import SavedJob
        SavedJob.objects.create(jobseeker=self.cand1.jobseeker_profile, job=self.jobs[0])

        self.client.force_login(self.cand2)
        response = self.client.get(self.dash_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["saved_jobs_count"], 0)
        self.assertEqual(len(response.context["recent_saved_jobs"]), 0)

    def test_candidate_dashboard_quick_links_includes_saved_jobs(self):
        self.client.force_login(self.cand1)
        response = self.client.get(self.dash_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(f'href="{reverse("saved_job_list")}"', content)
        self.assertIn("Saved Jobs (0)", content)


# ===========================================================================
# Step 6.13 — Public Employer / Company Experience Tests
# ===========================================================================

class Step613PublicCompanyExperienceTests(TestCase):

    def setUp(self):
        self.category = Category.objects.create(name="Engineering", slug="engineering-comp")
        self.location = Location.objects.create(name="Kathmandu", slug="ktm-comp")

        # Approved Company A
        self.emp_a_user = make_employer("emp_apex", "emp_apex@example.com")
        self.profile_a = self.emp_a_user.employer_profile
        self.profile_a.company_name = "Apex Solutions"
        self.profile_a.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.profile_a.industry = "FinTech"
        self.profile_a.address = "Putalisadak, Kathmandu"
        self.profile_a.website = "https://apexsolutions.example.com"
        self.profile_a.phone = "+977-1-4222222"
        self.profile_a.description = "Apex Solutions is a leading payments provider."
        self.profile_a.rejection_reason = "CONFIDENTIAL_ADMIN_NOTE_NEVER_SHOW"
        self.profile_a.verification_document = SimpleUploadedFile(
            "confidential_tax_cert.pdf",
            b"%PDF-1.4 private tax doc",
            content_type="application/pdf",
        )
        self.profile_a.save()

        # Approved Company B (no jobs initially)
        self.emp_b_user = make_employer("emp_beta", "emp_beta@example.com")
        self.profile_b = self.emp_b_user.employer_profile
        self.profile_b.company_name = "Beta Corp"
        self.profile_b.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.profile_b.save()

        # Pending Company C
        self.emp_c_user = make_employer("emp_gamma", "emp_gamma@example.com")
        self.profile_c = self.emp_c_user.employer_profile
        self.profile_c.verification_status = EmployerProfile.VerificationStatus.PENDING
        self.profile_c.save()

        # Rejected Company D
        self.emp_d_user = make_employer("emp_delta", "emp_delta@example.com")
        self.profile_d = self.emp_d_user.employer_profile
        self.profile_d.verification_status = EmployerProfile.VerificationStatus.REJECTED
        self.profile_d.save()

        # Jobseekers
        self.cand1 = make_jobseeker("cand_co1", "cand_co1@example.com")
        self.cand2 = make_jobseeker("cand_co2", "cand_co2@example.com")

        # Jobs for Company A: 2 open, 1 draft, 1 closed, 1 expired
        self.open_job_1 = Job.objects.create(
            employer=self.profile_a,
            title="Senior Backend Engineer",
            description="Python and Django backend systems.",
            category=self.category,
            location=self.location,
            status=Job.Status.PUBLISHED,
            application_deadline=timezone.localdate() + timedelta(days=10),
        )
        self.open_job_2 = Job.objects.create(
            employer=self.profile_a,
            title="Frontend Engineer",
            description="React, CSS, and modern user interfaces.",
            category=self.category,
            location=self.location,
            status=Job.Status.PUBLISHED,
            application_deadline=timezone.localdate() + timedelta(days=5),
        )
        self.draft_job = Job.objects.create(
            employer=self.profile_a,
            title="Draft DevOps Role",
            description="Kubernetes and Terraform setup.",
            category=self.category,
            location=self.location,
            status=Job.Status.DRAFT,
            application_deadline=timezone.localdate() + timedelta(days=10),
        )
        self.closed_job = Job.objects.create(
            employer=self.profile_a,
            title="Closed Sales Executive",
            description="Enterprise corporate sales.",
            category=self.category,
            location=self.location,
            status=Job.Status.CLOSED,
            application_deadline=timezone.localdate() + timedelta(days=10),
        )
        self.expired_job = Job.objects.create(
            employer=self.profile_a,
            title="Expired Product Manager",
            description="Product roadmaps and strategy.",
            category=self.category,
            location=self.location,
            status=Job.Status.PUBLISHED,
            application_deadline=timezone.localdate() - timedelta(days=1),
        )

        # Job for Company B
        self.other_job = Job.objects.create(
            employer=self.profile_b,
            title="Beta Corp Marketer",
            description="Marketing campaigns.",
            category=self.category,
            location=self.location,
            status=Job.Status.PUBLISHED,
            application_deadline=timezone.localdate() + timedelta(days=10),
        )

    def test_anonymous_guest_can_view_approved_company(self):
        url = reverse("company_detail", args=[self.profile_a.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["company"], self.profile_a)
        self.assertEqual(response.context["open_jobs_count"], 2)
        content = response.content.decode()
        self.assertIn("Apex Solutions", content)
        self.assertIn("Verified Company", content)
        self.assertIn("FinTech", content)
        self.assertIn("Putalisadak, Kathmandu", content)
        self.assertIn("https://apexsolutions.example.com", content)
        self.assertIn("+977-1-4222222", content)
        self.assertIn("Active Job Vacancies (2)", content)

    def test_authenticated_jobseeker_can_view_approved_company(self):
        self.client.force_login(self.cand1)
        url = reverse("company_detail", args=[self.profile_a.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["open_jobs_count"], 2)

    def test_pending_company_returns_404(self):
        url = reverse("company_detail", args=[self.profile_c.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_rejected_company_returns_404(self):
        url = reverse("company_detail", args=[self.profile_d.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_company_returns_404(self):
        url = reverse("company_detail", args=[999999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_private_fields_and_account_credentials_never_exposed(self):
        url = reverse("company_detail", args=[self.profile_a.pk])
        response = self.client.get(url)
        content = response.content.decode()
        self.assertNotIn("CONFIDENTIAL_ADMIN_NOTE_NEVER_SHOW", content)
        self.assertNotIn("confidential_tax_cert.pdf", content)
        self.assertNotIn(self.profile_a.verification_document.name, content)
        self.assertNotIn("emp_apex@example.com", content)
        self.assertNotIn("emp_apex", content)
        self.assertNotIn("private_media", content)

    def test_open_jobs_filtering_shows_only_open_jobs_of_this_company(self):
        url = reverse("company_detail", args=[self.profile_a.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Published open jobs belonging to Company A must appear
        self.assertIn("Senior Backend Engineer", content)
        self.assertIn("Frontend Engineer", content)

        # Draft, closed, expired, and other company's jobs must NOT appear
        self.assertNotIn("Draft DevOps Role", content)
        self.assertNotIn("Closed Sales Executive", content)
        self.assertNotIn("Expired Product Manager", content)
        self.assertNotIn("Beta Corp Marketer", content)

    def test_zero_open_jobs_renders_polite_empty_state(self):
        # Delete Company B's single job so it has 0 open jobs
        self.other_job.delete()
        url = reverse("company_detail", args=[self.profile_b.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["open_jobs_count"], 0)
        content = response.content.decode()
        self.assertIn("Beta Corp", content)
        self.assertIn("Active Job Vacancies (0)", content)
        self.assertIn(
            "There are currently no active job vacancies listed for this company. Please check back later.",
            content,
        )

    def test_navigation_link_on_job_detail_points_to_company(self):
        url = reverse("job_detail", args=[self.open_job_1.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        company_url = reverse("company_detail", args=[self.profile_a.pk])
        self.assertIn(company_url, content)

    def test_company_vacancy_links_to_correct_job_detail(self):
        url = reverse("company_detail", args=[self.profile_a.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        job1_url = reverse("job_detail", args=[self.open_job_1.pk])
        job2_url = reverse("job_detail", args=[self.open_job_2.pk])
        self.assertIn(job1_url, content)
        self.assertIn(job2_url, content)

    def test_pagination_with_multiple_pages(self):
        # Create 12 more open jobs for Company A (total = 14)
        for i in range(12):
            Job.objects.create(
                employer=self.profile_a,
                title=f"Extra Job {i+1}",
                description=f"Description {i+1}",
                category=self.category,
                location=self.location,
                status=Job.Status.PUBLISHED,
                application_deadline=timezone.localdate() + timedelta(days=15),
            )

        url = reverse("company_detail", args=[self.profile_a.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["open_jobs_count"], 14)
        self.assertEqual(len(response.context["jobs"]), 10)
        self.assertTrue(response.context["page_obj"].has_next())

        content = response.content.decode()
        self.assertIn("?page=2", content)

        # Page 2
        response2 = self.client.get(f"{url}?page=2")
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(len(response2.context["jobs"]), 4)
        self.assertTrue(response2.context["page_obj"].has_previous())
        content2 = response2.content.decode()
        self.assertIn("?page=1", content2)

    def test_saved_jobs_integration_for_jobseeker(self):
        from jobs.models import SavedJob
        # cand1 saves open_job_1
        SavedJob.objects.create(jobseeker=self.cand1.jobseeker_profile, job=self.open_job_1)

        self.client.force_login(self.cand1)
        url = reverse("company_detail", args=[self.profile_a.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.open_job_1.pk, response.context["saved_job_ids"])
        self.assertNotIn(self.open_job_2.pk, response.context["saved_job_ids"])

        content = response.content.decode()
        save_toggle_url = reverse("toggle_save_job", args=[self.open_job_1.pk])
        self.assertIn(save_toggle_url, content)
        self.assertIn("Saved", content)
        self.assertIn("Save", content)

    def test_saved_jobs_isolation_between_candidates(self):
        from jobs.models import SavedJob
        # cand1 saves open_job_1
        SavedJob.objects.create(jobseeker=self.cand1.jobseeker_profile, job=self.open_job_1)

        # cand2 logs in
        self.client.force_login(self.cand2)
        url = reverse("company_detail", args=[self.profile_a.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["saved_job_ids"]), 0)
        self.assertNotIn(self.open_job_1.pk, response.context["saved_job_ids"])

    def test_anonymous_user_sees_login_link_for_save(self):
        url = reverse("company_detail", args=[self.profile_a.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["saved_job_ids"]), 0)
        content = response.content.decode()
        self.assertIn(reverse("login"), content)
        self.assertNotIn('action="' + reverse("toggle_save_job", args=[self.open_job_1.pk]) + '"', content)

    def test_employer_does_not_see_candidate_save_buttons(self):
        self.client.force_login(self.emp_b_user)
        url = reverse("company_detail", args=[self.profile_a.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["saved_job_ids"]), 0)
        content = response.content.decode()
        self.assertNotIn('action="' + reverse("toggle_save_job", args=[self.open_job_1.pk]) + '"', content)

    def test_bounded_query_count_on_company_detail(self):
        from jobs.models import SavedJob
        # Create 10 open jobs
        for i in range(8):
            Job.objects.create(
                employer=self.profile_a,
                title=f"Query Bound Job {i+1}",
                description="Desc",
                category=self.category,
                location=self.location,
                status=Job.Status.PUBLISHED,
                application_deadline=timezone.localdate() + timedelta(days=15),
            )
        SavedJob.objects.create(jobseeker=self.cand1.jobseeker_profile, job=self.open_job_1)

        self.client.force_login(self.cand1)
        url = reverse("company_detail", args=[self.profile_a.pk])

        # Under authenticated jobseeker, query count is bounded and constant O(1):
        # 1: EmployerProfile lookup
        # 2: Job count query for paginator
        # 3: Session lookup (session middleware)
        # 4: User lookup (auth middleware)
        # 5: JobseekerProfile lookup (for saved_jobs query)
        # 6: 10 Jobs page slice with select_related category & location
        # 7: Batched SavedJob lookup with job_id IN (...)
        # 8: Unread notifications count in navbar context processor
        with self.assertNumQueries(8):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.context["jobs"]), 10)


# ---------------------------------------------------------------------------
# Step 6.16B: Reusable CBV Role-Based Access Mixins Tests
# ---------------------------------------------------------------------------
import sys
import types
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.urls import path
from django.views import View

import config.urls
from accounts.mixins import (
    ApprovedEmployerRequiredMixin,
    EmployerRequiredMixin,
    JobseekerRequiredMixin,
    StaffRequiredMixin,
)


class DummyJobseekerView(JobseekerRequiredMixin, View):
    def get(self, request):
        return HttpResponse("jobseeker ok")


class DummyEmployerView(EmployerRequiredMixin, View):
    def get(self, request):
        return HttpResponse("employer ok")


class DummyApprovedEmployerView(ApprovedEmployerRequiredMixin, View):
    def get(self, request):
        return HttpResponse("approved employer ok")


class DummyStaffView(StaffRequiredMixin, View):
    def get(self, request):
        return HttpResponse("staff ok")


_mixin_test_urlpatterns = list(config.urls.urlpatterns) + [
    path("test-cbv/jobseeker/", DummyJobseekerView.as_view(), name="test_cbv_jobseeker"),
    path("test-cbv/employer/", DummyEmployerView.as_view(), name="test_cbv_employer"),
    path("test-cbv/approved-employer/", DummyApprovedEmployerView.as_view(), name="test_cbv_approved_employer"),
    path("test-cbv/staff/", DummyStaffView.as_view(), name="test_cbv_staff"),
]

_mixin_test_urls_module = "accounts._test_cbv_urls"
_mod = types.ModuleType(_mixin_test_urls_module)
_mod.urlpatterns = _mixin_test_urlpatterns
sys.modules[_mixin_test_urls_module] = _mod


@override_settings(ROOT_URLCONF=_mixin_test_urls_module)
class RoleBasedAccessMixinsTests(TestCase):
    """Unit tests for Step 6.16B CBV role-based access mixins."""

    def setUp(self):
        self.factory = RequestFactory()

        # Jobseeker
        self.jobseeker = make_jobseeker(username="test_js_mixin", email="test_js_mixin@example.com")

        # Employers with different verification states
        self.employer_approved = User.objects.create_user(
            username="test_emp_app", email="test_emp_app@example.com", password="Testpass123!",
            role=User.Role.EMPLOYER,
        )
        self.profile_approved = EmployerProfile.objects.create(
            user=self.employer_approved, company_name="Approved Co",
            verification_status=EmployerProfile.VerificationStatus.APPROVED,
        )

        self.employer_pending = User.objects.create_user(
            username="test_emp_pend", email="test_emp_pend@example.com", password="Testpass123!",
            role=User.Role.EMPLOYER,
        )
        self.profile_pending = EmployerProfile.objects.create(
            user=self.employer_pending, company_name="Pending Co",
            verification_status=EmployerProfile.VerificationStatus.PENDING,
        )

        self.employer_rejected = User.objects.create_user(
            username="test_emp_rej", email="test_emp_rej@example.com", password="Testpass123!",
            role=User.Role.EMPLOYER,
        )
        self.profile_rejected = EmployerProfile.objects.create(
            user=self.employer_rejected, company_name="Rejected Co",
            verification_status=EmployerProfile.VerificationStatus.REJECTED,
        )

        # Employer without profile
        self.employer_no_profile = User.objects.create_user(
            username="test_emp_noprof", email="test_emp_noprof@example.com", password="Testpass123!",
            role=User.Role.EMPLOYER,
        )

        # Staff user
        self.staff_user = User.objects.create_user(
            username="test_staff_mixin", email="test_staff_mixin@example.com", password="Testpass123!",
            role=User.Role.JOBSEEKER, is_staff=True,
        )

        # Superuser
        self.superuser = User.objects.create_superuser(
            username="test_super_mixin", email="test_super_mixin@example.com", password="Testpass123!",
        )

    # -----------------------------------------------------------------------
    # JobseekerRequiredMixin
    # -----------------------------------------------------------------------
    def test_jobseeker_mixin_anonymous_redirects_to_login(self):
        response = self.client.get("/test-cbv/jobseeker/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/?next=/test-cbv/jobseeker/", response.headers["Location"])

    def test_jobseeker_mixin_correct_role_access(self):
        self.client.force_login(self.jobseeker)
        response = self.client.get("/test-cbv/jobseeker/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"jobseeker ok")

    def test_jobseeker_mixin_wrong_role_raises_403(self):
        self.client.force_login(self.employer_approved)
        response = self.client.get("/test-cbv/jobseeker/")
        self.assertEqual(response.status_code, 403)

    # -----------------------------------------------------------------------
    # EmployerRequiredMixin
    # -----------------------------------------------------------------------
    def test_employer_mixin_anonymous_redirects_to_login(self):
        response = self.client.get("/test-cbv/employer/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/?next=/test-cbv/employer/", response.headers["Location"])

    def test_employer_mixin_correct_role_access(self):
        self.client.force_login(self.employer_pending)
        response = self.client.get("/test-cbv/employer/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"employer ok")

    def test_employer_mixin_wrong_role_raises_403(self):
        self.client.force_login(self.jobseeker)
        response = self.client.get("/test-cbv/employer/")
        self.assertEqual(response.status_code, 403)

    # -----------------------------------------------------------------------
    # ApprovedEmployerRequiredMixin
    # -----------------------------------------------------------------------
    def test_approved_employer_mixin_anonymous_redirects_to_login(self):
        response = self.client.get("/test-cbv/approved-employer/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/?next=/test-cbv/approved-employer/", response.headers["Location"])

    def test_approved_employer_mixin_non_employer_raises_403(self):
        self.client.force_login(self.jobseeker)
        response = self.client.get("/test-cbv/approved-employer/")
        self.assertEqual(response.status_code, 403)

    def test_approved_employer_mixin_employer_without_profile_raises_403(self):
        self.client.force_login(self.employer_no_profile)
        response = self.client.get("/test-cbv/approved-employer/")
        self.assertEqual(response.status_code, 403)

    def test_approved_employer_mixin_pending_employer_raises_403(self):
        self.client.force_login(self.employer_pending)
        response = self.client.get("/test-cbv/approved-employer/")
        self.assertEqual(response.status_code, 403)

    def test_approved_employer_mixin_rejected_employer_raises_403(self):
        self.client.force_login(self.employer_rejected)
        response = self.client.get("/test-cbv/approved-employer/")
        self.assertEqual(response.status_code, 403)

    def test_approved_employer_mixin_approved_employer_allowed(self):
        self.client.force_login(self.employer_approved)
        response = self.client.get("/test-cbv/approved-employer/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"approved employer ok")

    # -----------------------------------------------------------------------
    # StaffRequiredMixin
    # -----------------------------------------------------------------------
    def test_staff_mixin_anonymous_redirects_to_login(self):
        response = self.client.get("/test-cbv/staff/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/?next=/test-cbv/staff/", response.headers["Location"])

    def test_staff_mixin_non_staff_raises_403(self):
        self.client.force_login(self.jobseeker)
        response = self.client.get("/test-cbv/staff/")
        self.assertEqual(response.status_code, 403)

    def test_staff_mixin_staff_user_allowed(self):
        self.client.force_login(self.staff_user)
        response = self.client.get("/test-cbv/staff/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"staff ok")

    def test_staff_mixin_superuser_allowed(self):
        self.client.force_login(self.superuser)
        response = self.client.get("/test-cbv/staff/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"staff ok")

    # -----------------------------------------------------------------------
    # Direct PermissionDenied Exception Verification (Unit-level)
    # -----------------------------------------------------------------------
    def test_mixins_raise_permission_denied_directly(self):
        request = self.factory.get("/test-cbv/jobseeker/")
        request.user = self.employer_approved
        with self.assertRaises(PermissionDenied):
            DummyJobseekerView.as_view()(request)

        request = self.factory.get("/test-cbv/employer/")
        request.user = self.jobseeker
        with self.assertRaises(PermissionDenied):
            DummyEmployerView.as_view()(request)

        request = self.factory.get("/test-cbv/approved-employer/")
        request.user = self.employer_pending
        with self.assertRaises(PermissionDenied):
            DummyApprovedEmployerView.as_view()(request)

        request = self.factory.get("/test-cbv/staff/")
        request.user = self.jobseeker
        with self.assertRaises(PermissionDenied):
            DummyStaffView.as_view()(request)


class PublicAndRegistrationCBVTests(TestCase):
    """
    Regression test suite verifying CBV conversion for the four Accounts public/registration views:
    RegisterChoiceView, RegisterJobseekerView, RegisterEmployerView, and CompanyDetailView.
    """

    def setUp(self):
        self.approved_employer = make_employer("pub_app_emp", "pub_app_emp@example.com")
        self.approved_profile = self.approved_employer.employer_profile
        self.approved_profile.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.approved_profile.company_name = "Public Approved Tech"
        self.approved_profile.save()

        self.pending_employer = make_employer("pub_pend_emp", "pub_pend_emp@example.com")
        self.pending_profile = self.pending_employer.employer_profile
        self.pending_profile.verification_status = EmployerProfile.VerificationStatus.PENDING
        self.pending_profile.save()

        self.jobseeker = make_jobseeker("pub_js_user", "pub_js_user@example.com")

    def test_cbv_class_hierarchy_and_url_resolution(self):
        # Verify CBV subclasses
        self.assertTrue(issubclass(RegisterChoiceView, TemplateView))
        self.assertTrue(issubclass(RegisterJobseekerView, FormView))
        self.assertTrue(issubclass(RegisterEmployerView, FormView))
        self.assertTrue(issubclass(CompanyDetailView, DetailView))

        # Verify callable aliases
        self.assertTrue(callable(register_choice))
        self.assertTrue(callable(register_jobseeker))
        self.assertTrue(callable(register_employer))
        self.assertTrue(callable(company_detail))

        self.assertIs(register_choice.view_class, RegisterChoiceView)
        self.assertIs(register_jobseeker.view_class, RegisterJobseekerView)
        self.assertIs(register_employer.view_class, RegisterEmployerView)
        self.assertIs(company_detail.view_class, CompanyDetailView)

        # Verify URL resolution
        self.assertIs(resolve(reverse("register")).func.view_class, RegisterChoiceView)
        self.assertIs(resolve(reverse("register_jobseeker")).func.view_class, RegisterJobseekerView)
        self.assertIs(resolve(reverse("register_employer")).func.view_class, RegisterEmployerView)
        self.assertIs(resolve(reverse("company_detail", args=[self.approved_profile.pk])).func.view_class, CompanyDetailView)

    def test_register_choice_view(self):
        response = self.client.get(reverse("register"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/register_choice.html")
        content = response.content.decode()
        self.assertIn(reverse("register_jobseeker"), content)
        self.assertIn(reverse("register_employer"), content)

    def test_authenticated_user_redirected_from_registration(self):
        self.client.force_login(self.jobseeker)
        # Jobseeker registration redirect
        res_js_get = self.client.get(reverse("register_jobseeker"))
        self.assertEqual(res_js_get.status_code, 302)
        self.assertRedirects(res_js_get, reverse("dashboard"), fetch_redirect_response=False)

        res_js_post = self.client.post(reverse("register_jobseeker"), {})
        self.assertEqual(res_js_post.status_code, 302)
        self.assertRedirects(res_js_post, reverse("dashboard"), fetch_redirect_response=False)

        # Employer registration redirect
        res_emp_get = self.client.get(reverse("register_employer"))
        self.assertEqual(res_emp_get.status_code, 302)
        self.assertRedirects(res_emp_get, reverse("dashboard"), fetch_redirect_response=False)

        res_emp_post = self.client.post(reverse("register_employer"), {})
        self.assertEqual(res_emp_post.status_code, 302)
        self.assertRedirects(res_emp_post, reverse("dashboard"), fetch_redirect_response=False)

    def test_register_jobseeker_form_lifecycle(self):
        # 1. GET returns 200 with form
        res_get = self.client.get(reverse("register_jobseeker"))
        self.assertEqual(res_get.status_code, 200)
        self.assertTemplateUsed(res_get, "accounts/register_jobseeker.html")
        self.assertIn("form", res_get.context)

        # 2. Invalid POST returns 200 with errors
        res_invalid = self.client.post(reverse("register_jobseeker"), {"username": ""})
        self.assertEqual(res_invalid.status_code, 200)
        self.assertIn("form", res_invalid.context)
        self.assertTrue(res_invalid.context["form"].errors)

        # 3. Valid POST creates user & profile, logs in, sets message, redirects
        payload = {
            "username": "brandnewjobseeker",
            "first_name": "First",
            "last_name": "Last",
            "email": "brandnewjs@example.com",
            "password1": "Password123!",
            "password2": "Password123!",
        }
        res_valid = self.client.post(reverse("register_jobseeker"), payload)
        self.assertRedirects(res_valid, reverse("dashboard"), fetch_redirect_response=False)
        user = User.objects.get(username="brandnewjobseeker")
        self.assertTrue(user.is_jobseeker)
        self.assertTrue(hasattr(user, "jobseeker_profile"))
        messages = list(res_valid.wsgi_request._messages)
        self.assertTrue(any("Account created. Welcome to NepalJobs!" in str(m) for m in messages))

    def test_register_employer_form_lifecycle(self):
        # 1. GET returns 200 with form
        res_get = self.client.get(reverse("register_employer"))
        self.assertEqual(res_get.status_code, 200)
        self.assertTemplateUsed(res_get, "accounts/register_employer.html")
        self.assertIn("form", res_get.context)

        # 2. Invalid POST returns 200 with errors
        res_invalid = self.client.post(reverse("register_employer"), {"username": ""})
        self.assertEqual(res_invalid.status_code, 200)
        self.assertIn("form", res_invalid.context)
        self.assertTrue(res_invalid.context["form"].errors)

        # 3. Valid POST creates user & profile with pending status, logs in, sets message, redirects
        payload = {
            "username": "brandnewemployer",
            "email": "brandnewemp@example.com",
            "company_name": "Brand New Innovations",
            "phone": "9800000001",
            "address": "Baneshwor, Kathmandu",
            "password1": "Password123!",
            "password2": "Password123!",
        }
        res_valid = self.client.post(reverse("register_employer"), payload)
        self.assertRedirects(res_valid, reverse("dashboard"), fetch_redirect_response=False)
        user = User.objects.get(username="brandnewemployer")
        self.assertTrue(user.is_employer)
        self.assertTrue(hasattr(user, "employer_profile"))
        self.assertEqual(user.employer_profile.company_name, "Brand New Innovations")
        self.assertEqual(user.employer_profile.verification_status, EmployerProfile.VerificationStatus.PENDING)
        messages = list(res_valid.wsgi_request._messages)
        self.assertTrue(any("Company account created. It is pending admin approval." in str(m) for m in messages))

    def test_company_detail_view_visibility_and_404(self):
        # 1. Approved company returns 200 and context variables
        url_app = reverse("company_detail", args=[self.approved_profile.pk])
        res_app = self.client.get(url_app)
        self.assertEqual(res_app.status_code, 200)
        self.assertTemplateUsed(res_app, "accounts/company_detail.html")
        self.assertEqual(res_app.context["company"], self.approved_profile)
        self.assertIn("page_obj", res_app.context)
        self.assertIn("jobs", res_app.context)
        self.assertIn("open_jobs_count", res_app.context)
        self.assertIn("saved_job_ids", res_app.context)

        # 2. Pending company returns 404
        url_pend = reverse("company_detail", args=[self.pending_profile.pk])
        self.assertEqual(self.client.get(url_pend).status_code, 404)

        # 3. Non-existent company returns 404
        url_none = reverse("company_detail", args=[999999])
        self.assertEqual(self.client.get(url_none).status_code, 404)


class DashboardsAndProfileEditingCBVTests(TestCase):
    """
    Step 6.16E2a regression tests for Dashboards and Profile Editing CBVs:
    - dashboard (DashboardView)
    - jobseeker_dashboard (JobseekerDashboardView)
    - employer_dashboard (EmployerDashboardView)
    - employer_profile (EmployerProfileView)
    - employer_profile_edit (EmployerProfileEditView)
    - profile_view (ProfileView)
    - profile_edit (ProfileEditView)
    - skills_edit (SkillsEditView)
    """

    def setUp(self):
        self.staff_user = User.objects.create_superuser(
            username="adminuser",
            email="adminuser@example.com",
            password="Testpass123!",
        )
        self.employer_user = make_employer(
            username="emp_owner",
            email="emp_owner@example.com",
            password="Testpass123!",
        )
        self.employer_profile = self.employer_user.employer_profile

        self.other_employer_user = make_employer(
            username="emp_other",
            email="emp_other@example.com",
            password="Testpass123!",
        )

        self.jobseeker_user = make_jobseeker(
            username="js_owner",
            email="js_owner@example.com",
            password="Testpass123!",
        )
        self.jobseeker_profile = self.jobseeker_user.jobseeker_profile

        self.other_jobseeker_user = make_jobseeker(
            username="js_other",
            email="js_other@example.com",
            password="Testpass123!",
        )

    def test_cbv_classes_and_callable_aliases(self):
        # 1. Class inheritance
        self.assertTrue(issubclass(DashboardView, View))
        self.assertTrue(issubclass(JobseekerDashboardView, TemplateView))
        self.assertTrue(issubclass(EmployerDashboardView, TemplateView))
        self.assertTrue(issubclass(EmployerProfileView, TemplateView))
        self.assertTrue(issubclass(EmployerProfileEditView, UpdateView))
        self.assertTrue(issubclass(ProfileView, TemplateView))
        self.assertTrue(issubclass(ProfileEditView, UpdateView))
        self.assertTrue(issubclass(SkillsEditView, FormView))

        # 2. Callable aliases
        self.assertTrue(callable(dashboard))
        self.assertTrue(callable(jobseeker_dashboard))
        self.assertTrue(callable(employer_dashboard))
        self.assertTrue(callable(employer_profile))
        self.assertTrue(callable(employer_profile_edit))
        self.assertTrue(callable(profile_view))
        self.assertTrue(callable(profile_edit))
        self.assertTrue(callable(skills_edit))

        self.assertIs(dashboard.view_class, DashboardView)
        self.assertIs(jobseeker_dashboard.view_class, JobseekerDashboardView)
        self.assertIs(employer_dashboard.view_class, EmployerDashboardView)
        self.assertIs(employer_profile.view_class, EmployerProfileView)
        self.assertIs(employer_profile_edit.view_class, EmployerProfileEditView)
        self.assertIs(profile_view.view_class, ProfileView)
        self.assertIs(profile_edit.view_class, ProfileEditView)
        self.assertIs(skills_edit.view_class, SkillsEditView)

        # 3. URL resolution to CBVs
        self.assertIs(resolve(reverse("dashboard")).func.view_class, DashboardView)
        self.assertIs(resolve(reverse("jobseeker_dashboard")).func.view_class, JobseekerDashboardView)
        self.assertIs(resolve(reverse("employer_dashboard")).func.view_class, EmployerDashboardView)
        self.assertIs(resolve(reverse("employer_profile")).func.view_class, EmployerProfileView)
        self.assertIs(resolve(reverse("employer_profile_edit")).func.view_class, EmployerProfileEditView)
        self.assertIs(resolve(reverse("profile")).func.view_class, ProfileView)
        self.assertIs(resolve(reverse("profile_edit")).func.view_class, ProfileEditView)
        self.assertIs(resolve(reverse("skills_edit")).func.view_class, SkillsEditView)

        # 4. Deterministic identity with callable aliases
        self.assertIs(resolve(reverse("dashboard")).func, dashboard)
        self.assertIs(resolve(reverse("jobseeker_dashboard")).func, jobseeker_dashboard)
        self.assertIs(resolve(reverse("employer_dashboard")).func, employer_dashboard)
        self.assertIs(resolve(reverse("employer_profile")).func, employer_profile)
        self.assertIs(resolve(reverse("employer_profile_edit")).func, employer_profile_edit)
        self.assertIs(resolve(reverse("profile")).func, profile_view)
        self.assertIs(resolve(reverse("profile_edit")).func, profile_edit)
        self.assertIs(resolve(reverse("skills_edit")).func, skills_edit)

    def test_dashboard_routing_and_access(self):
        # Anonymous user redirects to login
        res_anon = self.client.get(reverse("dashboard"))
        self.assertEqual(res_anon.status_code, 302)
        self.assertIn(reverse("login"), res_anon.url)

        # Staff user redirects to admin:index
        self.client.force_login(self.staff_user)
        res_staff = self.client.get(reverse("dashboard"))
        self.assertRedirects(res_staff, reverse("admin:index"), fetch_redirect_response=False)

        # Employer user redirects to employer_dashboard
        self.client.force_login(self.employer_user)
        res_emp = self.client.get(reverse("dashboard"))
        self.assertRedirects(res_emp, reverse("employer_dashboard"), fetch_redirect_response=False)

        # Jobseeker user redirects to jobseeker_dashboard
        self.client.force_login(self.jobseeker_user)
        res_js = self.client.get(reverse("dashboard"))
        self.assertRedirects(res_js, reverse("jobseeker_dashboard"), fetch_redirect_response=False)

    def test_jobseeker_dashboard_access_and_context(self):
        # Anonymous user redirects to login
        res_anon = self.client.get(reverse("jobseeker_dashboard"))
        self.assertEqual(res_anon.status_code, 302)
        self.assertIn(reverse("login"), res_anon.url)

        # Employer user gets 403 Forbidden
        self.client.force_login(self.employer_user)
        res_emp = self.client.get(reverse("jobseeker_dashboard"))
        self.assertEqual(res_emp.status_code, 403)

        # Jobseeker gets 200 OK with expected context variables
        self.client.force_login(self.jobseeker_user)
        res_js = self.client.get(reverse("jobseeker_dashboard"))
        self.assertEqual(res_js.status_code, 200)
        self.assertTemplateUsed(res_js, "accounts/jobseeker_dashboard.html")
        expected_keys = [
            "steps",
            "done",
            "total",
            "percent",
            "app_metrics",
            "total_applications",
            "under_review_count",
            "interview_count",
            "selected_count",
            "recent_applications",
            "upcoming_interviews",
            "saved_jobs_count",
            "recent_saved_jobs",
            "today",
        ]
        for key in expected_keys:
            self.assertIn(key, res_js.context)

    def test_employer_dashboard_access_and_context(self):
        # Anonymous user redirects to login
        res_anon = self.client.get(reverse("employer_dashboard"))
        self.assertEqual(res_anon.status_code, 302)
        self.assertIn(reverse("login"), res_anon.url)

        # Jobseeker user gets 403 Forbidden
        self.client.force_login(self.jobseeker_user)
        res_js = self.client.get(reverse("employer_dashboard"))
        self.assertEqual(res_js.status_code, 403)

        # Employer user gets 200 OK with expected context variables
        self.client.force_login(self.employer_user)
        res_emp = self.client.get(reverse("employer_dashboard"))
        self.assertEqual(res_emp.status_code, 200)
        self.assertTemplateUsed(res_emp, "accounts/employer_dashboard.html")
        expected_keys = [
            "profile",
            "employer_profile",
            "verification_status",
            "is_approved",
            "is_pending",
            "is_rejected",
            "rejection_reason",
            "has_verification_document",
            "can_post_jobs",
            "jobs_count",
            "active_jobs_count",
            "pipeline_metrics",
            "total_applicants",
            "needs_review_count",
            "screening_count",
            "interview_count",
            "hired_count",
            "upcoming_interviews",
            "recent_applicants",
        ]
        for key in expected_keys:
            self.assertIn(key, res_emp.context)

    def test_employer_profile_view_and_edit_lifecycle(self):
        # Anonymous access redirects to login
        self.client.logout()
        res_view_anon = self.client.get(reverse("employer_profile"))
        self.assertEqual(res_view_anon.status_code, 302)
        res_edit_anon = self.client.get(reverse("employer_profile_edit"))
        self.assertEqual(res_edit_anon.status_code, 302)

        # Jobseeker access gets 403 Forbidden
        self.client.force_login(self.jobseeker_user)
        res_view_js = self.client.get(reverse("employer_profile"))
        self.assertEqual(res_view_js.status_code, 403)
        res_edit_js = self.client.get(reverse("employer_profile_edit"))
        self.assertEqual(res_edit_js.status_code, 403)

        # Employer profile view returns 200 OK and own profile
        self.client.force_login(self.employer_user)
        res_view = self.client.get(reverse("employer_profile"))
        self.assertEqual(res_view.status_code, 200)
        self.assertTemplateUsed(res_view, "accounts/employer_profile_view.html")
        self.assertEqual(res_view.context["profile"], self.employer_profile)

        # Employer profile edit GET returns 200 OK with form
        res_edit_get = self.client.get(reverse("employer_profile_edit"))
        self.assertEqual(res_edit_get.status_code, 200)
        self.assertTemplateUsed(res_edit_get, "accounts/employer_profile_edit.html")
        self.assertIn("form", res_edit_get.context)

        # Invalid POST returns 200 with form errors
        res_invalid = self.client.post(reverse("employer_profile_edit"), {"company_name": ""})
        self.assertEqual(res_invalid.status_code, 200)
        self.assertTrue(res_invalid.context["form"].errors)

        # Valid POST updates company profile, sets message, redirects
        payload = {
            "company_name": "Updated Acme Corp",
            "description": "Leading tech company in Nepal.",
            "industry": "Technology",
            "website": "https://example.com",
            "address": "Pulchowk, Lalitpur",
            "phone": "9800000000",
        }
        res_valid = self.client.post(reverse("employer_profile_edit"), payload)
        self.assertRedirects(res_valid, reverse("employer_profile"), fetch_redirect_response=False)
        self.employer_profile.refresh_from_db()
        self.assertEqual(self.employer_profile.company_name, "Updated Acme Corp")
        self.assertEqual(self.employer_profile.description, "Leading tech company in Nepal.")
        self.assertEqual(self.employer_profile.address, "Pulchowk, Lalitpur")
        messages = list(res_valid.wsgi_request._messages)
        self.assertTrue(any("Company profile updated." in str(m) for m in messages))

    def test_jobseeker_profile_view_and_edit_lifecycle(self):
        # Anonymous access redirects to login
        self.client.logout()
        res_view_anon = self.client.get(reverse("profile"))
        self.assertEqual(res_view_anon.status_code, 302)
        res_edit_anon = self.client.get(reverse("profile_edit"))
        self.assertEqual(res_edit_anon.status_code, 302)

        # Employer access gets 403 Forbidden
        self.client.force_login(self.employer_user)
        res_view_emp = self.client.get(reverse("profile"))
        self.assertEqual(res_view_emp.status_code, 403)
        res_edit_emp = self.client.get(reverse("profile_edit"))
        self.assertEqual(res_edit_emp.status_code, 403)

        # Jobseeker profile view returns 200 OK with own profile and default_cv
        self.client.force_login(self.jobseeker_user)
        res_view = self.client.get(reverse("profile"))
        self.assertEqual(res_view.status_code, 200)
        self.assertTemplateUsed(res_view, "accounts/profile_view.html")
        self.assertEqual(res_view.context["profile"], self.jobseeker_profile)
        self.assertIn("default_cv", res_view.context)

        # Jobseeker profile edit GET returns 200 OK with form
        res_edit_get = self.client.get(reverse("profile_edit"))
        self.assertEqual(res_edit_get.status_code, 200)
        self.assertTemplateUsed(res_edit_get, "accounts/profile_edit.html")
        self.assertIn("form", res_edit_get.context)

        # Valid POST updates profile, sets message, redirects to profile
        payload = {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": self.jobseeker_user.email,
            "phone": "9812345678",
            "location": "Kathmandu",
            "summary": "Experienced full-stack engineer.",
        }
        res_valid = self.client.post(reverse("profile_edit"), payload)
        self.assertRedirects(res_valid, reverse("profile"), fetch_redirect_response=False)
        self.jobseeker_profile.refresh_from_db()
        self.jobseeker_user.refresh_from_db()
        self.assertEqual(self.jobseeker_user.first_name, "Jane")
        self.assertEqual(self.jobseeker_user.last_name, "Doe")
        self.assertEqual(self.jobseeker_profile.phone, "9812345678")
        self.assertEqual(self.jobseeker_profile.location, "Kathmandu")
        self.assertEqual(self.jobseeker_profile.summary, "Experienced full-stack engineer.")
        messages = list(res_valid.wsgi_request._messages)
        self.assertTrue(any("Profile updated." in str(m) for m in messages))

    def test_skills_edit_lifecycle(self):
        # Anonymous access redirects to login
        self.client.logout()
        res_anon = self.client.get(reverse("skills_edit"))
        self.assertEqual(res_anon.status_code, 302)

        # Employer access gets 403 Forbidden
        self.client.force_login(self.employer_user)
        res_emp = self.client.get(reverse("skills_edit"))
        self.assertEqual(res_emp.status_code, 403)

        # Jobseeker GET returns 200 with form and prefilled initial skills
        s1 = Skill.objects.create(name="python")
        self.jobseeker_profile.skills.add(s1)
        self.client.force_login(self.jobseeker_user)
        res_get = self.client.get(reverse("skills_edit"))
        self.assertEqual(res_get.status_code, 200)
        self.assertTemplateUsed(res_get, "accounts/skills_edit.html")
        self.assertIn("form", res_get.context)
        self.assertEqual(res_get.context["form"].initial["skills"], "python")

        # Invalid POST (more than MAX_SKILLS=20)
        too_many_skills = ", ".join([f"Skill{i}" for i in range(25)])
        res_invalid = self.client.post(reverse("skills_edit"), {"skills": too_many_skills})
        self.assertEqual(res_invalid.status_code, 200)
        self.assertTrue(res_invalid.context["form"].errors)

        # Valid POST updates skills, sets message, redirects to profile
        valid_skills = "Django, PostgreSQL, Docker"
        res_valid = self.client.post(reverse("skills_edit"), {"skills": valid_skills})
        self.assertRedirects(res_valid, reverse("profile"), fetch_redirect_response=False)
        self.jobseeker_profile.refresh_from_db()
        skill_names = set(self.jobseeker_profile.skills.values_list("name", flat=True))
        self.assertEqual(skill_names, {"django", "postgresql", "docker"})
        messages = list(res_valid.wsgi_request._messages)
        self.assertTrue(any("Skills updated." in str(m) for m in messages))


class VerificationAndCVOperationsCBVTests(TestCase):
    """
    Step 6.16E2b regression tests for Verification and CV Operations CBVs:
    - employer_verification_submit (EmployerVerificationSubmitView)
    - verification_document_download (VerificationDocumentDownloadView)
    - cv_list (CVListView)
    - cv_download (CVDownloadView)
    - cv_set_default (CVSetDefaultView)
    - cv_delete (CVDeleteView)
    """

    def setUp(self):
        self.staff_user = User.objects.create_superuser(
            username="admin_ver_cv",
            email="admin_ver_cv@example.com",
            password="Testpass123!",
        )
        self.employer_user = make_employer(
            username="emp_ver_cv",
            email="emp_ver_cv@example.com",
            password="Testpass123!",
        )
        self.employer_profile = self.employer_user.employer_profile

        self.other_employer_user = make_employer(
            username="other_emp_cv",
            email="other_emp_cv@example.com",
            password="Testpass123!",
        )

        self.jobseeker_user = make_jobseeker(
            username="js_ver_cv",
            email="js_ver_cv@example.com",
            password="Testpass123!",
        )
        self.jobseeker_profile = self.jobseeker_user.jobseeker_profile

        self.other_jobseeker_user = make_jobseeker(
            username="other_js_cv",
            email="other_js_cv@example.com",
            password="Testpass123!",
        )
        self.other_jobseeker_profile = self.other_jobseeker_user.jobseeker_profile

    def test_cbv_classes_and_callable_aliases(self):
        # 1. Class inheritance
        self.assertTrue(issubclass(EmployerVerificationSubmitView, UpdateView))
        self.assertTrue(issubclass(VerificationDocumentDownloadView, View))
        self.assertTrue(issubclass(CVListView, View))
        self.assertTrue(issubclass(CVDownloadView, View))
        self.assertTrue(issubclass(CVSetDefaultView, View))
        self.assertTrue(issubclass(CVDeleteView, View))

        # 2. Callable aliases
        self.assertTrue(callable(employer_verification_submit))
        self.assertTrue(callable(verification_document_download))
        self.assertTrue(callable(cv_list))
        self.assertTrue(callable(cv_download))
        self.assertTrue(callable(cv_set_default))
        self.assertTrue(callable(cv_delete))

        self.assertIs(employer_verification_submit.view_class, EmployerVerificationSubmitView)
        self.assertIs(verification_document_download.view_class, VerificationDocumentDownloadView)
        self.assertIs(cv_list.view_class, CVListView)
        self.assertIs(cv_download.view_class, CVDownloadView)
        self.assertIs(cv_set_default.view_class, CVSetDefaultView)
        self.assertIs(cv_delete.view_class, CVDeleteView)

        # 3. URL resolution to CBVs
        self.assertIs(
            resolve(reverse("employer_verification_submit")).func.view_class,
            EmployerVerificationSubmitView,
        )
        self.assertIs(
            resolve(reverse("verification_document_download", args=[1])).func.view_class,
            VerificationDocumentDownloadView,
        )
        self.assertIs(resolve(reverse("cv_list")).func.view_class, CVListView)
        self.assertIs(resolve(reverse("cv_download", args=[1])).func.view_class, CVDownloadView)
        self.assertIs(resolve(reverse("cv_set_default", args=[1])).func.view_class, CVSetDefaultView)
        self.assertIs(resolve(reverse("cv_delete", args=[1])).func.view_class, CVDeleteView)

        # 4. Identity with callable aliases
        self.assertIs(resolve(reverse("employer_verification_submit")).func, employer_verification_submit)
        self.assertIs(
            resolve(reverse("verification_document_download", args=[1])).func,
            verification_document_download,
        )
        self.assertIs(resolve(reverse("cv_list")).func, cv_list)
        self.assertIs(resolve(reverse("cv_download", args=[1])).func, cv_download)
        self.assertIs(resolve(reverse("cv_set_default", args=[1])).func, cv_set_default)
        self.assertIs(resolve(reverse("cv_delete", args=[1])).func, cv_delete)

    def test_employer_verification_submit_permissions_and_lifecycle(self):
        url = reverse("employer_verification_submit")

        # 1. Anonymous redirected to login
        res_anon = self.client.get(url)
        self.assertEqual(res_anon.status_code, 302)
        self.assertIn(reverse("login"), res_anon.url)

        # 2. Jobseeker receives 403 Forbidden
        self.client.force_login(self.jobseeker_user)
        self.assertEqual(self.client.get(url).status_code, 403)

        # 3. Approved employer redirected to employer_dashboard with message
        self.employer_profile.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.employer_profile.save()
        self.client.force_login(self.employer_user)
        res_appr = self.client.get(url)
        self.assertRedirects(res_appr, reverse("employer_dashboard"), fetch_redirect_response=False)
        messages = list(res_appr.wsgi_request._messages)
        self.assertTrue(any("Your company is already verified." in str(m) for m in messages))

        # 4. Pending employer GET returns 200 with form and profile
        self.employer_profile.verification_status = EmployerProfile.VerificationStatus.PENDING
        self.employer_profile.save()
        res_get = self.client.get(url)
        self.assertEqual(res_get.status_code, 200)
        self.assertTemplateUsed(res_get, "accounts/employer_verification.html")
        self.assertIn("form", res_get.context)
        self.assertEqual(res_get.context["profile"], self.employer_profile)

        # 5. Invalid document upload returns 200 with form error
        res_invalid = self.client.post(url, {})
        self.assertEqual(res_invalid.status_code, 200)
        self.assertTrue(res_invalid.context["form"].errors)

        # 6. Valid document upload updates status to PENDING and redirects
        self.employer_profile.verification_status = EmployerProfile.VerificationStatus.REJECTED
        self.employer_profile.rejection_reason = "Blurry document"
        self.employer_profile.save()

        valid_pdf = make_pdf("legal_reg.pdf")
        res_valid = self.client.post(url, {"verification_document": valid_pdf})
        self.assertRedirects(res_valid, reverse("employer_dashboard"), fetch_redirect_response=False)
        self.employer_profile.refresh_from_db()
        self.assertEqual(self.employer_profile.verification_status, EmployerProfile.VerificationStatus.PENDING)
        self.assertEqual(self.employer_profile.rejection_reason, "")
        messages = list(res_valid.wsgi_request._messages)
        self.assertTrue(any("Verification document submitted." in str(m) for m in messages))

    def test_verification_document_download_permissions_and_security(self):
        self.employer_profile.verification_document = make_pdf("company_cert.pdf")
        self.employer_profile.save()
        url = reverse("verification_document_download", args=[self.employer_profile.pk])

        # 1. Anonymous redirected to login
        self.client.logout()
        res_anon = self.client.get(url)
        self.assertEqual(res_anon.status_code, 302)
        self.assertIn(reverse("login"), res_anon.url)

        # 2. Jobseeker receives 403 Forbidden
        self.client.force_login(self.jobseeker_user)
        self.assertEqual(self.client.get(url).status_code, 403)

        # 3. Non-staff employer (even the owner) receives 403 Forbidden
        self.client.force_login(self.employer_user)
        self.assertEqual(self.client.get(url).status_code, 403)

        # 4. Staff downloads document successfully as FileResponse
        self.client.force_login(self.staff_user)
        res_staff = self.client.get(url)
        self.assertEqual(res_staff.status_code, 200)
        self.assertIsInstance(res_staff, FileResponse)

        # 5. Non-existent profile returns 404
        self.assertEqual(self.client.get(reverse("verification_document_download", args=[99999])).status_code, 404)

        # 6. Employer without document returns 404
        self.other_employer_user.employer_profile.verification_document = None
        self.other_employer_user.employer_profile.save()
        url_no_doc = reverse("verification_document_download", args=[self.other_employer_user.employer_profile.pk])
        self.assertEqual(self.client.get(url_no_doc).status_code, 404)

    def test_cv_list_and_upload_lifecycle(self):
        url = reverse("cv_list")

        # 1. Anonymous redirected to login
        self.client.logout()
        res_anon = self.client.get(url)
        self.assertEqual(res_anon.status_code, 302)
        self.assertIn(reverse("login"), res_anon.url)

        # 2. Employer receives 403 Forbidden
        self.client.force_login(self.employer_user)
        self.assertEqual(self.client.get(url).status_code, 403)

        # 3. Jobseeker GET returns 200 with isolated list
        self.client.force_login(self.jobseeker_user)
        res_get = self.client.get(url)
        self.assertEqual(res_get.status_code, 200)
        self.assertTemplateUsed(res_get, "accounts/cv_list.html")
        self.assertIn("cvs", res_get.context)
        self.assertIn("form", res_get.context)
        self.assertEqual(res_get.context["max_cvs"], MAX_ACTIVE_CVS)

        # 4. Valid upload creates CV and sets default
        pdf = make_pdf("my_first_cv.pdf")
        res_post = self.client.post(url, {"title": "Software Engineer Resume", "file": pdf})
        self.assertRedirects(res_post, url, fetch_redirect_response=False)
        self.assertEqual(self.jobseeker_profile.cvs.filter(is_active=True).count(), 1)
        created_cv = self.jobseeker_profile.cvs.filter(is_active=True).first()
        self.assertTrue(created_cv.is_default)
        self.assertEqual(created_cv.original_filename, "my_first_cv.pdf")

        # 5. MAX_ACTIVE_CVS limit enforcement
        for i in range(MAX_ACTIVE_CVS - 1):
            CV.objects.create(
                profile=self.jobseeker_profile,
                title=f"CV {i}",
                file=make_pdf(f"cv_{i}.pdf"),
                original_filename=f"cv_{i}.pdf",
                is_active=True,
                is_default=False,
            )
        self.assertEqual(self.jobseeker_profile.cvs.filter(is_active=True).count(), MAX_ACTIVE_CVS)

        # Attempt to upload one more
        extra_pdf = make_pdf("extra.pdf")
        res_overflow = self.client.post(url, {"title": "Overflow CV", "file": extra_pdf})
        self.assertEqual(res_overflow.status_code, 200)
        self.assertEqual(self.jobseeker_profile.cvs.filter(is_active=True).count(), MAX_ACTIVE_CVS)
        messages = list(res_overflow.wsgi_request._messages)
        self.assertTrue(any(f"You can keep up to {MAX_ACTIVE_CVS} CVs" in str(m) for m in messages))

    def test_cv_set_default_and_delete_post_only(self):
        cv = CV.objects.create(
            profile=self.jobseeker_profile,
            title="CV To Manage",
            file=make_pdf("manage.pdf"),
            original_filename="manage.pdf",
            is_active=True,
            is_default=False,
        )
        url_default = reverse("cv_set_default", args=[cv.pk])
        url_delete = reverse("cv_delete", args=[cv.pk])

        self.client.force_login(self.jobseeker_user)

        # 1. GET returns 405 Method Not Allowed
        self.assertEqual(self.client.get(url_default).status_code, 405)
        self.assertEqual(self.client.get(url_delete).status_code, 405)

        # 2. Other jobseeker cannot set default or delete foreign CV (404)
        self.client.force_login(self.other_jobseeker_user)
        self.assertEqual(self.client.post(url_default).status_code, 404)
        self.assertEqual(self.client.post(url_delete).status_code, 404)

        # 3. Owner sets default
        self.client.force_login(self.jobseeker_user)
        res_default = self.client.post(url_default)
        self.assertRedirects(res_default, reverse("cv_list"), fetch_redirect_response=False)
        cv.refresh_from_db()
        self.assertTrue(cv.is_default)

        # 4. Owner deletes CV
        res_del = self.client.post(url_delete)
        self.assertRedirects(res_del, reverse("cv_list"), fetch_redirect_response=False)
        cv.refresh_from_db()
        self.assertFalse(cv.is_active)

    def test_cv_download_authorization_matrix(self):
        import datetime
        from jobs.models import Category, Job, Location
        from applications.models import Application

        cv = CV.objects.create(
            profile=self.jobseeker_profile,
            title="Downloadable CV",
            file=make_pdf("down.pdf"),
            original_filename="down.pdf",
            is_active=True,
            is_default=True,
        )
        url = reverse("cv_download", args=[cv.pk])

        # 1. Anonymous redirected to login
        self.client.logout()
        res_anon = self.client.get(url)
        self.assertEqual(res_anon.status_code, 302)

        # 2. Foreign jobseeker receives 403 Forbidden
        self.client.force_login(self.other_jobseeker_user)
        self.assertEqual(self.client.get(url).status_code, 403)

        # 3. Unlinked employer receives 403 Forbidden
        self.client.force_login(self.employer_user)
        self.assertEqual(self.client.get(url).status_code, 403)

        # 4. Owner jobseeker downloads successfully
        self.client.force_login(self.jobseeker_user)
        res_owner = self.client.get(url)
        self.assertEqual(res_owner.status_code, 200)
        self.assertIsInstance(res_owner, FileResponse)

        # 5. Staff downloads successfully
        self.client.force_login(self.staff_user)
        res_staff = self.client.get(url)
        self.assertEqual(res_staff.status_code, 200)

        # 6. Approved employer with an application linking this CV can download
        self.employer_profile.verification_status = EmployerProfile.VerificationStatus.APPROVED
        self.employer_profile.save()

        cat, _ = Category.objects.get_or_create(name="Tech", defaults={"slug": "tech"})
        loc, _ = Location.objects.get_or_create(name="Kathmandu", defaults={"slug": "ktm"})
        job = Job.objects.create(
            employer=self.employer_profile,
            category=cat,
            location=loc,
            title="Software Developer",
            description="Build systems",
            application_deadline=datetime.date.today() + datetime.timedelta(days=15),
            status=Job.Status.PUBLISHED,
        )
        Application.objects.create(
            job=job,
            jobseeker=self.jobseeker_profile,
            cv=cv,
            status=Application.Status.APPLIED,
        )

        self.client.force_login(self.employer_user)
        res_app_emp = self.client.get(url)
        self.assertEqual(res_app_emp.status_code, 200)
        self.assertIsInstance(res_app_emp, FileResponse)

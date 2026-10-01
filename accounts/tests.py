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

from .forms import EmployerProfileForm, EmployerVerificationForm
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

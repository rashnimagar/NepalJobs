"""
accounts/tests.py
-----------------
Test suite for Steps 1–4: User model, registration, authentication, role
access control, jobseeker profile, CV management, skills, education,
experience, dashboard checklist, and URL routing regression tests.

Run with:  python manage.py test accounts
"""

import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse, resolve

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

from datetime import timedelta

from django import forms
from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Education, EmployerProfile, JobseekerProfile, Skill, User
from applications.models import Application
from jobs.admin import CategoryAdmin, JobAdmin, LocationAdmin, SavedJobAdmin
from jobs.forms import JobForm
from jobs.models import Category, Job, Location, SavedJob


def make_approved_employer(username="emp_approved", email="emp_app@example.com"):
    user = User.objects.create_user(
        username=username, email=email, password="Testpass123!", role=User.Role.EMPLOYER
    )
    profile = EmployerProfile.objects.create(
        user=user,
        company_name="TechCorp Nepal",
        verification_status=EmployerProfile.VerificationStatus.APPROVED,
    )
    return profile


def make_pending_employer(username="emp_pending", email="emp_pend@example.com"):
    user = User.objects.create_user(
        username=username, email=email, password="Testpass123!", role=User.Role.EMPLOYER
    )
    profile = EmployerProfile.objects.create(
        user=user,
        company_name="Pending Corp",
        verification_status=EmployerProfile.VerificationStatus.PENDING,
    )
    return profile
 
 
def make_category(name="IT & Telecommunications", slug="it-telecom"):
    return Category.objects.create(name=name, slug=slug)


def make_location(name="Kathmandu", slug="kathmandu", is_remote=False):
    return Location.objects.create(name=name, slug=slug, is_remote=is_remote)


class CategoryModelTests(TestCase):

    def test_valid_category_creation(self):
        category = Category.objects.create(
            name="Healthcare & Medical",
            slug="healthcare-medical",
            description="Healthcare and clinical positions.",
        )
        self.assertEqual(category.name, "Healthcare & Medical")
        self.assertEqual(category.slug, "healthcare-medical")
        self.assertTrue(category.is_active)
        self.assertEqual(str(category), "Healthcare & Medical")

    def test_unique_category_name(self):
        Category.objects.create(name="Banking", slug="banking")
        with self.assertRaises(IntegrityError):
            Category.objects.create(name="Banking", slug="banking-two")

    def test_unique_category_slug(self):
        Category.objects.create(name="Banking", slug="banking")
        with self.assertRaises(IntegrityError):
            Category.objects.create(name="Finance", slug="banking")


class LocationModelTests(TestCase):

    def test_valid_location_creation(self):
        location = Location.objects.create(name="Pokhara", slug="pokhara")
        self.assertEqual(location.name, "Pokhara")
        self.assertEqual(location.slug, "pokhara")
        self.assertFalse(location.is_remote)
        self.assertEqual(str(location), "Pokhara")

    def test_remote_location_flag(self):
        location = Location.objects.create(name="Remote", slug="remote", is_remote=True)
        self.assertTrue(location.is_remote)

    def test_unique_location_name(self):
        Location.objects.create(name="Lalitpur", slug="lalitpur")
        with self.assertRaises(IntegrityError):
            Location.objects.create(name="Lalitpur", slug="lalitpur-two")

    def test_unique_location_slug(self):
        Location.objects.create(name="Lalitpur", slug="lalitpur")
        with self.assertRaises(IntegrityError):
            Location.objects.create(name="Patan", slug="lalitpur")


class JobModelTests(TestCase):

    def setUp(self):
        self.employer = make_approved_employer()
        self.category = make_category()
        self.location = make_location()

    def test_valid_draft_job_creation(self):
        deadline = timezone.localdate() + timedelta(days=14)
        job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Backend Python Developer",
            description="Build scalable Django APIs.",
            application_deadline=deadline,
        )
        self.assertEqual(job.status, Job.Status.DRAFT)
        self.assertEqual(job.vacancies, 1)
        self.assertEqual(job.employment_type, Job.EmploymentType.FULL_TIME)
        self.assertFalse(job.is_remote)
        self.assertFalse(job.is_salary_negotiable)
        self.assertEqual(job.experience_years_min, 0)
        self.assertIsNone(job.published_at)
        self.assertIn("Backend Python Developer", str(job))
        self.assertIn("TechCorp Nepal", str(job))

    def test_job_required_skills_relationship(self):
        skill_python = Skill.objects.create(name="python")
        skill_django = Skill.objects.create(name="django")
        job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Django Specialist",
            description="Experienced Django developer.",
            application_deadline=timezone.localdate() + timedelta(days=7),
        )
        job.required_skills.add(skill_python, skill_django)
        self.assertEqual(job.required_skills.count(), 2)
        self.assertIn(skill_python, job.required_skills.all())

    def test_salary_range_validation(self):
        job = Job(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Dev",
            description="Desc",
            application_deadline=timezone.localdate() + timedelta(days=7),
            salary_min=80000,
            salary_max=50000,  # Invalid: max < min
        )
        with self.assertRaises(ValidationError) as ctx:
            job.clean()
        self.assertIn("salary_max", ctx.exception.message_dict)

        # Valid range cleans without error
        job.salary_max = 120000
        job.clean()

    def test_vacancy_validation(self):
        job = Job(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Dev",
            description="Desc",
            application_deadline=timezone.localdate() + timedelta(days=7),
            vacancies=0,  # Invalid: < 1
        )
        with self.assertRaises(ValidationError) as ctx:
            job.clean()
        self.assertIn("vacancies", ctx.exception.message_dict)

    def test_published_job_with_past_deadline_invalid(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        job = Job(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Senior QA",
            description="QA lead",
            application_deadline=yesterday,
            status=Job.Status.PUBLISHED,
        )
        with self.assertRaises(ValidationError) as ctx:
            job.clean()
        self.assertIn("application_deadline", ctx.exception.message_dict)

    def test_published_job_with_today_deadline_valid(self):
        today = timezone.localdate()
        job = Job(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Junior QA",
            description="QA assistant",
            application_deadline=today,
            status=Job.Status.PUBLISHED,
        )
        job.clean()  # Should not raise

    def test_published_job_with_future_deadline_valid(self):
        future = timezone.localdate() + timedelta(days=10)
        job = Job(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Junior QA",
            description="QA assistant",
            application_deadline=future,
            status=Job.Status.PUBLISHED,
        )
        job.clean()  # Should not raise

    def test_draft_job_with_past_deadline_cleans_valid(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        job = Job(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Draft Role",
            description="Draft job being drafted",
            application_deadline=yesterday,
            status=Job.Status.DRAFT,
        )
        job.clean()  # Draft jobs can hold dates that are edited prior to publishing


class JobIsOpenPropertyTests(TestCase):

    def setUp(self):
        self.approved_employer = make_approved_employer()
        self.pending_employer = make_pending_employer()
        self.category = make_category()
        self.location = make_location()

    def test_is_open_for_draft_job_is_false(self):
        job = Job.objects.create(
            employer=self.approved_employer,
            category=self.category,
            location=self.location,
            title="Draft Role",
            description="Desc",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.DRAFT,
        )
        self.assertFalse(job.is_open)

    def test_is_open_for_published_future_job_is_true(self):
        job = Job.objects.create(
            employer=self.approved_employer,
            category=self.category,
            location=self.location,
            title="Published Role",
            description="Desc",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
        )
        self.assertTrue(job.is_open)

    def test_is_open_for_closed_job_is_false(self):
        job = Job.objects.create(
            employer=self.approved_employer,
            category=self.category,
            location=self.location,
            title="Closed Role",
            description="Desc",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.CLOSED,
        )
        self.assertFalse(job.is_open)

    def test_is_open_for_expired_job_is_false(self):
        job = Job.objects.create(
            employer=self.approved_employer,
            category=self.category,
            location=self.location,
            title="Expired Role",
            description="Desc",
            application_deadline=timezone.localdate() - timedelta(days=1),
            status=Job.Status.PUBLISHED,
        )
        self.assertFalse(job.is_open)

    def test_is_open_for_unapproved_employer_job_is_false(self):
        job = Job.objects.create(
            employer=self.pending_employer,
            category=self.category,
            location=self.location,
            title="Pending Employer Role",
            description="Desc",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
        )
        self.assertFalse(job.is_open)


class JobQuerySetManagerTests(TestCase):

    def setUp(self):
        self.approved_employer = make_approved_employer()
        self.pending_employer = make_pending_employer()
        self.category = make_category()
        self.location = make_location()

        today = timezone.localdate()

        # 1. Open job: published, future deadline, approved employer
        self.job_open = Job.objects.create(
            employer=self.approved_employer,
            category=self.category,
            location=self.location,
            title="Open Position",
            description="Desc",
            application_deadline=today + timedelta(days=5),
            status=Job.Status.PUBLISHED,
        )

        # 2. Draft job
        self.job_draft = Job.objects.create(
            employer=self.approved_employer,
            category=self.category,
            location=self.location,
            title="Draft Position",
            description="Desc",
            application_deadline=today + timedelta(days=5),
            status=Job.Status.DRAFT,
        )

        # 3. Closed job
        self.job_closed = Job.objects.create(
            employer=self.approved_employer,
            category=self.category,
            location=self.location,
            title="Closed Position",
            description="Desc",
            application_deadline=today + timedelta(days=5),
            status=Job.Status.CLOSED,
        )

        # 4. Expired job: published, past deadline
        self.job_expired = Job.objects.create(
            employer=self.approved_employer,
            category=self.category,
            location=self.location,
            title="Expired Position",
            description="Desc",
            application_deadline=today - timedelta(days=2),
            status=Job.Status.PUBLISHED,
        )

        # 5. Published job with pending/unapproved employer
        self.job_unapproved_emp = Job.objects.create(
            employer=self.pending_employer,
            category=self.category,
            location=self.location,
            title="Unapproved Employer Position",
            description="Desc",
            application_deadline=today + timedelta(days=5),
            status=Job.Status.PUBLISHED,
        )

    def test_open_jobs_manager(self):
        open_jobs = list(Job.objects.open_jobs())
        self.assertIn(self.job_open, open_jobs)
        self.assertNotIn(self.job_draft, open_jobs)
        self.assertNotIn(self.job_closed, open_jobs)
        self.assertNotIn(self.job_expired, open_jobs)
        self.assertNotIn(self.job_unapproved_emp, open_jobs)
        self.assertEqual(len(open_jobs), 1)

    def test_expired_jobs_manager(self):
        expired = list(Job.objects.expired_jobs())
        self.assertIn(self.job_expired, expired)
        self.assertNotIn(self.job_open, expired)
        self.assertNotIn(self.job_draft, expired)
        self.assertNotIn(self.job_closed, expired)
        self.assertEqual(len(expired), 1)


class JobLifecycleTests(TestCase):

    def setUp(self):
        self.approved_employer = make_approved_employer()
        self.pending_employer = make_pending_employer()
        self.category = make_category()
        self.location = make_location()

    def test_publish_with_approved_employer_and_valid_deadline(self):
        job = Job.objects.create(
            employer=self.approved_employer,
            category=self.category,
            location=self.location,
            title="Full Stack Engineer",
            description="Full stack dev role",
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.DRAFT,
        )
        self.assertFalse(job.is_open)
        self.assertIsNone(job.published_at)

        job.publish()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.PUBLISHED)
        self.assertIsNotNone(job.published_at)
        self.assertTrue(job.is_open)

    def test_publish_rejects_unapproved_employer(self):
        job = Job.objects.create(
            employer=self.pending_employer,
            category=self.category,
            location=self.location,
            title="Sales Rep",
            description="Sales job",
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.DRAFT,
        )
        with self.assertRaises(ValidationError):
            job.publish()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.DRAFT)

    def test_publish_rejects_past_deadline(self):
        job = Job.objects.create(
            employer=self.approved_employer,
            category=self.category,
            location=self.location,
            title="Receptionist",
            description="Front desk role",
            application_deadline=timezone.localdate() - timedelta(days=2),
            status=Job.Status.DRAFT,
        )
        with self.assertRaises(ValidationError):
            job.publish()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.DRAFT)

    def test_close_transitions_to_closed(self):
        job = Job.objects.create(
            employer=self.approved_employer,
            category=self.category,
            location=self.location,
            title="DevOps Engineer",
            description="Cloud infrastructure",
            application_deadline=timezone.localdate() + timedelta(days=7),
            status=Job.Status.PUBLISHED,
        )
        self.assertTrue(job.is_open)

        job.close()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.CLOSED)
        self.assertFalse(job.is_open)


class JobFormTests(TestCase):

    def setUp(self):
        self.employer = make_approved_employer()
        self.category = make_category(name="Engineering", slug="engineering")
        self.location = make_location(name="Kathmandu", slug="kathmandu")
        self.skill_python = Skill.objects.create(name="Python")
        self.skill_django = Skill.objects.create(name="Django")

    def get_valid_data(self, **overrides):
        data = {
            "title": "Backend Python Developer",
            "category": self.category.pk,
            "location": self.location.pk,
            "is_remote": False,
            "employment_type": Job.EmploymentType.FULL_TIME,
            "vacancies": 2,
            "salary_min": 40000,
            "salary_max": 70000,
            "is_salary_negotiable": False,
            "experience_years_min": 2,
            "education_level": Education.Level.BACHELOR,
            "required_skills": [self.skill_python.pk, self.skill_django.pk],
            "application_deadline": (timezone.localdate() + timedelta(days=30)).isoformat(),
            "description": "We are seeking an experienced Python developer.",
            "responsibilities": "Develop backend APIs and maintain services.",
        }
        data.update(overrides)
        return data

    def test_valid_job_form_is_accepted(self):
        form = JobForm(data=self.get_valid_data())
        self.assertTrue(form.is_valid(), form.errors)
        job = form.save(commit=False)
        job.employer = self.employer
        job.save()
        form.save_m2m()

        self.assertEqual(job.title, "Backend Python Developer")
        self.assertEqual(job.vacancies, 2)
        self.assertEqual(job.salary_min, 40000)
        self.assertEqual(job.salary_max, 70000)
        self.assertFalse(job.is_salary_negotiable)
        self.assertEqual(job.experience_years_min, 2)
        self.assertEqual(job.education_level, Education.Level.BACHELOR)
        self.assertEqual(job.status, Job.Status.DRAFT)
        self.assertEqual(job.required_skills.count(), 2)

    def test_employer_not_present_as_editable_field(self):
        form = JobForm()
        self.assertNotIn("employer", form.fields)

    def test_status_not_present_as_editable_field(self):
        form = JobForm()
        self.assertNotIn("status", form.fields)

    def test_published_at_and_timestamps_not_present_as_editable_fields(self):
        form = JobForm()
        self.assertNotIn("published_at", form.fields)
        self.assertNotIn("created_at", form.fields)
        self.assertNotIn("updated_at", form.fields)

    def test_salary_range_validation_rejects_max_less_than_min(self):
        form = JobForm(data=self.get_valid_data(salary_min=80000, salary_max=50000))
        self.assertFalse(form.is_valid())
        self.assertIn("salary_max", form.errors)
        self.assertIn(
            "Maximum salary cannot be less than minimum salary.",
            form.errors["salary_max"],
        )

    def test_vacancy_validation_rejects_zero_and_negative(self):
        form_zero = JobForm(data=self.get_valid_data(vacancies=0))
        self.assertFalse(form_zero.is_valid())
        self.assertIn("vacancies", form_zero.errors)

        form_neg = JobForm(data=self.get_valid_data(vacancies=-2))
        self.assertFalse(form_neg.is_valid())
        self.assertIn("vacancies", form_neg.errors)

    def test_draft_with_past_deadline_is_valid_form(self):
        past_date = (timezone.localdate() - timedelta(days=5)).isoformat()
        form = JobForm(data=self.get_valid_data(application_deadline=past_date))
        self.assertTrue(form.is_valid(), form.errors)

        job = form.save(commit=False)
        job.employer = self.employer
        job.save()
        self.assertEqual(job.status, Job.Status.DRAFT)
        self.assertEqual(job.application_deadline, timezone.localdate() - timedelta(days=5))

        # Also verify editing an existing draft with a past deadline
        existing_draft = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Existing Draft",
            description="Existing draft description",
            application_deadline=timezone.localdate() - timedelta(days=10),
            status=Job.Status.DRAFT,
        )
        edit_form = JobForm(
            data=self.get_valid_data(application_deadline=past_date),
            instance=existing_draft,
        )
        self.assertTrue(edit_form.is_valid(), edit_form.errors)

    def test_required_skills_assigned_through_normal_m2m(self):
        form = JobForm(
            data=self.get_valid_data(
                required_skills=[self.skill_python.pk, self.skill_django.pk]
            )
        )
        self.assertTrue(form.is_valid(), form.errors)
        job = form.save(commit=False)
        job.employer = self.employer
        job.save()
        form.save_m2m()

        self.assertEqual(
            set(job.required_skills.all()),
            {self.skill_python, self.skill_django},
        )

        # Blank skills are also valid since required_skills is optional (blank=True)
        form_empty_skills = JobForm(data=self.get_valid_data(required_skills=[]))
        self.assertTrue(form_empty_skills.is_valid(), form_empty_skills.errors)

    def test_category_and_location_choices_appear_correctly(self):
        cat_design = make_category(name="Design & Creative", slug="design-creative")
        loc_pokhara = make_location(name="Pokhara", slug="pokhara")

        form = JobForm()
        category_choices = [c[0] for c in form.fields["category"].choices if c[0]]
        location_choices = [l[0] for l in form.fields["location"].choices if l[0]]

        self.assertIn(self.category.pk, category_choices)
        self.assertIn(cat_design.pk, category_choices)
        self.assertIn(self.location.pk, location_choices)
        self.assertIn(loc_pokhara.pk, location_choices)

    def test_employment_type_choices_appear_correctly(self):
        form = JobForm()
        form_choices = list(form.fields["employment_type"].choices)
        expected_choices = list(Job.EmploymentType.choices)
        self.assertEqual(form_choices, expected_choices)

    def test_education_level_choices_appear_correctly(self):
        form = JobForm()
        form_choices = [c[0] for c in form.fields["education_level"].choices if c[0]]
        expected_choices = [c[0] for c in Education.Level.choices]
        self.assertEqual(form_choices, expected_choices)

    def test_appropriate_widgets_and_styling(self):
        form = JobForm()

        deadline_widget = form.fields["application_deadline"].widget
        self.assertIsInstance(deadline_widget, forms.DateInput)
        self.assertEqual(deadline_widget.input_type, "date")
        self.assertIn("form-control", deadline_widget.attrs.get("class", ""))
        self.assertIn('type="date"', form["application_deadline"].as_widget())

        description_widget = form.fields["description"].widget
        self.assertIsInstance(description_widget, forms.Textarea)
        self.assertEqual(description_widget.attrs.get("rows"), 5)
        self.assertIn("form-control", description_widget.attrs.get("class", ""))

        responsibilities_widget = form.fields["responsibilities"].widget
        self.assertIsInstance(responsibilities_widget, forms.Textarea)
        self.assertEqual(responsibilities_widget.attrs.get("rows"), 4)
        self.assertIn("form-control", responsibilities_widget.attrs.get("class", ""))

        skills_widget = form.fields["required_skills"].widget
        self.assertIsInstance(skills_widget, forms.SelectMultiple)
        self.assertIn("form-select", skills_widget.attrs.get("class", ""))

        is_remote_widget = form.fields["is_remote"].widget
        self.assertIsInstance(is_remote_widget, forms.CheckboxInput)
        self.assertIn("form-check-input", is_remote_widget.attrs.get("class", ""))


class JobAdminTests(TestCase):

    def setUp(self):
        self.employer = make_approved_employer()
        self.category = make_category(name="Admin Category", slug="admin-cat")
        self.location = make_location(name="Admin Location", slug="admin-loc")

    def test_category_admin_registration_and_configuration(self):
        self.assertIn(Category, site._registry)
        admin_obj = site._registry[Category]
        self.assertIsInstance(admin_obj, CategoryAdmin)
        self.assertEqual(admin_obj.list_display, ("name", "slug", "is_active"))
        self.assertEqual(admin_obj.search_fields, ("name",))
        self.assertEqual(admin_obj.list_filter, ("is_active",))
        self.assertEqual(admin_obj.prepopulated_fields, {"slug": ("name",)})

    def test_location_admin_registration_and_configuration(self):
        self.assertIn(Location, site._registry)
        admin_obj = site._registry[Location]
        self.assertIsInstance(admin_obj, LocationAdmin)
        self.assertEqual(admin_obj.list_display, ("name", "slug", "is_remote"))
        self.assertEqual(admin_obj.search_fields, ("name",))
        self.assertEqual(admin_obj.list_filter, ("is_remote",))
        self.assertEqual(admin_obj.prepopulated_fields, {"slug": ("name",)})

    def test_job_admin_registration_and_configuration(self):
        self.assertIn(Job, site._registry)
        admin_obj = site._registry[Job]
        self.assertIsInstance(admin_obj, JobAdmin)
        self.assertEqual(
            admin_obj.list_display,
            (
                "title",
                "employer",
                "category",
                "location",
                "employment_type",
                "status",
                "application_deadline",
                "is_open",
                "created_at",
            ),
        )
        self.assertEqual(
            admin_obj.list_filter,
            (
                "status",
                "employment_type",
                "category",
                "location",
                "is_remote",
                "is_salary_negotiable",
            ),
        )
        self.assertEqual(
            admin_obj.search_fields,
            (
                "title",
                "employer__company_name",
                "description",
            ),
        )
        self.assertEqual(admin_obj.raw_id_fields, ("employer",))
        self.assertEqual(admin_obj.filter_horizontal, ("required_skills",))
        self.assertEqual(admin_obj.date_hierarchy, "application_deadline")
        self.assertEqual(admin_obj.ordering, ("-created_at",))

    def test_job_admin_safety_and_readonly_fields(self):
        admin_obj = site._registry[Job]
        self.assertIn("is_open", admin_obj.readonly_fields)
        self.assertIn("created_at", admin_obj.readonly_fields)
        self.assertIn("updated_at", admin_obj.readonly_fields)
        self.assertIn("published_at", admin_obj.readonly_fields)

        # Confirm is_open is not an editable database field on the model
        model_field_names = [f.name for f in Job._meta.get_fields()]
        self.assertNotIn("is_open", model_field_names)
        self.assertTrue(isinstance(getattr(Job, "is_open"), property))

    def test_job_admin_is_open_display_method(self):
        admin_obj = site._registry[Job]
        open_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Open Admin Job",
            description="Open job description",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
        )
        closed_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Closed Admin Job",
            description="Closed job description",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.CLOSED,
        )

        self.assertTrue(admin_obj.is_open(open_job))
        self.assertFalse(admin_obj.is_open(closed_job))
        self.assertFalse(admin_obj.is_open(None))
        unsaved_job = Job()
        self.assertFalse(admin_obj.is_open(unsaved_job))


def make_rejected_employer(username="emp_rejected", email="emp_rej@example.com"):
    user = User.objects.create_user(
        username=username, email=email, password="Testpass123!", role=User.Role.EMPLOYER
    )
    profile = EmployerProfile.objects.create(
        user=user,
        company_name="Rejected Corp",
        verification_status=EmployerProfile.VerificationStatus.REJECTED,
        rejection_reason="Invalid registration certificate",
    )
    return profile


def make_jobseeker(username="jobseeker1", email="js1@example.com"):
    user = User.objects.create_user(
        username=username, email=email, password="Testpass123!", role=User.Role.JOBSEEKER
    )
    JobseekerProfile.objects.get_or_create(user=user)
    return user


class EmployerJobAuthTests(TestCase):

    def setUp(self):
        self.approved_employer = make_approved_employer()
        self.pending_employer = make_pending_employer()
        self.rejected_employer = make_rejected_employer()
        self.jobseeker = make_jobseeker()
        self.category = make_category(name="IT Auth", slug="it-auth")
        self.location = make_location(name="Kathmandu Auth", slug="ktm-auth")
        self.job = Job.objects.create(
            employer=self.approved_employer,
            category=self.category,
            location=self.location,
            title="Senior Developer",
            description="Develop applications",
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.DRAFT,
        )

    def test_anonymous_cannot_access_employer_job_list(self):
        url = reverse("employer_job_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_anonymous_cannot_access_employer_job_create(self):
        url = reverse("employer_job_create")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_anonymous_cannot_access_employer_job_detail(self):
        url = reverse("employer_job_detail", args=[self.job.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_anonymous_cannot_access_employer_job_edit(self):
        url = reverse("employer_job_edit", args=[self.job.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_jobseeker_cannot_access_employer_management(self):
        self.client.force_login(self.jobseeker)
        for url in [
            reverse("employer_job_list"),
            reverse("employer_job_create"),
            reverse("employer_job_detail", args=[self.job.pk]),
            reverse("employer_job_edit", args=[self.job.pk]),
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)

    def test_pending_employer_cannot_access_employer_management(self):
        self.client.force_login(self.pending_employer.user)
        for url in [
            reverse("employer_job_list"),
            reverse("employer_job_create"),
            reverse("employer_job_detail", args=[self.job.pk]),
            reverse("employer_job_edit", args=[self.job.pk]),
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)

    def test_rejected_employer_cannot_access_employer_management(self):
        self.client.force_login(self.rejected_employer.user)
        for url in [
            reverse("employer_job_list"),
            reverse("employer_job_create"),
            reverse("employer_job_detail", args=[self.job.pk]),
            reverse("employer_job_edit", args=[self.job.pk]),
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)

    def test_unverified_employer_without_profile_cannot_access(self):
        user_no_profile = User.objects.create_user(
            username="no_profile", email="noprofile@example.com", password="Password123!", role=User.Role.EMPLOYER
        )
        self.client.force_login(user_no_profile)
        response = self.client.get(reverse("employer_job_list"))
        self.assertEqual(response.status_code, 403)

    def test_approved_employer_can_access_employer_management(self):
        self.client.force_login(self.approved_employer.user)
        self.assertEqual(self.client.get(reverse("employer_job_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("employer_job_create")).status_code, 200)
        self.assertEqual(self.client.get(reverse("employer_job_detail", args=[self.job.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("employer_job_edit", args=[self.job.pk])).status_code, 200)


class EmployerJobOwnershipTests(TestCase):

    def setUp(self):
        self.emp_a = make_approved_employer(username="emp_a", email="emp_a@example.com")
        self.emp_b = make_approved_employer(username="emp_b", email="emp_b@example.com")
        self.category = make_category(name="Tech Own", slug="tech-own")
        self.location = make_location(name="Patan Own", slug="patan-own")

        self.job_a1 = Job.objects.create(
            employer=self.emp_a,
            category=self.category,
            location=self.location,
            title="Job A1",
            description="Desc A1",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.DRAFT,
        )
        self.job_a2 = Job.objects.create(
            employer=self.emp_a,
            category=self.category,
            location=self.location,
            title="Job A2",
            description="Desc A2",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
        )
        self.job_b1 = Job.objects.create(
            employer=self.emp_b,
            category=self.category,
            location=self.location,
            title="Job B1",
            description="Desc B1",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.DRAFT,
        )

    def test_employer_sees_only_own_jobs_in_list(self):
        self.client.force_login(self.emp_a.user)
        response = self.client.get(reverse("employer_job_list"))
        self.assertEqual(response.status_code, 200)
        jobs_in_context = list(response.context["jobs"])
        self.assertIn(self.job_a1, jobs_in_context)
        self.assertIn(self.job_a2, jobs_in_context)
        self.assertNotIn(self.job_b1, jobs_in_context)

    def test_employer_cannot_access_another_employer_job_detail(self):
        self.client.force_login(self.emp_a.user)
        response = self.client.get(reverse("employer_job_detail", args=[self.job_b1.pk]))
        self.assertEqual(response.status_code, 404)

    def test_employer_cannot_edit_another_employer_job(self):
        self.client.force_login(self.emp_a.user)
        get_res = self.client.get(reverse("employer_job_edit", args=[self.job_b1.pk]))
        self.assertEqual(get_res.status_code, 404)

        post_res = self.client.post(
            reverse("employer_job_edit", args=[self.job_b1.pk]),
            {"title": "Hacked Title"},
        )
        self.assertEqual(post_res.status_code, 404)
        self.job_b1.refresh_from_db()
        self.assertEqual(self.job_b1.title, "Job B1")

    def test_ownership_cannot_be_changed_through_post_data(self):
        self.client.force_login(self.emp_a.user)
        # Attempt to change owner on edit
        edit_data = {
            "title": "Job A1 Updated",
            "category": self.category.pk,
            "location": self.location.pk,
            "is_remote": False,
            "employment_type": Job.EmploymentType.FULL_TIME,
            "vacancies": 1,
            "experience_years_min": 0,
            "application_deadline": (timezone.localdate() + timedelta(days=10)).isoformat(),
            "description": "Updated desc",
            "employer": self.emp_b.pk,
        }
        res = self.client.post(reverse("employer_job_edit", args=[self.job_a1.pk]), edit_data)
        self.assertEqual(res.status_code, 302)
        self.job_a1.refresh_from_db()
        self.assertEqual(self.job_a1.employer, self.emp_a)

        # Attempt to specify different owner on create
        create_data = dict(edit_data, title="New Job A")
        res_create = self.client.post(reverse("employer_job_create"), create_data)
        self.assertEqual(res_create.status_code, 302)
        new_job = Job.objects.get(title="New Job A")
        self.assertEqual(new_job.employer, self.emp_a)


class EmployerJobCreateTests(TestCase):

    def setUp(self):
        self.employer = make_approved_employer()
        self.category = make_category(name="Create Cat", slug="create-cat")
        self.location = make_location(name="Create Loc", slug="create-loc")
        self.skill1 = Skill.objects.create(name="Python")
        self.skill2 = Skill.objects.create(name="Django")
        self.client.force_login(self.employer.user)

    def get_valid_payload(self, **overrides):
        payload = {
            "title": "Software Engineer",
            "category": self.category.pk,
            "location": self.location.pk,
            "is_remote": True,
            "employment_type": Job.EmploymentType.FULL_TIME,
            "vacancies": 3,
            "salary_min": 50000,
            "salary_max": 90000,
            "is_salary_negotiable": True,
            "experience_years_min": 1,
            "education_level": Education.Level.BACHELOR,
            "required_skills": [self.skill1.pk, self.skill2.pk],
            "application_deadline": (timezone.localdate() + timedelta(days=20)).isoformat(),
            "description": "Exciting software engineering role.",
            "responsibilities": "Building scalable backend services.",
        }
        payload.update(overrides)
        return payload

    def test_get_create_renders_blank_form(self):
        response = self.client.get(reverse("employer_job_create"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "jobs/employer_job_form.html")
        self.assertIn("form", response.context)
        self.assertIsNone(response.context["form"].instance.pk)

    def test_valid_post_creates_draft_job(self):
        payload = self.get_valid_payload()
        response = self.client.post(reverse("employer_job_create"), payload)
        self.assertEqual(response.status_code, 302)
        created_job = Job.objects.get(title="Software Engineer")
        self.assertRedirects(response, reverse("employer_job_detail", args=[created_job.pk]))
        self.assertEqual(created_job.status, Job.Status.DRAFT)
        self.assertIsNone(created_job.published_at)

    def test_created_job_assigned_to_authenticated_employer(self):
        payload = self.get_valid_payload(title="Assigned Job")
        self.client.post(reverse("employer_job_create"), payload)
        job = Job.objects.get(title="Assigned Job")
        self.assertEqual(job.employer, self.employer)

    def test_created_job_cannot_be_automatically_published(self):
        payload = self.get_valid_payload(title="Draft Safety Job", status="published")
        self.client.post(reverse("employer_job_create"), payload)
        job = Job.objects.get(title="Draft Safety Job")
        self.assertEqual(job.status, Job.Status.DRAFT)
        self.assertIsNone(job.published_at)
        self.assertFalse(job.is_open)

    def test_required_skills_saved_via_m2m(self):
        payload = self.get_valid_payload(
            title="Skilled Job",
            required_skills=[self.skill1.pk, self.skill2.pk],
        )
        self.client.post(reverse("employer_job_create"), payload)
        job = Job.objects.get(title="Skilled Job")
        self.assertEqual(set(job.required_skills.all()), {self.skill1, self.skill2})

    def test_invalid_salary_range_rejected(self):
        payload = self.get_valid_payload(salary_min=100000, salary_max=50000)
        response = self.client.post(reverse("employer_job_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "salary_max", "Maximum salary cannot be less than minimum salary.")
        self.assertFalse(Job.objects.filter(salary_min=100000).exists())

    def test_invalid_vacancy_rejected(self):
        payload = self.get_valid_payload(vacancies=0)
        response = self.client.post(reverse("employer_job_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("vacancies"))
        self.assertEqual(Job.objects.count(), 0)

    def test_past_deadline_allowed_for_draft(self):
        past_date = (timezone.localdate() - timedelta(days=3)).isoformat()
        payload = self.get_valid_payload(title="Past Deadline Draft", application_deadline=past_date)
        response = self.client.post(reverse("employer_job_create"), payload)
        self.assertEqual(response.status_code, 302)
        job = Job.objects.get(title="Past Deadline Draft")
        self.assertEqual(job.status, Job.Status.DRAFT)
        self.assertEqual(job.application_deadline, timezone.localdate() - timedelta(days=3))


class EmployerJobEditTests(TestCase):

    def setUp(self):
        self.employer = make_approved_employer()
        self.category = make_category(name="Edit Cat", slug="edit-cat")
        self.location = make_location(name="Edit Loc", slug="edit-loc")
        self.skill1 = Skill.objects.create(name="Python")
        self.skill2 = Skill.objects.create(name="Django")
        self.skill3 = Skill.objects.create(name="PostgreSQL")
        self.job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Initial Title",
            description="Initial description",
            salary_min=30000,
            salary_max=60000,
            vacancies=1,
            application_deadline=timezone.localdate() + timedelta(days=15),
            status=Job.Status.DRAFT,
        )
        self.job.required_skills.add(self.skill1)
        self.client.force_login(self.employer.user)

    def test_get_edit_renders_existing_job_data(self):
        response = self.client.get(reverse("employer_job_edit", args=[self.job.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "jobs/employer_job_form.html")
        form = response.context["form"]
        self.assertEqual(form.instance.pk, self.job.pk)
        self.assertEqual(form.initial["title"], "Initial Title")

    def test_valid_post_updates_editable_fields(self):
        payload = {
            "title": "Senior Updated Engineer",
            "category": self.category.pk,
            "location": self.location.pk,
            "employment_type": Job.EmploymentType.PART_TIME,
            "vacancies": 4,
            "salary_min": 70000,
            "salary_max": 120000,
            "is_salary_negotiable": True,
            "experience_years_min": 3,
            "education_level": Education.Level.MASTER,
            "required_skills": [self.skill2.pk, self.skill3.pk],
            "application_deadline": (timezone.localdate() + timedelta(days=25)).isoformat(),
            "description": "Updated job description.",
            "responsibilities": "Updated responsibilities.",
        }
        response = self.client.post(reverse("employer_job_edit", args=[self.job.pk]), payload)
        self.assertRedirects(response, reverse("employer_job_detail", args=[self.job.pk]))
        self.job.refresh_from_db()
        self.assertEqual(self.job.title, "Senior Updated Engineer")
        self.assertEqual(self.job.employment_type, Job.EmploymentType.PART_TIME)
        self.assertEqual(self.job.vacancies, 4)
        self.assertEqual(self.job.salary_min, 70000)
        self.assertEqual(self.job.salary_max, 120000)
        self.assertTrue(self.job.is_salary_negotiable)
        self.assertEqual(self.job.experience_years_min, 3)
        self.assertEqual(self.job.education_level, Education.Level.MASTER)
        self.assertEqual(self.job.description, "Updated job description.")

    def test_m2m_skills_update_correctly(self):
        payload = {
            "title": self.job.title,
            "category": self.category.pk,
            "location": self.location.pk,
            "is_remote": self.job.is_remote,
            "employment_type": self.job.employment_type,
            "vacancies": self.job.vacancies,
            "experience_years_min": self.job.experience_years_min,
            "application_deadline": self.job.application_deadline.isoformat(),
            "description": self.job.description,
            "required_skills": [self.skill2.pk, self.skill3.pk],
        }
        response = self.client.post(reverse("employer_job_edit", args=[self.job.pk]), payload)
        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        self.assertEqual(set(self.job.required_skills.all()), {self.skill2, self.skill3})

    def test_employer_ownership_remains_unchanged(self):
        other_employer = make_approved_employer(username="other_emp", email="other@example.com")
        payload = {
            "title": "Title Preserved Owner",
            "category": self.category.pk,
            "location": self.location.pk,
            "is_remote": self.job.is_remote,
            "employment_type": self.job.employment_type,
            "vacancies": self.job.vacancies,
            "experience_years_min": self.job.experience_years_min,
            "application_deadline": self.job.application_deadline.isoformat(),
            "description": self.job.description,
            "employer": other_employer.pk,
        }
        response = self.client.post(reverse("employer_job_edit", args=[self.job.pk]), payload)
        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        self.assertEqual(self.job.employer, self.employer)

    def test_status_remains_unchanged(self):
        payload = {
            "title": "Title Status Protected",
            "category": self.category.pk,
            "location": self.location.pk,
            "is_remote": self.job.is_remote,
            "employment_type": self.job.employment_type,
            "vacancies": self.job.vacancies,
            "experience_years_min": self.job.experience_years_min,
            "application_deadline": self.job.application_deadline.isoformat(),
            "description": self.job.description,
            "status": "published",
        }
        response = self.client.post(reverse("employer_job_edit", args=[self.job.pk]), payload)
        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.DRAFT)

    def test_published_at_remains_unchanged(self):
        published_time = timezone.now() - timedelta(days=2)
        published_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Published Edit Job",
            description="Desc",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
            published_at=published_time,
        )
        payload = {
            "title": "Updated Published Job",
            "category": self.category.pk,
            "location": self.location.pk,
            "is_remote": published_job.is_remote,
            "employment_type": published_job.employment_type,
            "vacancies": published_job.vacancies,
            "experience_years_min": published_job.experience_years_min,
            "application_deadline": published_job.application_deadline.isoformat(),
            "description": published_job.description,
            "published_at": (timezone.now() + timedelta(days=10)).isoformat(),
        }
        response = self.client.post(reverse("employer_job_edit", args=[published_job.pk]), payload)
        self.assertEqual(response.status_code, 302)
        published_job.refresh_from_db()
        self.assertEqual(published_job.published_at, published_time)

    def test_audit_timestamps_behavior(self):
        original_created_at = self.job.created_at
        payload = {
            "title": "Audit Updated Job",
            "category": self.category.pk,
            "location": self.location.pk,
            "is_remote": self.job.is_remote,
            "employment_type": self.job.employment_type,
            "vacancies": self.job.vacancies,
            "experience_years_min": self.job.experience_years_min,
            "application_deadline": self.job.application_deadline.isoformat(),
            "description": self.job.description,
        }
        response = self.client.post(reverse("employer_job_edit", args=[self.job.pk]), payload)
        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        self.assertEqual(self.job.created_at, original_created_at)
        self.assertGreaterEqual(self.job.updated_at, original_created_at)


class EmployerJobViewUITests(TestCase):

    def setUp(self):
        self.employer = make_approved_employer()
        self.category = make_category(name="Design UI", slug="design-ui")
        self.location = make_location(name="Lalitpur UI", slug="lalitpur-ui")
        self.skill = Skill.objects.create(name="Figma")
        self.job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="UI/UX Designer",
            description="Design intuitive interfaces.",
            responsibilities="Wireframing and user research.",
            vacancies=2,
            salary_min=45000,
            salary_max=75000,
            application_deadline=timezone.localdate() + timedelta(days=12),
            status=Job.Status.DRAFT,
        )
        self.job.required_skills.add(self.skill)
        self.client.force_login(self.employer.user)

    def test_employer_job_detail_renders_correct_job(self):
        response = self.client.get(reverse("employer_job_detail", args=[self.job.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "jobs/employer_job_detail.html")
        content = response.content.decode()
        self.assertIn("UI/UX Designer", content)
        self.assertIn("Design intuitive interfaces.", content)
        self.assertIn("Wireframing and user research.", content)
        self.assertIn("Design UI", content)
        self.assertIn("Lalitpur UI", content)
        self.assertIn("figma", content)
        self.assertIn(reverse("employer_job_edit", args=[self.job.pk]), content)

    def test_employer_job_list_renders_owned_jobs(self):
        response = self.client.get(reverse("employer_job_list"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "jobs/employer_job_list.html")
        content = response.content.decode()
        self.assertIn("UI/UX Designer", content)
        self.assertIn("Draft", content)
        self.assertIn(reverse("employer_job_detail", args=[self.job.pk]), content)
        self.assertIn(reverse("employer_job_edit", args=[self.job.pk]), content)
        self.assertIn(reverse("employer_job_create"), content)

    def test_empty_employer_job_list_renders_correctly(self):
        new_employer = make_approved_employer(username="empty_emp", email="empty@example.com")
        self.client.force_login(new_employer.user)
        response = self.client.get(reverse("employer_job_list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("No Jobs Posted Yet", content)
        self.assertIn(reverse("employer_job_create"), content)

    def test_dashboard_job_management_integration(self):
        response = self.client.get(reverse("employer_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_post_jobs"])
        self.assertEqual(response.context["jobs_count"], 1)
        content = response.content.decode()
        self.assertIn(reverse("employer_job_create"), content)
        self.assertIn(reverse("employer_job_list"), content)
        self.assertIn("My Jobs (1)", content)


class EmployerJobPublishAuthTests(TestCase):
    def setUp(self):
        self.approved_employer = make_approved_employer(username="pub_app", email="pub_app@example.com")
        self.pending_employer = make_pending_employer(username="pub_pend", email="pub_pend@example.com")
        self.rejected_employer = make_rejected_employer(username="pub_rej", email="pub_rej@example.com")
        self.jobseeker = make_jobseeker(username="pub_js", email="pub_js@example.com")
        self.category = make_category(name="Pub Cat", slug="pub-cat")
        self.location = make_location(name="Pub Loc", slug="pub-loc")
        self.job = Job.objects.create(
            employer=self.approved_employer,
            category=self.category,
            location=self.location,
            title="Publishable Job",
            description="Job description",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.DRAFT,
        )

    def test_anonymous_cannot_publish(self):
        response = self.client.post(reverse("employer_job_publish", args=[self.job.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.DRAFT)

    def test_jobseeker_cannot_publish(self):
        self.client.force_login(self.jobseeker)
        response = self.client.post(reverse("employer_job_publish", args=[self.job.pk]))
        self.assertEqual(response.status_code, 403)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.DRAFT)

    def test_pending_employer_cannot_publish(self):
        self.client.force_login(self.pending_employer.user)
        response = self.client.post(reverse("employer_job_publish", args=[self.job.pk]))
        self.assertEqual(response.status_code, 403)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.DRAFT)

    def test_rejected_employer_cannot_publish(self):
        self.client.force_login(self.rejected_employer.user)
        response = self.client.post(reverse("employer_job_publish", args=[self.job.pk]))
        self.assertEqual(response.status_code, 403)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.DRAFT)

    def test_employer_without_profile_cannot_publish(self):
        user_no_profile = User.objects.create_user(
            username="pub_no_profile", email="pub_no_profile@example.com", password="Password123!", role=User.Role.EMPLOYER
        )
        self.client.force_login(user_no_profile)
        response = self.client.post(reverse("employer_job_publish", args=[self.job.pk]))
        self.assertEqual(response.status_code, 403)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.DRAFT)

    def test_approved_employer_can_publish_valid_draft(self):
        self.client.force_login(self.approved_employer.user)
        response = self.client.post(reverse("employer_job_publish", args=[self.job.pk]))
        self.assertRedirects(response, reverse("employer_job_detail", args=[self.job.pk]))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.PUBLISHED)
        self.assertIsNotNone(self.job.published_at)


class EmployerJobPublishOwnershipTests(TestCase):
    def setUp(self):
        self.emp_a = make_approved_employer(username="own_pub_a", email="own_pub_a@example.com")
        self.emp_b = make_approved_employer(username="own_pub_b", email="own_pub_b@example.com")
        self.category = make_category(name="Own Pub Cat", slug="own-pub-cat")
        self.location = make_location(name="Own Pub Loc", slug="own-pub-loc")
        self.job_b = Job.objects.create(
            employer=self.emp_b,
            category=self.category,
            location=self.location,
            title="Employer B Job",
            description="Description",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.DRAFT,
        )

    def test_employer_cannot_publish_another_employer_job(self):
        self.client.force_login(self.emp_a.user)
        response = self.client.post(reverse("employer_job_publish", args=[self.job_b.pk]))
        self.assertEqual(response.status_code, 404)
        self.job_b.refresh_from_db()
        self.assertEqual(self.job_b.status, Job.Status.DRAFT)

    def test_cross_employer_publish_returns_404(self):
        self.client.force_login(self.emp_a.user)
        response = self.client.post(reverse("employer_job_publish", args=[self.job_b.pk]))
        self.assertEqual(response.status_code, 404)


class EmployerJobPublishLifecycleTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="life_pub", email="life_pub@example.com")
        self.category = make_category(name="Life Pub Cat", slug="life-pub-cat")
        self.location = make_location(name="Life Pub Loc", slug="life-pub-loc")
        self.draft_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Draft Lifecycle Job",
            description="Description",
            application_deadline=timezone.localdate() + timedelta(days=15),
            status=Job.Status.DRAFT,
        )
        self.client.force_login(self.employer.user)

    def test_valid_draft_to_published(self):
        response = self.client.post(reverse("employer_job_publish", args=[self.draft_job.pk]))
        self.assertRedirects(response, reverse("employer_job_detail", args=[self.draft_job.pk]))
        self.draft_job.refresh_from_db()
        self.assertEqual(self.draft_job.status, Job.Status.PUBLISHED)

    def test_published_at_set_by_publish(self):
        before = timezone.now()
        self.client.post(reverse("employer_job_publish", args=[self.draft_job.pk]))
        after = timezone.now()
        self.draft_job.refresh_from_db()
        self.assertIsNotNone(self.draft_job.published_at)
        self.assertTrue(before <= self.draft_job.published_at <= after)

    def test_published_job_becomes_open_when_deadline_valid(self):
        self.client.post(reverse("employer_job_publish", args=[self.draft_job.pk]))
        self.draft_job.refresh_from_db()
        self.assertTrue(self.draft_job.is_open)
        self.assertIn(self.draft_job, Job.objects.open_jobs())

    def test_publishing_already_published_job(self):
        self.client.post(reverse("employer_job_publish", args=[self.draft_job.pk]))
        self.draft_job.refresh_from_db()
        self.assertEqual(self.draft_job.status, Job.Status.PUBLISHED)
        response = self.client.post(reverse("employer_job_publish", args=[self.draft_job.pk]))
        self.assertEqual(response.status_code, 302)
        self.draft_job.refresh_from_db()
        self.assertEqual(self.draft_job.status, Job.Status.PUBLISHED)

    def test_publishing_closed_job(self):
        self.draft_job.status = Job.Status.CLOSED
        self.draft_job.save()
        response = self.client.post(reverse("employer_job_publish", args=[self.draft_job.pk]))
        self.assertEqual(response.status_code, 302)
        self.draft_job.refresh_from_db()
        self.assertEqual(self.draft_job.status, Job.Status.PUBLISHED)


class EmployerJobPublishDeadlineValidationTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="dl_pub", email="dl_pub@example.com")
        self.category = make_category(name="DL Pub Cat", slug="dl-pub-cat")
        self.location = make_location(name="DL Pub Loc", slug="dl-pub-loc")
        self.client.force_login(self.employer.user)

    def test_draft_with_past_deadline_cannot_be_published(self):
        past_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Past Deadline Job",
            description="Description",
            application_deadline=timezone.localdate() - timedelta(days=2),
            status=Job.Status.DRAFT,
        )
        response = self.client.post(reverse("employer_job_publish", args=[past_job.pk]))
        self.assertRedirects(response, reverse("employer_job_detail", args=[past_job.pk]))
        past_job.refresh_from_db()
        self.assertEqual(past_job.status, Job.Status.DRAFT)
        self.assertIsNone(past_job.published_at)
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("Application deadline must be today or a future date." in str(m) for m in messages))

    def test_draft_with_today_deadline_can_be_published(self):
        today_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Today Deadline Job",
            description="Description",
            application_deadline=timezone.localdate(),
            status=Job.Status.DRAFT,
        )
        response = self.client.post(reverse("employer_job_publish", args=[today_job.pk]))
        self.assertRedirects(response, reverse("employer_job_detail", args=[today_job.pk]))
        today_job.refresh_from_db()
        self.assertEqual(today_job.status, Job.Status.PUBLISHED)
        self.assertTrue(today_job.is_open)

    def test_failed_publication_does_not_incorrectly_change_status(self):
        past_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Failed Pub Status Check",
            description="Description",
            application_deadline=timezone.localdate() - timedelta(days=5),
            status=Job.Status.DRAFT,
        )
        self.client.post(reverse("employer_job_publish", args=[past_job.pk]))
        past_job.refresh_from_db()
        self.assertEqual(past_job.status, Job.Status.DRAFT)
        self.assertIsNone(past_job.published_at)
        self.assertFalse(past_job.is_open)


class EmployerJobCloseAuthTests(TestCase):
    def setUp(self):
        self.approved_employer = make_approved_employer(username="cls_app", email="cls_app@example.com")
        self.pending_employer = make_pending_employer(username="cls_pend", email="cls_pend@example.com")
        self.rejected_employer = make_rejected_employer(username="cls_rej", email="cls_rej@example.com")
        self.jobseeker = make_jobseeker(username="cls_js", email="cls_js@example.com")
        self.category = make_category(name="Cls Cat", slug="cls-cat")
        self.location = make_location(name="Cls Loc", slug="cls-loc")
        self.job = Job.objects.create(
            employer=self.approved_employer,
            category=self.category,
            location=self.location,
            title="Job to Close",
            description="Description",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )

    def test_anonymous_cannot_close(self):
        response = self.client.post(reverse("employer_job_close", args=[self.job.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.PUBLISHED)

    def test_jobseeker_cannot_close(self):
        self.client.force_login(self.jobseeker)
        response = self.client.post(reverse("employer_job_close", args=[self.job.pk]))
        self.assertEqual(response.status_code, 403)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.PUBLISHED)

    def test_pending_employer_cannot_close(self):
        self.client.force_login(self.pending_employer.user)
        response = self.client.post(reverse("employer_job_close", args=[self.job.pk]))
        self.assertEqual(response.status_code, 403)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.PUBLISHED)

    def test_rejected_employer_cannot_close(self):
        self.client.force_login(self.rejected_employer.user)
        response = self.client.post(reverse("employer_job_close", args=[self.job.pk]))
        self.assertEqual(response.status_code, 403)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.PUBLISHED)

    def test_employer_without_profile_cannot_close(self):
        user_no_profile = User.objects.create_user(
            username="cls_no_profile", email="cls_no_profile@example.com", password="Password123!", role=User.Role.EMPLOYER
        )
        self.client.force_login(user_no_profile)
        response = self.client.post(reverse("employer_job_close", args=[self.job.pk]))
        self.assertEqual(response.status_code, 403)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.PUBLISHED)

    def test_approved_employer_can_close_owned_published_job(self):
        self.client.force_login(self.approved_employer.user)
        response = self.client.post(reverse("employer_job_close", args=[self.job.pk]))
        self.assertRedirects(response, reverse("employer_job_detail", args=[self.job.pk]))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.CLOSED)


class EmployerJobCloseOwnershipTests(TestCase):
    def setUp(self):
        self.emp_a = make_approved_employer(username="cls_own_a", email="cls_own_a@example.com")
        self.emp_b = make_approved_employer(username="cls_own_b", email="cls_own_b@example.com")
        self.category = make_category(name="Cls Own Cat", slug="cls-own-cat")
        self.location = make_location(name="Cls Own Loc", slug="cls-own-loc")
        self.job_b = Job.objects.create(
            employer=self.emp_b,
            category=self.category,
            location=self.location,
            title="Employer B Published Job",
            description="Description",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )

    def test_employer_cannot_close_another_employer_job(self):
        self.client.force_login(self.emp_a.user)
        response = self.client.post(reverse("employer_job_close", args=[self.job_b.pk]))
        self.assertEqual(response.status_code, 404)
        self.job_b.refresh_from_db()
        self.assertEqual(self.job_b.status, Job.Status.PUBLISHED)

    def test_cross_employer_close_returns_404(self):
        self.client.force_login(self.emp_a.user)
        response = self.client.post(reverse("employer_job_close", args=[self.job_b.pk]))
        self.assertEqual(response.status_code, 404)


class EmployerJobCloseLifecycleTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="cls_life", email="cls_life@example.com")
        self.category = make_category(name="Cls Life Cat", slug="cls-life-cat")
        self.location = make_location(name="Cls Life Loc", slug="cls-life-loc")
        self.job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Published Life Job",
            description="Description",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now() - timedelta(days=1),
        )
        self.client.force_login(self.employer.user)

    def test_published_to_closed(self):
        response = self.client.post(reverse("employer_job_close", args=[self.job.pk]))
        self.assertRedirects(response, reverse("employer_job_detail", args=[self.job.pk]))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.CLOSED)

    def test_closed_job_is_not_open(self):
        self.client.post(reverse("employer_job_close", args=[self.job.pk]))
        self.job.refresh_from_db()
        self.assertFalse(self.job.is_open)
        self.assertNotIn(self.job, Job.objects.open_jobs())

    def test_closing_does_not_alter_employer_ownership(self):
        self.client.post(reverse("employer_job_close", args=[self.job.pk]))
        self.job.refresh_from_db()
        self.assertEqual(self.job.employer, self.employer)

    def test_closing_preserves_audit_fields(self):
        original_created_at = self.job.created_at
        original_published_at = self.job.published_at
        self.client.post(reverse("employer_job_close", args=[self.job.pk]))
        self.job.refresh_from_db()
        self.assertEqual(self.job.created_at, original_created_at)
        self.assertEqual(self.job.published_at, original_published_at)


class EmployerJobExpirationTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="exp_emp", email="exp_emp@example.com")
        self.category = make_category(name="Exp Cat", slug="exp-cat")
        self.location = make_location(name="Exp Loc", slug="exp-loc")
        self.expired_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Expired Published Job",
            description="Description",
            application_deadline=timezone.localdate() - timedelta(days=1),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now() - timedelta(days=5),
        )

    def test_published_job_with_past_deadline_is_not_open(self):
        self.assertFalse(self.expired_job.is_open)

    def test_expired_published_job_excluded_from_open_jobs(self):
        self.assertNotIn(self.expired_job, Job.objects.open_jobs())

    def test_expired_published_job_included_in_expired_jobs(self):
        self.assertIn(self.expired_job, Job.objects.expired_jobs())


class EmployerJobHttpMethodTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="method_emp", email="method_emp@example.com")
        self.category = make_category(name="Method Cat", slug="method-cat")
        self.location = make_location(name="Method Loc", slug="method-loc")
        self.job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Method Test Job",
            description="Description",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.DRAFT,
        )
        self.client.force_login(self.employer.user)

    def test_get_publish_endpoint_is_rejected_with_405(self):
        response = self.client.get(reverse("employer_job_publish", args=[self.job.pk]))
        self.assertEqual(response.status_code, 405)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.DRAFT)

    def test_get_close_endpoint_is_rejected_with_405(self):
        self.job.status = Job.Status.PUBLISHED
        self.job.save()
        response = self.client.get(reverse("employer_job_close", args=[self.job.pk]))
        self.assertEqual(response.status_code, 405)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.PUBLISHED)


class EmployerJobLifecycleUITests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="ui_emp", email="ui_emp@example.com")
        self.category = make_category(name="UI Cat", slug="ui-cat")
        self.location = make_location(name="UI Loc", slug="ui-loc")
        self.draft_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="UI Draft Job",
            description="Description",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.DRAFT,
        )
        self.published_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="UI Published Job",
            description="Description",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.expired_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="UI Expired Job",
            description="Description",
            application_deadline=timezone.localdate() - timedelta(days=2),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now() - timedelta(days=10),
        )
        self.closed_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="UI Closed Job",
            description="Description",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.CLOSED,
        )
        self.client.force_login(self.employer.user)

    def test_draft_detail_displays_publish_action(self):
        response = self.client.get(reverse("employer_job_detail", args=[self.draft_job.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Publish Job", content)
        self.assertIn(reverse("employer_job_publish", args=[self.draft_job.pk]), content)
        self.assertNotIn(reverse("employer_job_close", args=[self.draft_job.pk]), content)

    def test_published_detail_displays_close_action(self):
        response = self.client.get(reverse("employer_job_detail", args=[self.published_job.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Close Job", content)
        self.assertIn(reverse("employer_job_close", args=[self.published_job.pk]), content)
        self.assertNotIn(reverse("employer_job_publish", args=[self.published_job.pk]), content)

    def test_closed_detail_does_not_display_publish_or_close(self):
        response = self.client.get(reverse("employer_job_detail", args=[self.closed_job.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn("Publish Job", content)
        self.assertNotIn(reverse("employer_job_publish", args=[self.closed_job.pk]), content)
        self.assertNotIn("Close Job", content)
        self.assertNotIn(reverse("employer_job_close", args=[self.closed_job.pk]), content)

    def test_expired_detail_displays_expired_warning_and_close_action(self):
        response = self.client.get(reverse("employer_job_detail", args=[self.expired_job.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Published (Expired)", content)
        self.assertIn("Deadline Passed", content)
        self.assertIn("The application deadline", content)
        self.assertIn("Close Job", content)

    def test_employer_job_list_displays_lifecycle_statuses(self):
        response = self.client.get(reverse("employer_job_list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Draft", content)
        self.assertIn("Open", content)
        self.assertIn("Expired", content)
        self.assertIn("Closed", content)


# =====================================================================
# STEP 6.5 — PUBLIC JOB DISCOVERY & JOB DETAIL TESTS
# =====================================================================

class PublicJobListAccessTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="access_emp", email="access_emp@example.com")
        self.jobseeker = make_jobseeker(username="access_js", email="access_js@example.com")
        self.category = make_category(name="IT Access", slug="it-access")
        self.location = make_location(name="Access Loc", slug="access-loc")
        self.job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Access Test Job",
            description="Access description",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )

    def test_anonymous_user_can_access_job_list(self):
        response = self.client.get(reverse("job_list"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "jobs/job_list.html")
        self.assertIn("Access Test Job", response.content.decode())

    def test_jobseeker_can_access_job_list(self):
        self.client.force_login(self.jobseeker)
        response = self.client.get(reverse("job_list"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Access Test Job", response.content.decode())

    def test_employer_can_access_job_list(self):
        self.client.force_login(self.employer.user)
        response = self.client.get(reverse("job_list"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Access Test Job", response.content.decode())


class PublicJobListVisibilityTests(TestCase):
    def setUp(self):
        self.approved_emp = make_approved_employer(username="vis_app", email="vis_app@example.com")
        self.pending_emp = make_pending_employer(username="vis_pend", email="vis_pend@example.com")
        self.rejected_emp = make_rejected_employer(username="vis_rej", email="vis_rej@example.com")
        self.category = make_category(name="Vis Cat", slug="vis-cat")
        self.location = make_location(name="Vis Loc", slug="vis-loc")

        # 1. Open published job
        self.open_job = Job.objects.create(
            employer=self.approved_emp,
            category=self.category,
            location=self.location,
            title="Open Published Job",
            description="Open description",
            application_deadline=timezone.localdate() + timedelta(days=7),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        # 2. Draft job
        self.draft_job = Job.objects.create(
            employer=self.approved_emp,
            category=self.category,
            location=self.location,
            title="Draft Hidden Job",
            description="Draft description",
            application_deadline=timezone.localdate() + timedelta(days=7),
            status=Job.Status.DRAFT,
        )
        # 3. Closed job
        self.closed_job = Job.objects.create(
            employer=self.approved_emp,
            category=self.category,
            location=self.location,
            title="Closed Hidden Job",
            description="Closed description",
            application_deadline=timezone.localdate() + timedelta(days=7),
            status=Job.Status.CLOSED,
            published_at=timezone.now() - timedelta(days=5),
        )
        # 4. Expired published job
        self.expired_job = Job.objects.create(
            employer=self.approved_emp,
            category=self.category,
            location=self.location,
            title="Expired Hidden Job",
            description="Expired description",
            application_deadline=timezone.localdate() - timedelta(days=1),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now() - timedelta(days=10),
        )
        # 5. Published job with pending employer
        self.pending_emp_job = Job.objects.create(
            employer=self.pending_emp,
            category=self.category,
            location=self.location,
            title="Pending Employer Hidden Job",
            description="Pending description",
            application_deadline=timezone.localdate() + timedelta(days=7),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        # 6. Published job with rejected employer
        self.rejected_emp_job = Job.objects.create(
            employer=self.rejected_emp,
            category=self.category,
            location=self.location,
            title="Rejected Employer Hidden Job",
            description="Rejected description",
            application_deadline=timezone.localdate() + timedelta(days=7),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )

    def test_open_published_job_appears_in_listing(self):
        response = self.client.get(reverse("job_list"))
        self.assertEqual(response.status_code, 200)
        jobs = response.context["jobs"]
        self.assertIn(self.open_job, jobs)

    def test_draft_job_does_not_appear_in_listing(self):
        response = self.client.get(reverse("job_list"))
        jobs = response.context["jobs"]
        self.assertNotIn(self.draft_job, jobs)

    def test_closed_job_does_not_appear_in_listing(self):
        response = self.client.get(reverse("job_list"))
        jobs = response.context["jobs"]
        self.assertNotIn(self.closed_job, jobs)

    def test_expired_published_job_does_not_appear_in_listing(self):
        response = self.client.get(reverse("job_list"))
        jobs = response.context["jobs"]
        self.assertNotIn(self.expired_job, jobs)

    def test_published_job_from_unapproved_employer_does_not_appear(self):
        response = self.client.get(reverse("job_list"))
        jobs = response.context["jobs"]
        self.assertNotIn(self.pending_emp_job, jobs)
        self.assertNotIn(self.rejected_emp_job, jobs)


class PublicJobDetailVisibilityTests(TestCase):
    def setUp(self):
        self.approved_emp = make_approved_employer(username="dtl_app", email="dtl_app@example.com")
        self.pending_emp = make_pending_employer(username="dtl_pend", email="dtl_pend@example.com")
        self.category = make_category(name="Dtl Cat", slug="dtl-cat")
        self.location = make_location(name="Dtl Loc", slug="dtl-loc")

        self.open_job = Job.objects.create(
            employer=self.approved_emp,
            category=self.category,
            location=self.location,
            title="Public Open Detail Job",
            description="Detail description",
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.draft_job = Job.objects.create(
            employer=self.approved_emp,
            category=self.category,
            location=self.location,
            title="Draft Secret Job",
            description="Secret draft",
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.DRAFT,
        )
        self.closed_job = Job.objects.create(
            employer=self.approved_emp,
            category=self.category,
            location=self.location,
            title="Closed Archived Job",
            description="Archived closed",
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.CLOSED,
            published_at=timezone.now() - timedelta(days=5),
        )
        self.expired_job = Job.objects.create(
            employer=self.approved_emp,
            category=self.category,
            location=self.location,
            title="Expired Old Job",
            description="Expired old",
            application_deadline=timezone.localdate() - timedelta(days=1),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now() - timedelta(days=10),
        )
        self.unapproved_job = Job.objects.create(
            employer=self.pending_emp,
            category=self.category,
            location=self.location,
            title="Unapproved Employer Job",
            description="Pending emp",
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )

    def test_open_job_detail_is_accessible_to_public(self):
        response = self.client.get(reverse("job_detail", args=[self.open_job.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "jobs/job_detail.html")
        self.assertEqual(response.context["job"], self.open_job)

    def test_draft_detail_returns_404(self):
        response = self.client.get(reverse("job_detail", args=[self.draft_job.pk]))
        self.assertEqual(response.status_code, 404)

    def test_closed_detail_returns_404(self):
        response = self.client.get(reverse("job_detail", args=[self.closed_job.pk]))
        self.assertEqual(response.status_code, 404)

    def test_expired_detail_returns_404(self):
        response = self.client.get(reverse("job_detail", args=[self.expired_job.pk]))
        self.assertEqual(response.status_code, 404)

    def test_job_from_unapproved_employer_returns_404(self):
        response = self.client.get(reverse("job_detail", args=[self.unapproved_job.pk]))
        self.assertEqual(response.status_code, 404)


class PublicJobSearchTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="search_emp", email="search_emp@example.com")
        self.cat_dev = make_category(name="Software Engineering", slug="software-eng")
        self.cat_mkt = make_category(name="Digital Marketing", slug="digital-marketing")
        self.loc_ktm = make_location(name="Kathmandu Hub", slug="kathmandu-hub")
        self.loc_pok = make_location(name="Pokhara Valley", slug="pokhara-valley")

        self.skill_python = Skill.objects.create(name="Python")
        self.skill_react = Skill.objects.create(name="React")

        self.job1 = Job.objects.create(
            employer=self.employer,
            category=self.cat_dev,
            location=self.loc_ktm,
            title="Senior Python Backend Developer",
            description="Build scalable APIs using Django and PostgreSQL.",
            responsibilities="Maintain system architecture and lead code reviews.",
            application_deadline=timezone.localdate() + timedelta(days=20),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.job1.required_skills.add(self.skill_python)

        self.job2 = Job.objects.create(
            employer=self.employer,
            category=self.cat_mkt,
            location=self.loc_pok,
            title="Social Media Manager",
            description="Manage social accounts and content creation.",
            responsibilities="Engage with audience and track campaign metrics.",
            application_deadline=timezone.localdate() + timedelta(days=15),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )

    def test_search_matches_title(self):
        response = self.client.get(reverse("job_list"), {"q": "Python"})
        jobs = list(response.context["jobs"])
        self.assertIn(self.job1, jobs)
        self.assertNotIn(self.job2, jobs)

    def test_search_matches_description(self):
        response = self.client.get(reverse("job_list"), {"q": "PostgreSQL"})
        jobs = list(response.context["jobs"])
        self.assertIn(self.job1, jobs)
        self.assertNotIn(self.job2, jobs)

    def test_search_matches_responsibilities(self):
        response = self.client.get(reverse("job_list"), {"q": "architecture"})
        jobs = list(response.context["jobs"])
        self.assertIn(self.job1, jobs)
        self.assertNotIn(self.job2, jobs)

    def test_search_is_case_insensitive(self):
        response = self.client.get(reverse("job_list"), {"q": "python"})
        jobs = list(response.context["jobs"])
        self.assertIn(self.job1, jobs)

        response_upper = self.client.get(reverse("job_list"), {"q": "PYTHON"})
        jobs_upper = list(response_upper.context["jobs"])
        self.assertIn(self.job1, jobs_upper)

    def test_non_matching_search_returns_empty(self):
        response = self.client.get(reverse("job_list"), {"q": "NonExistentKeywordXYZ"})
        self.assertEqual(len(response.context["jobs"]), 0)

    def test_search_matches_category_name(self):
        response = self.client.get(reverse("job_list"), {"q": "Software"})
        jobs = list(response.context["jobs"])
        self.assertIn(self.job1, jobs)
        self.assertNotIn(self.job2, jobs)

    def test_search_matches_location_name(self):
        response = self.client.get(reverse("job_list"), {"q": "Pokhara"})
        jobs = list(response.context["jobs"])
        self.assertIn(self.job2, jobs)
        self.assertNotIn(self.job1, jobs)

    def test_search_matches_required_skill(self):
        response = self.client.get(reverse("job_list"), {"q": "Python"})
        jobs = list(response.context["jobs"])
        self.assertIn(self.job1, jobs)

    def test_empty_or_whitespace_search_returns_all_open_jobs(self):
        response = self.client.get(reverse("job_list"), {"q": "   "})
        jobs = list(response.context["jobs"])
        self.assertEqual(len(jobs), 2)
        self.assertIn(self.job1, jobs)
        self.assertIn(self.job2, jobs)


class PublicJobFilterTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="filter_emp", email="filter_emp@example.com")
        self.cat_dev = make_category(name="Development", slug="development")
        self.cat_des = make_category(name="Design", slug="design")
        self.cat_inactive = Category.objects.create(name="Inactive Cat", slug="inactive-cat", is_active=False)

        self.loc_ktm = make_location(name="KTM", slug="ktm")
        self.loc_btl = make_location(name="Butwal", slug="butwal")

        self.job_dev_full_remote = Job.objects.create(
            employer=self.employer,
            category=self.cat_dev,
            location=self.loc_ktm,
            title="Fullstack Django Dev",
            description="Fullstack role",
            employment_type=Job.EmploymentType.FULL_TIME,
            is_remote=True,
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.job_dev_part_onsite = Job.objects.create(
            employer=self.employer,
            category=self.cat_dev,
            location=self.loc_ktm,
            title="Part-time Python Tutor",
            description="Tutor role",
            employment_type=Job.EmploymentType.PART_TIME,
            is_remote=False,
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.job_des_contract = Job.objects.create(
            employer=self.employer,
            category=self.cat_des,
            location=self.loc_btl,
            title="Contract UI Designer",
            description="Design role",
            employment_type=Job.EmploymentType.CONTRACT,
            is_remote=True,
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )

    def test_category_filter(self):
        response = self.client.get(reverse("job_list"), {"category": "development"})
        jobs = list(response.context["jobs"])
        self.assertEqual(len(jobs), 2)
        self.assertIn(self.job_dev_full_remote, jobs)
        self.assertIn(self.job_dev_part_onsite, jobs)
        self.assertNotIn(self.job_des_contract, jobs)

    def test_location_filter(self):
        response = self.client.get(reverse("job_list"), {"location": "butwal"})
        jobs = list(response.context["jobs"])
        self.assertEqual(len(jobs), 1)
        self.assertIn(self.job_des_contract, jobs)

    def test_employment_type_filter(self):
        response = self.client.get(reverse("job_list"), {"employment_type": Job.EmploymentType.FULL_TIME})
        jobs = list(response.context["jobs"])
        self.assertEqual(len(jobs), 1)
        self.assertIn(self.job_dev_full_remote, jobs)

    def test_remote_filter_remote_only(self):
        response = self.client.get(reverse("job_list"), {"remote": "remote"})
        jobs = list(response.context["jobs"])
        self.assertEqual(len(jobs), 2)
        self.assertIn(self.job_dev_full_remote, jobs)
        self.assertIn(self.job_des_contract, jobs)
        self.assertNotIn(self.job_dev_part_onsite, jobs)

    def test_remote_filter_onsite_only(self):
        response = self.client.get(reverse("job_list"), {"remote": "onsite"})
        jobs = list(response.context["jobs"])
        self.assertEqual(len(jobs), 1)
        self.assertIn(self.job_dev_part_onsite, jobs)
        self.assertNotIn(self.job_dev_full_remote, jobs)

    def test_inactive_category_excluded_from_filter_options(self):
        response = self.client.get(reverse("job_list"))
        categories = response.context["categories"]
        self.assertIn(self.cat_dev, categories)
        self.assertNotIn(self.cat_inactive, categories)

    def test_combined_filters(self):
        response = self.client.get(
            reverse("job_list"),
            {
                "q": "Django",
                "category": "development",
                "location": "ktm",
                "employment_type": Job.EmploymentType.FULL_TIME,
                "remote": "remote",
            },
        )
        jobs = list(response.context["jobs"])
        self.assertEqual(len(jobs), 1)
        self.assertIn(self.job_dev_full_remote, jobs)


class PublicJobSortingTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="sort_emp", email="sort_emp@example.com")
        self.category = make_category(name="Sort Cat", slug="sort-cat")
        self.location = make_location(name="Sort Loc", slug="sort-loc")
        today = timezone.localdate()

        self.job_early_deadline = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Early Deadline Job",
            description="Desc",
            application_deadline=today + timedelta(days=2),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.job_late_deadline = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Late Deadline Job",
            description="Desc",
            application_deadline=today + timedelta(days=30),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )

    def test_default_sort_is_newest(self):
        response = self.client.get(reverse("job_list"))
        jobs = list(response.context["jobs"])
        self.assertEqual(jobs[0], self.job_late_deadline)
        self.assertEqual(jobs[1], self.job_early_deadline)

    def test_deadline_sort(self):
        response = self.client.get(reverse("job_list"), {"sort": "deadline"})
        jobs = list(response.context["jobs"])
        self.assertEqual(jobs[0], self.job_early_deadline)
        self.assertEqual(jobs[1], self.job_late_deadline)


class PublicJobPaginationTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="page_emp", email="page_emp@example.com")
        self.category = make_category(name="Page Cat", slug="page-cat")
        self.location = make_location(name="Page Loc", slug="page-loc")
        today = timezone.localdate()

        self.created_jobs = []
        for i in range(15):
            job = Job.objects.create(
                employer=self.employer,
                category=self.category,
                location=self.location,
                title=f"Paginated Job {i + 1:02d}",
                description=f"Description for job {i + 1}",
                application_deadline=today + timedelta(days=10),
                status=Job.Status.PUBLISHED,
                published_at=timezone.now(),
            )
            self.created_jobs.append(job)

    def test_first_page_contains_ten_jobs(self):
        response = self.client.get(reverse("job_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["jobs"]), 10)
        self.assertEqual(response.context["total_count"], 15)
        self.assertTrue(response.context["page_obj"].has_next())

    def test_second_page_contains_remaining_five_jobs(self):
        response = self.client.get(reverse("job_list"), {"page": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["jobs"]), 5)
        self.assertTrue(response.context["page_obj"].has_previous())

    def test_query_params_preserved_in_pagination(self):
        response = self.client.get(reverse("job_list"), {"category": "page-cat", "page": 1})
        self.assertEqual(response.status_code, 200)
        query_string = response.context["query_string"]
        self.assertIn("category=page-cat", query_string)
        self.assertNotIn("page=", query_string)
        content = response.content.decode()
        self.assertIn("category=page-cat&page=2", content)


class PublicJobUITests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="ui_pub_emp", email="ui_pub_emp@example.com")
        self.employer.industry = "FinTech"
        self.employer.address = "Tinkune, Kathmandu"
        self.employer.website = "https://techcorp.example.com"
        self.employer.save()

        self.category = make_category(name="Finance UI", slug="finance-ui")
        self.location = make_location(name="Kathmandu UI", slug="kathmandu-ui")
        self.skill = Skill.objects.create(name="Accounting")

        today = timezone.localdate()
        self.job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Senior Financial Analyst",
            description="Manage corporate finance portfolios.",
            responsibilities="Prepare financial statements and audits.",
            experience_years_min=3,
            education_level=Education.Level.BACHELOR,
            vacancies=2,
            salary_min=50000,
            salary_max=80000,
            is_remote=True,
            application_deadline=today + timedelta(days=12),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.job.required_skills.add(self.skill)

    def test_job_card_renders_core_public_information(self):
        response = self.client.get(reverse("job_list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Senior Financial Analyst", content)
        self.assertIn(self.employer.company_name, content)
        self.assertIn("Kathmandu UI", content)
        self.assertIn("Remote", content)
        self.assertIn("Finance UI", content)
        self.assertIn("Full-time", content)
        self.assertIn("Rs. 50,000 – Rs. 80,000", content)
        self.assertIn(reverse("job_detail", args=[self.job.pk]), content)

    def test_salary_formatting_variations(self):
        # Range
        self.assertEqual(self.job.salary_display, "Rs. 50,000 – Rs. 80,000")

        # Min only
        self.job.salary_max = None
        self.assertEqual(self.job.salary_display, "Rs. 50,000+")

        # Max only
        self.job.salary_min = None
        self.job.salary_max = 60000
        self.assertEqual(self.job.salary_display, "Up to Rs. 60,000")

        # Negotiable only
        self.job.salary_min = None
        self.job.salary_max = None
        self.job.is_salary_negotiable = True
        self.assertEqual(self.job.salary_display, "Negotiable")

        # Not specified
        self.job.is_salary_negotiable = False
        self.assertEqual(self.job.salary_display, "Not specified")

        # Min/max + Negotiable
        self.job.salary_min = 40000
        self.job.salary_max = 70000
        self.job.is_salary_negotiable = True
        self.assertEqual(self.job.salary_display, "Rs. 40,000 – Rs. 70,000 (Negotiable)")

    def test_detail_page_renders_complete_information_and_application_notice(self):
        response = self.client.get(reverse("job_detail", args=[self.job.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn("Senior Financial Analyst", content)
        self.assertIn("Manage corporate finance portfolios.", content)
        self.assertIn("Prepare financial statements and audits.", content)
        self.assertIn("3 Years", content)
        self.assertIn("Bachelor&#x27;s", content)
        self.assertIn("accounting", content)
        self.assertIn("2 Positions", content)
        self.assertIn("Rs. 50,000 – Rs. 80,000", content)

        # Public employer details
        self.assertIn("FinTech", content)
        self.assertIn("Tinkune, Kathmandu", content)
        self.assertIn("https://techcorp.example.com", content)

        # Application call to action (anonymous sees Login to Apply)
        self.assertIn("Login to Apply", content)

    def test_empty_state_when_filters_yield_no_results(self):
        response = self.client.get(reverse("job_list"), {"q": "NonExistentTerm"})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("No Matching Jobs Found", content)
        self.assertIn("Clear All Filters", content)
        self.assertIn(reverse("job_list"), content)

    def test_empty_state_when_no_jobs_exist(self):
        Job.objects.all().delete()
        response = self.client.get(reverse("job_list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("No Jobs Currently Available", content)


# ===========================================================================
# Step 6.12 Saved Jobs Tests
# ===========================================================================

class SavedJobModelTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="sjm_emp", email="sjm_emp@example.com")
        self.category = make_category(name="SJM Cat", slug="sjm-cat")
        self.location = make_location(name="SJM Loc", slug="sjm-loc")
        self.user = make_jobseeker(username="sjm_cand", email="sjm_cand@example.com")
        self.jobseeker = self.user.jobseeker_profile
        self.job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Software Engineer",
            description="Build cool systems.",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )

    def test_saved_job_creation_and_str(self):
        saved = SavedJob.objects.create(jobseeker=self.jobseeker, job=self.job)
        self.assertEqual(saved.jobseeker, self.jobseeker)
        self.assertEqual(saved.job, self.job)
        self.assertIsNotNone(saved.created_at)
        self.assertEqual(str(saved), f"{self.jobseeker} saved {self.job.title}")

    def test_saved_job_unique_constraint(self):
        SavedJob.objects.create(jobseeker=self.jobseeker, job=self.job)
        with self.assertRaises(IntegrityError):
            SavedJob.objects.create(jobseeker=self.jobseeker, job=self.job)

    def test_saved_job_ordering_newest_first(self):
        job2 = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Frontend Engineer",
            description="Build UI.",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        saved1 = SavedJob.objects.create(jobseeker=self.jobseeker, job=self.job)
        saved2 = SavedJob.objects.create(jobseeker=self.jobseeker, job=job2)
        saved_list = list(SavedJob.objects.filter(jobseeker=self.jobseeker))
        self.assertEqual(saved_list, [saved2, saved1])

    def test_saved_job_cascade_on_job_delete(self):
        SavedJob.objects.create(jobseeker=self.jobseeker, job=self.job)
        self.assertEqual(SavedJob.objects.count(), 1)
        self.job.delete()
        self.assertEqual(SavedJob.objects.count(), 0)

    def test_saved_job_cascade_on_jobseeker_delete(self):
        SavedJob.objects.create(jobseeker=self.jobseeker, job=self.job)
        self.assertEqual(SavedJob.objects.count(), 1)
        self.jobseeker.delete()
        self.assertEqual(SavedJob.objects.count(), 0)


class SavedJobSecurityAndAuthorizationTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="sec_emp", email="sec_emp@example.com")
        self.category = make_category(name="Sec Cat", slug="sec-cat")
        self.location = make_location(name="Sec Loc", slug="sec-loc")
        self.cand1 = make_jobseeker(username="sec_cand1", email="sec_cand1@example.com")
        self.cand2 = make_jobseeker(username="sec_cand2", email="sec_cand2@example.com")
        self.job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="DevOps Engineer",
            description="Cloud infrastructure.",
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.saved_list_url = reverse("saved_job_list")
        self.toggle_url = reverse("toggle_save_job", args=[self.job.pk])

    def test_anonymous_saved_list_redirects_to_login(self):
        response = self.client.get(self.saved_list_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.assertIn(f"next={self.saved_list_url}", response.url)

    def test_anonymous_toggle_save_redirects_to_login(self):
        response = self.client.post(self.toggle_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.assertEqual(SavedJob.objects.count(), 0)

    def test_employer_cannot_access_saved_job_list(self):
        self.client.force_login(self.employer.user)
        response = self.client.get(self.saved_list_url)
        self.assertEqual(response.status_code, 403)

    def test_employer_cannot_toggle_save_job(self):
        self.client.force_login(self.employer.user)
        response = self.client.post(self.toggle_url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(SavedJob.objects.count(), 0)

    def test_get_method_rejected_on_toggle_endpoint(self):
        self.client.force_login(self.cand1)
        response = self.client.get(self.toggle_url)
        self.assertEqual(response.status_code, 405)

    def test_candidate_isolation_on_saved_list(self):
        SavedJob.objects.create(jobseeker=self.cand1.jobseeker_profile, job=self.job)
        self.client.force_login(self.cand2)
        response = self.client.get(self.saved_list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["saved_jobs"]), 0)
        self.assertEqual(response.context["total_count"], 0)


class SavedJobToggleActionTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="act_emp", email="act_emp@example.com")
        self.category = make_category(name="Act Cat", slug="act-cat")
        self.location = make_location(name="Act Loc", slug="act-loc")
        self.cand = make_jobseeker(username="act_cand", email="act_cand@example.com")
        self.job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Backend Engineer",
            description="API development.",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.toggle_url = reverse("toggle_save_job", args=[self.job.pk])
        self.client.force_login(self.cand)

    def test_save_open_job(self):
        response = self.client.post(self.toggle_url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SavedJob.objects.filter(jobseeker=self.cand.jobseeker_profile, job=self.job).exists())
        self.assertRedirects(response, reverse("job_detail", args=[self.job.pk]))

    def test_unsave_job(self):
        SavedJob.objects.create(jobseeker=self.cand.jobseeker_profile, job=self.job)
        response = self.client.post(self.toggle_url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SavedJob.objects.filter(jobseeker=self.cand.jobseeker_profile, job=self.job).exists())

    def test_duplicate_save_post_safety(self):
        self.client.post(self.toggle_url)
        self.assertEqual(SavedJob.objects.filter(jobseeker=self.cand.jobseeker_profile, job=self.job).count(), 1)
        self.client.post(self.toggle_url)
        self.assertEqual(SavedJob.objects.filter(jobseeker=self.cand.jobseeker_profile, job=self.job).count(), 0)

    def test_toggle_nonexistent_job_returns_404(self):
        response = self.client.post(reverse("toggle_save_job", args=[999999]))
        self.assertEqual(response.status_code, 404)

    def test_safe_redirect_with_next_param(self):
        next_path = reverse("job_list")
        response = self.client.post(self.toggle_url, {"next": next_path})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, next_path)

    def test_open_redirect_prevention(self):
        response = self.client.post(self.toggle_url, {"next": "https://malicious-external-site.com"})
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.url, "https://malicious-external-site.com")
        self.assertEqual(response.url, reverse("job_detail", args=[self.job.pk]))


class SavedJobLifecycleTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="lc_emp", email="lc_emp@example.com")
        self.category = make_category(name="LC Cat", slug="lc-cat")
        self.location = make_location(name="LC Loc", slug="lc-loc")
        self.cand = make_jobseeker(username="lc_cand", email="lc_cand@example.com")
        today = timezone.localdate()

        self.open_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Open Position",
            description="Active role.",
            application_deadline=today + timedelta(days=10),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.expired_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Expired Position",
            description="Old role.",
            application_deadline=today - timedelta(days=2),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now() - timedelta(days=30),
        )
        self.closed_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Closed Position",
            description="Filled role.",
            application_deadline=today + timedelta(days=5),
            status=Job.Status.CLOSED,
            published_at=timezone.now() - timedelta(days=10),
        )
        self.client.force_login(self.cand)

    def test_expired_saved_job_remains_visible_with_expired_badge(self):
        SavedJob.objects.create(jobseeker=self.cand.jobseeker_profile, job=self.expired_job)
        response = self.client.get(reverse("saved_job_list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Expired Position", content)
        self.assertIn("Expired", content)

    def test_closed_saved_job_remains_visible_with_closed_badge(self):
        SavedJob.objects.create(jobseeker=self.cand.jobseeker_profile, job=self.closed_job)
        response = self.client.get(reverse("saved_job_list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Closed Position", content)
        self.assertIn("Closed", content)

    def test_draft_or_unapproved_saved_job_displays_unavailable_badge(self):
        draft_job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Secret Draft Position",
            description="Draft role.",
            application_deadline=timezone.localdate() + timedelta(days=10),
            status=Job.Status.DRAFT,
        )
        SavedJob.objects.create(jobseeker=self.cand.jobseeker_profile, job=draft_job)
        response = self.client.get(reverse("saved_job_list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Secret Draft Position", content)
        self.assertIn("Unavailable", content)

    def test_open_saved_job_is_actionable(self):
        SavedJob.objects.create(jobseeker=self.cand.jobseeker_profile, job=self.open_job)
        response = self.client.get(reverse("saved_job_list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Open Position", content)
        self.assertIn("Open", content)
        self.assertIn("Apply Now", content)
        self.assertIn("View Job", content)

    def test_candidate_can_unsave_expired_or_closed_job(self):
        saved = SavedJob.objects.create(jobseeker=self.cand.jobseeker_profile, job=self.closed_job)
        response = self.client.post(reverse("toggle_save_job", args=[self.closed_job.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SavedJob.objects.filter(pk=saved.pk).exists())
        self.assertEqual(response.url, reverse("saved_job_list"))


class SavedJobListViewTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="lv_emp", email="lv_emp@example.com")
        self.category = make_category(name="LV Cat", slug="lv-cat")
        self.location = make_location(name="LV Loc", slug="lv-loc")
        self.cand = make_jobseeker(username="lv_cand", email="lv_cand@example.com")
        today = timezone.localdate()

        self.job1 = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="React Developer",
            description="Frontend role.",
            employment_type=Job.EmploymentType.FULL_TIME,
            salary_min=40000,
            salary_max=60000,
            application_deadline=today + timedelta(days=7),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.job2 = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Django Developer",
            description="Backend role.",
            employment_type=Job.EmploymentType.CONTRACT,
            salary_min=50000,
            salary_max=80000,
            application_deadline=today - timedelta(days=1),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now() - timedelta(days=15),
        )
        self.client.force_login(self.cand)

    def test_saved_job_list_renders_all_required_details(self):
        SavedJob.objects.create(jobseeker=self.cand.jobseeker_profile, job=self.job1)
        response = self.client.get(reverse("saved_job_list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("My Saved Jobs", content)
        self.assertIn("Browse Jobs", content)
        self.assertIn("React Developer", content)
        self.assertIn(self.employer.company_name, content)
        self.assertIn(self.location.name, content)
        self.assertIn("Full-time", content)
        self.assertIn("Rs. 40,000 – Rs. 60,000", content)
        self.assertIn("Open", content)
        self.assertIn("Unsave", content)

    def test_status_filters_all_open_and_closed(self):
        SavedJob.objects.create(jobseeker=self.cand.jobseeker_profile, job=self.job1)
        SavedJob.objects.create(jobseeker=self.cand.jobseeker_profile, job=self.job2)

        # All filter
        response_all = self.client.get(reverse("saved_job_list"), {"status": "all"})
        self.assertEqual(response_all.status_code, 200)
        self.assertEqual(len(response_all.context["saved_jobs"]), 2)

        # Open filter
        response_open = self.client.get(reverse("saved_job_list"), {"status": "open"})
        self.assertEqual(response_open.status_code, 200)
        self.assertEqual(len(response_open.context["saved_jobs"]), 1)
        self.assertEqual(response_open.context["saved_jobs"][0].job, self.job1)

        # Closed filter
        response_closed = self.client.get(reverse("saved_job_list"), {"status": "closed"})
        self.assertEqual(response_closed.status_code, 200)
        self.assertEqual(len(response_closed.context["saved_jobs"]), 1)
        self.assertEqual(response_closed.context["saved_jobs"][0].job, self.job2)

    def test_pagination_and_query_param_preservation(self):
        today = timezone.localdate()
        for i in range(12):
            j = Job.objects.create(
                employer=self.employer,
                category=self.category,
                location=self.location,
                title=f"Paged Job {i}",
                description="Paged desc.",
                application_deadline=today + timedelta(days=10),
                status=Job.Status.PUBLISHED,
                published_at=timezone.now(),
            )
            SavedJob.objects.create(jobseeker=self.cand.jobseeker_profile, job=j)

        response_p1 = self.client.get(reverse("saved_job_list"), {"status": "open", "page": 1})
        self.assertEqual(response_p1.status_code, 200)
        self.assertEqual(len(response_p1.context["saved_jobs"]), 10)
        self.assertTrue(response_p1.context["page_obj"].has_next())
        content_p1 = response_p1.content.decode()
        self.assertIn("status=open&page=2", content_p1)

        response_p2 = self.client.get(reverse("saved_job_list"), {"status": "open", "page": 2})
        self.assertEqual(response_p2.status_code, 200)
        self.assertEqual(len(response_p2.context["saved_jobs"]), 2)

    def test_already_applied_indicator_and_link(self):
        SavedJob.objects.create(jobseeker=self.cand.jobseeker_profile, job=self.job1)
        app = Application.objects.create(
            job=self.job1,
            jobseeker=self.cand.jobseeker_profile,
            cover_letter="Cover letter text",
        )
        response = self.client.get(reverse("saved_job_list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Already Applied", content)
        self.assertIn(reverse("jobseeker_application_detail", args=[app.pk]), content)
        self.assertIn("View Application", content)

    def test_saved_job_list_empty_state(self):
        response = self.client.get(reverse("saved_job_list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("No Saved Jobs Found", content)
        self.assertIn("Browse Jobs", content)


class SavedJobDiscoveryIntegrationTests(TestCase):
    def setUp(self):
        self.employer = make_approved_employer(username="disc_emp", email="disc_emp@example.com")
        self.category = make_category(name="Disc Cat", slug="disc-cat")
        self.location = make_location(name="Disc Loc", slug="disc-loc")
        self.cand = make_jobseeker(username="disc_cand", email="disc_cand@example.com")
        self.job = Job.objects.create(
            employer=self.employer,
            category=self.category,
            location=self.location,
            title="Fullstack Developer",
            description="Exciting role.",
            application_deadline=timezone.localdate() + timedelta(days=14),
            status=Job.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.detail_url = reverse("job_detail", args=[self.job.pk])
        self.list_url = reverse("job_list")

    def test_job_detail_shows_save_button_when_unsaved(self):
        self.client.force_login(self.cand)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Save Job", content)
        self.assertIn(reverse("toggle_save_job", args=[self.job.pk]), content)

    def test_job_detail_shows_saved_button_when_saved(self):
        SavedJob.objects.create(jobseeker=self.cand.jobseeker_profile, job=self.job)
        self.client.force_login(self.cand)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Saved", content)
        self.assertIn(reverse("toggle_save_job", args=[self.job.pk]), content)

    def test_job_detail_shows_login_link_for_anonymous(self):
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Save Job", content)
        self.assertIn(f"{reverse('login')}?next={self.detail_url}", content)

    def test_job_detail_hides_save_button_for_employer(self):
        self.client.force_login(self.employer.user)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(reverse("toggle_save_job", args=[self.job.pk]), content)

    def test_job_list_shows_saved_state_on_cards(self):
        SavedJob.objects.create(jobseeker=self.cand.jobseeker_profile, job=self.job)
        self.client.force_login(self.cand)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.job.pk, response.context["saved_job_ids"])
        content = response.content.decode()
        self.assertIn("Saved", content)

    def test_job_list_hides_save_controls_for_employer(self):
        self.client.force_login(self.employer.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["saved_job_ids"]), 0)
        content = response.content.decode()
        self.assertNotIn(reverse("toggle_save_job", args=[self.job.pk]), content)


class SavedJobAdminTests(TestCase):
    def test_saved_job_admin_registered(self):
        self.assertIn(SavedJob, site._registry)
        admin_instance = site._registry[SavedJob]
        self.assertIsInstance(admin_instance, SavedJobAdmin)
        self.assertEqual(admin_instance.ordering, ("-created_at",))


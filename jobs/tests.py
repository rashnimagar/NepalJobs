from datetime import timedelta

from django import forms
from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from accounts.models import Education, EmployerProfile, Skill, User
from jobs.admin import CategoryAdmin, JobAdmin, LocationAdmin
from jobs.forms import JobForm
from jobs.models import Category, Job, Location


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

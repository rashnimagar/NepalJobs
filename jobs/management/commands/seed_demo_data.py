"""
Management command to seed deterministic, idempotent demo data for NepalJobs.

Safe for repeated runs: creates or updates only demo records without
modifying or deleting any non-demo data.
"""

from datetime import timedelta
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    CV,
    Education,
    EmployerProfile,
    Experience,
    JobseekerProfile,
    Skill,
    User,
)
from applications.models import Application, Interview
from jobs.models import Category, Job, Location, SavedJob
from notifications.models import Notification

DEMO_PASSWORD = "NepalJobsDemo123!"


class Command(BaseCommand):
    help = "Seeds deterministic, idempotent demo data for NepalJobs."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding NepalJobs demo dataset..."))

        with transaction.atomic():
            # 1. Skills
            skills = self._seed_skills()

            # 2. Categories
            categories = self._seed_categories()

            # 3. Locations
            locations = self._seed_locations()

            # 4. Users & Profiles
            admin_user = self._seed_admin()
            employers = self._seed_employers()
            jobseekers = self._seed_jobseekers(skills)

            # 5. Jobs
            jobs = self._seed_jobs(employers, categories, locations, skills)

            # 6. Applications
            applications = self._seed_applications(jobs, jobseekers)

            # 7. Interviews
            interviews = self._seed_interviews(applications, employers)

            # 8. Notifications
            notifications = self._seed_notifications(applications, employers, jobseekers, jobs)

            # 9. Saved Jobs
            saved_jobs = self._seed_saved_jobs(jobseekers, jobs)

        self.stdout.write(self.style.SUCCESS("\nDemo data seeded successfully.\n"))

        # Structured Summary Output
        self.stdout.write(self.style.MIGRATE_HEADING("Users:"))
        self.stdout.write(f"- Admin: {admin_user.username} ({admin_user.email})")
        for emp_key, emp_user, _ in employers:
            self.stdout.write(f"- Employer: {emp_user.username} ({emp_user.email})")
        for js_key, js_user, _ in jobseekers:
            self.stdout.write(f"- Jobseeker: {js_user.username} ({js_user.email})")

        self.stdout.write(self.style.MIGRATE_HEADING("\nEmployers:"))
        for _, _, emp_prof in employers:
            self.stdout.write(f"- {emp_prof.company_name} ({emp_prof.get_verification_status_display()}, {emp_prof.industry})")

        self.stdout.write(self.style.MIGRATE_HEADING("\nJobseekers:"))
        for _, js_user, js_prof in jobseekers:
            self.stdout.write(f"- {js_user.get_full_name()} ({js_prof.location} - {js_prof.summary[:50]}...)")

        self.stdout.write(self.style.MIGRATE_HEADING("\nCategories:"))
        for cat in categories.values():
            self.stdout.write(f"- {cat.name}")

        self.stdout.write(self.style.MIGRATE_HEADING("\nLocations:"))
        for loc in locations.values():
            rem = " [Remote Allowed]" if loc.is_remote else ""
            self.stdout.write(f"- {loc.name}{rem}")

        self.stdout.write(self.style.MIGRATE_HEADING("\nJobs:"))
        for j in jobs.values():
            self.stdout.write(f"- [{j.get_status_display()}] {j.title} ({j.employer.company_name})")

        self.stdout.write(self.style.MIGRATE_HEADING("\nApplications:"))
        for app in applications.values():
            self.stdout.write(f"- {app.jobseeker.user.get_full_name()} -> {app.job.title} [{app.get_status_display()}]")

        self.stdout.write(self.style.MIGRATE_HEADING("\nInterviews:"))
        for iv in interviews:
            self.stdout.write(f"- [{iv.get_status_display()}] {iv.get_interview_type_display()} for {iv.application.jobseeker.user.get_full_name()} ({iv.application.job.title})")

        self.stdout.write(self.style.MIGRATE_HEADING("\nNotifications:"))
        for n in notifications:
            read_status = "Read" if n.is_read else "Unread"
            self.stdout.write(f"- [{read_status}] {n.title} -> {n.recipient.username}")

        self.stdout.write(self.style.MIGRATE_HEADING("\nSaved Jobs:"))
        for sj in saved_jobs:
            self.stdout.write(f"- {sj.jobseeker.user.get_full_name()} saved {sj.job.title}")

        self.stdout.write(self.style.WARNING("\nDemo Credentials (DEMO ONLY - Do not use in production):"))
        self.stdout.write(f"- Password for all demo accounts: {DEMO_PASSWORD}")
        self.stdout.write(f"- Admin: {admin_user.username}")
        for _, emp_user, _ in employers:
            self.stdout.write(f"- Employer: {emp_user.username}")
        for _, js_user, _ in jobseekers:
            self.stdout.write(f"- Jobseeker: {js_user.username}")

    def _seed_skills(self):
        skill_names = [
            "python",
            "django",
            "postgresql",
            "javascript",
            "react",
            "ui/ux",
            "figma",
            "accounting",
            "financial reporting",
            "data analysis",
            "recruitment",
            "content marketing",
        ]
        skills = {}
        for name in skill_names:
            skill, _ = Skill.objects.get_or_create(name=name)
            skills[name] = skill
        return skills

    def _seed_categories(self):
        cat_definitions = [
            ("Software Development", "software-development", "Software engineering, backend systems, and cloud development."),
            ("Web Development", "web-development", "Frontend, full-stack, and modern web application development."),
            ("Marketing & Communications", "marketing-communications", "Digital marketing, brand strategy, and public relations."),
            ("Finance & Accounting", "finance-accounting", "Corporate finance, auditing, accounting, and financial planning."),
            ("Human Resources", "human-resources", "Talent management, people operations, and employee engagement."),
            ("Design & Creative", "design-creative", "UI/UX design, visual branding, and digital creative direction."),
        ]
        categories = {}
        for name, slug, desc in cat_definitions:
            cat, _ = Category.objects.update_or_create(
                slug=slug,
                defaults={"name": name, "description": desc, "is_active": True},
            )
            categories[slug] = cat
        return categories

    def _seed_locations(self):
        loc_definitions = [
            ("Kathmandu", "kathmandu", False),
            ("Lalitpur", "lalitpur", False),
            ("Bhaktapur", "bhaktapur", False),
            ("Remote (Nepal)", "remote-nepal", True),
        ]
        locations = {}
        for name, slug, is_rem in loc_definitions:
            loc, _ = Location.objects.update_or_create(
                slug=slug,
                defaults={"name": name, "is_remote": is_rem},
            )
            locations[slug] = loc
        return locations

    def _seed_admin(self):
        admin_user = User.objects.filter(username="demo_admin").first()
        if not admin_user:
            admin_user = User.objects.create_superuser(
                username="demo_admin",
                email="admin@nepaljobs.demo",
                password=DEMO_PASSWORD,
            )
            admin_user.first_name = "System"
            admin_user.last_name = "Admin"
            admin_user.save()
        else:
            admin_user.email = "admin@nepaljobs.demo"
            admin_user.is_staff = True
            admin_user.is_superuser = True
            admin_user.set_password(DEMO_PASSWORD)
            admin_user.save()
        return admin_user

    def _seed_employers(self):
        employer_configs = [
            {
                "key": "tech",
                "username": "demo_emp_tech",
                "email": "employer.tech@nepaljobs.demo",
                "first_name": "Aayush",
                "last_name": "Sharma",
                "company_name": "Himalayan Tech Solutions",
                "industry": "Software & IT Services",
                "phone": "+977-1-4432100",
                "address": "Tinkune, Kathmandu",
                "website": "https://himalayantech.example.com",
                "description": "Leading Nepali software engineering firm delivering cloud and web applications across South Asia.",
            },
            {
                "key": "fin",
                "username": "demo_emp_fin",
                "email": "employer.fin@nepaljobs.demo",
                "first_name": "Sunita",
                "last_name": "Pradhan",
                "company_name": "Everest Financial Group",
                "industry": "Banking & FinTech",
                "phone": "+977-1-5521000",
                "address": "Pulchowk, Lalitpur",
                "website": "https://everestfinance.example.com",
                "description": "Modern financial institution providing digital corporate banking and analytics services.",
            },
        ]

        employers = []
        for cfg in employer_configs:
            user = User.objects.filter(username=cfg["username"]).first()
            if not user:
                user = User.objects.create_user(
                    username=cfg["username"],
                    email=cfg["email"],
                    password=DEMO_PASSWORD,
                    role=User.Role.EMPLOYER,
                    first_name=cfg["first_name"],
                    last_name=cfg["last_name"],
                )
            else:
                user.email = cfg["email"]
                user.role = User.Role.EMPLOYER
                user.first_name = cfg["first_name"]
                user.last_name = cfg["last_name"]
                user.set_password(DEMO_PASSWORD)
                user.save()

            profile, _ = EmployerProfile.objects.update_or_create(
                user=user,
                defaults={
                    "company_name": cfg["company_name"],
                    "industry": cfg["industry"],
                    "phone": cfg["phone"],
                    "address": cfg["address"],
                    "website": cfg["website"],
                    "description": cfg["description"],
                    "verification_status": EmployerProfile.VerificationStatus.APPROVED,
                    "reviewed_at": timezone.now(),
                    "rejection_reason": "",
                },
            )
            employers.append((cfg["key"], user, profile))

        return employers

    def _seed_jobseekers(self, skills):
        jobseeker_configs = [
            {
                "key": "ram",
                "username": "demo_js_ram",
                "email": "ram.shrestha@nepaljobs.demo",
                "first_name": "Ram",
                "last_name": "Shrestha",
                "phone": "+977-9841234567",
                "location": "Kathmandu",
                "summary": "Full-stack Python and Django developer with 4 years of hands-on experience building scalable web solutions.",
                "skills": [skills["python"], skills["django"], skills["postgresql"], skills["javascript"]],
                "educations": [
                    {
                        "level": Education.Level.BACHELOR,
                        "degree": "B.Sc. Computer Science and Information Technology",
                        "institution": "Tribhuvan University",
                        "field_of_study": "Computer Science",
                        "start_year": 2017,
                        "end_year": 2021,
                        "is_ongoing": False,
                    }
                ],
                "experiences": [
                    {
                        "job_title": "Software Engineer",
                        "company": "Valley Code Labs",
                        "location": "Kathmandu",
                        "start_date": timezone.localdate() - timedelta(days=730),
                        "end_date": None,
                        "is_current": True,
                        "description": "Architecting backend services and REST APIs with Django and PostgreSQL.",
                    }
                ],
            },
            {
                "key": "sita",
                "username": "demo_js_sita",
                "email": "sita.thapa@nepaljobs.demo",
                "first_name": "Sita",
                "last_name": "Thapa",
                "phone": "+977-9851234567",
                "location": "Lalitpur",
                "summary": "UI/UX product designer and frontend specialist passionate about human-centered design and accessible interfaces.",
                "skills": [skills["ui/ux"], skills["figma"], skills["react"], skills["javascript"]],
                "educations": [
                    {
                        "level": Education.Level.BACHELOR,
                        "degree": "Bachelor of Information Management",
                        "institution": "Kathmandu University",
                        "field_of_study": "Information Management",
                        "start_year": 2018,
                        "end_year": 2022,
                        "is_ongoing": False,
                    }
                ],
                "experiences": [
                    {
                        "job_title": "UI/UX Designer",
                        "company": "PixelCraft Studios",
                        "location": "Lalitpur",
                        "start_date": timezone.localdate() - timedelta(days=600),
                        "end_date": None,
                        "is_current": True,
                        "description": "Creating design systems, prototypes, and user flows in Figma.",
                    }
                ],
            },
            {
                "key": "kiran",
                "username": "demo_js_kiran",
                "email": "kiran.adhikari@nepaljobs.demo",
                "first_name": "Kiran",
                "last_name": "Adhikari",
                "phone": "+977-9861234567",
                "location": "Bhaktapur",
                "summary": "Finance professional and business analyst experienced in corporate financial modeling and reporting.",
                "skills": [skills["accounting"], skills["financial reporting"], skills["data analysis"]],
                "educations": [
                    {
                        "level": Education.Level.MASTER,
                        "degree": "Master of Business Studies (Finance)",
                        "institution": "Tribhuvan University",
                        "field_of_study": "Corporate Finance",
                        "start_year": 2020,
                        "end_year": 2022,
                        "is_ongoing": False,
                    }
                ],
                "experiences": [
                    {
                        "job_title": "Financial Analyst",
                        "company": "Himalayan Capital Partners",
                        "location": "Kathmandu",
                        "start_date": timezone.localdate() - timedelta(days=500),
                        "end_date": None,
                        "is_current": True,
                        "description": "Financial modeling, quarterly valuation reports, and audit reconciliation.",
                    }
                ],
            },
        ]

        jobseekers = []
        for cfg in jobseeker_configs:
            user = User.objects.filter(username=cfg["username"]).first()
            if not user:
                user = User.objects.create_user(
                    username=cfg["username"],
                    email=cfg["email"],
                    password=DEMO_PASSWORD,
                    role=User.Role.JOBSEEKER,
                    first_name=cfg["first_name"],
                    last_name=cfg["last_name"],
                )
            else:
                user.email = cfg["email"]
                user.role = User.Role.JOBSEEKER
                user.first_name = cfg["first_name"]
                user.last_name = cfg["last_name"]
                user.set_password(DEMO_PASSWORD)
                user.save()

            profile, _ = JobseekerProfile.objects.update_or_create(
                user=user,
                defaults={
                    "phone": cfg["phone"],
                    "location": cfg["location"],
                    "summary": cfg["summary"],
                },
            )
            profile.skills.set(cfg["skills"])

            # Deterministic default CV
            cv = profile.cvs.filter(title="Professional Resume").first()
            if not cv:
                cv = CV.objects.create(
                    profile=profile,
                    title="Professional Resume",
                    file=ContentFile(
                        b"%PDF-1.4 Demo curriculum vitae for " + user.get_full_name().encode(),
                        name=f"{user.username}_resume.pdf",
                    ),
                    original_filename=f"{user.username}_resume.pdf",
                    is_default=True,
                    is_active=True,
                )

            # Education
            for edu in cfg["educations"]:
                Education.objects.update_or_create(
                    profile=profile,
                    degree=edu["degree"],
                    defaults={
                        "level": edu["level"],
                        "institution": edu["institution"],
                        "field_of_study": edu["field_of_study"],
                        "start_year": edu["start_year"],
                        "end_year": edu["end_year"],
                        "is_ongoing": edu["is_ongoing"],
                    },
                )

            # Experience
            for exp in cfg["experiences"]:
                Experience.objects.update_or_create(
                    profile=profile,
                    job_title=exp["job_title"],
                    company=exp["company"],
                    defaults={
                        "location": exp["location"],
                        "start_date": exp["start_date"],
                        "end_date": exp["end_date"],
                        "is_current": exp["is_current"],
                        "description": exp["description"],
                    },
                )

            jobseekers.append((cfg["key"], user, profile))

        return jobseekers

    def _seed_jobs(self, employers, categories, locations, skills):
        emp_dict = {key: prof for key, _, prof in employers}
        today = timezone.localdate()

        job_configs = [
            # Job 1: Published, Remote, Salary Range
            {
                "key": "job_python",
                "employer": emp_dict["tech"],
                "title": "Senior Full-Stack Python Developer",
                "category": categories["software-development"],
                "location": locations["kathmandu"],
                "is_remote": True,
                "employment_type": Job.EmploymentType.FULL_TIME,
                "salary_min": 120000,
                "salary_max": 180000,
                "is_salary_negotiable": False,
                "experience_years_min": 4,
                "education_level": Education.Level.BACHELOR,
                "vacancies": 2,
                "application_deadline": today + timedelta(days=30),
                "status": Job.Status.PUBLISHED,
                "skills": [skills["python"], skills["django"], skills["postgresql"]],
                "description": "We are seeking a seasoned Senior Full-Stack Python Developer to lead development on enterprise web applications.",
                "responsibilities": "Design scalable system architectures, review merge requests, and mentor junior engineers.",
            },
            # Job 2: Published, Negotiable Salary
            {
                "key": "job_uiux",
                "employer": emp_dict["tech"],
                "title": "UI/UX Product Designer",
                "category": categories["design-creative"],
                "location": locations["lalitpur"],
                "is_remote": True,
                "employment_type": Job.EmploymentType.FULL_TIME,
                "salary_min": None,
                "salary_max": None,
                "is_salary_negotiable": True,
                "experience_years_min": 2,
                "education_level": Education.Level.BACHELOR,
                "vacancies": 1,
                "application_deadline": today + timedelta(days=25),
                "status": Job.Status.PUBLISHED,
                "skills": [skills["ui/ux"], skills["figma"]],
                "description": "Looking for a creative and detail-oriented UI/UX Product Designer to design intuitive digital products.",
                "responsibilities": "Conduct user research, design wireframes and high-fidelity mockups, and build unified design systems.",
            },
            # Job 3: Published, Contract, Remote Location
            {
                "key": "job_react",
                "employer": emp_dict["tech"],
                "title": "Frontend React Engineer",
                "category": categories["web-development"],
                "location": locations["remote-nepal"],
                "is_remote": True,
                "employment_type": Job.EmploymentType.CONTRACT,
                "salary_min": 90000,
                "salary_max": 130000,
                "is_salary_negotiable": False,
                "experience_years_min": 3,
                "education_level": Education.Level.BACHELOR,
                "vacancies": 1,
                "application_deadline": today + timedelta(days=20),
                "status": Job.Status.PUBLISHED,
                "skills": [skills["react"], skills["javascript"]],
                "description": "Join our distributed engineering crew as a Frontend React Engineer building performant interactive dashboards.",
                "responsibilities": "Implement responsive component hierarchies, optimize Core Web Vitals, and integrate GraphQL/REST APIs.",
            },
            # Job 4: Draft Job
            {
                "key": "job_devops",
                "employer": emp_dict["tech"],
                "title": "DevOps & Cloud Engineer",
                "category": categories["software-development"],
                "location": locations["kathmandu"],
                "is_remote": False,
                "employment_type": Job.EmploymentType.FULL_TIME,
                "salary_min": 140000,
                "salary_max": 200000,
                "is_salary_negotiable": False,
                "experience_years_min": 3,
                "education_level": Education.Level.BACHELOR,
                "vacancies": 1,
                "application_deadline": today + timedelta(days=45),
                "status": Job.Status.DRAFT,
                "skills": [skills["python"]],
                "description": "Upcoming opening for an experienced DevOps engineer to streamline our containerized deployment pipelines.",
                "responsibilities": "Manage Kubernetes clusters, automate CI/CD pipelines, and implement cloud observability.",
            },
            # Job 5: Published, Finance, Salary Range + Negotiable
            {
                "key": "job_finance",
                "employer": emp_dict["fin"],
                "title": "Senior Financial Analyst",
                "category": categories["finance-accounting"],
                "location": locations["kathmandu"],
                "is_remote": False,
                "employment_type": Job.EmploymentType.FULL_TIME,
                "salary_min": 75000,
                "salary_max": 110000,
                "is_salary_negotiable": True,
                "experience_years_min": 3,
                "education_level": Education.Level.MASTER,
                "vacancies": 2,
                "application_deadline": today + timedelta(days=28),
                "status": Job.Status.PUBLISHED,
                "skills": [skills["accounting"], skills["financial reporting"], skills["data analysis"]],
                "description": "Everest Financial Group is hiring a Senior Financial Analyst to lead strategic commercial evaluations.",
                "responsibilities": "Develop financial models, prepare board valuation packages, and monitor portfolio performance indicators.",
            },
            # Job 6: Published, HR
            {
                "key": "job_hr",
                "employer": emp_dict["fin"],
                "title": "Corporate HR Specialist",
                "category": categories["human-resources"],
                "location": locations["lalitpur"],
                "is_remote": False,
                "employment_type": Job.EmploymentType.FULL_TIME,
                "salary_min": 50000,
                "salary_max": 75000,
                "is_salary_negotiable": False,
                "experience_years_min": 2,
                "education_level": Education.Level.BACHELOR,
                "vacancies": 1,
                "application_deadline": today + timedelta(days=21),
                "status": Job.Status.PUBLISHED,
                "skills": [skills["recruitment"]],
                "description": "Seeking an HR professional to coordinate end-to-end recruitment pipelines and team development.",
                "responsibilities": "Manage candidate interviewing schedules, coordinate onboarding programs, and oversee workplace compliance.",
            },
            # Job 7: Closed Job
            {
                "key": "job_accounts",
                "employer": emp_dict["fin"],
                "title": "Junior Accounts Assistant",
                "category": categories["finance-accounting"],
                "location": locations["bhaktapur"],
                "is_remote": False,
                "employment_type": Job.EmploymentType.FULL_TIME,
                "salary_min": 35000,
                "salary_max": 45000,
                "is_salary_negotiable": False,
                "experience_years_min": 1,
                "education_level": Education.Level.BACHELOR,
                "vacancies": 1,
                "application_deadline": today - timedelta(days=5),
                "status": Job.Status.CLOSED,
                "skills": [skills["accounting"]],
                "description": "Entry-level position for an accounts assistant to support billing cycles and ledger reconciliation.",
                "responsibilities": "Process vendor payments, maintain petty cash records, and assist with month-end reporting.",
            },
        ]

        jobs = {}
        for cfg in job_configs:
            job = Job.objects.filter(employer=cfg["employer"], title=cfg["title"]).first()
            if not job:
                job = Job(
                    employer=cfg["employer"],
                    title=cfg["title"],
                    category=cfg["category"],
                    location=cfg["location"],
                    is_remote=cfg["is_remote"],
                    employment_type=cfg["employment_type"],
                    salary_min=cfg["salary_min"],
                    salary_max=cfg["salary_max"],
                    is_salary_negotiable=cfg["is_salary_negotiable"],
                    experience_years_min=cfg["experience_years_min"],
                    education_level=cfg["education_level"],
                    vacancies=cfg["vacancies"],
                    application_deadline=cfg["application_deadline"],
                    status=cfg["status"],
                    description=cfg["description"],
                    responsibilities=cfg["responsibilities"],
                    published_at=timezone.now() if cfg["status"] == Job.Status.PUBLISHED else None,
                )
                job.save()
            else:
                job.category = cfg["category"]
                job.location = cfg["location"]
                job.is_remote = cfg["is_remote"]
                job.employment_type = cfg["employment_type"]
                job.salary_min = cfg["salary_min"]
                job.salary_max = cfg["salary_max"]
                job.is_salary_negotiable = cfg["is_salary_negotiable"]
                job.experience_years_min = cfg["experience_years_min"]
                job.education_level = cfg["education_level"]
                job.vacancies = cfg["vacancies"]
                job.application_deadline = cfg["application_deadline"]
                job.status = cfg["status"]
                job.description = cfg["description"]
                job.responsibilities = cfg["responsibilities"]
                if cfg["status"] == Job.Status.PUBLISHED and not job.published_at:
                    job.published_at = timezone.now()
                job.save()

            if cfg["skills"]:
                job.required_skills.set(cfg["skills"])

            jobs[cfg["key"]] = job

        return jobs

    def _seed_applications(self, jobs, jobseekers):
        js_dict = {key: prof for key, _, prof in jobseekers}

        # Transition maps honoring Application.VALID_TRANSITIONS
        # APPLIED -> UNDER_REVIEW -> SHORTLISTED -> INTERVIEW -> SELECTED
        # or APPLIED -> REJECTED
        app_configs = [
            # App 1: Ram -> Python Job [Final: INTERVIEW]
            {
                "key": "app_ram_python",
                "job": jobs["job_python"],
                "jobseeker": js_dict["ram"],
                "target_status": Application.Status.INTERVIEW,
                "cover_letter": "I have extensive experience with Django and high-load web systems and would love to contribute to Himalayan Tech.",
            },
            # App 2: Ram -> React Job [Final: UNDER_REVIEW]
            {
                "key": "app_ram_react",
                "job": jobs["job_react"],
                "jobseeker": js_dict["ram"],
                "target_status": Application.Status.UNDER_REVIEW,
                "cover_letter": "My full-stack background gives me a solid foundation for React and frontend architecture.",
            },
            # App 3: Sita -> UI/UX Job [Final: SELECTED]
            {
                "key": "app_sita_uiux",
                "job": jobs["job_uiux"],
                "jobseeker": js_dict["sita"],
                "target_status": Application.Status.SELECTED,
                "cover_letter": "I specialize in Figma design systems and user-centric interfaces. Excited about the vision at Himalayan Tech.",
            },
            # App 4: Sita -> React Job [Final: SHORTLISTED]
            {
                "key": "app_sita_react",
                "job": jobs["job_react"],
                "jobseeker": js_dict["sita"],
                "target_status": Application.Status.SHORTLISTED,
                "cover_letter": "I bridge the gap between Figma designs and React component implementation with clean CSS and markup.",
            },
            # App 5: Kiran -> Finance Job [Final: APPLIED]
            {
                "key": "app_kiran_finance",
                "job": jobs["job_finance"],
                "jobseeker": js_dict["kiran"],
                "target_status": Application.Status.APPLIED,
                "cover_letter": "With a Master's degree in corporate finance and hands-on valuation experience, I am well suited for this role.",
            },
            # App 6: Kiran -> HR Job [Final: REJECTED]
            {
                "key": "app_kiran_hr",
                "job": jobs["job_hr"],
                "jobseeker": js_dict["kiran"],
                "target_status": Application.Status.REJECTED,
                "cover_letter": "Exploring general business opportunities at Everest Financial Group.",
                "rejection_notes": "Profile qualifications align with corporate finance rather than HR operations.",
            },
        ]

        transition_sequences = {
            Application.Status.APPLIED: [],
            Application.Status.UNDER_REVIEW: [Application.Status.UNDER_REVIEW],
            Application.Status.SHORTLISTED: [Application.Status.UNDER_REVIEW, Application.Status.SHORTLISTED],
            Application.Status.INTERVIEW: [
                Application.Status.UNDER_REVIEW,
                Application.Status.SHORTLISTED,
                Application.Status.INTERVIEW,
            ],
            Application.Status.SELECTED: [
                Application.Status.UNDER_REVIEW,
                Application.Status.SHORTLISTED,
                Application.Status.INTERVIEW,
                Application.Status.SELECTED,
            ],
            Application.Status.REJECTED: [Application.Status.REJECTED],
        }

        applications = {}
        for cfg in app_configs:
            app = Application.objects.filter(job=cfg["job"], jobseeker=cfg["jobseeker"]).first()
            if not app:
                cv = cfg["jobseeker"].cvs.filter(is_active=True).first()
                app = Application.objects.create(
                    job=cfg["job"],
                    jobseeker=cfg["jobseeker"],
                    cv=cv,
                    cover_letter=cfg["cover_letter"],
                    status=Application.Status.APPLIED,
                )
                steps = transition_sequences.get(cfg["target_status"], [])
                for step in steps:
                    notes = cfg.get("rejection_notes", "") if step == Application.Status.REJECTED else ""
                    app.transition_to(step, changed_by=cfg["job"].employer.user, notes=notes)

            applications[cfg["key"]] = app

        return applications

    def _seed_interviews(self, applications, employers):
        emp_dict = {key: user for key, user, _ in employers}
        interviews = []

        # 1. Upcoming Scheduled Interview for Ram (Senior Full-Stack Python Developer)
        app_ram = applications["app_ram_python"]
        iv_ram = Interview.objects.filter(
            application=app_ram,
            interview_type=Interview.InterviewType.VIDEO,
        ).first()

        if not iv_ram:
            iv_ram = Interview.objects.create(
                application=app_ram,
                interview_type=Interview.InterviewType.VIDEO,
                status=Interview.InterviewStatus.SCHEDULED,
                scheduled_at=timezone.now() + timedelta(days=3, hours=2),
                duration_minutes=45,
                location_or_link="https://meet.google.com/nepaljobs-demo-interview",
                candidate_instructions="Please join 5 minutes early with your camera enabled and code samples available.",
                internal_notes="Focus on Python asynchronous patterns, Django ORM optimization, and system design.",
                created_by=emp_dict["tech"],
            )
        interviews.append(iv_ram)

        # 2. Completed Interview for Sita (UI/UX Product Designer)
        app_sita = applications["app_sita_uiux"]
        iv_sita = Interview.objects.filter(
            application=app_sita,
            interview_type=Interview.InterviewType.IN_PERSON,
        ).first()

        if not iv_sita:
            iv_sita = Interview(
                application=app_sita,
                interview_type=Interview.InterviewType.IN_PERSON,
                status=Interview.InterviewStatus.COMPLETED,
                scheduled_at=timezone.now() - timedelta(days=2),
                duration_minutes=60,
                location_or_link="Himalayan Tech Solutions HQ, Tinkune, Kathmandu - Meeting Room B",
                candidate_instructions="Please bring an identification card for building entry.",
                internal_notes="[Outcome]: Candidate presented an outstanding portfolio and clear design thinking process. Strongly recommended for hire.",
                created_by=emp_dict["tech"],
            )
            iv_sita.save()
        interviews.append(iv_sita)

        return interviews

    def _seed_notifications(self, applications, employers, jobseekers, jobs):
        js_user_dict = {key: user for key, user, _ in jobseekers}
        emp_user_dict = {key: user for key, user, _ in employers}

        notifications = []

        notif_configs = [
            # Ram: Unread Interview Scheduled
            {
                "recipient": js_user_dict["ram"],
                "notification_type": Notification.NotificationType.INTERVIEW_SCHEDULED,
                "title": "Interview Scheduled",
                "message": f'An interview for "{jobs["job_python"].title}" has been scheduled.',
                "target_url": reverse("jobseeker_application_detail", kwargs={"pk": applications["app_ram_python"].pk}),
                "application": applications["app_ram_python"],
                "is_read": False,
                "read_at": None,
            },
            # Ram: Read Application Status Update
            {
                "recipient": js_user_dict["ram"],
                "notification_type": Notification.NotificationType.APPLICATION_STATUS_CHANGED,
                "title": "Application Status Updated",
                "message": f'Your application for "{jobs["job_react"].title}" has moved to Under Review.',
                "target_url": reverse("jobseeker_application_detail", kwargs={"pk": applications["app_ram_react"].pk}),
                "application": applications["app_ram_react"],
                "is_read": True,
                "read_at": timezone.now() - timedelta(days=1),
            },
            # Employer Tech: Read New Applicant
            {
                "recipient": emp_user_dict["tech"],
                "notification_type": Notification.NotificationType.NEW_APPLICANT,
                "title": "New Applicant",
                "message": f'A new candidate applied for "{jobs["job_python"].title}".',
                "target_url": reverse("employer_application_detail", kwargs={"pk": applications["app_ram_python"].pk}),
                "application": applications["app_ram_python"],
                "is_read": True,
                "read_at": timezone.now() - timedelta(days=3),
            },
            # Employer Tech: Unread New Applicant
            {
                "recipient": emp_user_dict["tech"],
                "notification_type": Notification.NotificationType.NEW_APPLICANT,
                "title": "New Applicant",
                "message": f'A new candidate applied for "{jobs["job_uiux"].title}".',
                "target_url": reverse("employer_application_detail", kwargs={"pk": applications["app_sita_uiux"].pk}),
                "application": applications["app_sita_uiux"],
                "is_read": False,
                "read_at": None,
            },
        ]

        for cfg in notif_configs:
            notif, _ = Notification.objects.get_or_create(
                recipient=cfg["recipient"],
                notification_type=cfg["notification_type"],
                application=cfg["application"],
                defaults={
                    "title": cfg["title"],
                    "message": cfg["message"],
                    "target_url": cfg["target_url"],
                    "is_read": cfg["is_read"],
                    "read_at": cfg["read_at"],
                },
            )
            notifications.append(notif)

        return notifications

    def _seed_saved_jobs(self, jobseekers, jobs):
        js_prof_dict = {key: prof for key, _, prof in jobseekers}
        saved_jobs = []

        # Ram saves 2 open jobs
        # Sita saves 1 open job
        # Kiran saves 2 open jobs
        saved_pairs = [
            (js_prof_dict["ram"], jobs["job_python"]),
            (js_prof_dict["ram"], jobs["job_react"]),
            (js_prof_dict["sita"], jobs["job_uiux"]),
            (js_prof_dict["kiran"], jobs["job_finance"]),
            (js_prof_dict["kiran"], jobs["job_hr"]),
        ]

        for js_prof, job in saved_pairs:
            sj, _ = SavedJob.objects.get_or_create(jobseeker=js_prof, job=job)
            saved_jobs.append(sj)

        return saved_jobs

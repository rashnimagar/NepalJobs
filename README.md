# NepalJobs

NepalJobs is a recruitment platform tailored for Nepal's hiring ecosystem. It connects jobseekers with verified employers through a structured job discovery, application, interview scheduling, and recruitment management pipeline.

---

## Technology Stack

* **Language**: Python 3.13
* **Framework**: Django 6.1.1
* **Database**: SQLite3 (default / development)
* **Frontend**: HTML5, Vanilla CSS / Bootstrap 5.3.3
* **Testing**: Django standard test suite (`TestCase`, `Client`)

---

## Major User Roles

1. **Guest / Public**: Browse active published vacancies, search jobs by keyword/category/location, view approved company profiles, register as jobseeker or employer.
2. **Jobseeker**: Manage candidate profile, upload and manage CVs (PDF/DOCX), apply to open jobs with attached CV and optional cover letter, save favorite jobs, track recruitment progress stages in real time, view scheduled interviews, and receive in-app notifications.
3. **Employer**: Manage company profile, submit verification documents, post and manage jobs (`Draft` → `Published` → `Closed`), review applicants across hiring stages, schedule/cancel/complete interviews, add candidate instructions, and track recruitment metrics.
4. **Staff / Administrator**: Manage platform taxonomy (categories, locations), review employer verification requests, oversee jobs, applications, interviews, and users via Django Admin.

---

## High-Level Architecture

* **`accounts`**: Custom `User` model with role enforcement (`JOBSEEKER`, `EMPLOYER`, `ADMIN`), candidate profiles, education, experience, skills, secure CV management, employer verification, and public company profiles.
* **`jobs`**: Job taxonomies (`Category`, `Location`), job model with lifecycle validation (`Draft`, `Published`, `Closed`), salary negotiation, deadlines, and `SavedJob` favorites.
* **`applications`**: Application lifecycle state machine (`Applied` → `Under Review` → `Shortlisted` → `Interview` → `Selected` / `Rejected`), status history auditing, interview scheduling (video, in-person, phone), and applicant management.
* **`notifications`**: In-app notification center for application updates, interview schedules, and applicant events.
* **`config`**: Project settings, environment-driven security, custom error handlers (`403`, `404`, `500`), and URL routing.

---

## Setup & Local Installation

### 1. Clone the repository
```bash
git clone https://github.com/rashnimagar/NepalJobs.git
cd NepalJobs
```

### 2. Create and activate virtual environment
```bash
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment variables (optional)
By default, the application runs in local development mode (`DEBUG=True`). To configure production settings, provide environment variables:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `SECRET_KEY` | Django secret key | Built-in development fallback |
| `DEBUG` | Enable debug mode (`true`/`false`) | `True` |
| `ALLOWED_HOSTS` | Comma-separated list of allowed hostnames | `127.0.0.1,localhost,testserver` |

### 5. Run migrations
```bash
python manage.py migrate
```

### 6. Seed demo dataset (idempotent)
Populate the database with representative demo users, approved employers, published vacancies, applications, and scheduled interviews:
```bash
python manage.py seed_demo_data
```

**Demo Credentials**:
* Password for all demo accounts: `NepalJobsDemo123!`
* Admin: `demo_admin`
* Employers: `demo_emp_tech`, `demo_emp_fin`
* Jobseekers: `demo_js_ram`, `demo_js_sita`, `demo_js_kiran`

### 7. Run the development server
```bash
python manage.py runserver
```
Access the application at `http://127.0.0.1:8000/`.

---

## Running Tests

Execute the automated test suite:
```bash
python manage.py test
```

Verify Django system configuration:
```bash
python manage.py check
python manage.py makemigrations --check
```

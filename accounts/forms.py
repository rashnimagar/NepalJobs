from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import CV, MAX_SKILLS, Education, EmployerProfile, Experience, JobseekerProfile, User


class BootstrapFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs.setdefault("class", css)


class StyledAuthenticationForm(BootstrapFormMixin, AuthenticationForm):
    pass


class JobseekerSignUpForm(BootstrapFormMixin, UserCreationForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.JOBSEEKER
        if commit:
            user.save()
            JobseekerProfile.objects.create(user=user)
        return user


class EmployerSignUpForm(BootstrapFormMixin, UserCreationForm):
    company_name = forms.CharField(max_length=200)
    phone = forms.CharField(max_length=20)
    address = forms.CharField(max_length=255)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.EMPLOYER
        if commit:
            user.save()
            EmployerProfile.objects.create(
                user=user,
                company_name=self.cleaned_data["company_name"],
                phone=self.cleaned_data["phone"],
                address=self.cleaned_data["address"],
            )
        return user

class JobseekerProfileForm(BootstrapFormMixin, forms.ModelForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()

    class Meta:
        model = JobseekerProfile
        fields = ("first_name", "last_name", "email", "phone", "location", "summary")
        widgets = {"summary": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = self.instance.user
        self.initial.update({
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
        })

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.user_id).exists():
            raise forms.ValidationError("This email is already used by another account.")
        return email

    def save(self, commit=True):
        profile = super().save(commit=commit)
        if commit:
            user = profile.user
            user.first_name = self.cleaned_data["first_name"]
            user.last_name = self.cleaned_data["last_name"]
            user.email = self.cleaned_data["email"]
            user.save(update_fields=["first_name", "last_name", "email"])
        return profile


class CVUploadForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CV
        fields = ("title", "file")

class EducationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Education
        fields = ("level", "degree", "institution", "field_of_study",
                  "start_year", "end_year", "is_ongoing")
        labels = {
            "field_of_study": "Field of study (optional)",
            "is_ongoing": "I'm currently studying here",
        }
        widgets = {
            "degree": forms.TextInput(attrs={"placeholder": "e.g. BCA, +2 Science"}),
        }


class ExperienceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Experience
        fields = ("job_title", "company", "location", "start_date",
                  "end_date", "is_current", "description")
        labels = {
            "location": "Location (optional)",
            "description": "What did you do? (optional)",
            "is_current": "I currently work here",
        }
        widgets = {
            "start_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "end_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class SkillsForm(BootstrapFormMixin, forms.Form):
    skills = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "python, django, sql, git"}),
        help_text=f"Separate skills with commas. Up to {MAX_SKILLS} skills.",
    )

    def clean_skills(self):
        names = []
        for part in self.cleaned_data["skills"].split(","):
            name = " ".join(part.split()).lower()
            if name and name not in names:
                names.append(name)
        if len(names) > MAX_SKILLS:
            raise forms.ValidationError(f"Please list at most {MAX_SKILLS} skills.")
        if any(len(name) > 50 for name in names):
            raise forms.ValidationError("Each skill must be 50 characters or fewer.")
        return names
from django import forms

from accounts.forms import BootstrapFormMixin
from jobs.models import Job


class JobForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Job
        fields = (
            "title",
            "category",
            "location",
            "is_remote",
            "employment_type",
            "vacancies",
            "salary_min",
            "salary_max",
            "is_salary_negotiable",
            "experience_years_min",
            "education_level",
            "required_skills",
            "application_deadline",
            "description",
            "responsibilities",
        )
        widgets = {
            "application_deadline": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "description": forms.Textarea(attrs={"rows": 5}),
            "responsibilities": forms.Textarea(attrs={"rows": 4}),
        }

    def clean(self):
        cleaned_data = super().clean()
        salary_min = cleaned_data.get("salary_min")
        salary_max = cleaned_data.get("salary_max")
        vacancies = cleaned_data.get("vacancies")

        if (
            salary_min is not None
            and salary_max is not None
            and salary_max < salary_min
        ):
            self.add_error(
                "salary_max", "Maximum salary cannot be less than minimum salary."
            )

        if vacancies is not None and vacancies < 1:
            self.add_error("vacancies", "Vacancies must be at least 1.")

        return cleaned_data

from django import forms

from accounts.forms import BootstrapFormMixin
from accounts.models import CV
from .models import Application


class JobApplicationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Application
        fields = ("cv", "cover_letter")
        widgets = {
            "cover_letter": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Explain why you are a great fit for this position (optional)...",
                }
            ),
        }

    def __init__(self, *args, jobseeker=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.jobseeker = jobseeker
        self.fields["cv"].required = True
        self.fields["cv"].empty_label = None

        if jobseeker:
            qs = jobseeker.cvs.filter(is_active=True)
            self.fields["cv"].queryset = qs
            self.fields["cv"].label_from_instance = lambda obj: (
                f"{obj.title} ({obj.original_filename})" + (" [Default]" if obj.is_default else "")
            )
            if not self.is_bound and not self.initial.get("cv"):
                default_cv = qs.filter(is_default=True).first()
                if default_cv:
                    self.initial["cv"] = default_cv.pk
                elif qs.exists():
                    self.initial["cv"] = qs.first().pk
        else:
            self.fields["cv"].queryset = CV.objects.none()

    def clean_cv(self):
        cv = self.cleaned_data.get("cv")
        if not cv:
            raise forms.ValidationError("Please select an active CV to submit.")
        if self.jobseeker and (cv.profile_id != self.jobseeker.id or not cv.is_active):
            raise forms.ValidationError(
                "Invalid CV selected. You may only submit an active CV belonging to your profile."
            )
        return cv


class ApplicationStatusUpdateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Application
        fields = ("status",)

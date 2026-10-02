from django import forms

from accounts.forms import BootstrapFormMixin
from accounts.models import CV
from .models import Application, Interview


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


class ApplicationStatusUpdateForm(BootstrapFormMixin, forms.Form):
    status = forms.ChoiceField(
        label="New Status",
        widget=forms.Select(),
    )
    notes = forms.CharField(
        label="Internal Notes",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Optional internal recruitment notes...",
            }
        ),
        help_text="Internal notes are stored in the recruitment history and are never visible to candidates.",
    )

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance
        application = self.instance
        if application and application.pk:
            allowed_next = application.VALID_TRANSITIONS.get(application.status, [])
            valid_choices = [
                (st, Application.Status(st).label) for st in allowed_next
            ]
            self.fields["status"].choices = valid_choices
            if not valid_choices:
                self.fields["status"].disabled = True
                self.fields["status"].required = False
            else:
                self.fields["status"].required = True
        else:
            self.fields["status"].choices = []
            self.fields["status"].disabled = True
            self.fields["status"].required = False

    def clean_status(self):
        new_status = self.cleaned_data.get("status")
        application = self.instance
        if not application or not application.pk:
            raise forms.ValidationError("Application instance is required.")

        if application.is_terminal:
            raise forms.ValidationError(
                "This application has reached a terminal status and cannot be modified."
            )

        if not new_status:
            raise forms.ValidationError("Please select a new status.")

        if not application.can_transition_to(new_status):
            target_label = (
                Application.Status(new_status).label
                if new_status in Application.Status.values
                else new_status
            )
            raise forms.ValidationError(
                f"Invalid transition from '{application.get_status_display()}' to '{target_label}'."
            )
        return new_status


class InterviewScheduleForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Interview
        fields = (
            "interview_type",
            "scheduled_at",
            "duration_minutes",
            "location_or_link",
            "candidate_instructions",
            "internal_notes",
        )
        widgets = {
            "scheduled_at": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "class": "form-control",
                },
                format="%Y-%m-%dT%H:%M",
            ),
            "location_or_link": forms.TextInput(
                attrs={
                    "placeholder": "Office address, Google Meet / Zoom URL, or phone number",
                }
            ),
            "candidate_instructions": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Instructions for the candidate (e.g. what to prepare, documents to bring)...",
                }
            ),
            "internal_notes": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Private notes for internal recruitment team...",
                }
            ),
        }
        labels = {
            "interview_type": "Interview Format",
            "scheduled_at": "Date & Time",
            "duration_minutes": "Duration (Minutes)",
            "location_or_link": "Location / Meeting Link / Phone",
            "candidate_instructions": "Candidate Instructions (Visible to Candidate)",
            "internal_notes": "Internal Notes (Private to Employer)",
        }
        help_texts = {
            "candidate_instructions": "Visible to the candidate on their application detail page.",
            "internal_notes": "Strictly confidential; never visible to the candidate.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["scheduled_at"].input_formats = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
        ]
        if self.instance and self.instance.pk:
            self.fields["duration_minutes"].initial = self.instance.duration_minutes
        else:
            self.fields["duration_minutes"].initial = 30
        self.fields["location_or_link"].required = True
        self.fields["scheduled_at"].required = True

    def clean_duration_minutes(self):
        duration = self.cleaned_data.get("duration_minutes")
        if duration is not None and duration <= 0:
            raise forms.ValidationError("Duration must be a positive number of minutes (e.g., 30, 45, 60).")
        return duration

    def clean_location_or_link(self):
        val = self.cleaned_data.get("location_or_link", "").strip()
        if not val:
            raise forms.ValidationError("Please provide a location, meeting link, or contact phone number.")
        return val

    def clean_scheduled_at(self):
        from django.utils import timezone

        scheduled_at = self.cleaned_data.get("scheduled_at")
        if not scheduled_at:
            raise forms.ValidationError("Please specify the scheduled date and time.")

        if self.instance.pk:
            original = Interview.objects.filter(pk=self.instance.pk).values_list("scheduled_at", flat=True).first()
            if original != scheduled_at and scheduled_at <= timezone.now():
                raise forms.ValidationError("Scheduled interview date and time must be in the future.")
        else:
            if scheduled_at <= timezone.now():
                raise forms.ValidationError("Scheduled interview date and time must be in the future.")

        return scheduled_at


class InterviewCompleteForm(BootstrapFormMixin, forms.Form):
    outcome_notes = forms.CharField(
        label="Interview Outcome Notes",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Optional internal interview feedback, notes, or hiring recommendation...",
            }
        ),
        help_text="Internal notes are strictly confidential and recorded in the interview history.",
    )

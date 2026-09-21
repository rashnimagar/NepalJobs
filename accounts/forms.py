from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import EmployerProfile, JobseekerProfile, User, CV


class BootstrapFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


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
    class Meta:
        model = JobseekerProfile
        fields = ("phone", "location", "summary")
        widgets = {"summary": forms.Textarea(attrs={"rows": 5})}


class CVUploadForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CV
        fields = ("title", "file")
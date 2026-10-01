from django import forms

from .models import ReadingList


class ReadingListForm(forms.ModelForm):
    class Meta:
        model = ReadingList
        fields = ("title", "description", "target_age_group")
        labels = {
            "title": "Titlul listei",
            "description": "Despre ce este",
            "target_age_group": "Pentru ce vârstă",
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

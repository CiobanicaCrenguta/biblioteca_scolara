from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import UserCreationForm

from .models import User, UserProfile


class RegisterForm(UserCreationForm):
    """Rolul nu apare aici. Un cont nou este întotdeauna STUDENT."""

    email = forms.EmailField(
        required=False,
        label="Email (opțional)",
        help_text="Folosit doar pentru recuperarea contului.",
    )

    class Meta:
        model = User
        fields = ("username", "email")
        labels = {"username": "Nume de utilizator"}
        help_texts = {
            "username": "Litere, cifre și caracterele @ . + - _ , cel mult 150.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Parolă"
        self.fields["password2"].label = "Repetă parola"
        # Textul standard al Django pentru parolă este o listă HTML introdusă
        # într-un span, ceea ce este invalid și se afișează rupt. Îl înlocuim.
        self.fields["password1"].help_text = (
            "Cel puțin 8 caractere, nu doar cifre și nu una dintre parolele "
            "foarte răspândite."
        )
        self.fields["password2"].help_text = ""

    def _post_clean(self):
        """Django validează puterea parolei aici și atașează eroarea celui
        de-al doilea câmp, deși utilizatorul a tastat parola în primul. O mutăm
        unde o caută, păstrând pe loc doar avertismentul că parolele diferă."""
        super()._post_clean()
        erori = self.errors.get("password2")
        if not erori:
            return
        ramase = []
        for eroare in erori:
            if "corespund" in eroare or "match" in eroare.lower():
                ramase.append(eroare)
            else:
                self.add_error("password1", eroare)
        if ramase:
            self.errors["password2"] = self.error_class(ramase)
        else:
            del self.errors["password2"]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.STUDENT
        user.email = self.cleaned_data.get("email", "") or ""
        if commit:
            user.save()
            UserProfile.objects.get_or_create(user=user)
        return user


class ProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = (
            "age_group",
            "preferred_language",
            "preferred_subjects",
            "personalization_enabled",
        )
        widgets = {"preferred_subjects": forms.CheckboxSelectMultiple}
        labels = {
            "age_group": "Categoria de vârstă",
            "preferred_language": "Limba preferată",
            "preferred_subjects": "Ce îți place să citești",
            "personalization_enabled": "Vreau recomandări personalizate",
        }


class FormularUtilizator(forms.ModelForm):
    """Formularul bibliotecarului pentru un cont.

    Conține numai câmpurile care îl privesc. Indicatorii tehnici ai Django,
    `is_staff`, `is_superuser` și permisiunile individuale, nu apar aici:
    accesul se decide prin rol, iar expunerea lor ar permite escaladarea
    privilegiilor dintr-un formular obișnuit.
    """

    parola = forms.CharField(
        label="Parolă", required=False, strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="La un cont nou este obligatorie. La editare, lasă gol ca să o păstrezi.",
    )

    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "role", "is_active")
        labels = {
            "username": "Nume de utilizator",
            "email": "Email",
            "first_name": "Prenume",
            "last_name": "Nume",
            "role": "Rol",
            "is_active": "Cont activ",
        }
        help_texts = {
            "username": "Litere, cifre și caracterele @ . + - _",
            "is_active": "Un cont inactiv nu se mai poate autentifica.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.este_nou = self.instance.pk is None
        if self.este_nou:
            self.fields["parola"].required = True
        self.fields["email"].required = False

    def clean_parola(self):
        parola = self.cleaned_data.get("parola", "")
        if parola:
            password_validation.validate_password(parola, self.instance)
        return parola

    def save(self, commit=True):
        user = super().save(commit=False)
        parola = self.cleaned_data.get("parola")
        if parola:
            user.set_password(parola)
        if commit:
            user.save()
            UserProfile.objects.get_or_create(user=user)
        return user

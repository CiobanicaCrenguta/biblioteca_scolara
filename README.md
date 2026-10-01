# Biblioteca școlară

Monolit modular Django. Toate cărțile publicate pot fi citite online de orice
utilizator autentificat. Nu există împrumut, stoc, rezervare sau abonament.

<img width="940" height="648" alt="image" src="https://github.com/user-attachments/assets/fc819c9f-62f3-479f-8d75-4c1ce19b8756" />


## Rulare

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

python manage.py migrate
python manage.py seed_demo        # date de test
python manage.py runserver
```

Conturi create de `seed_demo`, parolă `parola123`:

| utilizator   | rol         |
|--------------|-------------|
| bibliotecar  | LIBRARIAN (și superuser, are acces la `/admin/`) |
| profesor     | TEACHER     |
| student      | STUDENT     |

Teste:

```bash
python manage.py test tests
```

## Straturile

```
views.py        primește cererea, nu decide nimic
services.py     regulile aplicației (publicare, acces la lectură, progres)
selectors.py    interogările de citire
models.py       domeniul și constrângerile de bază de date
```

Un view nu schimbă niciodată `Book.status` direct. Trece prin
`apps/catalog/services.py`, singurul loc unde trăiește invariantul de publicare.

## Regula de publicare

O carte devine PUBLISHED doar dacă are titlu, cel puțin un autor, cel puțin un
subiect, categorie de vârstă și cel puțin o `BookResource` activă cu
`rights_status = VERIFIED`.

Verificarea se face în două momente, nu doar unul:

- la publicare, prin `services.publish()`;
- la dezactivarea unei resurse, prin `services.set_resource_active()`, care
  retrage automat cartea în READY dacă a rămas fără conținut valid.

Fără al doilea punct, o resursă dezactivată după publicare lasă în catalog o
carte pe care nimeni nu o poate deschide, iar eroarea apare abia în cititor.

Catalogul vizibil (`selectors.published_books()`) filtrează încă o dată pe
resursă utilizabilă, deci nici măcar o inconsistență scrisă direct în baza de
date nu ajunge în fața elevilor.

## Rute

```
/                              catalog public
/books/<slug>/                 fișa cărții
/books/<slug>/read/            cititor (login)
/books/<slug>/state/           POST — raft personal
/books/<slug>/reaction/        POST — apreciere
/books/<slug>/publish/         POST — bibliotecar
/books/<slug>/archive/         POST — bibliotecar
/resources/<id>/content/       fișierul, servit prin verificare
/resources/<id>/progress/      POST — salvează poziția
/my-library/                   raftul personal
/librarian/review/             ce lipsește fiecărei cărți nepublicate
/accounts/login|register|profile|logout
/admin/
```

Toate acțiunile care modifică date sunt POST, cu CSRF. `GET` pe `/publish/`
returnează 405.

## Bază de date

Code-first. Schema vine din modele plus migrări. SQLite implicit; dacă setezi
`POSTGRES_DB` în `.env`, `settings.py` comută pe PostgreSQL fără alte modificări.

Constrângeri aplicate la nivel de bază de date, nu doar în Python:
`UNIQUE(user, book)` pe starea lecturii, `UNIQUE(user, resource)` pe progres,
`CHECK` pe procent între 0 și 100, unicitate pe `(source_name, external_id)`
pentru ca importul repetat să nu creeze duplicate.

## Fișierele cărților

În baza de date stau metadatele și calea, nu binarul. Fișierele locale se
servesc prin `/resources/<id>/content/`, care verifică starea cărții, resursa
activă și drepturile înainte de a returna `FileResponse`. Media nu se expune
direct în producție.

Un PDF vizibil integral în browser poate fi descărcat. Folosește doar conținut
pe care ai dreptul să-l distribui; nu promite protecție anti-descărcare.

## Recomandări

`apps/recommendations/`. View-ul cere `services.recommendations_for(user, limit)`
și primește obiecte `Recommendation`. Nu știe ce algoritm rulează dedesubt, deci
motorul se schimbă fără să atingi nicio pagină:

```python
from apps.recommendations import services
services.set_engine(MyEngine())   # orice subclasă de RecommendationEngine
```

### Cum se calculează

Fiecare carte devine un document text din titlu, autori, subiecte, descriere,
vârstă și limbă — metadate, nu textul integral al romanului. Documentele intră
într-o matrice TF-IDF cu bigrame.

Profilul utilizatorului este media ponderată a vectorilor relevanți:

| semnal                     | pondere |
|----------------------------|---------|
| preferință din onboarding  | 3.0     |
| carte apreciată            | 3.0     |
| carte terminată            | 2.5     |
| carte salvată              | 1.5     |
| carte începută             | 1.0     |
| carte respinsă             | exclusă |

Scorul final:

```
0.70 × similaritate TF-IDF
0.15 × suprapunerea cu preferințele alese
0.10 × relevanța categoriei de vârstă
0.05 × selecția bibliotecarului
```

Vârsta este semnal de relevanță, niciodată interdicție: toate rolurile pot citi
orice carte publicată.

### Ce se exclude din descoperire

Orice carte care are deja o stare în raftul utilizatorului. Fără regula asta,
cartea pe care tocmai ai apreciat-o este cea mai similară cu propriul tău profil
și se recomandă pe ea însăși.

Apoi se diversifică: cel mult două titluri de la același autor și cel mult
jumătate din listă dintr-un singur subiect.

### Cold start

Fără istoric și fără preferințe nu inventăm „cele mai populare”, pentru că nu
avem datele. Arătăm selecția bibliotecarului, apoi adăugările recente.

### Explicații

Deterministe, construite din datele potrivirii, fără model generativ:
*„Se potrivește cu preferințele tale: «Aventură», «Fantasy».”*

### Index

Matricea se reconstruiește când se schimbă catalogul. Cheia de versiune combină
numărul de cărți publicate cu ultima modificare, deci o publicare sau un import
invalidează indexul singur, fără semnale și fără cron. Manual:

```bash
python manage.py rebuild_index
```

### Fără scikit-learn

`engine.py` conține `SimpleTfidfVectorizer`, o implementare proprie folosită
automat dacă scikit-learn lipsește. Ambele căi sunt acoperite de teste, deci
proiectul rulează și pe un calculator pe care nu poți instala nimic înainte de
prezentare.

### Limita curentă

Scorarea trece prin toate cărțile publicate la fiecare cerere. Pentru câteva mii
de titluri este instantaneu. Peste ordinul zecilor de mii, matricea trebuie
păstrată într-un cache partajat și candidații pre-filtrați pe subiect.

## Design

`static/css/app.css`, un singur fișier, fără framework. Tokenurile de culoare și
spațiere stau la început în `:root`. Cărțile fără copertă primesc un gradient
determinist din `Book.cover_theme`, deci același titlu are mereu aceeași culoare.

## Listele educaționale

`apps/reading_lists/`. Aici rolul de profesor devine real:

| acțiune                        | student | profesor | bibliotecar |
|--------------------------------|---------|----------|-------------|
| vede listele publicate         | da      | da       | da          |
| creează o listă                | nu      | da       | da          |
| modifică lista proprie         | nu      | da       | da          |
| modifică lista altui profesor  | nu      | nu       | da          |
| publică în catalog             | nu      | nu       | da          |

Două invariante:

- într-o listă intră numai cărți publicate, pentru că elevii trebuie să le poată
  deschide;
- o listă nu se publică dacă între timp una dintre cărți a fost arhivată.

A doua regulă este cea care se uită ușor. Fără ea, o listă publicată în
septembrie trimite elevii, în februarie, către o carte pe care bibliotecarul a
retras-o.

Listele publicate alimentează și cold start-ul: pentru un elev fără istoric, un
titlu recomandat de un profesor este un semnal mai bun decât „adăugat recent”.

## Profilul de cititor

`apps/reader/stats.py`. Numărul de cărți pe fiecare raft, temele și autorii pe
care îi citești, progresul mediu, activitatea pe ultimele șase luni și un buton
de reluare a ultimei cărți deschise.

Totul se calculează din raft și din progres. Nu am adăugat tabele noi ca să
afișăm niște cifre; datele existau deja.

## Protecția datelor

`apps/accounts/privacy.py`, câte o funcție pentru fiecare drept:

| rută                             | ce face                                        |
|----------------------------------|------------------------------------------------|
| `/profile/privacy/`              | ce date se păstrează, de ce și cât timp        |
| `/profile/export-data/`          | descarcă tot, ca JSON                          |
| `/profile/stop-profiling/`       | oprește personalizarea și șterge evenimentele  |
| `/profile/clear-history/`        | șterge raftul, progresul și evenimentele       |
| `/profile/delete-account/`       | șterge contul, cu confirmare pe nume           |

Ce nu se colectează, la fel de important ca ce se colectează: nu se înregistrează
timpul petrecut pe pagină sau derularea, nu se păstrează data nașterii ci doar un
interval de vârstă, iar profesorii nu au acces la raftul sau istoricul elevilor.

Ștergerea contului duce cu ea, prin cascadă, și listele create de un profesor.
Este alegerea corectă din perspectiva protecției datelor, dar are o consecință
practică: o listă care merită păstrată trebuie transferată înainte.

## Modificări față de versiunea descrisă în lucrare

Această versiune adaugă câteva lucruri peste cea documentată. Nu apar entități
noi: modelul rămâne la douăsprezece tabele. Se adaugă doar câmpuri.

| Ce s-a schimbat | Unde | Efect asupra lucrării |
|---|---|---|
| `BookResource.total_pages` | catalog | câmp nou, nu entitate nouă |
| `ReadingProgress.session_count`, `total_reading_minutes`, `last_session_at` | reader | trei câmpuri noi |
| Erorile de parolă se mută pe câmpul tastat | accounts | corectură de interfață |
| Temă proprie pentru interfața de administrare | static, templates | doar prezentare |
| Salvare automată a poziției la 30 de secunde | reader | comportament nou |
| Secțiunile „Citești acum" și „Cărți citite" în profil | accounts | Tabelul 6.2 crește |
| Indicatori: rată de finalizare, sesiuni, ore, serie zilnică, scor de implicare | reader | Tabelul 6.2 crește |
| Atelierul bibliotecarului, la `/gestiune/` | catalog, accounts | rute noi în tabelul de rute |
| Denumiri românești pentru modele | toate | doar afișare, migrări de stare |
| 180 de teste în loc de 78 | tests | capitolul 9 se actualizează |

### Contoarele de sesiune și afirmația din lucrare

Secțiunea 6.8 a lucrării susține că statisticile se calculează la cerere, fără
contoare, tocmai pentru ca ele să nu poată diverge de la realitate. Afirmația
rămâne adevărată pentru toți indicatorii care se pot deduce din raft.

`session_count` și `total_reading_minutes` sunt excepția și merită explicate.
O sesiune de lectură nu poate fi dedusă ulterior: rândul din `ReadingProgress`
păstrează numai ultima poziție, nu istoricul salvărilor. Informația se pierde
dacă nu este consemnată în momentul în care se produce. Alternativa ar fi fost
un tabel de sesiuni, adică o a treisprezecea entitate și o diagramă
entitate-relație diferită de cea din lucrare.

Ambele contoare se actualizează într-un singur loc, `services.save_progress()`,
în aceeași tranzacție cu poziția, ceea ce limitează riscul de divergență.

### Cum se estimează timpul de lectură

O salvare la mai puțin de treizeci de minute după precedenta continuă aceeași
sesiune, iar intervalul dintre ele se adună la timpul de lectură. O pauză mai
lungă deschide o sesiune nouă, fără să adauge timp: nu știm ce a făcut
utilizatorul între timp și nu presupunem. Pragul este o alegere euristică, la
fel ca ponderile din motorul de recomandare.

### Ce nu s-a adăugat, deliberat

Formularul de înregistrare nu cere numele și prenumele, deși ar fi fost simplu.
Capitolul 8 al lucrării susține că se colectează numai datele necesare unei
funcții existente, iar nicio funcție nu are nevoie de numele real al elevului.

## Atelierul bibliotecarului

Înainte, o carte se adăuga din Django admin, prin patru pagini separate: întâi
autorul, apoi opera, apoi ediția, apoi resursa. `apps/catalog/workbench.py` și
`/gestiune/` înlocuiesc acest drum cu un singur formular.

| Rută | Ce face |
|---|---|
| `/gestiune/` | lista cărților și formularul, pe aceeași pagină |
| `/gestiune/carte/<slug>/` | aceeași pagină, cu cartea încărcată pentru editare |
| `/gestiune/autori/`, `/gestiune/teme/` | sugestii pentru completarea automată |
| `/accounts/gestiune/utilizatori/` | conturile, cu aceeași așezare |

### Starea reală, nu câmpul `status`

Problema care a motivat pagina: o carte putea avea `status = PUBLISHED` și
totuși să lipsească din catalog, dacă resursa ei nu avea drepturile verificate.
Django admin arăta „Published" și atât.

`workbench.situatie()` calculează ce vede elevul, nu ce scrie în câmp:

| Etichetă | Când apare |
|---|---|
| Vizibilă în catalog | publicată și cu resursă activă, cu drepturi verificate |
| Publicată, dar invizibilă | publicată, dar fără resursă utilizabilă |
| Gata de publicare | îndeplinește invariantul, nu a fost încă publicată |
| Incompletă | lipsesc metadate, cu lista lor |
| Arhivată | retrasă din catalog |

### Autori și teme

Câmpul este un input obișnuit, cu nume separate prin virgulă, deci formularul
funcționează și fără JavaScript. Scriptul îl transformă în etichete și cere
sugestii de la server. Potrivirea ignoră majusculele, ca „jules verne" să nu
creeze un al doilea autor lângă „Jules Verne". Numele care nu există se creează
la salvare, iar mesajul de confirmare le enumeră.

### Conturi

Formularul are șase câmpuri și atât: utilizator, email, prenume, nume, rol și
cont activ, plus parolă la creare. Indicatorii tehnici ai Django, `is_staff`,
`is_superuser`, grupurile și permisiunile individuale, nu apar: accesul se
decide prin rol, iar expunerea lor ar permite escaladarea privilegiilor dintr-un
formular obișnuit. Bibliotecarul nu își poate schimba propriul rol, nu își poate
dezactiva contul și nu se poate șterge pe sine.



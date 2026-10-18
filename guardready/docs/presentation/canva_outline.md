# GuardReady: Canva Outline (IT102 OOP Exam)

This file is the source of truth for the Canva deck, and it matches the saved
deck as of Oct 17, 2026. Every slide below has its title, the exact text, the
layout, any image placeholders, and the speaker notes with seconds. The
speaker notes are copied word for word from the Canva notes. If you change the
deck, change this file too.

- Canva deck: "GuardReady Exam Presentation", 14 pages (10 main slides and 4
  backup slides): https://canva.link/2kirsqu1qa834bg
- Other files in this folder: `class_diagram.mmd` and `class_diagram.png` (for
  slide 6) and `screenshots.md` (for slide B2).

## Facts checked in the code (Oct 17, 2026)

- Repo: the last commit is "Last stage: README, OOP map and paperwork". No git
  remote yet.
- Tests: `python manage.py test` ran 247 tests, all OK (Python 3.12, Django
  6.1). accounts 16, guards 114, audit 41, deployment 22, reports 54.
- `python manage.py check` and `makemigrations --check` report no problems.
- Menu for Admin/HR: Dashboard, Guards, Sites, Guard reports, Agency permits,
  Notifications (with the number of new notices), Audit log. Security alerts,
  Print Government Report and Print Client Report are buttons on the Audit log
  screen.
- Menu for Guard: My record only. Every other page shows "Access refused" and is
  logged as DENY.
- Built: dashboard with counts, urgent banner and LTO line; guard list and
  profile with Profile, History and Report tabs; Add Guard and Edit Guard; Add
  and "Renew or correct" for each document; step-up (password plus reason, 120
  seconds); employment status; expiry notices and the Notifications page;
  agency permits (LTO); sites, posts and the assign screen, which refuses a
  guard who is not ready and logs every reason (Stage 3); guard reports for
  punctuality, guard type and evaluation, with attendance and evaluation forms
  and a CSV download (Stage 4); audit log; security alerts; printable government
  and client compliance reports; idle timeout (180 seconds); README.md and
  docs/OOP_MAP.md.
- Not built (Future Works only): a way to correct a wrong attendance record, a
  report page for guards, screens to add sites and posts, email or SMS
  reminders, scanned file upload, PostgreSQL with an insert-only audit table.
- Validity periods: the LESP (5 years) and the LTO (5 years at most) are
  confirmed by RA 11917, Secs. 13 and 7. The drug test (1 year) is confirmed by
  Dangerous Drugs Board Regulation No. 2, s. 2003, Sec. 7. The clearances, the
  neuro exam and the training certificate are still placeholders.
- App text is gender neutral since Oct 17, 2026 (for example "since the hire
  date"), so every line can be read aloud.
- Expiry notices are made by `python manage.py check_expiry`. It must run once
  a day, because there are no background workers. `seed_demo` runs it once.
- AppendOnlyRecord blocks save() on a saved row, delete(), and bulk update()
  and delete(). SQLite can still be changed outside the app, so a real build
  should use PostgreSQL with an insert-only audit table.

## Design rules (as built)

- Format: Canva Presentation, 16:9 (1920 x 1080).
- One theme on every page: white background, a navy (#1B2A49) header bar with
  the title in white, teal (#1F8A8A) as the main accent and amber (#F2A541) as
  the second accent. The title page and the Thank You page are navy, with a
  teal line and an amber edge.
- Green (#2E7D32) marks the test result, and red (#A3301F) marks the two Zero
  Trust demo steps (refusals). They mean the same as in the app.
- Text sizes (Canva units): titles 56 (150 on the title page), body 31 to 36,
  box and diagram labels 23 to 29, captions 24. The smallest text in the deck
  is 23, so nothing is below 20.
- At most 5 bullets or steps in any list, in short phrases. The NSDB grid has
  3 points per card, and the User Journey lanes have 6 and 5 steps.
- The User Journey and the Conceptual Framework are built from shapes and
  arrows, not text blocks.
- Speaker notes start with "Time: about N seconds", then "Say:". Notes on the
  backup slides start with "Show only if asked."
- No em dashes anywhere.

## Timing (main slides plus demo)

| Slide | Seconds |
| --- | --- |
| 1 Title | 15 |
| 2 Description | 35 |
| 3 Members | 15 |
| 4 NSDB | 50 |
| 5 User Journey | 45 |
| 6 Class Diagram | 60 |
| 7 Conceptual Framework | 40 |
| 8 Supporting Files | 20 |
| 9 Live Demo | 180 |
| 10 Thank You | 10 |
| Total | 470 (7 min 50 s) |

Add about 20 seconds to switch to the demo laptop. That makes a little over 8
minutes and leaves time for questions.

The seconds were checked against the notes, at about 140 to 150 spoken words a
minute. The demo notes are only about 110 seconds of talking on purpose,
because logging in, clicking and typing take the rest of the 3 minutes.

Backup slides, only if asked: B1 about 60 s, B2 about 30 s, B3 about 35 s, B4
about 45 s.

---

## Slide 1: Project Alias

**Title:** GuardReady

**Exact text:**
- Guard Credential and Deployment Readiness System
- Know which guards can be posted, and why.
- Bottom band: IT102 | Mapua Malayan Colleges Mindanao | [Presentation date]

**Layout:** Navy title page. "GuardReady" very large (150, white), the full
name below it (43), and the tagline in light teal (40). Under them, a teal line
and a navy band with an amber edge on the left. The band has the course, the
school and the date placeholder (32).

**Image placeholders:** none.

**Speaker notes:**

Time: about 15 seconds

Say: Good morning, everyone. Our project is GuardReady, the Guard Credential and
Deployment Readiness System. In one line, it shows which guards can be posted,
and why.

---

## Slide 2: Description

**Title:** What GuardReady Does

**Exact text (4 bullets on the left):**
- Problem: guard papers expire on different dates, tracked on paper or in one Excel file
- Tracks the 6 required papers of every guard, like the LESP and NBI clearance
- Shows who is Cleared, Expiring soon or Not cleared, with expiry notices
- Used by Admin/HR staff; a guard sees only his own record

**SDG badges (on the right):**
- SDG 8 / Decent Work and Economic Growth (teal, the larger badge, our main goal)
- SDG 16 / (16.6, 16.10) / Accountability and Privacy (navy, smaller)

**Layout:** The 4 bullets fill the left half (34). The two SDG badges sit side
by side on the right, with an amber line under them.

**Image placeholders:** none. Optional: the official SDG 8 and SDG 16 icons, if
you add them yourself in Canva.

**Speaker notes:**

Time: about 35 seconds

Say: Guard papers expire on different dates, and agencies track them in folders
or one Excel file, so an expired paper is often found too late. GuardReady
tracks the six required papers of every guard, like the LESP and NBI clearance.
It shows who is Cleared, Expiring soon or Not cleared, with notices before a
paper expires. HR staff use it, and a guard sees only his own record. Our main
goal is SDG 8, decent work. We connect to SDG 16 only for accountability and
privacy.

---

## Slide 3: Members

**Title:** Our Team

**Exact text:**
- Henrich Lumanas
- Role: [Henrich's role]
- [Groupmate name]
- Role: [Groupmate's role]

**Layout:** Two cards side by side, light teal for Henrich and light amber for
the groupmate. Each card has a colored circle at the top, the name in bold
(52) and the role placeholder below it (32).

**Image placeholders:** optional. The circle on each card is where a photo can
go.

**Speaker notes:**

Time: about 15 seconds

Say: We are a group of two. I am Henrich Lumanas, and my role was [your role].
My groupmate is [groupmate name], who worked on [groupmate's role].

---

## Slide 4: NSDB

**Title:** Need, Solution, Differentiation, Benefits

**Exact text (2 by 2 grid):**

Need
- Guard papers expire on different dates
- Expired papers are found too late
- Shared file: anyone can read private data, no record of who looked

Solution
- One record per guard with all 6 papers
- Readiness and expiry notices worked out by the system
- Role-based access, every action logged

Differentiation: Zero Trust
- Permission check on every page
- Step-up (password + reason) for sensitive records
- Append-only audit log of every view, change and refusal

Benefits
- HR sees who can be posted, and why not
- Renewals are caught before papers expire
- Guard privacy is protected and every access is traceable

**Layout:** 2 by 2 grid of light cards. Each card has a colored header strip
(teal for Need and Differentiation, amber for Solution and Benefits) and 3
short points (31). The Differentiation card also has a teal border and a light
teal fill, so it stands out.

**Image placeholders:** none.

**Speaker notes:**

Time: about 50 seconds

Say: First, the need. Every paper expires on a different date, and an expired
paper is often found too late. In a shared file, anyone can read a guard's
private data, and nobody knows who opened it.

Our solution keeps one record per guard with all six papers. The system works
out the readiness on every page, and a daily expiry check makes the notices.

What makes us different is Zero Trust. Every page checks the user's permission,
not just the menu. Sensitive records need the password again, plus a reason. And
every view, change and refusal goes into an audit log that the app never lets
anyone edit or delete.

The benefits: HR sees who can be posted and why not, renewals are caught early,
and guard privacy is protected.

If asked how notices are made: python manage.py check_expiry. It must run once a
day (for example with Windows Task Scheduler), because there are no background
workers.

If asked about the database: SQLite can still be changed outside the app. A real
build should use PostgreSQL with an insert-only audit table (backup slide B4).

---

## Slide 5: User Journey

**Title:** User Journey

**Exact text (two lanes of numbered boxes):**

Lane label: Admin/HR
1. Log in: dashboard counts and urgent banner
2. Notifications: new expiry notices
3. Guards list, then a guard profile
4. Unlock with password (2 minutes)
5. Renew a paper, assign to a post
6. Guard reports, audit log, alerts

Lane label: Guard
1. Log in: goes to My record
2. Own papers and readiness (read only)
3. Unlock own sensitive details
4. Other pages: Access refused
5. Idle 3 minutes: logged out

**Layout:** Two lanes of boxes, left to right, with an arrow between each pair
of boxes. Top lane: 6 teal boxes for Admin/HR (25). Bottom lane: 5 amber boxes
for Guard (26). Each box shows its number and a short label. The lane label
sits above its lane, in teal for Admin/HR and in dark amber for Guard (34).

**Image placeholders:** none. Built from shapes and arrows.

**Speaker notes:**

Time: about 45 seconds

Say: GuardReady has two roles. Admin or HR logs in and sees the dashboard: the
counts and a red banner for urgent papers. Then they check the notifications,
open a guard's profile, and unlock the sensitive part with their password for
two minutes. They can renew a paper, and assign a guard to a post. GuardReady
refuses anyone who is not ready. Last, they check the guard reports, the audit
log and the security alerts.

A guard logs in and goes straight to their own record. They can see their
papers and unlock their own sensitive details. Any other page is refused and
logged, and after three idle minutes they are logged out.

---

## Slide 6: Class Diagram

**Title:** Class Diagram (Main Classes)

**Exact text (legend on the right):**
- Legend
- Inheritance: Person → Employee → Guard
- Composition: a Guard owns its Credentials
- Aggregation: a Post holds Guards through Assignments
- Abstraction: Report is the base of every report
- 19 main classes. Full OOP map: docs/OOP_MAP.md

**Layout:** A large light box for the diagram fills the left three quarters
(1450 x 873). The legend column is on the right: "Legend" (46) with a teal line
under it, then the 5 lines (27).

**Image placeholder:** the big box says "[Class diagram image]" and "Upload
class_diagram.png from docs/presentation" (36). Put `class_diagram.png` from
this folder in the box (4704 x 2958, white background), then delete the
placeholder text. The PNG is rendered from `class_diagram.mmd`, and you can
export it again from https://mermaid.live.

**Speaker notes:**

Time: about 60 seconds

Say: This is our class diagram with the main classes. Guard inherits from
Employee, and Employee inherits from Person, so that is three levels. A Guard
owns its credentials, which is composition. Credential extends the abstract
ExpiringDocument. It has four proxy classes: License, Clearance, MedicalCert and
TrainingCert. Each one overrides validity_months(), and typed() picks the right
class from the kind field. renew() is the only way to change a credential, and
it saves the old values in a CredentialVersion first. CredentialVersion and
AuditEntry extend AppendOnlyRecord, so the app never lets anyone edit or delete
them. A ClientSite owns its posts, which is composition. A post holds guards
through assignments, which is aggregation, because a guard can move to another
post. Last, Report is the abstract base of every report. GuardReport,
SummaryReport and ComplianceReport override its methods, and one write_csv() in
Report writes all of them.

Tip: if the panel wants details, zoom in on class_diagram.png on the laptop.

---

## Slide 7: Conceptual Framework

**Title:** Conceptual Framework

**Exact text (Input, Process, Output):**

INPUT
- Guard records and 6 papers each
- Agency License to Operate (LTO)
- Attendance and evaluations
- Logins and actions by role

PROCESS: Python OOP classes in Django
- ExpiringDocument classes: days left, status, notice band
- Guard and Post: readiness() and refusal_reasons()
- Report classes: punctuality and evaluations
- Zero Trust: permission checks, step-up, audit log

OUTPUT
- Dashboard counts and urgent banner
- Expiry notices: 60, 30, 14, 7, 1 days, Expired
- Refused postings, guard reports and CSV
- Audit log, security alerts, compliance reports

Feedback arrow label: Renew or correct: renewed papers go back in as input

Tech strip: Python 3.12 | Django | SQLite | Bootstrap CSS | no JavaScript

**Layout:** Three boxes left to right with thick teal arrows between them:
Input (teal), Process (navy, the widest) and Output (amber). Each box has its
heading above it (34). An amber dashed arrow runs under the boxes from Output
back to Input, with its label in dark amber (28). A light tech strip is at the
bottom (30). Box text 27 to 28. The three boxes are the same height (386), so
the four lines in each one fit.

**Image placeholders:** none. Built from shapes and arrows.

**Speaker notes:**

Time: about 40 seconds

Say: The input is the guard records and papers, the agency's License to
Operate, the attendance and evaluations, and each user's actions. In the
process, our Python classes do the work. Each document works out its days left
and status. Guard and Post work out readiness and why a guard cannot be posted.
The report classes count punctuality and average the evaluations. Zero Trust
checks every request and logs it. The output is the dashboard, the notices,
refused postings, guard reports, the audit log and the compliance reports. When
HR renews a paper, it goes back in as input.

---

## Slide 8: Other Supporting Files

**Title:** Other Supporting Files

**Exact text (5 rows):**
- GitHub repo: [GitHub repo link]
- README: setup, demo accounts and test steps (README.md)
- Tests: 247 automated tests, all pass (python manage.py test)
- OOP map: docs/OOP_MAP.md, with class diagrams
- Proposal: [proposal link]

**Layout:** Five rows with a thin gray line under each. Each row has a small
colored square on the left (teal, amber, green, amber, teal) and the text
(36). The tests row is bold and green to show the pass result.

**Image placeholders:** none. Optional: a QR code for the repo link, once the
repo is on GitHub.

**Speaker notes:**

Time: about 20 seconds

Say: These are our supporting files: our GitHub repo, the README with the setup
steps and demo accounts, and 247 automated tests that all pass. Our OOP map in
docs/OOP_MAP.md shows where each OOP idea is in the code. And this is our
proposal.

Before the exam: push the repo to GitHub and paste the link, and add the
proposal link.

---

## Slide 9: Live Demo

**Title:** Live Demo (Bring Your Own Device)

**Exact text (5 numbered steps):**
1. admin logs in: dashboard, urgent banner, 8 new notices
2. Rowena: Not cleared (NBI expired), unlock with password
3. Assign Rowena to a post: refused, with the reason
4. Zero Trust: guard1 (private window) opens /audit/, Access refused
5. Zero Trust: Audit log shows the refusals, Security alerts flags guard1

**Layout:** Five rows, each with a big number circle and the step text (36).
Circles 1 to 3 are teal. Circles 4 and 5 are amber, and their text is red, to
mark the Zero Trust moment.

**Image placeholders:** none.

**Speaker notes (the setup steps are at the top of the notes):**

Time: about 180 seconds (3 minutes)

Before the demo (same day): delete db.sqlite3, run python manage.py migrate,
then python manage.py seed_demo (it also makes the 8 expiry notices). Start
python manage.py runserver 0.0.0.0:8000. Log in only when the demo starts,
because you are logged out after 3 minutes idle. Accounts: admin / admin123 and
guard1 / guard123.

Step 1 (30 seconds): I log in as admin. The dashboard shows 8 current guards: 3
Cleared, 2 Expiring soon, and 3 Not cleared. The red banner lists the urgent
papers, and the menu shows 8 new notices. The last line warns that the agency's
License to Operate expires in 5 days.

Step 2 (40 seconds): I open Guards, then Rowena Villanueva. She is Not cleared,
and the reason is right there: her NBI clearance expired. Her medical results
say Locked. I click Unlock with password, type my password and a reason. Now her
details show for two minutes only, and this is logged as STEP_UP.

Step 3 (40 seconds): Now I try to post her anyway. I open Sites and click
Assign a guard next to Basement Parking. I pick Rowena and click Assign the
guard I picked. GuardReady refuses, because her NBI clearance expired, and
there is no override. The refusal is logged as ASSIGN, Denied. Then I pick
Ricardo, who is Expiring soon but still allowed, and he is posted.

Step 4 (35 seconds): In a private window, I log in as guard1. He only sees My
record. I type /audit/ in the address bar. The page says Access refused. I try
/dashboard/ and /guards/ too, and both are refused.

Step 5 (35 seconds): Back as admin, I open the Audit log and filter the action
to DENY. guard1's refusals are there, with the time and the reason. Then I open
Security alerts. It shows Repeated refusals for guard1, because he was refused 3
times within an hour. This is Zero Trust: every page checks, and every refusal
is recorded.

If the panel asks for more: renew Ricardo's LESP to show Expiring soon becoming
Cleared, open Guard reports and download a CSV, or use Print Client Report on
the Audit log screen (Bayview Mall, password re-check, a GR-RPT number, and only
Cleared or Not cleared, never the reason).

---

## Slide 10: Thank You / Questions

**Title:** Thank You!

**Exact text:**
- Questions?
- Bottom band: GuardReady | IT102 | Mapua Malayan Colleges Mindanao
- Henrich Lumanas and [Groupmate name]

**Layout:** Same style as the title page. "Thank You!" large (145, white),
"Questions?" in light teal (64), then a teal and amber line and the navy band
with the two lines (32).

**Image placeholders:** none.

**Speaker notes:**

Time: about 10 seconds

Say: Thank you for listening. We are happy to answer your questions.

If asked, use the backup slides: B1 OOP principles, B2 screenshots, B3 Django
and MVC, B4 future works.

---

# Backup slides (pages 11 to 14, shown only if asked)

## Slide B1: OOP Principles

**Title:** Backup: OOP Principles in Our Code

**Exact text (2 by 2 grid plus a bottom strip):**

Abstraction
- ExpiringDocument: abstract model; validity_months() raises NotImplementedError until typed()
- Report(ABC): @abstractmethod title(), sections() and _request_rows()

Encapsulation
- renew() is the only way to change a credential; it saves the old values first
- AppendOnlyRecord: editing or deleting raises RecordLockedError

Inheritance
- Person → Employee → Guard (3 levels)
- Report → ComplianceReport → GovernmentReport → SosiaReport (4 levels)

Polymorphism
- Each proxy overrides validity_months(); MedicalCert.row() hides results until step-up
- check_expiry() calls make_notice() on credentials and agency permits alike

Bottom strip (3 boxes):
- Composition: a Guard owns its Credentials; a ClientSite owns its Posts
- Aggregation: a Post holds Guards through Assignments
- typed() factory: CREDENTIAL_CLASSES[kind] picks the proxy class, no extra query

**Layout:** 2 by 2 grid of light cards with header strips (teal for
Abstraction and Inheritance, amber for Encapsulation and Polymorphism).
Headers 32, card text 25. A strip of 3 boxes at the bottom (navy, navy and
amber, text 23).

**Image placeholders:** none.

**Speaker notes:**

Show only if asked. Time: about 60 seconds

Say: Abstraction: ExpiringDocument is an abstract model, and its
validity_months() raises NotImplementedError until typed() picks the real class.
Report is an ABC with abstract title(), sections() and _request_rows(), like
BankAccount in the Balaman Bank activity.

Encapsulation: renew() is the only way to change a credential, and it saves the
old values first. AppendOnlyRecord blocks every edit and delete with
RecordLockedError.

Inheritance: Person, Employee and Guard make three levels. Report,
ComplianceReport, GovernmentReport and SosiaReport make four.

Polymorphism: every proxy overrides validity_months(), and MedicalCert overrides
row() so results stay Locked until step-up. check_expiry() calls make_notice()
on credentials and agency permits the same way, with no if or elif on the type.

Composition: a Guard owns its credentials. Aggregation: a Post holds guards
through assignments. And typed() is our factory: a dictionary picks the class
from the kind field.

---

## Slide B2: GUI Evidence

**Title:** Backup: GUI Evidence

**Exact text (6 captions):**
1. Dashboard: counts, urgent banner, LTO line (admin)
2. Guard profile: results Locked (admin)
3. Step-up: password and reason (admin)
4. Access refused: guard1 opens /audit/
5. Audit log: guard1's DENY entries (admin)
6. Notifications: expiry notices (admin)

**Layout:** 3 by 2 grid of light placeholder boxes (550 x 300), each with its
caption below it (24).

**Image placeholders (the text in each box, see screenshots.md):**
- [Screenshot 1] gui_1_dashboard.png
- [Screenshot 2] gui_2_profile_locked.png
- [Screenshot 3] gui_3_step_up.png
- [Screenshot 4] gui_4_access_refused.png
- [Screenshot 5] gui_5_audit_log_deny.png
- [Screenshot 6] gui_6_notifications.png

**Speaker notes:**

Show only if asked. Time: about 30 seconds

Say: These are screenshots of the real screens. The dashboard with the counts
and the urgent banner. A guard profile where the medical results are Locked. The
step-up form that asks for the password and a reason. The Access refused page
when guard1 opens the audit log. The audit log with his refusals. And the
notifications page with the expiry notices.

To do: take the 6 screenshots listed in docs/presentation/screenshots.md, upload
them to Canva, put each one in its box, and delete the placeholder text.

---

## Slide B3: Django and MVC

**Title:** Backup: Django and MVC

**Exact text:**

Mapping (3 boxes):
- Model = models.py / Guard, Credential, AuditEntry
- View = templates / guard_profile.html, base.html
- Controller = views.py + urls.py / the guard_profile() view

One real request: GET /guards/6/ (Rowena's profile)
1. config/urls.py → guards/urls.py
2. `"guards/<int:pk>/" → views.guard_profile`
3. @access_required and can_view_guard() check the user
4. Guard.readiness(), block_reasons(), credential_rows()
5. guard_profile.html renders; AuditMiddleware logs a VIEW

Note under the steps: Box colors match the top row: steps 1 to 3 are the
Controller, step 4 is the Model, step 5 is the View.

**Layout:** Three boxes in a row at the top: Model (teal), View (amber) and
Controller (navy), text 29. The request label (34) is under them. Then five
numbered boxes with teal arrows between them (23). Boxes 1 to 3 are light
navy, box 4 is light teal and box 5 is light amber, to match the top row. The
note (26) is at the bottom.

**Image placeholders:** none.

**Speaker notes:**

Show only if asked. Time: about 35 seconds

Say: Django uses Model, Template, View. In MVC terms, our models are the Model,
our templates are the View, and Django views plus urls.py are the Controller.
For example, when HR opens Rowena's profile at /guards/6/, config/urls.py passes
it to guards/urls.py, which calls the guard_profile view. The view checks the
permission with @access_required and can_view_guard(). Then it asks the Guard
model for readiness(), block_reasons() and the document rows. It renders
guard_profile.html, and the AuditMiddleware writes a VIEW entry in the audit
log.

---

## Slide B4: Future Works

**Title:** Backup: Future Works (Not Built Yet)

**Exact text (5 numbered points):**
1. Correct a wrong attendance record, and a report page for guards
2. Screens to add client sites and posts
3. Confirm placeholders (some validity periods, guard types, alert limits) with PNP SOSIA and the agency
4. Email or SMS reminders, and upload of scanned papers
5. PostgreSQL with an insert-only audit table

**Layout:** Five rows, each with a number circle (teal and amber in turn) and
the text (32).

**Image placeholders:** none.

**Speaker notes:**

Show only if asked. Time: about 45 seconds

Say: These are not built yet. First, a way to correct a wrong attendance
record, because records are append only, and a page where guards can see their
own report. Second, screens to add client sites and posts. Right now they come
from the demo data. Third, some numbers are still placeholders, like the
clearance, neuro exam and training validity, the guard types and the alert
limits. We already confirmed the LESP and LTO periods with RA 11917, and the
drug test with a Dangerous Drugs Board regulation. Last, email or SMS
reminders, scanned file upload, and PostgreSQL with an insert-only audit table.

---

## To do before the exam

1. Fill in the date (slide 1), the groupmate's name and both roles (slides 3
   and 10, and the slide 3 notes). Add the groupmate's name to README.md too.
2. Put `class_diagram.png` on slide 6 (if it is not there yet) and the 6
   screenshots on slide B2 (see `screenshots.md`).
3. Push the repo to GitHub and paste the link on slide 8. Add the proposal
   link.
4. Update the proposal from 90, 60, 30 days to 60, 30, 14, 7, 1 days, so it
   matches slide 7.
5. Optional: the small labels on slides 7, 10, B2 and B3 use a different font
   from the titles. In Canva, use Copy style from a title to match them.
6. Practice the demo once on the demo laptop on the same day, including the
   refused assign in step 3.

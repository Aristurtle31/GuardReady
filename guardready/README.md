# GuardReady

**Guard Credential and Deployment Readiness System.** Know which guards can be
posted, and why.

GuardReady is a Django web app for Philippine security agencies. It keeps the
six papers every security guard needs to stay deployable, works out who is
ready, warns HR before a paper expires, and refuses to post a guard whose
papers are missing or expired. Every page view, change and refusal goes into
an audit log.

IT102 (Python OOP) course project, first year BS Information Systems, Mapua
Malayan Colleges Mindanao. Members: Henrich Lumanas and [Groupmate name].

SDG 8 (Decent Work and Economic Growth) is the main goal. SDG 16 (targets 16.6
and 16.10) is used only for accountability and privacy.

All names, numbers and records in the demo data are made up.

---

## What it does

**Admin/HR** (menu: Dashboard, Guards, Sites, Guard reports, Agency permits,
Notifications, Audit log)

- **Dashboard:** how many guards are Cleared, Expiring soon and Not cleared, a
  red banner for urgent papers, and a line for the agency's License to Operate.
- **Guards:** the guard list and each guard's page, with Profile, History and
  Report tabs. Add Guard, Edit Guard, Change status, and Add or "Renew or
  correct" for each paper.
- **Sites:** client sites and their posts. Assign a guard to a post. GuardReady
  refuses a guard who is not ready, on leave, no longer employed or already
  posted, and it refuses a full post. Every reason is logged, and there is no
  override. End posting lets a guard move to another post.
- **Guard reports:** punctuality, guard type and character evaluation for
  every guard, with Record attendance, Add evaluation and Download CSV.
- **Agency permits:** the agency's own License to Operate (LTO), tracked like
  a guard's papers.
- **Notifications:** expiry notices 60, 30, 14, 7 and 1 days before a paper
  expires, and on the expiry date.
- **Audit log:** every view, change and refusal. Its buttons open Security
  alerts, Print Government Report and Print Client Report.

**Guard** (menu: My record)

- My record: the guard's own profile and history, read only. Sensitive details
  show only after the password is typed again.
- Every other page is refused, and the refusal is logged.

### The papers

| Paper | Validity used for the suggested expiry date |
| --- | --- |
| LESP (License to Exercise Security Profession) | 5 years. Confirmed: RA 11917, Sec. 13 [1] |
| NBI clearance | 12 months (placeholder) |
| Police clearance | 12 months (placeholder) |
| Drug test | 1 year. Confirmed: DDB Regulation No. 2, s. 2003, Sec. 7 [2] |
| Neuro-psychiatric exam | 12 months (placeholder) |
| Basic Security Guard Course certificate | 36 months (placeholder) |
| Agency License to Operate (LTO) | 5 years at most. Confirmed: RA 11917, Sec. 7 [1] |

HR always types the expiry date printed on the paper. These numbers only fill
in the suggested date on the renew form. All of them are in
`guards/constants.py`.

A guard is **Not cleared** if a paper is missing or expired (a paper counts as
expired on its expiry date), **Expiring soon** if a paper expires within 60
days, and **Cleared** otherwise. A Not cleared guard cannot be posted. An
Expiring soon guard can still be posted, so HR has time to renew the paper.

---

## Zero Trust

The professor asked for role-based and time-limited access, extra verification
for sensitive records, read-only access where needed, and automatic logs.

| Requirement | How GuardReady does it |
| --- | --- |
| Role-based access | Two roles, Admin/HR and Guard. `ROLE_PERMISSIONS` in `accounts/roles.py` is the only list of what each role can do. Every page uses `@access_required` and checks the permission on every request, not just the menu. `can_view_guard()` also checks the guard itself, so a guard opens only their own record. |
| Time-limited access | Logged out after 180 seconds without activity (`IDLE_TIMEOUT_SECONDS`). An unlock lasts 120 seconds (`STEP_UP_SECONDS`) and covers one guard only. |
| Extra verification | "Unlock with password" asks for the password again and a reason before sensitive details show. Printing a compliance report asks for the password again too. |
| Read-only access | A guard's own record is read only. Audit entries, old versions of papers, status changes, attendance and evaluations can be added but never edited or deleted (`AppendOnlyRecord`). The Django admin is for the superuser only and is read only. |
| Automatic logs | `AuditMiddleware` logs every page view (VIEW) and every refusal (DENY). The app also logs LOGIN, LOGOUT, CREATE, UPDATE, ASSIGN, STEP_UP, TIMEOUT and REPORT. A failed login keeps the typed username, never the password. Security alerts read the last 7 days of the log. |

### Privacy

The Data Privacy Act of 2012 (RA 10173) asks for transparency, legitimate
purpose and proportionality (Sec. 11), and it counts health information and
numbers issued by government agencies, like social security numbers, as
sensitive personal information (Sec. 3(l)) [3].

- Sensitive in GuardReady: medical results (drug test and neuro-psychiatric
  exam), birth date, home address, contact number (shown masked), SSS, TIN and
  PhilHealth numbers.
- They stay hidden until an unlock, and they never appear in notices, history,
  guard reports, CSV files or compliance reports.
- Each compliance report shows only what that requester needs. A client report
  shows only "Cleared" or "Not cleared", never the reason.

---

## Built with

Python 3.12, Django 6.1, SQLite, and Bootstrap 5.3.3 CSS from jsDelivr. No
JavaScript and no other packages.

## Setup

### Windows (PowerShell)

```powershell
cd path\to\guardready
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in. If PowerShell will not run
`Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once,
or use Command Prompt and `.venv\Scripts\activate.bat`.

### GitHub Codespaces

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver 0.0.0.0:8000
```

Open the forwarded port 8000. The settings already allow the
`.app.github.dev` address and trust it for forms (CSRF).

### Demo accounts

| Username | Password | Role | Person |
| --- | --- | --- | --- |
| admin | admin123 | Admin/HR | Liza Ramos |
| guard1 | guard123 | Guard | Juan Dela Cruz (GR-0001) |

These passwords are for the demo only.

### Demo data

`python manage.py seed_demo` is safe to run again. Its dates are relative to
today, so the demo always looks the same:

- 8 current guards: 3 Cleared, 2 Expiring soon and 3 Not cleared.
- 1 guard who resigned (Noel Castillo), who is not counted.
- 2 client sites with 4 posts, attendance for the last 4 weeks, and some
  evaluations.
- The agency's LTO expires in 5 days, so the dashboard warns about it.
- 8 expiry notices, because the seed runs the expiry check once.

To start over, delete `db.sqlite3`, then run `migrate` and `seed_demo` again.

---

## Daily expiry check

Expiry notices are made by:

```
python manage.py check_expiry
```

There are no background workers, so it has to run once a day. It never makes
the same notice twice, so running it more often is safe. Each run writes one
entry by "system" in the audit log.

To run it every day on Windows, use Task Scheduler:

1. Open Task Scheduler and click **Create Basic Task**.
2. Name it `GuardReady expiry check`, and pick **Daily** at a time when the
   computer is on.
3. Pick **Start a program**, then fill in:
   - Program/script: `C:\path\to\guardready\.venv\Scripts\python.exe`
   - Add arguments: `manage.py check_expiry`
   - Start in: `C:\path\to\guardready`
4. Click **Finish**. To test it, right-click the task, click **Run**, then
   open Notifications.

## Tests

```
python manage.py test
python manage.py check
python manage.py makemigrations --check --dry-run
```

There are 247 tests. They take a few minutes, mostly because of password
hashing in the login tests. They check the permission on every page, every
refusal and its audit entry, the append-only records, the expiry bands, the
assign rules, the reports and CSV files, and that no sensitive data shows up
in notices, history, reports or CSV files.

---

## Project layout

```
config/       settings and the main URL list
accounts/     login, roles (ROLE_PERMISSIONS), @access_required, step-up, idle timeout
guards/       guards, their papers, employment status, expiry notices,
              agency permits, dashboard, seed_demo and check_expiry
deployment/   client sites, posts, assignments and the assign rules
audit/        audit log, change summaries, security alerts, guard history
reports/      attendance, evaluations, guard reports, compliance reports, CSV
templates/    base page and the "Access refused" page
static/       the app's own CSS
docs/         OOP_MAP.md, the OOP map for the panel
```

## OOP design

The OOP design is graded, so `docs/OOP_MAP.md` shows where each idea is in the
code, with class diagrams. In short:

- **Abstraction:** abstract base classes like `Report`, `ReportSection`,
  `AlertRule`, `HistoryEvent` and `EmploymentStatus`, and abstract Django
  models like `ExpiringDocument` and `AppendOnlyRecord`.
- **Inheritance:** `Person` → `Employee` → `Guard`, and `Report` →
  `ComplianceReport` → `GovernmentReport` → `SosiaReport`.
- **Polymorphism:** `check_expiry()` calls `make_notice()` on guard papers and
  agency permits alike, and one `write_csv()` writes every report.
- **Encapsulation:** `renew()` is the only way to change a paper, and the
  append-only records refuse every edit and delete.
- **Factory:** `typed()`, `PERMIT_TYPES`, `STATUS_CLASSES` and
  `COMPLIANCE_REPORTS` pick the class once, like `ACCOUNT_TYPES` and
  `create_account()` in the Balaman Bank activity.

---

## Placeholders and known limits

Still to confirm with the agency or PNP SOSIA (each one is a constant):

- The validity months marked PLACEHOLDER in `guards/constants.py` (NBI and
  police clearance, neuro-psychiatric exam, training certificate).
- The guard types and the employment status reasons in `guards/constants.py`.
- The agency name and address on compliance reports in `reports/constants.py`.
- The security alert limits and office hours in `audit/constants.py`.

Known limits:

- For real use, set `GUARDREADY_SECRET_KEY`, turn `DEBUG` off, and use
  PostgreSQL with an audit table that only allows inserts. SQLite can still be
  changed outside the app.
- The 180 second idle timeout is short on purpose for the demo.
- No email or SMS, no upload of scanned papers, no account screens and no
  background workers.
- Sites and posts come from the demo data. There is no screen to add them yet.
- A wrong attendance record cannot be corrected yet, and guards cannot see
  their own guard report yet.
- The issuer of a paper cannot be corrected, because that needs a model
  change.

---

## Sources

1. Republic Act No. 11917, Private Security Services Industry Act (2022).
   Sec. 7: the LTO is valid for a maximum period of five years, and the Chief
   PNP may set a shorter one. Sec. 13: the LESP is valid for five years from
   the date it was issued. https://legacy.senate.gov.ph/republic_acts/ra%2011917.pdf
   (also at https://elibrary.judiciary.gov.ph/thebookshelf/showdocs/2/95597)
2. Dangerous Drugs Board, Board Regulation No. 2, Series of 2003, Sec. 7
   (Validity of the Test Result): a drug test result is valid for one year
   from the date of issue.
   https://ddb.gov.ph/images/Board_Regulation/2003/Bd.%20Reg.%202%2003.pdf
3. Republic Act No. 10173, Data Privacy Act of 2012, Secs. 3(l) and 11.
   https://privacy.gov.ph/data-privacy-act/

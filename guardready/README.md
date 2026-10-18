# GuardReady

**Guard Credential and Deployment Readiness System.** Know which guards can be posted, and why.
**Jump to:** [Quick start](#quick-start) | [Codespaces](#run-in-github-codespaces) | [Run locally](#run-locally) | [Demo accounts](#demo-accounts) | [Quick tour](#quick-tour)

## About

Many security agencies in the Philippines track guard papers in paper folders or one shared Excel file. Each paper expires on a different date, so an expired paper may only be found during an inspection. A shared file also lets everyone see sensitive records, and nobody can tell who opened them. GuardReady keeps the six papers of every guard in one place, warns HR before a paper expires, refuses to post a guard who is not ready, and logs every view, change and refusal. It also tracks the two licenses in [RA 11917](https://legacy.senate.gov.ph/republic_acts/ra%2011917.pdf), the Private Security Services Industry Act: the guard's License to Exercise Security Profession (LESP) and the agency's License to Operate (LTO). Health information and numbers issued by government agencies stay hidden until the user types their password again, because the [Data Privacy Act of 2012 (RA 10173)](https://www.privacy.gov.ph/data-privacy-act/) treats them as sensitive personal information. Our main goal is SDG 8 (Decent Work and Economic Growth), and we use SDG 16 only for accountability and privacy (targets 16.6 and 16.10).

## Features

Everything below is built and working.

- **Dashboard:** counts of Cleared, Expiring soon and Not cleared guards, a red banner for urgent papers, and a line for the agency's License to Operate.
- **Guard records:** a guard list, and a page for each guard with Profile, History and Report tabs. Add Guard and Edit Guard.
- **Credential tracking:** the 6 required papers of every guard, with Add and "Renew or correct" for each one. Old values are kept in the history.
- **Readiness:** each guard is Cleared, Expiring soon or Not cleared, and the page says why.
- **Expiry notices:** 60, 30, 14, 7 and 1 days before a paper expires, and on the expiry date, on a Notifications page with a count in the menu.
- **Employment status:** Active, On leave, Resigned or Let go. Guards who left drop out of lists and counts, and their login stops working.
- **Sites and posts:** assign a guard to a post. GuardReady refuses a guard with a missing or expired paper, a guard who is on leave, no longer employed or already posted, and a full post. There is no override.
- **Guard history:** postings, refused postings, paper changes and expiry notices, newest first.
- **Guard reports:** punctuality, guard type and character evaluation, with Record attendance, Add evaluation and Download CSV.
- **Compliance reports:** printable reports for a government office (PNP SOSIA, the National Privacy Commission or another office) or a client, each showing only what that requester needs.
- **Agency permits:** the agency's own License to Operate (LTO), tracked like a guard's papers.
- **Audit log:** every page view, change and refusal, with filters.
- **Security alerts:** reads the last 7 days of the audit log and flags failed logins, repeated refusals, many unlocks, bulk viewing and after-hours staff activity.

### Zero Trust

- **Permission check on every page:** every page checks the user's permission on every request, not just the menu. A refused page says "Access refused" and is logged as DENY.
- **Step-up for sensitive records:** "Unlock with password" asks for the password again and a reason. It unlocks one guard for 120 seconds. Printing a compliance report asks for the password again too.
- **Idle timeout:** after 180 seconds without activity, the user is logged out and a TIMEOUT entry is logged.
- **Append-only audit log:** audit entries, old versions of papers, status changes, attendance and evaluations can be added but never edited or deleted.
- **Masked personal data:** the contact number shows only its last 4 digits. Medical results, birth date, home address and government numbers stay hidden until a step-up, and they never appear in notices, history, reports or CSV files.

## Tech stack

- **Python 3.12** (tested with 3.12.14). Django 6.1 works with Python 3.12, 3.13 and 3.14 ([Django FAQ](https://docs.djangoproject.com/en/6.1/faq/install/)).
- **Django 6.1** (`requirements.txt` says `Django>=6.1,<6.2`, tested with 6.1.2). pip also installs asgiref and sqlparse, which Django needs.
- **SQLite**, the database that comes with Python. Nothing extra to install.
- **Bootstrap 5.3.3 CSS** from the jsDelivr CDN, plus our own `static/css/guardready.css`. The pages need internet for the Bootstrap CSS. Without it, they still work but look plain.
- **No JavaScript.**

## Quick start

You need Python 3.12, 3.13 or 3.14, and Git. On macOS or Linux:

```bash
git clone [GitHub repo URL] guardready
cd guardready
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in as `admin` with the password `admin123`.

On Windows, use the commands in [Run locally](#run-locally). No Python on your computer? Use [GitHub Codespaces](#run-in-github-codespaces).

## Run in GitHub Codespaces

A codespace runs the app in your browser, so you do not need to install anything. The default codespace already has Python. You can check the version with `python --version`. It must be 3.12, 3.13 or 3.14.

1. Open the repo on GitHub: [GitHub repo URL]
2. Click the green **Code** button, open the **Codespaces** tab, and click **Create codespace on main**.
3. Wait for the editor to open. In the terminal at the bottom, run:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py seed_demo
   python manage.py runserver 0.0.0.0:8000
   ```

4. A pop-up says that your application on port 8000 is available. Click **Open in Browser**.
5. If you miss the pop-up, open the **PORTS** tab next to the terminal. Hover over the address of port 8000 and click the globe icon (**Open in Browser**).
6. Log in with a [demo account](#demo-accounts).

The app opens on an address that ends in `.app.github.dev`. The settings already allow it (`ALLOWED_HOSTS`) and trust it for forms (`CSRF_TRUSTED_ORIGINS`), so the login works. The port is private by default, so only you can open it. Press Ctrl+C in the terminal to stop the server.

## Run locally

You need Python 3.12, 3.13 or 3.14 ([python.org](https://www.python.org/downloads/)), and Git.

**1. Get the code**

```bash
git clone [GitHub repo URL] guardready
cd guardready
```

**2. Create and turn on a virtual environment**

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Windows (Command Prompt):

```bat
python -m venv .venv
.venv\Scripts\activate.bat
```

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

You should now see `(.venv)` at the start of the prompt.

- If PowerShell says that running scripts is disabled, run this once, then turn on the virtual environment again:

  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  ```

- If Windows cannot find `python`, use `py` instead, for example `py -m venv .venv`.

**3. Install Django, build the database and add the demo data**

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
```

**4. Start the server**

```bash
python manage.py runserver
```

**5. Open the app**

Go to http://127.0.0.1:8000/ in your browser. You will see the login page.

Press Ctrl+C to stop the server. Next time, turn on the virtual environment again and run `python manage.py runserver`.

## Demo accounts

| Username | Password | Role | Person (made up) |
| --- | --- | --- | --- |
| `admin` | `admin123` | Admin/HR | Liza Ramos |
| `guard1` | `guard123` | Guard | Juan Dela Cruz (GR-0001) |

**These are demo accounts with fake data.** Every name, number and record in the demo is made up. Change these accounts before any real use, for example with `python manage.py changepassword admin` and `python manage.py changepassword guard1`. Running `seed_demo` again keeps a changed password. Never enter real guard data in the demo.

## Quick tour

Use a normal window for Admin/HR and a private (incognito) window for the guard, so both can stay logged in. If a window sits idle for 3 minutes, log in again.

**As Admin/HR (`admin` / `admin123`)**

1. Log in. The Dashboard shows 8 current guards: 3 Cleared, 2 Expiring soon and 3 Not cleared. A red Urgent banner warns about 5 papers that expire within 7 days or have expired, and a line warns that the agency's License to Operate expires in 5 days.
2. Click **Notifications** in the menu (it shows 8 new) to see the expiry notices.
3. Click **Guards**, then **Rowena Villanueva**. She is Not cleared because her NBI clearance expired, and her sensitive records are hidden.
4. Click **Unlock with password**. Type your password and a reason, like "Checking the NBI clearance". Her details show for 120 seconds, and the unlock is logged as STEP_UP.
5. Click **Sites**, then **Assign a guard** next to Basement Parking. Pick Rowena Villanueva and click **Assign the guard I picked**. GuardReady refuses and shows the reason, and the refused attempt is logged as ASSIGN, Denied. Ricardo Santos is Expiring soon but can still be posted.
6. Click **Audit log** to see every view, change and refusal.

**As a Guard (`guard1` / `guard123`)**

1. Log in. You go straight to My record, the profile of Juan Dela Cruz. The menu has only My record.
2. Look at your own papers and readiness. Everything is read only.
3. Click **Unlock with password** to see your own sensitive details for 120 seconds.
4. Go to http://127.0.0.1:8000/audit/ (in Codespaces, add `/audit/` to the app address). The page says **Access refused**, and that the attempt was recorded in the audit log. Try `/dashboard/` and `/guards/` too.
5. Do nothing for 3 minutes, then click a link. You are logged out and sent to the login page.

**Back as Admin/HR:** open **Audit log**, set **Action** to DENY and click **Filter**. The guard's refusals are there, with the time, the page and the reason. Then click **Security alerts**. It shows Repeated refusals for guard1, because guard1 was refused 3 times within an hour.

## Roles and permissions

`ROLE_PERMISSIONS` in `accounts/roles.py` is the only place that decides what each role can do. `seed_demo` builds the two groups from it, so run `seed_demo` again after you change it.

| Permission | What it opens | Admin/HR | Guard |
| --- | --- | --- | --- |
| `view_dashboard`, `view_all_guards` | Dashboard, guard list and every profile | Yes | No |
| `view_own_record` | My record (own profile, read only) | No | Yes |
| `step_up_sensitive` | Unlock with password | Yes | Own record only |
| `add_guard`, `change_guard` | Add Guard, Edit Guard, Change status | Yes | No |
| `manage_credentials` | Add or renew papers, Agency permits, Notifications | Yes | No |
| `assign_guard` | Sites, posts, Assign and End posting | Yes | No |
| `record_performance`, `view_summary_report` | Attendance, evaluations, Guard reports and CSV files | Yes | No |
| `view_audit_log` | Audit log, Security alerts, compliance reports | Yes | No |
| `delete_guard` | Delete a guard | No | No (never given to anyone) |

## Useful commands

Run these in the project folder, with the virtual environment turned on.

| Command | What it does |
| --- | --- |
| `python manage.py runserver` | Starts the app at http://127.0.0.1:8000/ |
| `python manage.py runserver 0.0.0.0:8000` | Starts the app so Codespaces can forward port 8000 |
| `python manage.py migrate` | Creates or updates the database tables |
| `python manage.py seed_demo` | Adds the demo accounts and demo data. Safe to run more than once |
| `python manage.py check_expiry` | Makes today's expiry notices. Safe to run more than once a day |
| `python manage.py test` | Runs all the automated tests |
| `python manage.py check` | Checks the project for problems |
| `python manage.py changepassword admin` | Changes the password of a user (here, `admin`) |
| `python manage.py createsuperuser` | Makes a superuser for the read-only Django admin at /admin/ |

`seed_demo` and `check_expiry` are GuardReady's own commands. The others come with Django.

**Run the tests**

```bash
python manage.py test
```

On October 18, 2026, all 247 tests passed in about a minute (Python 3.12.14, Django 6.1.2).

**Reset the demo data**

Stop the server first (Ctrl+C).

Windows (PowerShell or Command Prompt):

```powershell
del db.sqlite3
python manage.py migrate
python manage.py seed_demo
```

macOS or Linux:

```bash
rm db.sqlite3
python manage.py migrate
python manage.py seed_demo
```

**Run the expiry check every day**

`check_expiry` makes the expiry notices. There are no background workers, so it has to run once a day (`seed_demo` runs it once). On Windows, use Task Scheduler:

1. Open Task Scheduler and click **Create Basic Task**.
2. Name it `GuardReady expiry check` and pick **Daily**, at a time when the computer is on.
3. Pick **Start a program**, then fill in:
   - Program/script: `C:\path\to\guardready\.venv\Scripts\python.exe`
   - Add arguments: `manage.py check_expiry`
   - Start in: `C:\path\to\guardready`
4. Click **Finish**. To test it, right-click the task, click **Run**, then open Notifications.

## Configuration

These settings are in `config/settings.py`:

- `IDLE_TIMEOUT_SECONDS = 180`: logs the user out after this many seconds without activity. It is short on purpose for the demo.
- `STEP_UP_SECONDS = 120`: how long "Unlock with password" keeps one guard's sensitive details open.

This environment variable is read when the server starts:

- `GUARDREADY_SECRET_KEY`: the secret key Django uses. Without it, the app uses the development key written in `config/settings.py`, so set your own key before any real use.

Make a random key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Then set it in the same terminal where you start the server.

Windows (PowerShell):

```powershell
$env:GUARDREADY_SECRET_KEY = 'paste-your-key-here'
```

Windows (Command Prompt):

```bat
set GUARDREADY_SECRET_KEY=paste-your-key-here
```

macOS or Linux:

```bash
export GUARDREADY_SECRET_KEY='paste-your-key-here'
```

Other values, like the validity months, the notice days and the alert limits, are constants in `guards/constants.py`, `reports/constants.py` and `audit/constants.py`.

## Project structure

- `config/`: settings and the main URL list
- `accounts/`: login and logout, roles (`ROLE_PERMISSIONS`), `@access_required`, step-up and the idle timeout
- `guards/`: guards and their papers, employment status, expiry notices, agency permits, the dashboard, and the `seed_demo` and `check_expiry` commands
- `deployment/`: client sites, posts, assignments and the assign rules
- `audit/`: the audit log, change summaries, security alerts and guard history
- `reports/`: attendance, evaluations, guard reports, compliance reports and CSV files
- `templates/`: the base page and the "Access refused" page
- `static/`: our own CSS file
- `docs/`: `OOP_MAP.md`, the OOP map for the panel

## OOP design

- `Person` → `Employee` → `Guard`: two abstract models share the personal and job fields, and only `Guard` has a table.
- `ExpiringDocument` (abstract) → `Credential` → the proxies `License`, `Clearance`, `MedicalCert` and `TrainingCert`. `typed()` picks the class from the kind field, and each proxy overrides `validity_months()`. `AgencyPermit` (with its proxy `LicenseToOperate`) also extends `ExpiringDocument`, so it shares the same expiry rules.
- `AppendOnlyRecord` (abstract) → `AuditEntry`, `CredentialVersion`, `AttendanceRecord`, `Evaluation` and more. These rows can be added but never edited or deleted (`RecordLockedError`).
- `Report` (an ABC) → `ComplianceReport`, `GuardReport` and `SummaryReport`. One shared `write_csv()` writes every report.

The full OOP map is in [docs/OOP_MAP.md](docs/OOP_MAP.md). Its [class diagrams](docs/OOP_MAP.md#8-class-diagrams) are written in Mermaid, which GitHub draws.

## Limitations

GuardReady is a student project. It is not ready for real use.

- `DEBUG = True` in `config/settings.py`.
- `SECRET_KEY` has a development default in the code. Set `GUARDREADY_SECRET_KEY` instead.
- It uses SQLite. The app blocks edits to the audit log, but anyone with the `db.sqlite3` file can still change it.
- Four validity periods are placeholders: the NBI clearance, the police clearance, the neuro-psychiatric exam and the Basic Security Guard Course certificate. The LESP (5 years) and the LTO (5 years at most) come from [RA 11917](https://legacy.senate.gov.ph/republic_acts/ra%2011917.pdf), Secs. 13 and 7. The drug test (1 year) comes from [Dangerous Drugs Board Regulation No. 2, s. 2003](https://ddb.gov.ph/images/Board_Regulation/2003/Bd.%20Reg.%202%2003.pdf), Sec. 7.
- Other placeholders: the guard types, the employment status reasons, the agency name and address on compliance reports, and the security alert limits and office hours.
- `check_expiry` must run once a day, because there are no background workers.
- The 180 second idle timeout is short on purpose for the demo.

**Never enter real guard data in the demo.**

## Future work

These are not built yet:

- Confirm the placeholders above with the agency and PNP SOSIA.
- A way to correct a wrong attendance record, for example a correction record that points to the old one.
- Let guards see their own guard report, attendance and evaluations on My record.
- Screens to add and edit client sites and posts. For now they come from the demo data.
- A way to correct the issuer of a paper.
- Email or SMS reminders, and a background scheduler for the daily expiry check.
- Upload of scanned papers.
- Account management screens, so passwords can be changed in the app.
- PostgreSQL with an audit table that only allows inserts, a real secret key, and `DEBUG` turned off.
- A REST API for other systems.

## Team

Henrich Lumanas and Art Rian Cartin

IT102, Mapúa Malayan Colleges Mindanao

## Disclaimer

GuardReady is a student project. It is not affiliated with the PNP, SOSIA, or any security agency. All names, numbers and records in the demo data are made up.

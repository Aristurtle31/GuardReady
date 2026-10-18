# Screenshots for the Canva deck

These go on slide B2 (GUI Evidence). Slide 6 uses `class_diagram.png`, which is
already in this folder. All the data in the screenshots is fake seed data.

## Setup (do this once, on the same day)

1. In the repo folder, delete `db.sqlite3`, then run:
   `python manage.py migrate`
   `python manage.py seed_demo`
2. Run `python manage.py runserver 0.0.0.0:8000` and open http://127.0.0.1:8000/
   in Chrome.
3. Make the window full screen with the zoom at 100% (use 80% or 90% if a table
   is cut off).
4. Take each screenshot with the Snipping Tool (Win + Shift + S) and save it as
   a PNG with the file name below.
5. Take them in this order. The idle timeout is 3 minutes, so if you are logged
   out, just log in again.

## The 6 screenshots for slide B2

| No. | File name | Account | Where to go | What must be visible |
| --- | --- | --- | --- | --- |
| 1 | gui_1_dashboard.png | admin / admin123 | Log in. You land on the Dashboard (/dashboard/). | The red "Urgent" banner, the cards 8, 3, 2 and 3, the License to Operate line at the bottom, and "Notifications 8 new" in the menu. |
| 2 | gui_2_profile_locked.png | admin | Guards, then Rowena Villanueva (/guards/6/). | "Not cleared", "Cannot be posted because: NBI Clearance expired on ...", the Documents table with "Locked" in the Result column, and the "Sensitive records" box with the "Unlock with password" button. |
| 3 | gui_3_step_up.png | admin | On Rowena's profile, click "Unlock with password" (/accounts/step-up/6/). | The "Confirm it is you" form. Type a reason first, like "Checking her NBI clearance". Type the password so only dots show, or leave it empty. Take the screenshot before you click Unlock. |
| 4 | gui_4_access_refused.png | guard1 / guard123, in a private window (Ctrl + Shift + N) | Log in. You land on My record. Then type 127.0.0.1:8000/audit/ in the address bar. | "Access refused", "Your role is missing the permission: audit.view_audit_log", and "This attempt has been recorded in the audit log." The menu shows only "My record" and "guard1 (Guard)". |
| 5 | gui_5_audit_log_deny.png | admin, back in the normal window | Before this, in the guard1 window, also open /dashboard/ and /guards/ (no screenshot). Then as admin: Audit log (/audit/), set Action to DENY, click Filter. | guard1's DENY rows with the time, the role Guard, the page and the reason. |
| 6 | gui_6_notifications.png | admin | Menu: Notifications (/notifications/). | The list of notices with their bands (Expired, 1 day, 1 week, 2 weeks, 1 month, 2 months). Do not click "Mark as seen". |

## Optional extras (for questions, not on the slide)

| File name | Account | Where to go | What must be visible |
| --- | --- | --- | --- |
| gui_7_security_alerts.png | admin | Audit log, then Security alerts (/audit/alerts/). Take it within 1 hour of screenshot 5. | "Repeated refusals" for guard1, with the time window and the count. |
| gui_8_unlocked.png | admin | Unlock Rowena with your password and a reason. | "Unlocked. Locks again at ... (seconds left)" and her details. |
| gui_9_client_report.png | admin | Audit log, Print Client Report, choose Bayview Mall, fill in the request, re-enter the password, click Generate report. | The report number (GR-RPT-...) and the guards table with only "Cleared" or "Not cleared". |
| gui_10_assign_refused.png | admin | Sites, click Assign a guard next to Basement Parking, pick Rowena Villanueva, click Assign the guard I picked. | "Refused. Rowena Villanueva cannot be posted here: NBI Clearance expired on ..." and "This attempt was recorded in the audit log." |
| gui_11_guard_reports.png | admin | Menu: Guard reports (/reports/guards/). | The 8 current guards with guard type, duties, on time, late, absent, punctuality and average score, and the Download CSV button. |

## Putting them in Canva

1. Open the deck in Canva, then Uploads, then Upload files, and pick the PNGs.
2. On slide B2, drag each screenshot onto its box, then delete the placeholder
   text in that box.
3. On slide 6, do the same with `class_diagram.png`.

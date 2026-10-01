"""
python manage.py seed_demo

Creates the demo data from spec section 9. Safe to run more than once:
anything that already exists is left alone. To start over, delete
db.sqlite3 and run "python manage.py migrate" again.

All dates are relative to today, so the mix stays the same on any day:
3 cleared, 2 expiring soon, 3 not cleared.
"""

import random
from datetime import date, datetime, time, timedelta

from django.contrib.auth.models import Group, Permission, User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.roles import ADMIN, COMMANDER, GUARD, ROLE_PERMISSIONS
from deployment.constants import DAY_SHIFT, NIGHT_SHIFT
from deployment.models import Assignment, ClientSite, Post
from guards import constants as c
from guards.dates import add_months
from guards.models import Credential, Guard
from guards.services import readiness_counts
from reports.constants import LATE_GRACE_MINUTES
from reports.models import AttendanceRecord, Evaluation

# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

# username, password, role, first name, last name
ACCOUNTS = [
    ("admin", "admin123", ADMIN, "Liza", "Ramos"),
    ("commander", "commander123", COMMANDER, "Rogelio", "Tan"),
    ("guard1", "guard123", GUARD, "Juan", "Dela Cruz"),
]

# site name: (address, [(post name, shift, headcount), ...])
SITES = {
    "Northgate Corporate Center": (
        "Lanang, Davao City",
        [("Main Lobby", DAY_SHIFT, 2), ("Basement Parking", NIGHT_SHIFT, 1)],
    ),
    "Bayview Mall": (
        "Bajada, Davao City",
        [("Mall Entrance A", DAY_SHIFT, 2), ("Stockroom", NIGHT_SHIFT, 1)],
    ),
}

# Days left before expiry for a document with no problem (all past 60 days).
HEALTHY_DAYS_LEFT = {
    c.LESP_LICENSE: 400,
    c.NBI_CLEARANCE: 200,
    c.POLICE_CLEARANCE: 150,
    c.DRUG_TEST: 120,
    c.NEURO_EXAM: 250,
    c.BASIC_COURSE: 800,
}

NUMBER_PREFIX = {
    c.LESP_LICENSE: "LESP",
    c.NBI_CLEARANCE: "NBI",
    c.POLICE_CLEARANCE: "PC",
    c.DRUG_TEST: "DT",
    c.NEURO_EXAM: "NP",
    c.BASIC_COURSE: "BSGC",
}

ISSUERS = {
    c.LESP_LICENSE: "PNP SOSIA",
    c.NBI_CLEARANCE: "National Bureau of Investigation",
    c.POLICE_CLEARANCE: "Davao City Police Office",
    c.DRUG_TEST: "Mindanao Drug Testing Center",
    c.NEURO_EXAM: "Davao Neuro-Psych Clinic",
    c.BASIC_COURSE: "Southern Mindanao Security Academy",
}

RESULTS = {
    c.DRUG_TEST: "Negative",
    c.NEURO_EXAM: "Fit for duty",
}

# One dictionary per guard.
# "problems": documents that differ from HEALTHY_DAYS_LEFT.
#   A number is days left (negative means already expired). None means not on file.
# "postings": (site, post, started days ago, ended days ago or None if still open)
# "late" and "absent": chances used to make the attendance mix.
# "evaluations": (days ago, (discipline, attitude, appearance, honesty, alertness), remarks)
GUARDS = [
    {
        "employee_no": "GR-0001", "first": "Juan", "last": "Dela Cruz", "login": "guard1",
        "guard_type": "Unarmed Security Guard", "rank": "Security Guard",
        "born": date(1995, 4, 12), "hired_days_ago": 1100,
        "phone": "09171234501", "address": "Purok 3, Talomo, Davao City",
        "sss": "34-1234501-1", "tin": "301-234-501-000", "philhealth": "12-345678501-1",
        "problems": {},
        "postings": [
            ("Northgate Corporate Center", "Main Lobby", 150, 21),
            ("Bayview Mall", "Mall Entrance A", 21, None),
        ],
        "late": 0.08, "absent": 0.02,
        "evaluations": [
            (75, (5, 5, 4, 5, 4), "Neat and reliable. Polite to visitors."),
            (40, (5, 4, 5, 5, 4), "Handled a lost child case calmly."),
            (5, (5, 5, 5, 5, 4), "Settled in well after the transfer."),
        ],
    },
    {
        "employee_no": "GR-0002", "first": "Mario", "last": "Reyes",
        "guard_type": "Armed Security Guard", "rank": "Head Guard",
        "born": date(1988, 9, 3), "hired_days_ago": 1500,
        "phone": "09181234502", "address": "Buhangin, Davao City",
        "sss": "34-1234502-2", "tin": "301-234-502-000", "philhealth": "12-345678502-2",
        "problems": {},
        "postings": [("Northgate Corporate Center", "Main Lobby", 200, None)],
        "late": 0.15, "absent": 0.04,
        "evaluations": [
            (70, (4, 4, 4, 5, 4), "Steady performer."),
            (10, (4, 5, 4, 5, 5), "Alert during lobby checks."),
        ],
    },
    {
        "employee_no": "GR-0003", "first": "Joel", "last": "Mendoza",
        "guard_type": "Security Officer", "rank": "Shift-in-Charge",
        "born": date(1985, 1, 22), "hired_days_ago": 2000,
        "phone": "09191234503", "address": "Matina, Davao City",
        "sss": "34-1234503-3", "tin": "301-234-503-000", "philhealth": "12-345678503-3",
        "problems": {},
        "postings": [("Bayview Mall", "Stockroom", 30, None)],
        "late": 0.03, "absent": 0.0,
        "evaluations": [
            (60, (5, 4, 5, 5, 5), "Clear and complete incident reports."),
            (15, (5, 5, 5, 5, 5), "Strong leader on the night shift."),
        ],
    },
    {
        "employee_no": "GR-0004", "first": "Ricardo", "last": "Santos",
        "guard_type": "Unarmed Security Guard", "rank": "Security Guard",
        "born": date(1992, 6, 15), "hired_days_ago": 900,
        "phone": "09201234504", "address": "Toril, Davao City",
        "sss": "34-1234504-4", "tin": "301-234-504-000", "philhealth": "12-345678504-4",
        "problems": {c.LESP_LICENSE: 45},  # inside the 60 day band
        "postings": [("Bayview Mall", "Stockroom", 200, 30)],
        "late": 0.30, "absent": 0.08,
        "evaluations": [
            (80, (3, 4, 4, 4, 3), "Late several times. Reminded about punctuality."),
            (50, (3, 3, 4, 4, 3), "Still late on some duties."),
            (35, (4, 4, 4, 4, 4), "Improving."),
        ],
    },
    {
        "employee_no": "GR-0005", "first": "Elmer", "last": "Bautista",
        "guard_type": "Armed Security Guard", "rank": "Security Guard",
        "born": date(1990, 11, 30), "hired_days_ago": 700,
        "phone": "09211234505", "address": "Agdao, Davao City",
        "sss": "34-1234505-5", "tin": "301-234-505-000", "philhealth": "12-345678505-5",
        "problems": {c.DRUG_TEST: 20},  # inside the 30 day band
        "postings": [("Northgate Corporate Center", "Main Lobby", 21, None)],
        "late": 0.20, "absent": 0.05,
        "evaluations": [
            (50, (4, 3, 3, 4, 4), "Uniform needs attention."),
            (12, (4, 4, 4, 4, 4), "Better appearance this month."),
        ],
    },
    {
        "employee_no": "GR-0006", "first": "Rowena", "last": "Villanueva",
        "guard_type": "Lady Security Guard", "rank": "Security Guard",
        "born": date(1993, 2, 8), "hired_days_ago": 1300,
        "phone": "09221234506", "address": "Sasa, Davao City",
        "sss": "34-1234506-6", "tin": "301-234-506-000", "philhealth": "12-345678506-6",
        # NBI expired 10 days ago. Drug test inside the 14 day band.
        "problems": {c.NBI_CLEARANCE: -10, c.DRUG_TEST: 10},
        "postings": [("Bayview Mall", "Mall Entrance A", 300, 10)],
        "late": 0.10, "absent": 0.05,
        "evaluations": [
            (65, (5, 5, 5, 5, 4), "Courteous and firm at the entrance."),
            (20, (4, 5, 5, 5, 4), "Good bag inspection procedure."),
        ],
    },
    {
        "employee_no": "GR-0007", "first": "Danilo", "last": "Ocampo",
        "guard_type": "Armed Security Guard", "rank": "Security Guard",
        "born": date(1983, 8, 19), "hired_days_ago": 1800,
        "phone": "09231234507", "address": "Panacan, Davao City",
        "sss": "34-1234507-7", "tin": "301-234-507-000", "philhealth": "12-345678507-7",
        # Neuro-psych expired 5 days ago. Police clearance inside the 7 day band.
        "problems": {c.NEURO_EXAM: -5, c.POLICE_CLEARANCE: 5},
        "postings": [("Northgate Corporate Center", "Basement Parking", 250, 5)],
        "late": 0.35, "absent": 0.12,
        "evaluations": [
            (90, (3, 3, 3, 4, 3), "Needs closer supervision."),
            (30, (2, 3, 3, 4, 3), "Found resting on duty once. Warned."),
        ],
    },
    {
        "employee_no": "GR-0008", "first": "Arnel", "last": "Padilla",
        "guard_type": "Unarmed Security Guard", "rank": "Security Guard",
        "born": date(1999, 12, 1), "hired_days_ago": 120,
        "phone": "09241234508", "address": "Bunawan, Davao City",
        "sss": "34-1234508-8", "tin": "301-234-508-000", "philhealth": "12-345678508-8",
        # Police clearance not on file. LESP inside the 1 day band.
        "problems": {c.POLICE_CLEARANCE: None, c.LESP_LICENSE: 1},
        "postings": [("Bayview Mall", "Mall Entrance A", 80, 22)],
        "late": 0.25, "absent": 0.10,
        "evaluations": [],
    },
]

# Past renewals: (employee no, document). The old version is kept.
RENEWALS = [
    ("GR-0001", c.NBI_CLEARANCE),
    ("GR-0003", c.DRUG_TEST),
]

# The last 4 weeks of duty are recorded for each guard.
DUTY_DAYS = 28


class Command(BaseCommand):
    help = "Create the GuardReady demo data. Safe to run more than once."

    @transaction.atomic
    def handle(self, *args, **options):
        self.today = timezone.localdate()
        self.create_groups()
        self.users = self.create_users()
        self.posts = self.create_sites()

        created = 0
        for data in GUARDS:
            if Guard.objects.filter(employee_no=data["employee_no"]).exists():
                continue
            self.create_guard(data)
            created += 1

        counts = readiness_counts(Guard.objects.prefetch_related("credentials"))
        self.stdout.write(self.style.SUCCESS(f"Done. {created} new guards created."))
        for level, count in counts.items():
            self.stdout.write(f"  {level}: {count}")

    # --- Groups and users ---

    def create_groups(self):
        """One group per role, with exactly the permissions in accounts/roles.py."""
        for role, permission_names in ROLE_PERMISSIONS.items():
            group, _ = Group.objects.get_or_create(name=role)
            group.permissions.set([find_permission(name) for name in permission_names])

    def create_users(self):
        users = {}
        for username, password, role, first, last in ACCOUNTS:
            user, created = User.objects.get_or_create(
                username=username, defaults={"first_name": first, "last_name": last}
            )
            if created:
                user.set_password(password)  # Django's built-in hashing
                user.save()
            user.groups.set([Group.objects.get(name=role)])
            users[username] = user
        return users

    # --- Sites and posts ---

    def create_sites(self):
        posts = {}
        for site_name, (address, post_list) in SITES.items():
            site, _ = ClientSite.objects.get_or_create(name=site_name, defaults={"address": address})
            for post_name, shift, headcount in post_list:
                post, _ = Post.objects.get_or_create(
                    site=site, name=post_name, defaults={"shift": shift, "headcount": headcount}
                )
                posts[(site_name, post_name)] = post
        return posts

    # --- One guard with everything that belongs to him ---

    def create_guard(self, data):
        login = data.get("login")
        guard = Guard.objects.create(
            employee_no=data["employee_no"],
            first_name=data["first"],
            last_name=data["last"],
            guard_type=data["guard_type"],
            rank=data["rank"],
            birth_date=data["born"],
            date_hired=self.days_ago(data["hired_days_ago"]),
            contact_number=data["phone"],
            home_address=data["address"],
            sss_number=data["sss"],
            tin_number=data["tin"],
            philhealth_number=data["philhealth"],
            user=self.users[login] if login else None,
        )
        self.create_credentials(guard, data)
        self.create_postings(guard, data)
        self.create_attendance(guard, data)
        self.create_evaluations(guard, data)

    def create_credentials(self, guard, data):
        for doc_type in c.REQUIRED_DOCUMENTS:
            days_left = data["problems"].get(doc_type, HEALTHY_DAYS_LEFT[doc_type])
            if days_left is None:
                continue  # not on file
            expires = self.today + timedelta(days=days_left)
            issued = add_months(expires, -validity_months(doc_type))
            number = make_number(doc_type, guard, expires.year)

            if (guard.employee_no, doc_type) in RENEWALS:
                self.add_with_past_renewal(guard, doc_type, number, issued, expires)
            else:
                guard.add_credential(
                    doc_type, number, issued, expires, ISSUERS[doc_type], RESULTS.get(doc_type, "")
                )

    def add_with_past_renewal(self, guard, doc_type, number, issued, expires):
        """Add the older document first, then renew it on the new issue date."""
        old_expires = issued + timedelta(days=3)
        old_issued = add_months(old_expires, -validity_months(doc_type))
        old_number = make_number(doc_type, guard, old_expires.year) + "-OLD"
        result = RESULTS.get(doc_type, "")
        credential = guard.add_credential(
            doc_type, old_number, old_issued, old_expires, ISSUERS[doc_type], result
        )
        renewed_at = timezone.make_aware(datetime.combine(issued, time(9, 0)))
        credential.renew(number, issued, expires, self.users["admin"], changed_at=renewed_at)

    def create_postings(self, guard, data):
        for site_name, post_name, started, ended in data["postings"]:
            post = self.posts[(site_name, post_name)]
            assignment = Assignment.start(
                guard, post, self.users["commander"], start_date=self.days_ago(started)
            )
            if ended is not None:
                assignment.close(self.days_ago(ended))

    def create_attendance(self, guard, data):
        """The last 4 weeks the guard was posted. Sundays are rest days."""
        chance = random.Random(guard.employee_no)  # same "random" mix every time
        for day, post in self.last_duty_days(guard):
            if day.weekday() == 6:
                continue
            start = post.scheduled_start()
            absent = chance.random() < data["absent"]
            late = not absent and chance.random() < data["late"]
            AttendanceRecord.objects.create(
                guard=guard,
                date=day,
                post=post,
                scheduled_start=start,
                time_in=None if absent else make_time_in(chance, day, start, late),
                absent=absent,
                recorded_by=self.users["commander"],
            )

    def last_duty_days(self, guard):
        """(day, post) pairs for the last DUTY_DAYS days the guard was posted."""
        days = []
        for assignment in guard.assignments.all():
            if assignment.end_date:
                last_day = assignment.end_date - timedelta(days=1)
            else:
                last_day = self.today - timedelta(days=1)
            day = assignment.start_date
            while day <= last_day:
                days.append((day, assignment.post))
                day += timedelta(days=1)
        days.sort(key=lambda pair: pair[0], reverse=True)
        return days[:DUTY_DAYS]

    def create_evaluations(self, guard, data):
        for index, (days_ago, scores, remarks) in enumerate(data["evaluations"]):
            discipline, attitude, appearance, honesty, alertness = scores
            evaluator = self.users["admin"] if index == 0 else self.users["commander"]
            Evaluation.objects.create(
                guard=guard,
                date=self.days_ago(days_ago),
                evaluator=evaluator,
                discipline=discipline,
                attitude=attitude,
                appearance=appearance,
                honesty=honesty,
                alertness=alertness,
                remarks=remarks,
            )

    def days_ago(self, days):
        return self.today - timedelta(days=days)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def find_permission(full_name):
    """Turn "guards.view_dashboard" into the Permission row."""
    app_label, codename = full_name.split(".")
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def validity_months(doc_type):
    """Ask the right proxy class (License, MedicalCert, ...) for its validity."""
    sample = Credential(kind=c.DOCUMENT_KINDS[doc_type], doc_type=doc_type).typed()
    return sample.validity_months()


def make_number(doc_type, guard, year):
    """A demo document number, for example LESP-2027-0001."""
    return f"{NUMBER_PREFIX[doc_type]}-{year}-{guard.employee_no[-4:]}"


def make_time_in(chance, day, start, late):
    """On time: up to 20 minutes early or inside the grace period. Late: 6 to 45 minutes."""
    if late:
        minutes = chance.randint(LATE_GRACE_MINUTES + 1, 45)
    else:
        minutes = chance.randint(-20, LATE_GRACE_MINUTES)
    return (datetime.combine(day, start) + timedelta(minutes=minutes)).time()

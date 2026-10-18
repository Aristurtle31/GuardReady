"""
Tests for the audit app: the Security alerts page (Part 2, Oct 13, 2026) and
the guard history classes in audit/history.py (Stage 3).

The rule tests build unsaved AuditEntry objects with chosen times, because a
saved entry always gets the current time (auto_now_add). The page tests use
the real login, step-up, profile and audit log pages.

Run with: python manage.py test audit
"""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import ADMIN, GUARD
from deployment.models import Post
from guards import constants as gc
from guards.dates import long_date
from guards.models import CredentialVersion, Guard

from . import constants as c
from .alerts import (
    AfterHoursRule,
    Alert,
    BulkViewingRule,
    FailedLoginRule,
    ManyUnlocksRule,
    RepeatedDenialRule,
    philippine_time,
    staff_roles,
)
from .history import (
    HISTORY_EVENTS,
    AssignmentEvent,
    CredentialEvent,
    HistoryEvent,
    NoticeEvent,
    RefusedAssignmentEvent,
    history_for,
)
from .models import AuditEntry

# Monday, October 12, 2026, midnight, in Philippine time.
MONDAY = datetime(2026, 10, 12, tzinfo=c.PH_TIME_ZONE)
MONDAY_10_AM = MONDAY.replace(hour=10)
SUNDAY_10_AM = MONDAY_10_AM - timedelta(days=1)
SATURDAY_10_AM = MONDAY_10_AM + timedelta(days=5)
WRONG_PASSWORD = "Wrong-Pass-4821"


def seed():
    """Build the demo data quietly."""
    call_command("seed_demo", stdout=StringIO())


def entry(
    action, at, username="admin", role=ADMIN, outcome=AuditEntry.SUCCESS, user_id=1, details=""
):
    """An unsaved AuditEntry with a chosen time. The rules only read entries."""
    return AuditEntry(
        timestamp=at,
        username=username,
        role=role,
        action=action,
        outcome=outcome,
        user_id=user_id,
        details=details,
    )


def failed_login(at, username="juan"):
    """What login_view writes for a wrong password: the typed username and no user."""
    return entry(
        AuditEntry.LOGIN,
        at,
        username=username,
        role="Anonymous",
        outcome=AuditEntry.DENIED,
        user_id=None,
        details="Wrong username or password.",
    )


def refusal(at):
    """A DENY entry for a logged-in user."""
    return entry(AuditEntry.DENY, at, outcome=AuditEntry.DENIED, details="Refused. (GET /audit/)")


def unlock(at):
    """A good step-up."""
    return entry(AuditEntry.STEP_UP, at, details="Reason: checking documents")


def profile_view(at):
    """What the audit middleware writes when a guard profile opens."""
    return entry(AuditEntry.VIEW, at, details=f"GET {reverse('guard_profile', args=[3])}")


def spread(make, count, minutes, start=MONDAY_10_AM):
    """count entries spread evenly from start to start + minutes."""
    span = timedelta(minutes=minutes)
    gaps = max(count - 1, 1)
    return [make(start + span * i / gaps) for i in range(count)]


class ThresholdRuleTests(SimpleTestCase):
    """Each counting rule fires at its threshold and not one below it."""

    def assert_threshold(self, rule, make):
        # THRESHOLD entries, the last one exactly at the end of the window: one alert.
        alerts = rule.find(spread(make, rule.THRESHOLD, rule.WINDOW_MINUTES))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].count, rule.THRESHOLD)
        self.assertEqual(alerts[0].username, make(MONDAY_10_AM).username)
        # One below the threshold: nothing.
        self.assertEqual(rule.find(spread(make, rule.THRESHOLD - 1, rule.WINDOW_MINUTES)), [])
        # The same number, spread one minute wider than the window: nothing.
        self.assertEqual(rule.find(spread(make, rule.THRESHOLD, rule.WINDOW_MINUTES + 1)), [])

    def test_failed_logins_fire_at_the_threshold_and_not_one_below(self):
        self.assert_threshold(FailedLoginRule(), failed_login)

    def test_repeated_refusals_fire_at_the_threshold_and_not_one_below(self):
        self.assert_threshold(RepeatedDenialRule(), refusal)

    def test_many_unlocks_fire_at_the_threshold_and_not_one_below(self):
        self.assert_threshold(ManyUnlocksRule(), unlock)

    def test_bulk_viewing_fires_at_the_threshold_and_not_one_below(self):
        self.assert_threshold(BulkViewingRule(), profile_view)

    def test_each_typed_username_is_counted_on_its_own(self):
        rule = FailedLoginRule()
        below = rule.THRESHOLD - 1
        maria = spread(lambda at: failed_login(at, "maria"), below, 5)
        entries = spread(failed_login, below, 5) + maria
        self.assertEqual(rule.find(entries), [])

    def test_a_good_login_is_not_a_failed_login(self):
        rule = FailedLoginRule()
        good_logins = spread(lambda at: entry(AuditEntry.LOGIN, at), rule.THRESHOLD, 5)
        self.assertEqual(rule.find(good_logins), [])

    def test_refusals_of_visitors_who_are_not_logged_in_do_not_count(self):
        def visitor(at):
            return entry(
                AuditEntry.DENY,
                at,
                username="anonymous",
                role="Anonymous",
                outcome=AuditEntry.DENIED,
                user_id=None,
            )

        rule = RepeatedDenialRule()
        self.assertEqual(rule.find(spread(visitor, rule.THRESHOLD * 2, 5)), [])

    def test_a_wrong_password_at_step_up_counts_as_an_unlock_try(self):
        def wrong_password(at):
            return entry(AuditEntry.STEP_UP, at, outcome=AuditEntry.DENIED)

        rule = ManyUnlocksRule()
        self.assertEqual(len(rule.find(spread(wrong_password, rule.THRESHOLD, 60))), 1)

    def test_bulk_viewing_counts_only_the_profile_page(self):
        rule = BulkViewingRule()
        for path in [
            reverse("edit_guard", args=[3]),
            reverse("change_status", args=[3]),
            reverse("guard_list"),
            "/not-a-page/",
        ]:
            with self.subTest(path=path):
                def other_page(at):
                    return entry(AuditEntry.VIEW, at, details=f"GET {path}")

                views = spread(other_page, rule.THRESHOLD, 1)
                self.assertEqual(rule.find(views), [])
        # A profile opened with a query string still counts.
        profile = f"GET {reverse('guard_profile', args=[3])}?page=2"
        views = spread(lambda at: entry(AuditEntry.VIEW, at, details=profile), rule.THRESHOLD, 1)
        self.assertEqual(len(rule.find(views)), 1)

    def test_one_long_burst_is_one_alert_with_its_full_count(self):
        rule = FailedLoginRule()
        entries = spread(failed_login, rule.THRESHOLD * 2, rule.WINDOW_MINUTES)
        alerts = rule.find(list(reversed(entries)))  # the order of the entries does not matter
        self.assertEqual([alert.count for alert in alerts], [rule.THRESHOLD * 2])

    def test_counting_starts_again_after_an_alert(self):
        rule = FailedLoginRule()
        later = MONDAY_10_AM + timedelta(minutes=rule.WINDOW_MINUTES * 2)
        first = spread(failed_login, rule.THRESHOLD, 1)
        second = spread(failed_login, rule.THRESHOLD, 1, start=later)
        alerts = rule.find(first + second)
        self.assertEqual([alert.count for alert in alerts], [rule.THRESHOLD, rule.THRESHOLD])


class AfterHoursRuleTests(SimpleTestCase):
    """Staff activity outside office hours, in Philippine time. Guards are never checked."""

    rule = AfterHoursRule()

    def admin_at(self, at):
        return entry(AuditEntry.VIEW, at, details="GET /dashboard/")

    def guard_at(self, at):
        return entry(
            AuditEntry.VIEW, at, username="guard1", role=GUARD, user_id=2, details="GET /guards/me/"
        )

    def test_a_guard_at_2_am_does_not_fire_but_an_admin_does(self):
        two_am = MONDAY.replace(hour=2)
        self.assertEqual(self.rule.find([self.guard_at(two_am)]), [])
        alerts = self.rule.find([self.admin_at(two_am)])
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].username, "admin")
        self.assertEqual(alerts[0].window_text, "October 12, 2026, 2:00:00 AM")

    def test_staff_roles_come_from_the_permission(self):
        self.assertIn(ADMIN, staff_roles())
        self.assertNotIn(GUARD, staff_roles())

    def test_utc_timestamps_are_read_in_philippine_time(self):
        # 11:30 UTC is 7:30 PM in Manila (closed). 10:30 UTC is 6:30 PM (open).
        evening = datetime(2026, 10, 12, 11, 30, tzinfo=dt_timezone.utc)
        afternoon = datetime(2026, 10, 12, 10, 30, tzinfo=dt_timezone.utc)
        with timezone.override("UTC"):
            alerts = self.rule.find([self.admin_at(evening), self.admin_at(afternoon)])
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0].count, 1)
            self.assertEqual(alerts[0].window_text, "October 12, 2026, 7:30:00 PM")

    def test_office_hours_edges_and_days(self):
        cases = [
            (MONDAY.replace(hour=6, minute=59), 1),
            (MONDAY.replace(hour=7), 0),
            (MONDAY.replace(hour=18, minute=59), 0),
            (MONDAY.replace(hour=19), 1),
            (SATURDAY_10_AM, 0),
            (SUNDAY_10_AM, 1),
        ]
        for moment, expected in cases:
            with self.subTest(moment=moment):
                self.assertEqual(len(self.rule.find([self.admin_at(moment)])), expected)

    def test_early_morning_and_evening_are_separate_alerts(self):
        entries = [self.admin_at(MONDAY.replace(hour=hour)) for hour in (5, 6, 20, 21, 22)]
        alerts = sorted(self.rule.find(entries), key=lambda alert: alert.start)
        self.assertEqual([alert.count for alert in alerts], [2, 3])
        self.assertEqual(alerts[1].window_text, "October 12, 2026, 8:00:00 PM to 10:00:00 PM")


class AlertTests(SimpleTestCase):
    """An Alert is read only, shows Philippine time, and links to the audit log filters."""

    def test_an_alert_cannot_be_changed(self):
        nine_minutes_later = MONDAY_10_AM + timedelta(minutes=9)
        alert = Alert(FailedLoginRule(), "juan", MONDAY_10_AM, nine_minutes_later, 5)
        for name in ["rule", "username", "start", "end", "count"]:
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(alert, name, None)
        self.assertEqual(
            str(alert),
            "Failed logins: juan, 5 entries, October 12, 2026, 10:00:00 AM to 10:09:00 AM",
        )

    def test_entries_in_the_same_second_show_one_time(self):
        a_moment_later = MONDAY_10_AM + timedelta(milliseconds=300)
        alert = Alert(RepeatedDenialRule(), "guard1", MONDAY_10_AM, a_moment_later, 3)
        self.assertEqual(alert.window_text, "October 12, 2026, 10:00:00 AM")

    def test_a_window_that_crosses_midnight_links_to_both_days(self):
        start = MONDAY.replace(hour=23, minute=55)
        alert = Alert(FailedLoginRule(), "juan", start, start + timedelta(minutes=10), 5)
        self.assertEqual(
            alert.window_text, "October 12, 2026, 11:55:00 PM to October 13, 2026, 12:05:00 AM"
        )
        self.assertEqual(
            alert.audit_log_links(),
            [
                ("October 12, 2026", "user=juan&action=LOGIN&date=2026-10-12"),
                ("October 13, 2026", "user=juan&action=LOGIN&date=2026-10-13"),
            ],
        )

    def test_after_hours_links_do_not_filter_by_action(self):
        eight_pm = MONDAY.replace(hour=20)
        alert = Alert(AfterHoursRule(), "admin", eight_pm, eight_pm, 1)
        self.assertEqual(
            alert.audit_log_links(), [("October 12, 2026", "user=admin&date=2026-10-12")]
        )


class SecurityAlertsPageTests(TestCase):
    """The Security alerts page, with the real login, step-up, profile and audit log pages."""

    @classmethod
    def setUpTestData(cls):
        seed()
        cls.guard = Guard.objects.get(user__username="guard1")

    def log_in(self, username="admin", password="admin123"):
        self.assertTrue(self.client.login(username=username, password=password))

    def fail_login(self, username, times):
        for _ in range(times):
            self.client.post(reverse("login"), {"username": username, "password": WRONG_PASSWORD})

    def open_alerts(self):
        response = self.client.get(reverse("security_alerts"))
        self.assertEqual(response.status_code, 200)
        return response

    def found(self, response, rule_class, username):
        """The alerts on the page from one rule, for one username."""
        return [
            alert
            for alert in response.context["alerts"]
            if isinstance(alert.rule, rule_class) and alert.username == username
        ]

    def test_a_quiet_week_shows_no_alerts(self):
        self.log_in()
        response = self.open_alerts()
        self.assertEqual(response.context["alerts"], [])
        self.assertContains(response, "No alerts.")

    def test_failed_logins_are_logged_without_the_password(self):
        self.fail_login("admin", 2)
        failed = AuditEntry.objects.filter(action=AuditEntry.LOGIN, outcome=AuditEntry.DENIED)
        self.assertEqual(failed.count(), 2)
        for logged in failed:
            self.assertIsNone(logged.user)
            self.assertEqual(logged.username, "admin")
        for logged in AuditEntry.objects.all():
            self.assertNotIn(WRONG_PASSWORD, str(vars(logged)))

    def test_five_failed_logins_show_an_alert_that_links_to_the_audit_log(self):
        threshold = FailedLoginRule.THRESHOLD
        self.fail_login("intruder", threshold - 1)
        self.log_in()
        self.assertEqual(self.found(self.open_alerts(), FailedLoginRule, "intruder"), [])

        self.client.logout()
        self.fail_login("intruder", 1)
        self.log_in()
        response = self.open_alerts()
        [alert] = self.found(response, FailedLoginRule, "intruder")
        self.assertEqual(alert.count, threshold)
        today = philippine_time(timezone.now()).date().isoformat()
        query = f"user=intruder&action=LOGIN&date={today}"
        link = f'href="{reverse("audit_log")}?{query.replace("&", "&amp;")}"'
        self.assertContains(response, link)

        # The link uses the audit log's own filters, and it finds those entries.
        response = self.client.get(f"{reverse('audit_log')}?{query}")
        self.assertEqual(response.context["page"].paginator.count, threshold)

    def test_bulk_viewing_counts_real_profile_views(self):
        self.log_in()
        for _ in range(BulkViewingRule.THRESHOLD):
            self.client.get(reverse("guard_profile", args=[self.guard.pk]))
        response = self.open_alerts()
        [alert] = self.found(response, BulkViewingRule, "admin")
        self.assertEqual(alert.count, BulkViewingRule.THRESHOLD)
        # Usernames, times and counts only. Nothing about the guard who was opened.
        self.assertNotContains(response, self.guard.employee_no)
        self.assertNotContains(response, self.guard.last_name)

    def test_repeated_refusals_count_real_refusals(self):
        self.log_in("guard1", "guard123")
        for _ in range(RepeatedDenialRule.THRESHOLD):
            self.assertEqual(self.client.get(reverse("audit_log")).status_code, 403)
        self.client.logout()
        self.log_in()
        [alert] = self.found(self.open_alerts(), RepeatedDenialRule, "guard1")
        self.assertEqual(alert.count, RepeatedDenialRule.THRESHOLD)

    def test_many_unlocks_never_show_the_reason_given(self):
        self.log_in()
        reason = "Checking his private file for the panel"
        for _ in range(ManyUnlocksRule.THRESHOLD):
            self.client.post(
                reverse("step_up", args=[self.guard.pk]), {"password": "admin123", "reason": reason}
            )
        response = self.open_alerts()
        [alert] = self.found(response, ManyUnlocksRule, "admin")
        self.assertEqual(alert.count, ManyUnlocksRule.THRESHOLD)
        # The reason is in the audit log, but never on the alerts page.
        self.assertTrue(AuditEntry.objects.filter(details__contains=reason).exists())
        self.assertNotContains(response, reason)

    def test_a_guard_at_2_am_does_not_fire_but_an_admin_does(self):
        yesterday = philippine_time(timezone.now()) - timedelta(days=1)
        two_am = yesterday.replace(hour=2, minute=0, second=0, microsecond=0)
        with mock.patch("django.utils.timezone.now", return_value=two_am):
            AuditEntry.objects.create(
                user=User.objects.get(username="admin"),
                username="admin",
                role=ADMIN,
                action=AuditEntry.VIEW,
                details="GET /dashboard/",
            )
            AuditEntry.objects.create(
                user=self.guard.user,
                username="guard1",
                role=GUARD,
                action=AuditEntry.VIEW,
                details="GET /guards/me/",
            )
        self.log_in()
        response = self.open_alerts()
        at_two_am = [
            alert
            for alert in response.context["alerts"]
            if isinstance(alert.rule, AfterHoursRule) and alert.start == two_am
        ]
        self.assertEqual([alert.username for alert in at_two_am], ["admin"])

    def test_entries_older_than_the_lookback_are_not_read(self):
        now = timezone.now()
        tries = [("old-guess", c.LOOKBACK_DAYS + 1), ("recent-guess", c.LOOKBACK_DAYS - 1)]
        for username, days_ago in tries:
            then = now - timedelta(days=days_ago)
            with mock.patch("django.utils.timezone.now", return_value=then):
                for _ in range(FailedLoginRule.THRESHOLD):
                    AuditEntry.objects.create(
                        username=username,
                        role="Anonymous",
                        action=AuditEntry.LOGIN,
                        outcome=AuditEntry.DENIED,
                    )
        self.log_in()
        response = self.open_alerts()
        self.assertEqual(self.found(response, FailedLoginRule, "old-guess"), [])
        self.assertEqual(len(self.found(response, FailedLoginRule, "recent-guess")), 1)

    def test_guard1_is_refused_on_the_alerts_page(self):
        self.log_in("guard1", "guard123")
        response = self.client.get(reverse("security_alerts"))
        self.assertEqual(response.status_code, 403)
        refused = AuditEntry.objects.first()
        self.assertEqual(refused.action, AuditEntry.DENY)
        self.assertEqual(refused.outcome, AuditEntry.DENIED)
        self.assertEqual(refused.username, "guard1")
        self.assertIn(reverse("security_alerts"), refused.details)

    def test_visitors_who_are_not_logged_in_are_sent_to_login(self):
        response = self.client.get(reverse("security_alerts"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('security_alerts')}")

    def test_opening_the_page_is_logged_as_a_view(self):
        self.log_in()
        self.open_alerts()
        opened = AuditEntry.objects.first()
        self.assertEqual(opened.action, AuditEntry.VIEW)
        self.assertEqual(opened.target_type, "SecurityAlerts")
        self.assertEqual(opened.username, "admin")

    def test_the_audit_log_links_to_the_alerts_page(self):
        self.log_in()
        response = self.client.get(reverse("audit_log"))
        self.assertContains(response, f'href="{reverse("security_alerts")}"')
        self.assertContains(response, "Security alerts")


# ---------------------------------------------------------------------------
# Stage 3: the guard history classes (audit/history.py)
# ---------------------------------------------------------------------------


class HistoryEventTests(TestCase):
    """Each HistoryEvent wraps one record, and history_for() puts them in order."""

    @classmethod
    def setUpTestData(cls):
        seed()
        cls.admin = User.objects.get(username="admin")

    def setUp(self):
        self.client.login(username="admin", password="admin123")

    def guard(self, employee_no):
        return Guard.objects.get(employee_no=employee_no)

    def assign(self, post_name, guard):
        """Pick a guard on the assign page, like HR does."""
        post = Post.objects.get(name=post_name)
        url = reverse("assign_to_post", args=[post.pk])
        return self.client.post(url, {"guard": guard.pk, "show": gc.SHOW_CURRENT})

    def events_of(self, guard, event_class):
        return [event for event in history_for(guard) if isinstance(event, event_class)]

    def test_the_base_class_cannot_be_used_on_its_own(self):
        with self.assertRaises(TypeError):
            HistoryEvent(None)
        self.assertEqual(
            HISTORY_EVENTS, [AssignmentEvent, RefusedAssignmentEvent, CredentialEvent, NoticeEvent]
        )
        for event_class in HISTORY_EVENTS:
            with self.subTest(event=event_class.__name__):
                self.assertTrue(issubclass(event_class, HistoryEvent))
                self.assertTrue(event_class.LABEL)

    def test_an_event_keeps_its_record_read_only(self):
        posting = self.guard("GR-0001").current_assignment()
        event = AssignmentEvent(posting)
        self.assertIs(event.record, posting)
        with self.assertRaises(AttributeError):
            event.record = None
        self.assertEqual(str(event), f"Posting: {event.describe()}")

    def test_juans_history_has_his_postings_and_his_nbi_renewal_newest_first(self):
        juan = self.guard("GR-0001")
        events = history_for(juan)
        kinds = [type(event) for event in events]
        self.assertEqual(kinds, [AssignmentEvent, AssignmentEvent, CredentialEvent])
        times = [event.when() for event in events]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertIn("Mall Entrance A", events[0].describe())
        self.assertIn("Still posted", events[0].describe())
        self.assertIn("Main Lobby", events[1].describe())

        version = CredentialVersion.objects.get(credential__guard=juan)
        nbi = juan.get_credential(gc.NBI_CLEARANCE)
        expected = f'Expiry date from "{long_date(version.old_expires)}" to "{long_date(nbi.expires)}"'
        self.assertIn(expected, events[2].describe())
        self.assertEqual(events[2].row()["by"], "Liza Ramos")

    def test_a_document_change_never_shows_the_medical_result(self):
        joel = self.guard("GR-0003")  # his drug test was renewed in the seed
        version = CredentialVersion.objects.get(credential__guard=joel)
        self.assertTrue(version.old_result)
        [event] = self.events_of(joel, CredentialEvent)
        self.assertIn("Drug Test renewed or corrected", event.describe())
        self.assertNotIn(version.old_result, str(event.row()))
        self.assertNotIn(joel.get_credential(gc.DRUG_TEST).result, str(event.row()))

    def test_each_change_shows_the_values_that_replaced_it(self):
        mario = self.guard("GR-0002")
        lesp = mario.get_credential(gc.LESP_LICENSE)
        expires = lesp.expires
        lesp.renew("LESP-A", lesp.issued, expires + timedelta(days=10), self.admin)
        lesp.renew("LESP-B", lesp.issued, expires + timedelta(days=20), self.admin)
        older, newer = sorted(self.events_of(mario, CredentialEvent), key=lambda event: event.record.pk)
        self.assertIn('to "LESP-A"', older.describe())
        self.assertIn(f'to "{long_date(expires + timedelta(days=10))}"', older.describe())
        self.assertIn('Number from "LESP-A" to "LESP-B"', newer.describe())

    def test_a_correction_that_keeps_the_number_and_dates_says_so(self):
        mario = self.guard("GR-0002")
        lesp = mario.get_credential(gc.LESP_LICENSE)
        lesp.renew(lesp.number, lesp.issued, lesp.expires, self.admin)
        [event] = self.events_of(mario, CredentialEvent)
        self.assertIn("the number and dates stayed the same", event.describe())

    def test_notices_show_their_status_and_urgent_ones_are_red(self):
        danilo_rows = [event.row() for event in self.events_of(self.guard("GR-0007"), NoticeEvent)]
        self.assertEqual(len(danilo_rows), 2)  # police clearance (1 week) and neuro exam (expired)
        for row in danilo_rows:
            with self.subTest(details=row["details"]):
                self.assertEqual(row["color"], "danger")
                self.assertIn("Notice status: New.", row["details"])
                self.assertEqual(row["by"], c.SYSTEM_ROLE)
        [elmer] = self.events_of(self.guard("GR-0005"), NoticeEvent)  # 1 month is not urgent
        self.assertEqual(elmer.row()["color"], NoticeEvent.COLOR)

    def test_a_refused_posting_shows_in_his_history_but_a_success_does_not(self):
        rowena, ricardo = self.guard("GR-0006"), self.guard("GR-0004")
        self.assign("Mall Entrance A", rowena)
        self.assign("Basement Parking", ricardo)

        newest = history_for(rowena)[0]
        self.assertIsInstance(newest, RefusedAssignmentEvent)
        row = newest.row()
        self.assertIn("Mall Entrance A", row["details"])
        self.assertIn("NBI Clearance expired on", row["details"])
        self.assertEqual((row["by"], row["color"]), ("Liza Ramos", "danger"))

        self.assertEqual(self.events_of(ricardo, RefusedAssignmentEvent), [])
        posted = history_for(ricardo)[0]
        self.assertIsInstance(posted, AssignmentEvent)
        self.assertIn("Basement Parking", posted.describe())
        self.assertIn("Still posted (0 days so far)", posted.describe())

    def test_a_posting_made_today_sorts_after_a_refusal_earlier_today(self):
        juan = self.guard("GR-0001")
        self.assign("Basement Parking", juan)  # refused: he is already posted
        self.client.post(reverse("end_posting", args=[juan.current_assignment().pk]))
        self.assign("Basement Parking", juan)  # now it works
        events = history_for(juan)
        self.assertEqual(
            [type(event) for event in events[:2]], [AssignmentEvent, RefusedAssignmentEvent]
        )
        self.assertIn("Basement Parking", events[0].describe())
        self.assertIn("to " + long_date(timezone.localdate()), events[2].describe())

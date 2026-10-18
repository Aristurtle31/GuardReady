"""
Tests for the deployment app (Stage 3): the posting rules, the Sites, post and
assign pages, End posting, and guard1 refused.

Run with: python manage.py test deployment

The demo data on a fresh seed:
- Basement Parking 0 of 1, Mall Entrance A 1 of 2 (Juan), Main Lobby 2 of 2
  (Mario, Elmer), Stockroom 1 of 1 (Joel).
- Not posted: Ricardo (Expiring soon, can be posted), Rowena (NBI expired),
  Danilo (neuro exam expired), Arnel (police clearance not on file), and
  Noel, who resigned.
"""

from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEntry, RecordLockedError
from guards import constants as c
from guards.models import Guard

from .models import Assignment, Post

ADMIN_LOGIN = {"username": "admin", "password": "admin123"}
GUARD_LOGIN = {"username": "guard1", "password": "guard123"}


def seed():
    """Build the demo data quietly."""
    call_command("seed_demo", stdout=StringIO())


def every_posting():
    """Every assignment's values, to prove that nothing changed."""
    return list(Assignment.objects.order_by("pk").values_list("pk", "guard_id", "post_id", "end_date"))


class DeploymentTestCase(TestCase):
    """Shared setup: the demo data and a few helpers."""

    @classmethod
    def setUpTestData(cls):
        seed()
        cls.admin = User.objects.get(username="admin")

    def setUp(self):
        self.today = timezone.localdate()

    def guard(self, employee_no):
        return Guard.objects.get(employee_no=employee_no)

    def post_named(self, name):
        return Post.objects.get(name=name)

    def go_on_leave(self, guard):
        guard.change_employment_status(c.ON_LEAVE, "Approved leave", self.today, self.admin)


class PostRuleTests(DeploymentTestCase):
    """Post.refusal_reasons(): every object answers for itself."""

    def test_a_deployable_guard_who_is_not_posted_can_go_to_an_open_post(self):
        ricardo = self.guard("GR-0004")  # Expiring soon still counts as deployable
        self.assertEqual(ricardo.readiness(), c.EXPIRING_SOON)
        self.assertEqual(self.post_named("Basement Parking").refusal_reasons(ricardo), [])

    def test_a_guard_who_is_not_cleared_is_refused_with_his_document_reasons(self):
        entrance = self.post_named("Mall Entrance A")
        rowena, arnel = self.guard("GR-0006"), self.guard("GR-0008")
        rowena_reasons = entrance.refusal_reasons(rowena)
        self.assertEqual(rowena_reasons, rowena.block_reasons())
        self.assertIn("NBI Clearance expired on", rowena_reasons[0])
        self.assertEqual(entrance.refusal_reasons(arnel), ["Police Clearance is not on file"])

    def test_on_leave_and_guards_who_left_are_refused_with_their_status_first(self):
        basement = self.post_named("Basement Parking")
        noel = self.guard("GR-0009")  # resigned in the seed
        self.assertEqual(basement.refusal_reasons(noel)[0], c.SEPARATED_REFUSAL)

        ricardo = self.guard("GR-0004")
        self.go_on_leave(ricardo)
        self.assertEqual(basement.refusal_reasons(ricardo), [c.ON_LEAVE_REFUSAL])

    def test_a_guard_who_is_already_posted_is_refused(self):
        juan = self.guard("GR-0001")
        reasons = self.post_named("Basement Parking").refusal_reasons(juan)
        self.assertEqual(reasons, ["Already posted at Bayview Mall, Mall Entrance A (Day)"])

    def test_a_full_post_is_refused(self):
        ricardo = self.guard("GR-0004")
        reasons = self.post_named("Main Lobby").refusal_reasons(ricardo)
        self.assertEqual(reasons, ["This post is full (2 of 2 posted)"])

    def test_open_slots(self):
        expected = {"Basement Parking": 1, "Mall Entrance A": 1, "Main Lobby": 0, "Stockroom": 0}
        for name, slots in expected.items():
            with self.subTest(post=name):
                self.assertEqual(self.post_named(name).open_slots(), slots)


class AssignPageTests(DeploymentTestCase):
    """The Sites, post and assign pages, as Admin/HR uses them."""

    def setUp(self):
        super().setUp()
        self.client.login(**ADMIN_LOGIN)

    def assign(self, post, guard, show=c.SHOW_CURRENT):
        """Pick a guard on the assign page and submit, like HR does."""
        url = reverse("assign_to_post", args=[post.pk])
        return self.client.post(url, {"guard": guard.pk, "show": show})

    def last_assign_entry(self):
        return AuditEntry.objects.filter(action=AuditEntry.ASSIGN).first()

    def test_the_sites_page_lists_every_site_and_post_with_its_slots(self):
        response = self.client.get(reverse("site_list"))
        self.assertEqual(response.status_code, 200)
        for text in ["Northgate Corporate Center", "Bayview Mall", "0 of 1", "1 of 2", "2 of 2",
                     "1 of 1", "Full", "1 open slot"]:
            with self.subTest(text=text):
                self.assertContains(response, text)
        for post in Post.objects.all():
            self.assertContains(response, reverse("post_detail", args=[post.pk]))
            self.assertContains(response, reverse("assign_to_post", args=[post.pk]))
        entry = AuditEntry.objects.first()
        self.assertEqual((entry.action, entry.target_type), (AuditEntry.VIEW, "ClientSite"))

    def test_the_admin_menu_has_the_sites_link(self):
        link = f'<a class="nav-link" href="{reverse("site_list")}">Sites</a>'
        self.assertContains(self.client.get(reverse("dashboard")), link, html=True)

    def test_the_post_page_shows_who_is_posted_now_and_before(self):
        entrance = self.post_named("Mall Entrance A")
        juan = self.guard("GR-0001")
        response = self.client.get(reverse("post_detail", args=[entrance.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([posting.guard for posting in response.context["current"]], [juan])
        past = {posting.guard.full_name for posting in response.context["past"]}
        self.assertEqual(past, {"Rowena Villanueva", "Arnel Padilla"})
        self.assertContains(response, reverse("end_posting", args=[juan.current_assignment().pk]))

    def test_the_assign_page_lists_current_guards_and_a_filter_for_guards_who_left(self):
        url = reverse("assign_to_post", args=[self.post_named("Basement Parking").pk])
        current = self.client.get(url)
        names = [row["guard"].full_name for row in current.context["rows"]]
        self.assertEqual(len(names), 8)
        self.assertNotIn("Noel Castillo", names)
        reasons = {row["guard"].employee_no: row["reasons"] for row in current.context["rows"]}
        self.assertEqual(reasons["GR-0004"], [])  # Ricardo shows "Yes"
        self.assertEqual(reasons["GR-0006"], self.guard("GR-0006").block_reasons())  # Rowena, "No"

        left = self.client.get(url, {"show": c.SHOW_LEFT})
        self.assertEqual([row["guard"].full_name for row in left.context["rows"]], ["Noel Castillo"])

    def test_a_deployable_guard_is_posted_from_today_and_logged(self):
        basement, ricardo = self.post_named("Basement Parking"), self.guard("GR-0004")
        response = self.assign(basement, ricardo)
        self.assertRedirects(response, reverse("post_detail", args=[basement.pk]))

        posting = ricardo.current_assignment()
        self.assertEqual(posting.post, basement)
        self.assertEqual(posting.start_date, self.today)
        self.assertEqual(posting.assigned_by, self.admin)
        self.assertTrue(basement.is_full())

        entry = self.last_assign_entry()
        self.assertEqual((entry.outcome, entry.target_type, entry.target_id),
                         (AuditEntry.SUCCESS, "Guard", str(ricardo.pk)))
        self.assertIn("Posted GR-0004 Ricardo Santos", entry.details)
        self.assertIn("Basement Parking", entry.details)

    def test_a_guard_who_is_not_deployable_is_refused_and_logged_as_denied(self):
        entrance, rowena = self.post_named("Mall Entrance A"), self.guard("GR-0006")
        before = every_posting()
        response = self.assign(entrance, rowena)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Refused. Rowena Villanueva cannot be posted here")
        self.assertEqual(response.context["reasons"], rowena.block_reasons())
        for reason in rowena.block_reasons():
            self.assertContains(response, f"<li>{reason}</li>", html=True)
        self.assertEqual(every_posting(), before)
        self.assertIsNone(rowena.current_assignment())

        entry = self.last_assign_entry()
        self.assertEqual((entry.outcome, entry.target_type, entry.target_id, entry.user),
                         (AuditEntry.DENIED, "Guard", str(rowena.pk), self.admin))
        self.assertIn("Reasons: NBI Clearance expired on", entry.details)

    def test_a_guard_who_left_is_refused_as_no_longer_employed(self):
        noel = self.guard("GR-0009")
        response = self.assign(self.post_named("Mall Entrance A"), noel, show=c.SHOW_LEFT)
        self.assertContains(response, c.SEPARATED_REFUSAL)
        # The page keeps the "Guards who left" list after the refusal.
        self.assertEqual(response.context["show"], c.SHOW_LEFT)
        self.assertContains(response, "Noel Castillo")
        self.assertIn(f"Reasons: {c.SEPARATED_REFUSAL}", self.last_assign_entry().details)
        self.assertIsNone(noel.current_assignment())

    def test_an_on_leave_guard_is_refused_as_on_leave(self):
        ricardo = self.guard("GR-0004")
        self.go_on_leave(ricardo)
        self.assign(self.post_named("Basement Parking"), ricardo)
        entry = self.last_assign_entry()
        self.assertEqual(entry.outcome, AuditEntry.DENIED)
        self.assertIn(f"Reasons: {c.ON_LEAVE_REFUSAL}.", entry.details)
        self.assertIsNone(ricardo.current_assignment())

    def test_a_full_post_and_a_guard_already_posted_are_refused(self):
        before = every_posting()
        self.assign(self.post_named("Main Lobby"), self.guard("GR-0004"))
        self.assertIn("This post is full (2 of 2 posted)", self.last_assign_entry().details)
        self.assign(self.post_named("Basement Parking"), self.guard("GR-0001"))
        self.assertIn("Already posted at Bayview Mall, Mall Entrance A (Day)",
                      self.last_assign_entry().details)
        self.assertEqual(every_posting(), before)

    def test_trying_again_never_overrides_a_refusal(self):
        entrance, rowena = self.post_named("Mall Entrance A"), self.guard("GR-0006")
        for _ in range(2):
            self.assign(entrance, rowena)
        self.assertIsNone(rowena.current_assignment())
        refused = AuditEntry.objects.filter(
            action=AuditEntry.ASSIGN, outcome=AuditEntry.DENIED, target_id=str(rowena.pk)
        )
        self.assertEqual(refused.count(), 2)

    def test_submitting_without_a_real_guard_is_refused_and_logged(self):
        basement = self.post_named("Basement Parking")
        url = reverse("assign_to_post", args=[basement.pk])
        cases = [({"show": c.SHOW_CURRENT}, "Pick a guard first."),
                 ({"guard": 99999, "show": c.SHOW_CURRENT}, "Pick a guard from the list.")]
        for data, message in cases:
            with self.subTest(message=message):
                response = self.client.post(url, data)
                self.assertContains(response, message)
                entry = self.last_assign_entry()
                self.assertEqual((entry.outcome, entry.target_type, entry.target_id),
                                 (AuditEntry.DENIED, "Post", str(basement.pk)))
        self.assertFalse(basement.active_assignments().exists())

    def test_end_posting_closes_it_today_once_and_logs_it(self):
        juan = self.guard("GR-0001")
        posting = juan.current_assignment()
        url = reverse("end_posting", args=[posting.pk])
        response = self.client.post(url)
        self.assertRedirects(response, reverse("post_detail", args=[posting.post_id]))
        posting.refresh_from_db()
        self.assertEqual(posting.end_date, self.today)
        self.assertIsNone(juan.current_assignment())
        entry = AuditEntry.objects.filter(action=AuditEntry.UPDATE).first()
        self.assertEqual((entry.outcome, entry.target_type, entry.target_id),
                         (AuditEntry.SUCCESS, "Assignment", str(posting.pk)))
        self.assertIn("Ended the posting of GR-0001 Juan Dela Cruz", entry.details)

        # A second try is refused and logged, and the end date stays.
        self.client.post(url)
        entry = AuditEntry.objects.filter(action=AuditEntry.UPDATE).first()
        self.assertEqual(entry.outcome, AuditEntry.DENIED)
        self.assertIn("already closed", entry.details)
        posting.refresh_from_db()
        self.assertEqual(posting.end_date, self.today)
        with self.assertRaises(RecordLockedError):
            posting.close()

    def test_end_posting_does_nothing_on_a_get(self):
        posting = self.guard("GR-0001").current_assignment()
        response = self.client.get(reverse("end_posting", args=[posting.pk]))
        self.assertEqual(response.status_code, 405)
        posting.refresh_from_db()
        self.assertIsNone(posting.end_date)

    def test_moving_a_guard_means_ending_his_posting_first(self):
        juan, basement = self.guard("GR-0001"), self.post_named("Basement Parking")
        self.assign(basement, juan)
        self.assertEqual(self.last_assign_entry().outcome, AuditEntry.DENIED)

        self.client.post(reverse("end_posting", args=[juan.current_assignment().pk]))
        response = self.assign(basement, juan)
        self.assertRedirects(response, reverse("post_detail", args=[basement.pk]))
        self.assertEqual(juan.current_assignment().post, basement)
        self.assertEqual(juan.assignments.count(), 3)  # Main Lobby, Mall Entrance A, Basement Parking


class GuardRefusedTests(DeploymentTestCase):
    """guard1 cannot open or use any deployment page."""

    def setUp(self):
        super().setUp()
        self.client.login(**GUARD_LOGIN)

    def test_guard1_is_refused_on_every_deployment_page(self):
        before = every_posting()
        juan_posting = self.guard("GR-0001").current_assignment()
        basement = self.post_named("Basement Parking")
        pages = [
            reverse("site_list"),
            reverse("post_detail", args=[basement.pk]),
            reverse("assign_to_post", args=[basement.pk]),
        ]
        attempts = [(self.client.get, url) for url in pages] + [
            (self.client.post, reverse("assign_to_post", args=[basement.pk])),
            (self.client.post, reverse("end_posting", args=[juan_posting.pk])),
        ]
        for method, url in attempts:
            with self.subTest(url=url, method=method.__name__):
                response = method(url, {"guard": self.guard("GR-0004").pk})
                self.assertEqual(response.status_code, 403)
                entry = AuditEntry.objects.first()
                self.assertEqual((entry.action, entry.username), (AuditEntry.DENY, "guard1"))
        self.assertEqual(every_posting(), before)
        self.assertFalse(AuditEntry.objects.filter(action=AuditEntry.ASSIGN).exists())

    def test_guard1_has_no_sites_link_and_no_post_links_on_his_profile(self):
        juan = self.guard("GR-0001")
        response = self.client.get(reverse("guard_profile", args=[juan.pk]))
        self.assertEqual(response.status_code, 200)
        post_url = reverse("post_detail", args=[juan.current_assignment().post_id])
        self.assertNotContains(response, reverse("site_list"))
        self.assertNotContains(response, post_url)
        self.assertContains(response, "Mall Entrance A")  # his own Postings table

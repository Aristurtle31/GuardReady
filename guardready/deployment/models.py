"""
Deployment app models: client sites, posts, and assignments.

COMPOSITION: a ClientSite owns its Posts.
AGGREGATION: a Post holds Guards through Assignments. The guards exist on
their own and move between posts.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from audit.models import RecordLockedError

from .constants import SHIFT_CHOICES, SHIFT_START_TIMES


class ClientSite(models.Model):
    """A client of the agency, for example a mall or an office building."""

    name = models.CharField(max_length=100, unique=True)
    address = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def needed(self):
        """How many guards all posts of this site need."""
        return sum(post.headcount for post in self.posts.all())

    def filled(self):
        """How many guards are posted at this site right now."""
        return sum(post.filled_count() for post in self.posts.all())


class Post(models.Model):
    """One guard post inside a site, for example Main Lobby, day shift."""

    site = models.ForeignKey(ClientSite, on_delete=models.PROTECT, related_name="posts")
    name = models.CharField(max_length=100)
    shift = models.CharField(max_length=10, choices=SHIFT_CHOICES)
    headcount = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["site__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "name"], name="unique_post_per_site"),
        ]

    def __str__(self):
        return f"{self.site.name}, {self.name} ({self.shift})"

    def scheduled_start(self):
        """The time this post's shift starts."""
        return SHIFT_START_TIMES[self.shift]

    def active_assignments(self):
        return self.assignments.filter(end_date__isnull=True)

    def filled_count(self):
        return self.active_assignments().count()

    def is_full(self):
        return self.filled_count() >= self.headcount


class Assignment(models.Model):
    """
    One guard at one post from a start date to an end date.
    The end date can be set only once. Nothing else can ever change.
    """

    guard = models.ForeignKey("guards.Guard", on_delete=models.PROTECT, related_name="assignments")
    post = models.ForeignKey(Post, on_delete=models.PROTECT, related_name="assignments")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assignments_made"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "-id"]
        default_permissions = ("add", "view")
        permissions = [("assign_guard", "Can assign a guard to a post")]

    def __str__(self):
        return f"{self.guard} at {self.post}"

    @classmethod
    def start(cls, guard, post, by_user, start_date=None):
        """
        Open a new assignment. Only assign_guard() and seed_demo call this.
        assign_guard() does the readiness check first.
        """
        return cls.objects.create(
            guard=guard,
            post=post,
            assigned_by=by_user,
            start_date=start_date or timezone.localdate(),
        )

    def close(self, end_date=None):
        """ENCAPSULATION: set the end date. This works only once."""
        if self.end_date is not None:
            raise RecordLockedError("This assignment is already closed.")
        end_date = end_date or timezone.localdate()
        if end_date < self.start_date:
            raise ValidationError("The end date cannot be before the start date.")
        self.end_date = end_date
        self.save()

    def is_open(self):
        return self.end_date is None

    def days_served(self):
        """Days from the start date to the end date (or today if still open)."""
        last_day = self.end_date or timezone.localdate()
        return (last_day - self.start_date).days

    def save(self, *args, **kwargs):
        """Block every change except closing an open assignment."""
        if not self._state.adding:
            old = Assignment.objects.get(pk=self.pk)
            if old.end_date is not None:
                raise RecordLockedError("A closed assignment cannot be changed.")
            old_values = (old.guard_id, old.post_id, old.start_date, old.assigned_by_id)
            new_values = (self.guard_id, self.post_id, self.start_date, self.assigned_by_id)
            if old_values != new_values:
                raise RecordLockedError("Only the end date of an assignment can be set.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RecordLockedError("Assignments cannot be deleted.")

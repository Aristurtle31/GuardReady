"""Read-only admin screens for the superuser."""

from django.contrib import admin

from audit.admin import ReadOnlyAdmin

from .models import Assignment, ClientSite, Post


@admin.register(ClientSite)
class ClientSiteAdmin(ReadOnlyAdmin):
    list_display = ["name", "address"]


@admin.register(Post)
class PostAdmin(ReadOnlyAdmin):
    list_display = ["site", "name", "shift", "headcount"]


@admin.register(Assignment)
class AssignmentAdmin(ReadOnlyAdmin):
    list_display = ["guard", "post", "start_date", "end_date", "assigned_by"]

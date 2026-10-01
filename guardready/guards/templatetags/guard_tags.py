"""Template filter that turns a status into a Bootstrap badge color."""

from django import template

from guards.constants import STATUS_COLORS

register = template.Library()


@register.filter
def badge(status):
    """Usage: <span class="badge text-bg-{{ status|badge }}">{{ status }}</span>"""
    return STATUS_COLORS.get(status, "secondary")

from django.urls import path

from . import views

urlpatterns = [
    path("", views.audit_log, name="audit_log"),
    path("alerts/", views.security_alerts, name="security_alerts"),
]

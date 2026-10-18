from django.urls import path

from . import views

# Attendance records and evaluations can only be added. There is no edit or
# delete URL, because both are append only.
urlpatterns = [
    path("compliance/government/", views.choose_office, name="compliance_offices"),
    path("compliance/new/<slug:kind>/", views.compliance_request, name="compliance_request"),
    # Guard reports (Stage 4). Both CSV buttons are POST only.
    path("guards/", views.summary_report, name="summary_report"),
    path("guards/csv/", views.summary_report_csv, name="summary_report_csv"),
    path("guards/<int:pk>/", views.guard_report, name="guard_report"),
    path("guards/<int:pk>/csv/", views.guard_report_csv, name="guard_report_csv"),
    path("guards/<int:pk>/attendance/new/", views.record_attendance, name="record_attendance"),
    path("guards/<int:pk>/evaluations/new/", views.add_evaluation, name="add_evaluation"),
]

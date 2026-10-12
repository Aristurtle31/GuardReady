from django.urls import path

from . import views

urlpatterns = [
    path("compliance/government/", views.choose_office, name="compliance_offices"),
    path("compliance/new/<slug:kind>/", views.compliance_request, name="compliance_request"),
]

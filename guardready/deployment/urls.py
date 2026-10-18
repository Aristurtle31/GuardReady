from django.urls import path

from . import views

# Sites and posts are shown, not edited. A posting is never deleted: it is
# ended once with Assignment.close(), so the deployment history stays.
urlpatterns = [
    path("sites/", views.site_list, name="site_list"),
    path("sites/posts/<int:pk>/", views.post_detail, name="post_detail"),
    path("sites/posts/<int:pk>/assign/", views.assign_to_post, name="assign_to_post"),
    path("sites/postings/<int:pk>/end/", views.end_posting, name="end_posting"),
]

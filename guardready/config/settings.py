"""
Settings for GuardReady.

Everything the app needs to run is in this one file.
"""

import os
from pathlib import Path

from django.contrib.messages import constants as message_constants

BASE_DIR = Path(__file__).resolve().parent.parent

# Development key. In a real deployment, set the GUARDREADY_SECRET_KEY
# environment variable instead.
SECRET_KEY = os.environ.get(
    "GUARDREADY_SECRET_KEY",
    "dev-only-key-change-me-guardready-it102",
)

DEBUG = True

# localhost for our own machines, .app.github.dev for GitHub Codespaces.
ALLOWED_HOSTS = ["localhost", "127.0.0.1", ".app.github.dev"]

# Codespaces opens the app on an https address, so Django must trust it
# or every form (login included) fails the CSRF check.
CSRF_TRUSTED_ORIGINS = ["https://*.app.github.dev"]


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Our apps
    "accounts",
    "guards",
    "deployment",
    "audit",
    "reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Zero Trust: idle timeout runs first, then every request is logged.
    "accounts.middleware.IdleTimeoutMiddleware",
    "audit.middleware.AuditMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # Builds the menu for the logged in user's role.
                "accounts.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# All database settings live here. To switch to PostgreSQL later, replace
# the "default" entry with something like this (and pip install psycopg):
#
#     "default": {
#         "ENGINE": "django.db.backends.postgresql",
#         "NAME": "guardready",
#         "USER": "guardready",
#         "PASSWORD": os.environ.get("GUARDREADY_DB_PASSWORD", ""),
#         "HOST": "localhost",
#         "PORT": "5432",
#     }
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# Passwords use Django's built-in hashing (PBKDF2 with a salt).
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"

# The login ends when the browser closes.
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Bootstrap calls the red alert "danger", Django calls it "error".
MESSAGE_TAGS = {message_constants.ERROR: "danger"}


# Zero Trust settings
# Log the user out after this many seconds with no activity (180 for the demo).
IDLE_TIMEOUT_SECONDS = 180
# How long a step-up (password re-check) unlocks one guard's sensitive data.
STEP_UP_SECONDS = 120


# Refused requests (403) are already in our audit log, so the terminal does
# not need to print a long traceback for each one. Real errors still show.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {
        "django.request": {"level": "ERROR"},
    },
}


# Language and time
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True


# Static files (CSS)
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

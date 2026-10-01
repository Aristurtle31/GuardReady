"""Constants for attendance and evaluations."""

# A guard is late if he timed in more than this many minutes after the
# scheduled start of his shift.
LATE_GRACE_MINUTES = 5

# Character evaluation categories. The Evaluation model has one field for
# each, named the same in lower case (discipline, attitude, ...).
EVALUATION_CATEGORIES = ["Discipline", "Attitude", "Appearance", "Honesty", "Alertness"]

LOWEST_SCORE = 1
HIGHEST_SCORE = 5

# Attendance statuses
ON_TIME = "On time"
LATE = "Late"
ABSENT = "Absent"

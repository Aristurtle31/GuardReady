"""Constants for client sites, posts, and shifts."""

from datetime import time

DAY_SHIFT = "Day"
NIGHT_SHIFT = "Night"
SHIFT_CHOICES = [(DAY_SHIFT, "Day shift"), (NIGHT_SHIFT, "Night shift")]

# When each shift starts. Used for attendance (late or on time).
SHIFT_START_TIMES = {
    DAY_SHIFT: time(6, 0),
    NIGHT_SHIFT: time(18, 0),
}

"""Hard-coded programme rules and weekly tasks.

Edit this file to change what students are asked to do. Nothing else needs to change.
"""
from __future__ import annotations

from dataclasses import dataclass

PROGRAM_NAME = "Industrial Attachment"
DEFAULT_CAPTION = "Industrial Attachment 2026"

# Streak day. Monday = 0 ... Friday = 4. Students may upload on ANY day;
# an upload always counts for the Monday-Sunday week it was made in.
STREAK_WEEKDAY = 4
STREAK_DAY_NAME = "Friday"


@dataclass(frozen=True)
class Task:
    key: str
    title: str
    instructions: str
    required: bool  # required tasks decide whether the week counts toward the streak


WEEKLY_TASKS: tuple[Task, ...] = (
    Task(
        "logbook",
        "1. Upload your logbook photo",
        "Photograph this week's logbook page. Keep it flat and well lit, all four corners "
        "visible, with the date and your supervisor's signature readable.",
        True,
    ),
    Task(
        "face",
        "2. Upload your face photo with a pen",
        "After the logbook, take a clear photo of your face holding a pen near your chest "
        "(pen visible, plain background, good light).",
        True,
    ),
    Task(
        "social",
        "3. Make your social media card (bonus)",
        "Open the Studio tab, pick a theme and export your card for WhatsApp, Instagram or LinkedIn.",
        False,
    ),
)

TASK_KEYS = tuple(t.key for t in WEEKLY_TASKS)
REQUIRED_KEYS = frozenset(t.key for t in WEEKLY_TASKS if t.required)
UPLOAD_KEYS = ("logbook", "face")  # tasks that are satisfied by uploading a photo

RULES: tuple[str, ...] = (
    "Take a photo of your logbook first, then a photo of your face holding a pen.",
    f"Every {STREAK_DAY_NAME} is streak day: finish tasks 1 and 2 to add a week to your streak.",
    f"You can upload on any day. It counts toward the week (Monday to Sunday) you upload in.",
    "Miss a whole week and your streak restarts, so keep it going.",
    "Upload your own filled-in logbook page for the week. Your supervisor may check it against your paper logbook.",
    "After your face photo, use the Studio to turn it into a social media card.",
)

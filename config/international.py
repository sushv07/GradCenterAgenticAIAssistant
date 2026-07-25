"""
config/international.py
Single source of truth for CSULB international-applicant guidance.

Centralized here (not scraped per request, not duplicated across routing and
rendering code) so the content is maintained in exactly one place. The values
mirror the official CSULB Center for International Education page.
"""
from __future__ import annotations

INTERNATIONAL_INFO: dict = {
    "title": "International applicant information",
    "intro": (
        "International applicants should review CSULB International Education "
        "requirements and guidance before applying."
    ),
    "international_page": {
        "label": "International Education",
        "url":   "https://www.csulb.edu/international",
    },
    # Categorized contacts so students reach the right office for their stage.
    "emails": [
        {"label": "Applications",         "email": "cie-apply@csulb.edu"},
        {"label": "Admissions",           "email": "cie-admission@csulb.edu"},
        {"label": "Immigration Advising", "email": "cie-student@csulb.edu"},
        {"label": "Study Abroad",         "email": "studyabroad@csulb.edu"},
    ],
    "links": [
        {"label": "Staff Contacts",
         "url":   "https://www.csulb.edu/international/staff-contacts"},
        {"label": "Academic Affairs Calendar (campus academic holidays)",
         "url":   "https://www.csulb.edu/academic-affairs/academic-affairs-calendar"},
    ],
    "office_hours": [
        "Monday–Thursday: 9:00 a.m.–12:00 p.m. and 1:00–4:00 p.m.",
        "Friday: 9:00 a.m.–12:00 p.m. and 1:00–3:00 p.m.",
        "Closed during campus academic holidays.",
    ],
    "phone":    "562-985-5555",
    "location": "Foundation Building, Suite 185B",
}

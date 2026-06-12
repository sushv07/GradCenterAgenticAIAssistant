"""
CSULB Grad Center – Guidance Agent
Input:  user query + admissions.json content (or path to it)
Output: structured step-by-step guidance list as JSON

Selects the most relevant step sequence from admissions.json based on
the query, then enriches each step with contextual notes and warnings.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent.parent / "data"

# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

# Maps intent label → (trigger tokens, admissions section key)
# Order matters: more specific intents must appear before general ones to win ties.
_INTENT_MAP: list[tuple[str, set[str], str]] = [
    (
        "international",
        {"international", "visa", "f1", "foreign", "abroad", "overseas", "cie", "english", "immigrant"},
        "international_students",
    ),
    (
        "eligibility",
        {"eligible", "eligibility", "qualify", "gpa", "requirement", "requirements", "need", "minimum"},
        "eligibility",
    ),
    (
        "orientation",
        {"orientation", "orientate", "welcome", "onboarding"},
        "orientation",
    ),
    (
        "newly_admitted",
        {"admitted", "accepted", "enrolled", "next", "after", "got", "new", "just", "what"},
        "newly_admitted_steps",
    ),
    (
        # Doctoral intent — must appear BEFORE application_process so doctoral
        # queries ("I want to apply for a PhD") score higher here than below.
        "doctoral_application",
        {"phd", "doctorate", "doctoral", "dnp", "dpt", "edd", "ed", "d"},
        "doctoral_application_steps",
    ),
    (
        "application_process",
        {"apply", "applying", "application", "submit", "start", "begin", "process", "steps"},
        "application_steps",
    ),
]

_STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "i", "me", "my", "we", "you", "your", "it", "its", "do", "does",
    "to", "of", "in", "on", "at", "for", "by", "with", "from", "that",
    "this", "and", "or", "but", "so", "if", "as",
}


def _tokenize(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    return tokens - _STOP_WORDS


def detect_intent(query: str) -> tuple[str, str]:
    """
    Return (intent_label, section_key) for the best-matching intent.
    Falls back to ("application_process", "application_steps").
    """
    query_tokens = _tokenize(query)
    best_intent, best_section, best_score = "application_process", "application_steps", 0

    for label, triggers, section in _INTENT_MAP:
        score = len(triggers & query_tokens)
        if score > best_score:
            best_intent, best_section, best_score = label, section, score

    return best_intent, best_section


# ---------------------------------------------------------------------------
# Step builders – one per admissions section type
# ---------------------------------------------------------------------------

@dataclass
class GuidanceStep:
    # Identity ---------------------------------------------------------------
    id:        str                  = ""                           # unique per flow
    step:      int                  = 0                            # ordinal within flow
    title:     str                  = ""
    action:    str                  = ""

    # Content ----------------------------------------------------------------
    details:   str                  = ""
    prep:      list[str]            = field(default_factory=list)  # what to have ready
    how:       list[str]            = field(default_factory=list)  # concrete sub-steps
    time:      str                  = ""                           # "5–10 min" / "1–2 hours"
    outcome:   str                  = ""                           # what happens next
    glossary:  dict[str, str]       = field(default_factory=dict)  # term → plain-English
    warnings:  list[str]            = field(default_factory=list)
    resources: list[dict[str, str]] = field(default_factory=list)

    # Workflow / scheduling --------------------------------------------------
    primary_action: str             = ""                           # single most important next move
    priority:       str             = "medium"                     # high | medium | low
    status:         str             = "pending"                    # pending | in_progress | completed
    depends_on:     list[str]       = field(default_factory=list)  # ids of prerequisite steps

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "id":             self.id,
            "step":           self.step,
            "title":          self.title,
            "action":         self.action,
            "primary_action": self.primary_action,
            "details":        self.details,
            "priority":       self.priority,
            "status":         self.status,
            "depends_on":     self.depends_on,
        }
        for key in ("prep", "how", "time", "outcome", "glossary", "warnings", "resources"):
            value = getattr(self, key)
            if value:
                d[key] = value
        return d


# Static warnings and resources keyed by step title fragment
_STEP_WARNINGS: dict[str, list[str]] = {
    "doctoral eligibility":  ["GPA calculations are NOT rounded. Most doctoral programs also require a master's degree — confirm with your target program."],
    "doctoral application":  ["Not all doctoral programs admit every term — confirm your program's specific deadline before applying."],
    "deadline":      ["Not all programs admit every term — confirm your program's specific deadline before applying."],
    "fee":           ["$70 application fee is nonrefundable. No waivers are available for graduate applicants."],
    "transcript":    ["Transcripts must be sent directly from your institution. Student-submitted copies are not accepted."],
    "conditional":   ["Failure to complete prerequisites within your department's timeframe may result in dismissal."],
    "provisional":   ["Provisional admits must submit final transcripts by Aug 15 (fall) or Jan 15 (spring)."],
    "immunization":  ["Immunization compliance required by June 1 (fall) or December 1 (spring). Non-compliance may block enrollment."],
    "appeal":        ["Appeals are rarely successful and must include new, serious, and compelling information."],
    "gpa":           ["GPA calculations are NOT rounded. Programs may require a higher GPA than the university minimum."],
    "visa":          ["F-1 visa requirements apply. Contact the Center for International Education (CIE) for maintenance rules."],
}

_STEP_RESOURCES: dict[str, list[dict[str, str]]] = {
    "doctoral eligibility":  [
        {"label": "Doctoral Admission Eligibility", "url": "https://www.csulb.edu/admissions/doctoral-programs-admission-eligibility"},
        {"label": "Doctoral Programs Application Process", "url": "https://www.csulb.edu/admissions/doctoral-programs-application-process"},
    ],
    "doctoral application":  [
        {"label": "Doctoral Application Process", "url": "https://www.csulb.edu/admissions/doctoral-programs-application-process"},
        {"label": "Doctoral Programs — Advisors & Deadlines", "url": "https://www.csulb.edu/graduate-studies-csulb/article/programs-advisors-and-deadlines-doctoral"},
        {"label": "Graduate Programs & Advisors", "url": "https://www.csulb.edu/graduate-studies/graduate-programs-and-academic-advisors"},
    ],
    "deadline":    [{"label": "Programs, Advisors & Deadlines", "url": "https://www.csulb.edu/graduate-studies/article/programs-advisors-and-deadlines-masters"}],
    "university application": [{"label": "Cal State Apply Portal", "url": "https://www.calstate.edu/apply"}],
    "transcript":  [{"label": "Enrollment Services – Transcripts", "url": "https://www.csulb.edu/enrollment-services"}, {"label": "Email", "url": "ES-IDPTrans@csulb.edu"}],
    "program-specific": [
        {"label": "Graduate Programs & Advisors", "url": "https://www.csulb.edu/graduate-studies/graduate-programs-and-academic-advisors"},
        {"label": "Writing a Statement of Purpose", "url": "https://www.csulb.edu/graduate-center/writing-a-statement-of-purpose"},
        {"label": "Writing a CV or Résumé", "url": "https://www.csulb.edu/graduate-center/writing-a-cv-or-resume-for-graduate-school"},
        {"label": "Graduate Center — Request Appointment", "url": "https://www.csulb.edu/graduate-center/graduate-school-support"},
        {"label": "Materials Feedback Service", "url": "https://csulb.qualtrics.com/jfe/form/SV_eerjJlu6eVLBv2C"},
        {"label": "University Writing Center (UWC)", "url": "https://www.csulb.edu/university-writing-center"},
        {"label": "Graduate Writing Specialist", "url": "https://www.csulb.edu/graduate-center/request-writing-appointment"},
        {"label": "Grad Admissions Resources (Writing Specialist)", "url": "https://thegraduatewritingguy.com/getting-into-grad-school/"},
    ],
    "satisfy admission": [{"label": "Doctoral Programs Application Process", "url": "https://www.csulb.edu/admissions/doctoral-programs-application-process"}],
    "appeal":      [
        {"label": "Submit an Admissions Appeal", "url": "https://es-forms.es.csulb.edu/forms/ADAPPL.php"},
        {"label": "Bob Murphy Access Center Services", "url": "https://www.csulb.edu/node/527261"},
    ],
    "financial":   [{"label": "Financial Aid for Graduate Students", "url": "https://www.csulb.edu/financial-aid-and-scholarships/how-to-apply-for-aid-graduate-students"}],
    "advisor":     [{"label": "Graduate Programs & Advisors", "url": "https://www.csulb.edu/graduate-studies/graduate-programs-and-academic-advisors"}],
    "register":    [{"label": "Schedule of Classes", "url": "https://www.csulb.edu/student-records/schedule-of-classes"}, {"label": "MyCSULB", "url": "https://sso.csulb.edu"}],
    "orientation": [{"label": "Graduate Student Orientation", "url": "https://www.csulb.edu/graduate-studies/article/graduate-student-orientation"}],
    "graduate center": [{"label": "Graduate Center", "url": "https://www.csulb.edu/graduate-center"}],
    "international": [{"label": "Center for International Education", "url": "https://www.csulb.edu/international"}, {"label": "CIE Graduate Admissions Requirements", "url": "https://www.csulb.edu/international/future-students/graduate-admissions-requirements"}],
    "english":     [{"label": "CIE English Language Requirements", "url": "https://www.csulb.edu/international/future-students/english-language-requirement"}],
}


# ---------------------------------------------------------------------------
# Beginner-friendly enrichments
# ---------------------------------------------------------------------------

# Map raw step titles → clearer imperative action phrases
_ACTION_REWRITES: dict[str, str] = {
    "Confirm Doctoral Eligibility":           "Confirm you meet doctoral eligibility requirements",
    "Verify Doctoral Application Deadlines":  "Find your doctoral program's application deadline",
    "Verify Deadlines":                       "Find your program's application deadline",
    "Submit University Application":          "Apply through the Cal State Apply portal",
    "Submit Official Transcripts":            "Have your transcripts sent to CSULB",
    "Complete Program-Specific Requirements": "Finish your program's extra application items",
    "Check Application Status":               "Track your application status in MyCSULB",
    "Accept Admission Offer":                 "Accept your admission offer (if admitted)",
    "Satisfy Admission Terms":                "Submit any items required after admission",
    "Appeal Process":                         "Appeal a denial (only if necessary)",

    "Activate Account":                       "Activate your CSULB email and student account",
    "Accept/Decline Admission":               "Accept (or decline) your offer in MyCSULB",
    "Address Conditional Requirements":       "Complete any prerequisites you still owe",
    "Review Financial Aid":                   "Apply for financial aid and review your awards",
    "Connect with Graduate Advisor":          "Set up a meeting with your graduate advisor",
    "Register for Classes":                   "Register for your first-semester classes",
    "Attend University-Wide Orientation":     "Attend the university-wide graduate orientation",
    "Attend Program-Specific Orientation":    "Attend your program's orientation session",
    "Submit Final Transcripts":               "Send your final official transcripts (if provisional)",
    "Submit Final Transcripts (Provisional Admits)": "Send your final official transcripts (if provisional)",
    "Immunization Compliance":                "Submit your immunization records",
    "Utilize Online Tools":                   "Set up MyCSULB, Canvas, and Beach Connect",
    "Visit Graduate Center":                  "Visit the Graduate Center for support and resources",
}

# What the user should have ready before starting (matched on title+details substring)
_STEP_PREP: dict[str, list[str]] = {
    "doctoral eligibility":      ["Your unofficial transcripts to check your GPA", "Confirmation that you hold (or will complete) a bachelor's degree", "Whether your target program requires a master's degree"],
    "doctoral application":      ["Your target doctoral program name", "Your target start term (Fall or Spring — not all programs admit each term)"],
    "deadline":                  ["Your target program name", "Your target start term (Fall or Spring)"],
    "university application":    [
        "An email address you check often",
        "Bachelor's degree info (school, dates, GPA)",
        "$70 for the application fee (credit/debit card)",
        "Statement of Purpose draft",
        "CV or résumé",
        "Names and emails of recommenders (if your program requires letters)",
    ],
    "transcript":                ["Knowledge of every college you attended", "ES-IDPTrans@csulb.edu (the email transcripts go to)"],
    "program-specific":          ["Cal State Apply login", "Any extra documents your program lists (writing samples, portfolio, GRE scores, etc.)"],
    "application status":        ["Your CSULB ID (sent in your application confirmation email)"],
    "accept admission":          ["Login to MyCSULB Student Center", "Payment method for the enrollment deposit"],
    "satisfy admission":         ["Your admission letter (lists any conditions)"],
    "appeal":                    ["New, serious, and compelling information not in your original application"],
    "activate":                  ["Your admission email (it has temporary credentials)", "Phone for verification text/call"],
    "accept/decline":            ["MyCSULB login (set up in Step 1)"],
    "conditional":               ["List of unfinished prerequisites from your admission letter"],
    "financial aid":             ["FAFSA or California Dream Act login", "Tax info (yours or your parents')"],
    "graduate advisor":          ["Your program-specific advisor's email (see graduate advisors directory)"],
    "register":                  ["MyCSULB login", "Schedule of Classes URL", "Your registration appointment time (emailed to you)"],
    "university-wide orientation": ["Zoom installed", "An hour or two on the orientation date"],
    "program-specific orient":   ["Your program's email contact (they'll send the schedule)"],
    "final transcript":          ["Each previous school's registrar contact info"],
    "immunization":              ["Your vaccine records (MMR, Tdap, Hepatitis B, etc.)"],
    "online tools":              ["MyCSULB login", "BeachID and password"],
    "graduate center":           ["Nothing required — just walk in or book online"],
}

# Concrete how-to sub-steps
_STEP_HOW: dict[str, list[str]] = {
    "doctoral eligibility":      [
        "Check your cumulative GPA — doctoral programs require 3.0 or higher (not rounded)",
        "Confirm whether your target program requires a master's degree (most do)",
        "Visit https://www.csulb.edu/admissions/doctoral-programs-admission-eligibility for full requirements",
        "Contact your target program's Graduate Advisor if you have questions about your eligibility",
    ],
    "doctoral application":      [
        "Spring admission: application period opens July 1",
        "Fall admission: application period opens October 1",
        "Visit https://www.csulb.edu/admissions/doctoral-programs-application-process for the full process",
        "Confirm whether your program admits students in both terms — not all programs do",
        "Check the Graduate Studies website for your program's specific deadline",
        "View doctoral program deadlines at https://www.csulb.edu/graduate-studies-csulb/article/programs-advisors-and-deadlines-doctoral",
    ],
    "deadline":                  [
        "Open https://www.csulb.edu/graduate-studies/graduate-programs-and-academic-advisors",
        "Find your program in the list",
        "Note the deadline for your target term",
    ],
    "university application":    [
        "Go to https://www.calstate.edu/apply",
        "Create an account or sign in",
        "Choose 'Graduate' and select CSULB",
        "Fill out personal info, education history, and program selection",
        "Upload required documents",
        "Pay the $70 fee",
        "Submit before your deadline",
    ],
    "transcript":                [
        "Contact the registrar at every college you attended",
        "Request an OFFICIAL transcript (electronic preferred)",
        "Have it sent to ES-IDPTrans@csulb.edu (or mailed to CSULB Enrollment Services)",
    ],
    "program-specific":          [
        "Log back into Cal State Apply",
        "Find the supplemental section for your program",
        "Upload any extra documents your program requires",
        "Submit before the program's deadline",
        "Need help writing your Statement of Purpose? → https://www.csulb.edu/graduate-center/writing-a-statement-of-purpose",
        "Need help with your CV or résumé? → https://www.csulb.edu/graduate-center/writing-a-cv-or-resume-for-graduate-school",
        "CSULB undergrad, alum, or prospective student: request a one-on-one appointment with a Graduate Center Coordinator → https://www.csulb.edu/graduate-center/graduate-school-support",
        "Upload drafts for written feedback via the Graduate Center's materials feedback service → https://csulb.qualtrics.com/jfe/form/SV_eerjJlu6eVLBv2C",
        "Or attend Graduate Center drop-in hours → https://www.csulb.edu/graduate-center",
        "Current CSULB student (grad or undergrad): request an appointment with the University Writing Center (UWC) → https://www.csulb.edu/university-writing-center",
        "Current CSULB graduate student: request an appointment with the Graduate Writing Specialist → https://www.csulb.edu/graduate-center/request-writing-appointment",
        "Graduate Writing Specialist's grad admissions resources → https://thegraduatewritingguy.com/getting-into-grad-school/",
    ],
    "application status":        [
        "Log into MyCSULB Student Center",
        "Check the 'Admissions' tile for status updates",
        "Watch your CSULB email for follow-up requests",
    ],
    "accept admission":          [
        "Log into MyCSULB Student Center",
        "Open your admission offer",
        "Click 'Accept'",
        "Pay the enrollment deposit (or request a waiver if you have financial need)",
    ],
    "satisfy admission":         [
        "Re-read your admission letter to find your admission type (Provisional or Conditionally Classified)",
        "Provisional Admission: request your final official transcript from your bachelor's/master's institution",
        "Have it sent directly to CSULB Enrollment Services by August 15 (Fall) or January 15 (Spring)",
        "Conditionally Classified: enroll in and complete required prerequisite courses as directed by your department",
        "Contact your department to confirm your status has been updated to 'Classified' once conditions are met",
    ],
    "appeal":                    [
        "Read your denial letter carefully — note the specific reason for denial",
        "Gather new, serious, and compelling evidence not included in your original application; include supporting documentation",
        "Complete the Admissions Appeal Process form at https://es-forms.es.csulb.edu/forms/ADAPPL.php — no hard copy, email, or fax accepted",
        "Submit within 15 days of receiving your admissions decision — late appeals are not accepted",
        "You cannot appeal being waitlisted or your position on a waitlist",
        "Allow 4–6 weeks for a response; maximum one appeal per academic term",
        "Residency decision appeals: es-residency@csulb.edu",
        "Applied through Bob Murphy Access Center? Contact https://www.csulb.edu/node/527261 at (562) 985.4430",
    ],
    "activate":                  [
        "Open the email subject line: 'CSULB Admission Decision'",
        "Click the activation link to the CSULB Password Utility",
        "Verify your identity by phone or text",
        "Set your CSULB email password",
    ],
    "accept/decline":            [
        "Sign in to MyCSULB Student Center",
        "Click 'Accept Admission'",
        "Pay the enrollment deposit",
    ],
    "conditional":               [
        "Read your admission letter to find the exact prerequisites",
        "Enroll in (or finish) those courses by your department's deadline",
        "Confirm completion with your graduate advisor",
    ],
    "financial aid":             [
        "Submit the FAFSA at https://studentaid.gov OR the Dream Act application",
        "Wait for your award letter to appear in MyCSULB",
        "Accept any grants/loans you want in MyCSULB",
        "Apply separately for scholarships (Beach Scholarships, college scholarships)",
    ],
    "graduate advisor":          [
        "Find your program's advisor at https://www.csulb.edu/graduate-studies/graduate-programs-and-academic-advisors",
        "Email them to schedule a meeting",
        "Bring questions about coursework, milestones, and timeline",
    ],
    "register":                  [
        "Wait for your registration appointment email",
        "Browse https://www.csulb.edu/student-records/schedule-of-classes",
        "Talk to your advisor about which courses to take",
        "Register through MyCSULB at your appointment time",
    ],
    "university-wide orientation": [
        "Watch your CSULB email for the Zoom link",
        "Attend the live session (Aug 13, 2026 for Fall 2026)",
        "If you can't make it, watch the recording when it's emailed",
    ],
    "program-specific orient":   [
        "Email your program's coordinator to confirm the date",
        "Attend in person or via Zoom",
    ],
    "final transcript":          [
        "Once you've finished your bachelor's, request a final official transcript",
        "Have it sent directly to CSULB Enrollment Services",
        "Confirm receipt in MyCSULB",
    ],
    "immunization":              [
        "Gather your vaccine records from your doctor or previous school",
        "Submit them through Student Health Services",
        "Confirm the hold is removed before registration",
    ],
    "online tools":              [
        "Log into MyCSULB at https://sso.csulb.edu",
        "Open Canvas (linked from MyCSULB) — your courses appear here",
        "Download Beach Connect from your phone's app store",
    ],
    "graduate center":           [
        "Visit University Library 214 during open hours",
        "Or book an appointment at https://www.csulb.edu/graduate-center/request-appointment",
    ],
}

# Rough time estimates
_STEP_TIME: dict[str, str] = {
    "doctoral eligibility":      "15–30 min",
    "doctoral application":      "5–10 min",
    "deadline":                  "5–10 min",
    "university application":    "2–4 hours (split across sessions)",
    "transcript":                "1 hour to request; 1–4 weeks to arrive",
    "program-specific":          "Varies — 1–6 hours depending on what's required",
    "application status":        "5 min (check periodically)",
    "accept admission":          "10–15 min",
    "satisfy admission":         "1 hour to arrange transcript; 1–4 weeks to arrive",
    "appeal":                    "2–3 hours to prepare; reviewed within 4–6 weeks",
    "activate":                  "10 min",
    "accept/decline":            "10 min",
    "conditional":               "Whatever your prerequisites take (a semester or more)",
    "financial aid":             "1–2 hours for FAFSA; weeks of processing",
    "graduate advisor":          "30–60 min meeting",
    "register":                  "30 min, once your appointment opens",
    "university-wide orientation": "2–3 hours (live session)",
    "program-specific orient":   "1–3 hours",
    "final transcript":          "1 hour to request; 1–4 weeks to arrive",
    "immunization":              "30 min if you have records; longer if you need shots",
    "online tools":              "30 min total",
    "graduate center":           "30 min – 1 hour appointment",
}

# What success looks like for each step
_STEP_OUTCOME: dict[str, str] = {
    "doctoral eligibility":      "You'll know whether you meet the baseline requirements and can move forward with your application.",
    "doctoral application":      "You'll know the exact deadline for your doctoral program and target term.",
    "deadline":                  "You'll know the exact date your application is due.",
    "university application":    "You'll get a confirmation email with your CSULB ID. Admissions begins reviewing.",
    "transcript":                "Your transcripts arrive at CSULB and are matched to your application.",
    "program-specific":          "Your application becomes complete and is forwarded to your department.",
    "application status":        "You'll see one of: under review, admitted, denied, or 'documents needed'.",
    "accept admission":          "Your spot in the program is reserved and you can begin enrolling.",
    "satisfy admission":         "Your admission status is confirmed — Provisional converts to Classified, or prerequisites are cleared.",
    "appeal":                    "You'll receive a written decision within 4–6 weeks (most appeals are denied).",
    "activate":                  "You can log into all CSULB systems with your BeachID.",
    "accept/decline":            "Your seat is held; you can begin everything else on this list.",
    "conditional":               "Your status updates from 'Conditionally Classified' to 'Classified'.",
    "financial aid":             "You'll see your award package in MyCSULB; funds disburse before classes.",
    "graduate advisor":          "You'll have a clear roadmap for coursework and milestones.",
    "register":                  "You'll be enrolled in your first semester's courses.",
    "university-wide orientation": "You'll know how to navigate CSULB systems, milestones, and resources.",
    "program-specific orient":   "You'll meet faculty and fellow students in your cohort.",
    "final transcript":          "Your provisional admission converts to full classified status.",
    "immunization":              "Any registration hold related to immunization is cleared.",
    "online tools":              "You can read announcements, submit work, and check deadlines anywhere.",
    "graduate center":           "You'll have a plan and (often) feedback on your application/writing.",
}

# Plain-English glossary — terms that appear in details get auto-defined
_GLOSSARY: dict[str, str] = {
    "matriculated":       "officially enrolled as a degree-seeking student",
    "provisional":        "admitted but you must finish your bachelor's degree first",
    "conditionally classified": "admitted but with prerequisites you must complete",
    "classified":         "fully admitted with no remaining conditions",
    "post-baccalaureate": "after completing your bachelor's degree",
    "supplemental":       "extra application materials beyond the main Cal State Apply form",
    "enrollment deposit": "a deposit (usually small) to reserve your seat — applied to first-term tuition",
    "candidacy":          "departmental approval that you're cleared to do your thesis/dissertation",
    "culminating activity": "the final project required to graduate (thesis, project, or comprehensive exam)",
    "gs 700":             "a placeholder course you enroll in while finishing your thesis/project",
    "fafsa":              "the federal financial aid application",
    "cada":               "the California Dream Act application (alternative to FAFSA for some students)",
    "f-1 visa":           "the standard student visa for international students",
}


# ---------------------------------------------------------------------------
# Workflow tables — keyed by raw step title (stable across flows)
# ---------------------------------------------------------------------------

_STEP_PRIORITY: dict[str, str] = {
    # application_steps
    "Verify Deadlines":                       "high",
    "Submit University Application":          "high",
    "Submit Official Transcripts":            "high",
    "Complete Program-Specific Requirements": "high",
    "Check Application Status":               "medium",
    "Accept Admission Offer":                 "high",
    "Satisfy Admission Terms":                "high",
    "Appeal Process":                         "low",

    # newly_admitted_steps
    "Activate Account":                       "high",
    "Accept/Decline Admission":               "high",
    "Address Conditional Requirements":       "high",
    "Review Financial Aid":                   "high",
    "Connect with Graduate Advisor":          "high",
    "Register for Classes":                   "high",
    "Attend University-Wide Orientation":     "medium",
    "Attend Program-Specific Orientation":    "medium",
    "Submit Final Transcripts":               "high",
    "Submit Final Transcripts (Provisional Admits)": "high",
    "Immunization Compliance":                "high",
    "Utilize Online Tools":                   "medium",
    "Visit Graduate Center":                  "low",

    # doctoral_application_steps
    "Confirm Doctoral Eligibility":                "high",
    "Verify Doctoral Application Deadlines":       "high",

    # eligibility / international / orientation builders
    "Confirm Degree Status":                       "high",
    "Check GPA Requirement":                       "high",
    "Check Program-Specific GPA":                  "medium",
    "Contact Center for International Education (CIE)": "high",
    "Prepare International Transcripts":           "high",
    "Satisfy English Language Requirements":       "high",
    "Understand Visa Requirements":                "high",
    "Review Tuition and Costs":                    "medium",
    "Register for University-Wide Graduate Orientation": "high",
    "Attend Program-Specific Orientation":         "medium",
    "Review Orientation Topics":                   "low",
}

# Dependencies — keyed by title, values are the titles of prerequisite steps.
# Resolved to step ids during build.
_STEP_DEPENDS_ON: dict[str, list[str]] = {
    # application_steps (mostly linear)
    "Verify Deadlines":                       [],
    "Submit University Application":          ["Verify Deadlines"],
    "Submit Official Transcripts":            ["Submit University Application"],
    "Complete Program-Specific Requirements": ["Submit University Application"],
    "Check Application Status":               ["Submit University Application"],
    "Accept Admission Offer":                 ["Check Application Status"],
    "Satisfy Admission Terms":                ["Accept Admission Offer"],
    "Appeal Process":                         ["Check Application Status"],

    # doctoral_application_steps — unique doctoral titles get explicit deps;
    # shared titles (Submit Official Transcripts, etc.) reuse entries above.
    "Confirm Doctoral Eligibility":           [],
    "Verify Doctoral Application Deadlines":  ["Confirm Doctoral Eligibility"],

    # newly_admitted_steps — partial DAG (many can run in parallel)
    "Activate Account":                       [],
    "Accept/Decline Admission":               ["Activate Account"],
    "Address Conditional Requirements":       ["Accept/Decline Admission"],
    "Review Financial Aid":                   ["Activate Account"],
    "Connect with Graduate Advisor":          ["Accept/Decline Admission"],
    "Register for Classes":                   ["Connect with Graduate Advisor"],
    "Attend University-Wide Orientation":     ["Accept/Decline Admission"],
    "Attend Program-Specific Orientation":    ["Accept/Decline Admission"],
    "Submit Final Transcripts":               ["Accept/Decline Admission"],
    "Submit Final Transcripts (Provisional Admits)": ["Accept/Decline Admission"],
    "Immunization Compliance":                ["Accept/Decline Admission"],
    "Utilize Online Tools":                   ["Activate Account"],
    "Visit Graduate Center":                  [],

    # other flows are linear
    "Confirm Degree Status":                  [],
    "Check GPA Requirement":                  ["Confirm Degree Status"],
    "Check Program-Specific GPA":             ["Check GPA Requirement"],
    "Contact Center for International Education (CIE)": [],
    "Prepare International Transcripts":      ["Contact Center for International Education (CIE)"],
    "Satisfy English Language Requirements":  ["Contact Center for International Education (CIE)"],
    "Understand Visa Requirements":           ["Contact Center for International Education (CIE)"],
    "Review Tuition and Costs":               ["Contact Center for International Education (CIE)"],
    "Register for University-Wide Graduate Orientation": [],
    "Review Orientation Topics":              [],
}

# Sharp imperative for the single most important move within a step
_STEP_PRIMARY_ACTION: dict[str, str] = {
    "Confirm Doctoral Eligibility":           "Check that you meet the 3.0 GPA requirement and — for most programs — hold a master's degree.",
    "Verify Doctoral Application Deadlines":  "Visit the Graduate Programs & Advisors page and note the deadline for your doctoral program and target term.",
    "Verify Deadlines":                       "Open the program advisors page and note your program's deadline for your target term.",
    "Submit University Application":          "Create your Cal State Apply account and start filling out the form.",
    "Submit Official Transcripts":            "Email your previous registrar today — transcripts often take 1–4 weeks.",
    "Complete Program-Specific Requirements": "Open Cal State Apply and check your program's supplemental section.",
    "Check Application Status":               "Log into MyCSULB and open the Admissions tile.",
    "Accept Admission Offer":                 "Log into MyCSULB and click 'Accept' on your admission offer.",
    "Satisfy Admission Terms":                "Re-read your admission letter, identify your admission type (Provisional or Conditionally Classified), and meet the deadline.",
    "Appeal Process":                         "Only appeal if you have new, compelling information — submit the online form within 15 days.",

    "Activate Account":                       "Find your admission email and click the activation link.",
    "Accept/Decline Admission":               "Log into MyCSULB and accept your offer.",
    "Address Conditional Requirements":       "Read your admission letter and identify the exact prerequisites you owe.",
    "Review Financial Aid":                   "Submit the FAFSA at studentaid.gov (or the CADA if you're an AB-540 student).",
    "Connect with Graduate Advisor":          "Email your program's graduate advisor to schedule an intro meeting.",
    "Register for Classes":                   "Watch your CSULB email for your registration appointment time.",
    "Attend University-Wide Orientation":     "Add the orientation date to your calendar.",
    "Attend Program-Specific Orientation":    "Email your program coordinator to confirm the orientation date.",
    "Submit Final Transcripts":               "Request your final official transcript from your bachelor's institution.",
    "Submit Final Transcripts (Provisional Admits)": "Request your final official transcript from your bachelor's institution.",
    "Immunization Compliance":                "Gather your vaccine records and submit them to Student Health Services.",
    "Utilize Online Tools":                   "Log into MyCSULB at sso.csulb.edu and bookmark Canvas.",
    "Visit Graduate Center":                  "Walk into University Library 214 or book online.",
}


def _slug(text: str) -> str:
    """Lowercase + replace non-alphanumerics with hyphens, collapse repeats."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-+", "-", s)


# Map intent label → short, stable id prefix
_INTENT_ID_PREFIX = {
    "application_process":    "apply",
    "doctoral_application":   "doctoral",
    "newly_admitted":         "admitted",
    "eligibility":            "eligibility",
    "international":          "international",
    "orientation":            "orientation",
}


def _make_step_id(intent: str, step_number: int) -> str:
    prefix = _INTENT_ID_PREFIX.get(intent, _slug(intent) or "step")
    return f"{prefix}-{step_number}"


def _attach_metadata(step: GuidanceStep) -> GuidanceStep:
    """
    Enrich a step with beginner-friendly fields:
    rewritten action verb, prep list, how-to, time estimate, outcome,
    glossary, warnings, and resources — all driven by keyword matches.
    """
    # Imperative action rewrite (most clarity bang-for-buck)
    if step.title in _ACTION_REWRITES:
        step.action = _ACTION_REWRITES[step.title]

    # Narrow haystack (title + rewritten action only) prevents stray words in
    # `details` (e.g. "deadline" appearing in step 9's "Submit Final Transcripts")
    # from hijacking the keyword match.
    narrow = (step.title + " " + step.action).lower()
    full   = (step.title + " " + step.action + " " + step.details).lower()

    def _first_match(table: dict, text: str) -> Any:
        for keyword, value in table.items():
            if keyword in text:
                return value
        return None

    if not step.prep:
        step.prep = _first_match(_STEP_PREP, narrow) or []
    if not step.how:
        step.how = _first_match(_STEP_HOW, narrow) or []
    if not step.time:
        step.time = _first_match(_STEP_TIME, narrow) or ""
    if not step.outcome:
        step.outcome = _first_match(_STEP_OUTCOME, narrow) or ""

    # Glossary: define every jargon term that appears anywhere in the step
    if not step.glossary:
        step.glossary = {
            term: defn for term, defn in _GLOSSARY.items()
            if term in full
        }

    if not step.warnings:
        for keyword, warnings in _STEP_WARNINGS.items():
            if keyword in narrow:
                step.warnings = warnings
                break
    if not step.resources:
        for keyword, resources in _STEP_RESOURCES.items():
            if keyword in narrow:
                step.resources = resources
                break

    # Workflow fields
    if step.priority == "medium":   # default — only override if we have a better mapping
        step.priority = _STEP_PRIORITY.get(step.title, "medium")

    if not step.primary_action:
        step.primary_action = (
            _STEP_PRIMARY_ACTION.get(step.title)
            or (step.how[0] if step.how else step.action)
        )

    return step


def _resolve_dependencies(steps: list[GuidanceStep]) -> list[GuidanceStep]:
    """Translate depends_on titles into step ids within the same flow."""
    title_to_id = {s.title: s.id for s in steps}
    for s in steps:
        prereq_titles = _STEP_DEPENDS_ON.get(s.title, [])
        s.depends_on = [title_to_id[t] for t in prereq_titles if t in title_to_id]
    return steps


# ---------------------------------------------------------------------------
# Step validation
# ---------------------------------------------------------------------------

def validate_steps(steps: list[dict]) -> list[str]:
    """
    Validate a list of step dicts.  Works on the output of GuidanceStep.to_dict()
    or any list of dicts that carry 'id', 'step', and 'depends_on' fields.

    Checks
    ------
    1. All depends_on ids exist in the step set.
    2. No circular dependencies (DFS-based cycle detection).

    Returns
    -------
    list[str]  — one error string per problem found.  Empty list = valid.
    """
    errors: list[str] = []
    id_set: set[str] = {s.get("id", "") for s in steps if s.get("id")}

    # ------------------------------------------------------------------
    # 1. Unknown depends_on ids
    # ------------------------------------------------------------------
    for s in steps:
        for dep_id in s.get("depends_on") or []:
            if dep_id and dep_id not in id_set:
                errors.append(
                    f"Step '{s.get('id')}' (step {s.get('step')}) "
                    f"references unknown depends_on id: '{dep_id}'"
                )

    # ------------------------------------------------------------------
    # 2. Circular dependencies  (white / gray / black DFS)
    #
    # Edge direction: step → its depends_on ids (prerequisites).
    # A cycle means some chain of prereqs loops back to a node that is
    # still on the current DFS call stack (gray).
    # ------------------------------------------------------------------
    adj: dict[str, list[str]] = {
        s.get("id", ""): [d for d in (s.get("depends_on") or []) if d in id_set]
        for s in steps
        if s.get("id")
    }
    # 0 = unvisited  |  1 = in DFS stack (gray)  |  2 = fully visited (black)
    state: dict[str, int] = {sid: 0 for sid in id_set}

    def _dfs(node: str, path: list[str]) -> None:
        state[node] = 1         # mark gray
        path.append(node)
        for dep in adj.get(node, []):
            if state[dep] == 1:
                # dep is on the current stack → cycle found
                try:
                    idx   = path.index(dep)
                    cycle = path[idx:] + [dep]
                except ValueError:
                    cycle = [dep, node, dep]
                errors.append(
                    f"Circular dependency detected: {' → '.join(cycle)}"
                )
            elif state[dep] == 0:
                _dfs(dep, path)
        state[node] = 2         # mark black
        path.pop()

    for sid in sorted(id_set):
        if state[sid] == 0:
            _dfs(sid, [])

    return errors


def _build_steps_from_list(raw_steps: list[dict], intent: str) -> list[GuidanceStep]:
    """Convert a raw steps list (application_steps / newly_admitted_steps) into GuidanceSteps."""
    result = []
    for item in raw_steps:
        n = item.get("step", len(result) + 1)
        step = GuidanceStep(
            id=_make_step_id(intent, n),
            step=n,
            title=item.get("title", ""),
            action=item.get("title", ""),  # imperative form = title (later rewritten in _attach_metadata)
            details=item.get("details", ""),
        )
        result.append(_attach_metadata(step))
    return result


def _build_eligibility_steps(eligibility: dict, intent: str = "eligibility") -> list[GuidanceStep]:
    """Convert eligibility section into a checklist of verification steps."""
    steps: list[GuidanceStep] = []
    n = 1

    def _new(title: str, action: str, details: str, **kwargs) -> GuidanceStep:
        nonlocal n
        s = GuidanceStep(id=_make_step_id(intent, n), step=n, title=title,
                         action=action, details=details, **kwargs)
        n += 1
        return _attach_metadata(s)

    min_reqs = eligibility.get("minimum_requirements", [])
    if min_reqs:
        steps.append(_new(
            "Confirm Degree Status",
            "Verify you hold (or are completing) an acceptable bachelor's degree from a regionally accredited institution",
            "; ".join(min_reqs),
        ))

    gpa = eligibility.get("gpa_requirements", {})
    if gpa:
        options = [gpa.get(k, "") for k in ("standard", "alternative_1", "alternative_2", "provisional")]
        gpa_detail = " | ".join(o for o in options if o)
        if gpa.get("note"):
            gpa_detail += f". Note: {gpa['note']}"
        steps.append(_new(
            "Check GPA Requirement",
            "Confirm your GPA meets at least one of the university minimums",
            gpa_detail,
        ))

    if eligibility.get("additional"):
        steps.append(_new(
            "Check Program-Specific GPA",
            "Verify GPA requirements with your target program — they may exceed university minimums",
            eligibility["additional"],
            resources=[{"label": "Graduate Programs & Advisors",
                        "url": "https://www.csulb.edu/graduate-studies/graduate-programs-and-academic-advisors"}],
        ))

    return steps


def _build_international_steps(intl: dict, intent: str = "international") -> list[GuidanceStep]:
    """Convert international student section into actionable steps."""
    def _step(n: int, title: str, action: str, details: str, **kwargs) -> GuidanceStep:
        return _attach_metadata(GuidanceStep(
            id=_make_step_id(intent, n), step=n,
            title=title, action=action, details=details, **kwargs))

    steps: list[GuidanceStep] = [
        _step(1, "Contact Center for International Education (CIE)",
              "Visit the CIE for program-specific international admission requirements",
              intl.get("key_resources", "Center for International Education (CIE)")),
        _step(2, "Prepare International Transcripts",
              "Ensure your transcripts meet CSULB's international standards",
              intl.get("transcript_requirements", "")),
        _step(3, "Satisfy English Language Requirements",
              "Confirm you meet CSULB's English proficiency requirement",
              intl.get("english_requirements", "")),
        _step(4, "Understand Visa Requirements",
              "Review F-1 visa application and maintenance requirements with CIE",
              intl.get("visa", "")),
        _step(5, "Review Tuition and Costs",
              "Check international student tuition and fee information",
              "International tuition rates differ from domestic rates.",
              resources=[{"label": "International Tuition & Fees", "url": intl.get("tuition_link", "")}]),
    ]
    return steps


def _build_orientation_steps(orientation: dict, intent: str = "orientation") -> list[GuidanceStep]:
    """Convert orientation section into attendance steps."""
    fall = orientation.get("fall_2026", {})
    topics = orientation.get("topics_covered", [])

    def _step(n: int, title: str, action: str, details: str, **kwargs) -> GuidanceStep:
        return _attach_metadata(GuidanceStep(
            id=_make_step_id(intent, n), step=n,
            title=title, action=action, details=details, **kwargs))

    return [
        _step(1, "Register for University-Wide Graduate Orientation",
              "Attend the virtual university-wide orientation",
              f"{fall.get('date', '')} | {fall.get('time', '')} | {fall.get('format', '')}. Spring: recordings distributed by email.",
              resources=[{"label": "Graduate Student Orientation", "url": orientation.get("source", "")}]),
        _step(2, "Attend Program-Specific Orientation",
              "Check with your graduate program and attend their orientation separately",
              orientation.get("note", "")),
        _step(3, "Review Orientation Topics",
              "Come prepared — orientation covers these areas",
              ", ".join(topics) if topics else ""),
    ]


# ---------------------------------------------------------------------------
# Section dispatcher
# ---------------------------------------------------------------------------

_SECTION_TO_INTENT = {
    "application_steps":          "application_process",
    "doctoral_application_steps": "doctoral_application",
    "newly_admitted_steps":       "newly_admitted",
    "eligibility":                "eligibility",
    "international_students":     "international",
    "orientation":                "orientation",
}


def _build_guidance(section_key: str, data: dict) -> list[GuidanceStep]:
    # v2 schema uses "content"; fall back to legacy "sections" for safety
    sections = data.get("content") or data.get("sections", {})
    section  = sections.get(section_key, {})
    intent   = _SECTION_TO_INTENT.get(section_key, section_key)

    if section_key in ("application_steps", "doctoral_application_steps", "newly_admitted_steps"):
        steps = _build_steps_from_list(section.get("steps", []), intent)
    elif section_key == "eligibility":
        steps = _build_eligibility_steps(section, intent)
    elif section_key == "international_students":
        steps = _build_international_steps(section, intent)
    elif section_key == "orientation":
        steps = _build_orientation_steps(section, intent)
    else:
        return []

    steps = _resolve_dependencies(steps)

    # Validate: catch bad ids and cycles introduced by data changes
    errors = validate_steps([s.to_dict() for s in steps])
    if errors:
        raise ValueError(
            f"Guidance step validation failed ({len(errors)} error(s)):\n"
            + "\n".join(f"  • {e}" for e in errors)
        )

    return steps


# ---------------------------------------------------------------------------
# Output builder
# ---------------------------------------------------------------------------

def _source_url_for(section_key: str, data: dict) -> str:
    sections = data.get("content") or data.get("sections", {})
    section = sections.get(section_key, {})
    return (
        section.get("source_url")
        or section.get("source")
        or data.get("source_url")
        or data.get("source")
        or "https://www.csulb.edu/graduate-center"
    )


# ---------------------------------------------------------------------------
# Main guidance agent
# ---------------------------------------------------------------------------

def guide(query: str, admissions_data: dict) -> dict:
    """
    Build step-by-step guidance from admissions.json content.

    Args:
        query:           Natural-language question from the user.
        admissions_data: Parsed admissions.json dict.

    Returns:
        Structured JSON with intent, steps list, source, and next steps.
    """
    if not query or not query.strip():
        return {"error": "Empty query", "steps": []}

    intent, section_key = detect_intent(query)
    steps = _build_guidance(section_key, admissions_data)

    if not steps:
        return {
            "query": query,
            "intent": intent,
            "steps": [],
            "message": "I don't know. No guidance available for this query in admissions data.",
            "source_file": "admissions.json",
            "source_url": "https://www.csulb.edu/graduate-center",
        }

    return {
        "query": query,
        "intent": intent,
        "total_steps": len(steps),
        "steps": [s.to_dict() for s in steps],
        "source_file": "admissions.json",
        "source_url": _source_url_for(section_key, admissions_data),
    }


def guide_from_file(query: str, path: Path | None = None) -> dict:
    """Load admissions.json from disk and run guide()."""
    admissions_path = path or (DATA_DIR / "admissions.json")
    with admissions_path.open() as f:
        admissions_data = json.load(f)
    return guide(query, admissions_data)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Enter your query: ")
    result = guide_from_file(query)
    print(json.dumps(result, indent=2))

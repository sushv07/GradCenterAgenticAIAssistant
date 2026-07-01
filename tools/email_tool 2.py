"""
tools/email_tool.py
Email draft builder and Outlook Web deep-link generator.

Two separate, independently callable functions:
  draft_email()      — build a polished subject + body template
  build_outlook_url() — encode subject + body into an Outlook Web compose URL

Safety contract (enforced throughout):
  - Outlook is NEVER auto-opened.  build_outlook_url() returns a URL string.
    The caller (UI layer) decides whether and how to surface it.
  - No emails are sent from here.  No external network calls.
  - User must explicitly request and confirm before the URL is shown in the UI.

Logic extracted from agent.py (_tool_draft_email, _tool_create_outlook_draft)
with the following changes:
  - Return type changed from string sentinel to structured dict.
  - mailto: fallback removed — Outlook Web deep-link only.
  - Both functions are independently importable.

Output schemas:

    draft_email():
    {
        "found":   True,
        "tool":    "email_tool.draft_email",
        "sources": [],
        "error":   None | str,
        "subject": str,
        "body":    str,
        "to":      str,       # advisor_email passed in
    }

    build_outlook_url():
    {
        "found":       True,
        "tool":        "email_tool.build_outlook_url",
        "sources":     [],
        "error":       None | str,
        "outlook_url": str,   # NEVER auto-opened — user action required
    }
"""

from __future__ import annotations

import urllib.parse


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def draft_email(
    advisor_name:  str,
    advisor_email: str,
    program:       str,
    context:       str = "",
) -> dict:
    """
    Generate a polished, student-friendly email draft to a CSULB doctoral advisor.

    Logic is identical to agent._tool_draft_email() but returns a structured
    dict instead of a raw string sentinel.

    Args:
        advisor_name:  Full name of the advisor (from advisor_tool.get_advisor).
        advisor_email: Advisor's email address (from advisor_tool.get_advisor).
        program:       Program name the student is enquiring about.
        context:       Optional extra context, e.g. "applying for Fall 2025".

    Returns:
        {
            "found":   True,
            "tool":    "email_tool.draft_email",
            "sources": [],
            "error":   None,
            "subject": str,   # ready-to-use subject line
            "body":    str,   # multi-line body with [Your Name] placeholders
            "to":      str,   # advisor_email echoed back for downstream use
        }
    """
    if not advisor_name or not advisor_email or not program:
        missing = [
            f for f, v in [
                ("advisor_name", advisor_name),
                ("advisor_email", advisor_email),
                ("program", program),
            ] if not v
        ]
        return {
            "found":   False,
            "tool":    "email_tool.draft_email",
            "sources": [],
            "error":   f"Missing required fields: {', '.join(missing)}",
            "subject": "",
            "body":    "",
            "to":      advisor_email or "",
        }

    context_line = f" I am {context}." if context and context.strip() else ""

    subject = f"Inquiry About the {program} Program — Prospective Student"

    body = (
        f"Dear {advisor_name},\n\n"
        f"I hope this message finds you well. My name is [Your Name], and I am "
        f"reaching out to learn more about the {program} program at CSULB."
        f"{context_line}\n\n"
        f"I would love the opportunity to ask a few questions about the program "
        f"requirements, application process, and any upcoming deadlines.\n\n"
        f"Would you be available for a brief meeting or a quick email exchange at "
        f"your convenience? I truly appreciate your time and guidance.\n\n"
        f"Thank you,\n"
        f"[Your Name]\n"
        f"[Your Phone Number]\n"
        f"[Your CSULB ID / Email]"
    )

    return {
        "found":   True,
        "tool":    "email_tool.draft_email",
        "sources": [],
        "error":   None,
        "subject": subject,
        "body":    body,
        "to":      advisor_email,
    }


def build_outlook_url(to_email: str, subject: str, body: str) -> dict:
    """
    Encode an email draft into an Outlook Web compose deep-link.

    The URL opens outlook.office.com/mail/deeplink/compose with To, Subject,
    and Body pre-filled.  Compatible with any Office 365 / CSULB account.

    SAFETY:  This function returns a URL string.  It does NOT open a browser,
    trigger a redirect, or send any data over the network.  The caller is
    responsible for deciding whether and when to surface the URL to the user.
    Outlook must remain user-controlled at all times.

    Args:
        to_email: Recipient email address.
        subject:  Email subject line.
        body:     Full email body text (newlines preserved via %0A encoding).

    Returns:
        {
            "found":       True,
            "tool":        "email_tool.build_outlook_url",
            "sources":     [],
            "error":       None | str,
            "outlook_url": str,    # never auto-opened — display to user for click
        }
    """
    if not to_email or not subject or not body:
        missing = [
            f for f, v in [
                ("to_email", to_email),
                ("subject", subject),
                ("body", body),
            ] if not v
        ]
        return {
            "found":       False,
            "tool":        "email_tool.build_outlook_url",
            "sources":     [],
            "error":       f"Missing required fields: {', '.join(missing)}",
            "outlook_url": "",
        }

    try:
        subject_enc = urllib.parse.quote(subject,  safe="")
        body_enc    = urllib.parse.quote(body,     safe="")
        to_enc      = urllib.parse.quote(to_email, safe="")

        outlook_url = (
            "https://outlook.office.com/mail/deeplink/compose"
            f"?to={to_enc}&subject={subject_enc}&body={body_enc}"
        )

        return {
            "found":       True,
            "tool":        "email_tool.build_outlook_url",
            "sources":     [],
            "error":       None,
            "outlook_url": outlook_url,
        }

    except Exception as exc:
        return {
            "found":       False,
            "tool":        "email_tool.build_outlook_url",
            "sources":     [],
            "error":       f"URL encoding failed: {exc}",
            "outlook_url": "",
        }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

def run_cli_test() -> None:
    """
    Smoke-test both email tool functions.

    Run from the project root:
        python -m tools.email_tool
    """
    print("=" * 60)
    print("email_tool — CLI smoke test")
    print("=" * 60)

    # ── Test 1: draft_email with context ─────────────────────────────────────
    print("\n[1] draft_email — with context")
    result = draft_email(
        advisor_name  = "Dr. Jane Smith",
        advisor_email = "jane.smith@csulb.edu",
        program       = "Doctor of Nursing Practice (DNP)",
        context       = "currently a registered nurse with 5 years of experience",
    )
    status = "✓" if result["found"] and result["subject"] and result["body"] else "✗"
    print(f"  {status}  found={result['found']}")
    print(f"     Subject: {result['subject']}")
    print(f"     To:      {result['to']}")
    print(f"     Body snippet: {result['body'][:100].strip()}…")

    # ── Test 2: draft_email without context ───────────────────────────────────
    print("\n[2] draft_email — without context")
    result2 = draft_email(
        advisor_name  = "Dr. John Doe",
        advisor_email = "john.doe@csulb.edu",
        program       = "Ed.D. in P-12 Educational Leadership",
    )
    status2 = "✓" if result2["found"] else "✗"
    print(f"  {status2}  found={result2['found']}  error={result2['error']}")

    # ── Test 3: draft_email — missing fields ──────────────────────────────────
    print("\n[3] draft_email — missing advisor_name")
    result3 = draft_email(advisor_name="", advisor_email="x@csulb.edu", program="DNP")
    status3 = "✓" if not result3["found"] and result3["error"] else "✗"
    print(f"  {status3}  found={result3['found']}  error={result3['error']}")

    # ── Test 4: build_outlook_url ─────────────────────────────────────────────
    print("\n[4] build_outlook_url — well-formed inputs")
    url_result = build_outlook_url(
        to_email = "jane.smith@csulb.edu",
        subject  = result["subject"],
        body     = result["body"],
    )
    status4 = "✓" if url_result["found"] and url_result["outlook_url"].startswith("https://outlook") else "✗"
    print(f"  {status4}  found={url_result['found']}")
    print(f"     URL prefix: {url_result['outlook_url'][:80]}…")

    # ── Test 5: build_outlook_url — missing body ──────────────────────────────
    print("\n[5] build_outlook_url — missing body")
    url_bad = build_outlook_url(to_email="x@csulb.edu", subject="Test", body="")
    status5 = "✓" if not url_bad["found"] and url_bad["error"] else "✗"
    print(f"  {status5}  found={url_bad['found']}  error={url_bad['error']}")

    print(f"\n{'='*60}")
    print("email_tool smoke test complete.")


if __name__ == "__main__":
    run_cli_test()

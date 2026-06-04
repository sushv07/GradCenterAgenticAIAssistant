"""
agent.py
Agentic assistant for the CSULB Graduate Center using OpenAI function calling.

Supports multi-turn conversations — conversation history is passed in and
returned so the UI can persist it across chat turns.

Tools:
    get_advisor(program)                       → advisor details
    draft_email(advisor_name, advisor_email,   → email subject + body template
                program, context)
    create_outlook_draft(to_email, subject,    → mailto: URL for email client
                         body)
    ask_clarification(question, reason)        → request missing info

Environment:
    OPENAI_API_KEY — required
    OPENAI_MODEL   — optional, defaults to gpt-4o-mini
"""

from __future__ import annotations

import json
import os
import urllib.parse
from typing import Any

from openai import OpenAI

from advisor_retrieval import find_advisor, format_advisor_result


# ---------------------------------------------------------------------------
# OpenAI client
# ---------------------------------------------------------------------------

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
MODEL  = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an AI assistant for the CSULB Graduate Center.

You have access to these tools:
  - get_advisor(program)
  - draft_email(advisor_name, advisor_email, program, context)
  - create_outlook_draft(to_email, subject, body)
  - ask_clarification(question, reason)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP-BY-STEP EMAIL WORKFLOW  (follow in order)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1 — Look up the advisor
  • Call get_advisor(program).
  • NEVER use advisor names or emails not returned by this tool.

STEP 2 — Show the advisor contact card
  Always begin your reply with this block (copy the format exactly):

  **Advisor:** [Full Name from tool]
  **Program:** [Program from tool]
  **Email:** [Email from tool]
  **Phone:** [Phone from tool, or "Not available"]

STEP 3 — Draft the email
  • Call draft_email using ONLY the name and email from get_advisor.
  • Display the draft clearly:
      **Subject:** …
      **Body:**
      [full body text]

STEP 4 — Ask for Outlook Web confirmation
  End your reply with exactly this question:
  "Would you like me to open this in Outlook Web?"
  Do NOT call create_outlook_draft yet.

STEP 5 — Generate the Outlook Web link (only after explicit confirmation)
  • Trigger: user says "yes", "open it", "go ahead", "sure", "confirm", or similar.
  • Call create_outlook_draft(to_email, subject, body).
  • The tool returns OUTLOOK_WEB_URL and MAILTO_URL sentinels — include them
    verbatim in your reply so the UI can extract them.
  • Repeat the advisor contact card (Step 2 format) at the top of this reply too.
  • Add this note at the end:
    "If the link doesn't open correctly, please ensure you are logged into Outlook Web."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADDITIONAL RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Never generate an Outlook link unless the user has explicitly confirmed in this turn.
• Never hallucinate advisor details — all names and emails must come from get_advisor.
• If the query is ambiguous (no program mentioned), call ask_clarification first.
• If a tool returns no result, explain clearly and suggest next steps.
• Be polite, concise, and student-friendly — avoid raw JSON in responses.
"""


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_advisor",
            "description": (
                "Look up the graduate advisor for a specific CSULB program. "
                "Always call this first before drafting any email. "
                "Use when the user asks who to contact, who their advisor is, "
                "or mentions a program name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "program": {
                        "type": "string",
                        "description": "Program name, e.g. 'nursing', 'computer science PhD', 'DNP', 'Ed.D.'",
                    }
                },
                "required": ["program"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_email",
            "description": (
                "Generate a polished, student-friendly email draft to a graduate advisor. "
                "Call this after get_advisor returns the advisor's name and email. "
                "Returns a subject line and body ready to review."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "advisor_name": {
                        "type": "string",
                        "description": "Full name of the advisor from get_advisor result",
                    },
                    "advisor_email": {
                        "type": "string",
                        "description": "Advisor's email address from get_advisor result",
                    },
                    "program": {
                        "type": "string",
                        "description": "Program the student is enquiring about",
                    },
                    "context": {
                        "type": "string",
                        "description": "Any extra context from the user's message, e.g. 'applying for Fall 2025', 'questions about deadlines'",
                    },
                },
                "required": ["advisor_name", "advisor_email", "program"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_outlook_draft",
            "description": (
                "Create an Outlook email draft by generating a mailto: link that opens "
                "the student's default email client with the message pre-filled. "
                "ONLY call this after the user has explicitly confirmed the draft."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to_email": {
                        "type": "string",
                        "description": "Recipient email address",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line",
                    },
                    "body": {
                        "type": "string",
                        "description": "Full email body text",
                    },
                },
                "required": ["to_email", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": (
                "Ask the user a clarifying question when the query is ambiguous or "
                "missing a required detail such as a program name. "
                "Call this BEFORE any other tool when information is missing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Clear, specific question to ask the user",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why clarification is needed",
                    },
                },
                "required": ["question", "reason"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _tool_get_advisor(program: str) -> str:
    """Fuzzy-match the program against the advisor dataset."""
    result = find_advisor(program)
    match  = result.get("match")

    if match:
        name    = match.get("advisor_name", "Not available")
        email   = match.get("email", "Not available")
        prog    = match.get("program", program)
        phone   = match.get("phone", "")
        office  = match.get("office", "")
        lines   = [
            f"ADVISOR_NAME: {name}",
            f"ADVISOR_EMAIL: {email}",
            f"PROGRAM: {prog}",
        ]
        if phone:  lines.append(f"PHONE: {phone}")
        if office: lines.append(f"OFFICE: {office}")
        return "\n".join(lines)

    suggestions = result.get("suggestions", [])
    if suggestions:
        return (
            "No exact match found. Did you mean one of these programs?\n"
            + "\n".join(f"- {s}" for s in suggestions)
        )
    return "No advisor found for that program. Please check the program name and try again."


def _tool_draft_email(
    advisor_name: str,
    advisor_email: str,
    program: str,
    context: str = "",
) -> str:
    """Return a structured email draft (subject + body) as a labelled string."""
    context_line = f" I am {context}." if context else ""

    subject = f"Inquiry About the {program} Program — Prospective Student"

    body = (
        f"Dear {advisor_name},\n\n"
        f"I hope this message finds you well. My name is [Your Name], and I am reaching out "
        f"to learn more about the {program} program at CSULB.{context_line}\n\n"
        f"I would love the opportunity to ask a few questions about the program requirements, "
        f"application process, and any upcoming deadlines.\n\n"
        f"Would you be available for a brief meeting or a quick email exchange at your "
        f"convenience? I truly appreciate your time and guidance.\n\n"
        f"Thank you,\n"
        f"[Your Name]\n"
        f"[Your Phone Number]\n"
        f"[Your CSULB ID / Email]"
    )

    return f"SUBJECT: {subject}\nTO: {advisor_email}\nBODY:\n{body}"


def _tool_create_outlook_draft(to_email: str, subject: str, body: str) -> str:
    """
    Build email-client URLs for the student.

    Two links are returned:
    1. Outlook Web deep-link — opens outlook.office.com/compose in the browser
       with To / Subject / Body pre-filled.  Works for any Office 365 / CSULB
       account without requiring a locally installed mail client.
    2. mailto: fallback — opens the OS default mail client (Outlook desktop,
       Apple Mail, Thunderbird, etc.) if configured.

    Uses RFC 2368 percent-encoding so spaces → %20, newlines → %0A.
    """
    subject_enc = urllib.parse.quote(subject,  safe="")
    body_enc    = urllib.parse.quote(body,     safe="")
    to_enc      = urllib.parse.quote(to_email, safe="")

    # Outlook Web compose deep-link (Office 365 / CSULB accounts)
    outlook_web = (
        f"https://outlook.office.com/mail/deeplink/compose"
        f"?to={to_enc}&subject={subject_enc}&body={body_enc}"
    )

    return (
        f"OUTLOOK_WEB_URL: {outlook_web}\n"
        f"Your draft is ready. The UI will open it in Outlook Web automatically."
    )


def _execute_tool(name: str, args: dict) -> str:
    """Dispatch a tool call and return the result string."""
    try:
        if name == "get_advisor":
            return _tool_get_advisor(args["program"])

        elif name == "draft_email":
            return _tool_draft_email(
                advisor_name  = args["advisor_name"],
                advisor_email = args["advisor_email"],
                program       = args["program"],
                context       = args.get("context", ""),
            )

        elif name == "create_outlook_draft":
            return _tool_create_outlook_draft(
                to_email = args["to_email"],
                subject  = args["subject"],
                body     = args["body"],
            )

        elif name == "ask_clarification":
            question = args.get("question", "")
            reason   = args.get("reason", "")
            return f"__CLARIFICATION__:{question}|{reason}"

        else:
            return f"Unknown tool: {name}"

    except KeyError as e:
        return f"Missing argument for {name}: {e}"
    except Exception as e:
        return f"Tool error ({name}): {e}"


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------

def run_agent(
    query: str,
    session_id: str = "default",
    conversation_history: list[dict] | None = None,
    max_iterations: int = 8,
) -> dict[str, Any]:
    """
    Run the OpenAI agentic loop for a user query.

    Supports multi-turn conversations via conversation_history — pass the
    returned "conversation_history" back on the next call to maintain context
    (e.g., so the agent remembers the email draft when the user says "yes").

    Returns:
        {
            "answer":                 str   — markdown response to display,
            "needs_clarification":    bool,
            "clarification_question": str,
            "clarification_reason":   str,
            "tools_used":             list[str],
            "conversation_history":   list[dict] — updated OpenAI messages,
            "session_id":             str,
            "model":                  str,
        }
    """
    _base: dict[str, Any] = {
        "answer":                 "",
        "needs_clarification":    False,
        "clarification_question": "",
        "clarification_reason":   "",
        "tools_used":             [],
        "conversation_history":   conversation_history or [],
        "session_id":             session_id,
        "model":                  MODEL,
    }

    if not query or not query.strip():
        return {**_base, "answer": "Please ask me something about CSULB graduate admissions."}

    # Build message list: system + history + new user message
    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        *(conversation_history or []),
        {"role": "user", "content": query},
    ]

    tools_used: list[str] = []

    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=_TOOLS,
            tool_choice="auto",
        )

        msg    = response.choices[0].message
        reason = response.choices[0].finish_reason

        messages.append(msg.model_dump(exclude_unset=True))

        # ── RESPOND: model has a complete final answer ─────────────────────────
        if reason == "stop" or not msg.tool_calls:
            # Strip system prompt from persisted history
            history = [m for m in messages if m.get("role") != "system"]
            return {
                **_base,
                "answer":               msg.content or "",
                "tools_used":           tools_used,
                "conversation_history": history,
            }

        # ── CALL_TOOL: execute each tool call ────────────────────────────────
        clarification_hit: dict | None = None

        for tool_call in msg.tool_calls:
            fn_name = tool_call.function.name
            try:
                fn_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            tools_used.append(fn_name)
            tool_result = _execute_tool(fn_name, fn_args)

            # Detect ASK_CLARIFICATION sentinel
            if tool_result.startswith("__CLARIFICATION__:"):
                payload    = tool_result[len("__CLARIFICATION__:"):]
                parts      = payload.split("|", 1)
                clarification_hit = {
                    "question": parts[0].strip(),
                    "reason":   parts[1].strip() if len(parts) > 1 else "",
                }
                tool_result = "Clarification requested — awaiting user response."

            messages.append({
                "role":         "tool",
                "tool_call_id": tool_call.id,
                "content":      tool_result,
            })

        if clarification_hit:
            history = [m for m in messages if m.get("role") != "system"]
            return {
                **_base,
                "needs_clarification":    True,
                "clarification_question": clarification_hit["question"],
                "clarification_reason":   clarification_hit["reason"],
                "tools_used":             tools_used,
                "conversation_history":   history,
            }

    # Safety fallback
    history = [m for m in messages if m.get("role") != "system"]
    return {
        **_base,
        "answer": (
            "I wasn't able to complete that in the allowed steps. "
            "Please try rephrasing your request."
        ),
        "tools_used":           tools_used,
        "conversation_history": history,
    }


# ---------------------------------------------------------------------------
# CLI (multi-turn REPL)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY is not set.")
        sys.exit(1)

    print(f"CSULB Grad Center Agent  |  model: {MODEL}  |  type 'exit' to quit\n")
    history: list[dict] = []

    while True:
        try:
            q = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not q or q.lower() in ("exit", "quit"):
            break

        result  = run_agent(q, conversation_history=history)
        history = result["conversation_history"]

        if result["needs_clarification"]:
            print(f"\nAssistant: {result['clarification_question']}\n")
        else:
            print(f"\nAssistant: {result['answer']}\n")

        if result["tools_used"]:
            print(f"[Tools: {', '.join(result['tools_used'])}]\n")

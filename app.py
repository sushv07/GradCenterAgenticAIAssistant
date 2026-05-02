"""
CSULB Grad Center – Streamlit UI
Run: streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so local imports work
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import tracker
import orchestrator

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="CSULB Grad Center Assistant",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Shared CSS
# ─────────────────────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    /* ── Card container ──────────────────────────────── */
    .step-card {
        border: 1px solid #d1d5db;
        border-radius: 10px;
        padding: 16px 18px;
        margin-bottom: 12px;
        background: #ffffff;
        transition: box-shadow .15s;
    }
    .step-card:hover { box-shadow: 0 3px 10px rgba(0,0,0,.10); }

    /* blocked card — no opacity (kills contrast); just mute the bg */
    .step-card.blocked {
        background: #f9fafb;
        border-color: #e5e7eb;
        border-left: 4px solid #f87171;
    }

    /* ── Status badges ───────────────────────────────── */
    .badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: .75rem;
        font-weight: 700;
        letter-spacing: .3px;
    }
    /* All badge text must clear WCAG AA (≥4.5:1) */
    .badge-pending     { background: #e5e7eb; color: #374151; }
    .badge-in_progress { background: #fef3c7; color: #92400e; }
    .badge-completed   { background: #d1fae5; color: #065f46; }
    .badge-blocked     { background: #fee2e2; color: #991b1b; }

    /* ── Priority labels ─────────────────────────────── */
    .pri-high   { color: #b91c1c; font-weight: 700; font-size: .8rem; }
    .pri-medium { color: #c2410c; font-weight: 700; font-size: .8rem; }
    .pri-low    { color: #15803d; font-weight: 700; font-size: .8rem; }

    /* ── Step card meta line ─────────────────────────── */
    .step-meta {
        font-size: .78rem;
        color: #6b7280;          /* replaces #999 — passes AA on white */
        margin-bottom: 4px;
    }

    /* ── Summary box ─────────────────────────────────── */
    .summary-box {
        background: #eff6ff;
        border-left: 4px solid #3b82f6;
        border-radius: 6px;
        padding: 14px 18px;
        margin-bottom: 14px;
        color: #1e3a5f;          /* explicit dark text — no inherited grey */
        font-size: .97rem;
        line-height: 1.55;
    }

    /* ── Primary action box — high-visibility highlight ─ */
    .action-box {
        background: #fffbeb;
        border-left: 5px solid #d97706;
        border-radius: 6px;
        padding: 12px 18px;
        margin-bottom: 18px;
        color: #1c1917;          /* near-black for maximum contrast */
        font-size: 1rem;
        font-weight: 600;
        line-height: 1.5;
    }
    .action-box .action-label {
        display: inline-block;
        background: #d97706;
        color: #ffffff;
        font-size: .7rem;
        font-weight: 700;
        letter-spacing: .6px;
        text-transform: uppercase;
        border-radius: 4px;
        padding: 2px 7px;
        margin-right: 8px;
        vertical-align: middle;
    }

    /* ── Blocked step warning ────────────────────────── */
    .blocked-msg {
        margin-top: 8px;
        padding: 6px 10px;
        background: #fff1f2;
        border-radius: 5px;
        color: #9f1239;          /* deep rose — AA on #fff1f2 */
        font-size: .84rem;
    }

    /* ── Suggestion chips ────────────────────────────── */
    .chip-label {
        font-size: .82rem;
        font-weight: 600;
        color: #374151;
        margin-bottom: 6px;
    }

    /* ── Hide Streamlit branding ─────────────────────── */
    #MainMenu, footer { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# Session state initialisation
# ─────────────────────────────────────────────────────────────────────────────

def _init_state() -> None:
    defaults: dict = {
        "session_id":   "default",
        "messages":     [],        # [{role, content, response}]
        "last_response": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_PRI_LABEL = {"high": "● High", "medium": "● Medium", "low": "● Low"}
_PRI_CLASS = {"high": "pri-high", "medium": "pri-medium", "low": "pri-low"}

_STATUS_EMOJI = {
    "pending":     "⏳",
    "in_progress": "🚧",
    "completed":   "✅",
}


def _badge(status: str, is_blocked: bool = False) -> str:
    if is_blocked:
        return '<span class="badge badge-blocked">🔒 Blocked</span>'
    return f'<span class="badge badge-{status}">{_STATUS_EMOJI.get(status, "")} {status.replace("_", " ").title()}</span>'


def _pri_html(priority: str) -> str:
    cls = _PRI_CLASS.get(priority, "pri-medium")
    lbl = _PRI_LABEL.get(priority, priority)
    return f'<span class="{cls}">{lbl}</span>'


def _reload_progress() -> dict | None:
    sid = st.session_state["session_id"]
    try:
        return tracker.progress(sid)
    except KeyError:
        return None


def _mark(step_ref: int | str, status: str) -> None:
    """Mark a step and trigger a full rerun so the UI refreshes."""
    sid = st.session_state["session_id"]
    try:
        tracker.mark(sid, step_ref, status)
        st.toast(f"Step {step_ref} → {status.replace('_', ' ')}", icon="✅")
    except Exception as e:
        st.error(str(e))
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown("## 🎓 Grad Center")
        st.markdown("---")

        # Session picker
        sessions = tracker.list_sessions()
        session_ids = [s["session_id"] for s in sessions]

        st.markdown("**Session**")
        new_sid = st.text_input(
            "Session ID",
            value=st.session_state["session_id"],
            label_visibility="collapsed",
        )
        if new_sid != st.session_state["session_id"]:
            st.session_state["session_id"] = new_sid
            st.session_state["messages"] = []
            st.session_state["last_response"] = None
            st.rerun()

        if sessions:
            st.markdown("**Saved sessions**")
            for s in sessions:
                pct = round(100 * s["completed"] / max(s["total"], 1))
                active = "← active" if s["session_id"] == st.session_state["session_id"] else ""
                if st.button(
                    f"{s['session_id']}  {s['completed']}/{s['total']} ({pct}%) {active}",
                    key=f"switch_{s['session_id']}",
                    use_container_width=True,
                ):
                    st.session_state["session_id"] = s["session_id"]
                    st.session_state["messages"] = []
                    st.session_state["last_response"] = None
                    st.rerun()

        st.markdown("---")
        sid = st.session_state.get("session_id", "default")
        if st.button("🗑 Clear session history", key=f"{sid}_clear_history", use_container_width=True):
            st.session_state["messages"] = []
            st.session_state["last_response"] = None
            st.rerun()

        st.markdown("---")
        st.caption("CSULB Graduate Center AI Assistant")


# ─────────────────────────────────────────────────────────────────────────────
# Progress bar widget
# ─────────────────────────────────────────────────────────────────────────────

def _render_progress_widget(p: dict) -> None:
    pct      = p["percent_done"]
    total    = p["total"]
    done     = p["completed"]
    blocked  = p.get("blocked", 0)
    in_prog  = p.get("in_progress", 0)
    remaining = total - done

    st.progress(pct / 100, text=f"**{pct}%** complete — {done} of {total} done")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("✅ Done",        f"{done}/{total}")
    col2.metric("🚧 In Progress", in_prog)
    col3.metric("⏳ Remaining",   remaining)
    col4.metric("🔒 Blocked",     blocked)


# ─────────────────────────────────────────────────────────────────────────────
# Step card renderer
# ─────────────────────────────────────────────────────────────────────────────

def _render_step_card(step: dict, idx: int, view: str = "card") -> None:
    step_num   = step.get("step", idx + 1)
    step_id    = step.get("id", f"step-{step_num}")
    title      = step.get("title") or step.get("action", "")
    status     = step.get("status", "pending")
    priority   = step.get("priority", "medium")
    is_blocked = bool(step.get("is_blocked"))
    blocked_by = step.get("blocked_by") or []
    warnings   = step.get("warnings") or []
    resources  = step.get("resources") or []
    primary    = step.get("primary_action", "")
    details    = step.get("details", "")
    depends_on = step.get("depends_on") or []
    completed  = status == "completed"

    card_cls = "step-card blocked" if is_blocked else "step-card"

    # Card header
    blocked_html = ""
    if is_blocked and blocked_by:
        msgs = "".join(
            f'<div class="blocked-msg">⛔ Blocked until <strong>Step {b["step"]} — {b["title"]}</strong> is completed</div>'
            for b in blocked_by
        )
        blocked_html = msgs

    st.markdown(
        f"""
        <div class="{card_cls}">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
            <div style="flex:1; min-width:0;">
              <div class="step-meta">Step {step_num} &nbsp;·&nbsp; <code style="font-size:.75rem; color:#6b7280;">{step_id}</code></div>
              <strong style="font-size:1rem; color:#111827;">{title}</strong>
            </div>
            <div style="text-align:right; white-space:nowrap; flex-shrink:0;">
              {_badge(status, is_blocked)}&nbsp;{_pri_html(priority)}
            </div>
          </div>
          {blocked_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Buttons are rendered below (outside the card HTML for Streamlit interactivity)

    # Buttons — shown outside the raw HTML for Streamlit interactivity
    # Key includes `view` so the same step rendered in multiple tabs never collides
    sid = st.session_state["session_id"]
    k = f"{sid}_{view}_{step_id}"
    if not completed and not is_blocked:
        btn_col1, btn_col2, _ = st.columns([1.4, 1.6, 4])
        with btn_col1:
            if status != "in_progress":
                if st.button(
                    "▶ Start",
                    key=f"{k}_start",
                    use_container_width=True,
                    type="secondary",
                ):
                    _mark(step_num, "in_progress")
        with btn_col2:
            if st.button(
                "✓ Mark complete",
                key=f"{k}_done",
                use_container_width=True,
                type="primary",
            ):
                _mark(step_num, "completed")

    elif completed:
        col_undo, _ = st.columns([1.5, 5])
        with col_undo:
            if st.button(
                "↩ Undo",
                key=f"{k}_undo",
                use_container_width=True,
                type="secondary",
            ):
                _mark(step_num, "pending")

    # Expander with extra detail
    if primary or details or warnings or resources:
        with st.expander("Details", expanded=False):
            if primary:
                st.markdown(
                    f'<div class="action-box" style="margin-bottom:10px;">'
                    f'<span class="action-label">Do this</span>{primary}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            if details:
                st.markdown(
                    f'<p style="color:#374151; font-size:.9rem; margin:0 0 8px 0;">{details}</p>',
                    unsafe_allow_html=True,
                )
            if warnings:
                for w in warnings:
                    st.warning(w)
            if resources:
                st.markdown("**Resources:**")
                for r in resources:
                    label = r.get("label", r.get("url", "Link"))
                    url   = r.get("url", "")
                    if url.startswith("http"):
                        st.markdown(f"- [{label}]({url})")
                    else:
                        st.markdown(f"- {label}: `{url}`")


# ─────────────────────────────────────────────────────────────────────────────
# Pending panel (priority-sorted with block info)
# ─────────────────────────────────────────────────────────────────────────────

def _render_pending_panel() -> None:
    sid = st.session_state["session_id"]
    try:
        view = tracker.pending(sid)
    except KeyError:
        st.info("No active session. Ask me to build a checklist first.")
        return

    pending_steps = view["pending"]
    if not pending_steps:
        st.success("🎉 All tasks completed!")
        return

    ready   = view.get("ready_count", len(pending_steps))
    blocked = view.get("blocked_count", 0)
    total   = view["total"]
    done    = total - len(pending_steps)

    st.markdown(
        f"**{done}/{total} done** &nbsp;·&nbsp; "
        f"✅ {ready} ready &nbsp;·&nbsp; 🔒 {blocked} blocked",
        unsafe_allow_html=True,
    )
    st.divider()

    for i, step in enumerate(pending_steps):
        _render_step_card(step, i, view="pending")


# ─────────────────────────────────────────────────────────────────────────────
# Full checklist panel (from steps list in response)
# ─────────────────────────────────────────────────────────────────────────────

def _render_checklist_panel(steps: list[dict]) -> None:
    if not steps:
        st.info("No steps to display.")
        return

    sid = st.session_state["session_id"]

    # Reload live status from tracker so buttons take effect immediately
    try:
        record = tracker.load(sid)
        if record:
            id_to_status = {s["id"]: s["status"] for s in record.get("steps", []) if "id" in s}
            completed_ids = {s["id"] for s in record.get("steps", []) if s.get("status") == "completed"}

            # Annotate steps with live status + blocked info
            enriched = []
            for step in steps:
                sid_key = step.get("id", "")
                live_status = id_to_status.get(sid_key, step.get("status", "pending"))
                enriched_step = {**step, "status": live_status}
                enriched_step = tracker._annotate_step(enriched_step, steps, completed_ids)
                enriched.append(enriched_step)
            steps = enriched
    except Exception:
        pass

    for i, step in enumerate(steps):
        _render_step_card(step, i, view="checklist")


# ─────────────────────────────────────────────────────────────────────────────
# Guidance panel (read-only numbered list)
# ─────────────────────────────────────────────────────────────────────────────

def _render_guidance_panel(steps: list[dict]) -> None:
    for step in steps:
        step_num = step.get("number") or step.get("step", "?")
        title    = step.get("do") or step.get("title") or step.get("action", "")
        outcome  = step.get("why") or step.get("outcome", "")
        time_est = step.get("time", "")
        watch    = step.get("watch_out") or (step.get("warnings") or [None])[0]
        link     = step.get("link") or (step.get("resources") or [{}])[0].get("url")

        with st.expander(f"Step {step_num} — {title}", expanded=step_num == 1):
            if outcome:
                st.markdown(f"**Goal:** {outcome}")
            if time_est:
                st.caption(f"⏱ {time_est}")
            how_items = step.get("how") or step.get("how", [])
            if how_items:
                st.markdown("**How to:**")
                for h in how_items:
                    st.markdown(f"- {h}")
            prep_items = step.get("prep") or []
            if prep_items:
                st.markdown("**Before you start:**")
                for p in prep_items:
                    st.markdown(f"- {p}")
            if watch:
                st.warning(f"⚠️ {watch}")
            if link and link.startswith("http"):
                st.markdown(f"[🔗 Resource]({link})")


# ─────────────────────────────────────────────────────────────────────────────
# Advisor panel
# ─────────────────────────────────────────────────────────────────────────────

def _render_advisor_panel(response: dict) -> None:
    advisor_data = response.get("advisor_data", {})
    match        = advisor_data.get("match")
    suggestions  = advisor_data.get("suggestions", [])

    if match:
        col_l, col_r = st.columns(2)

        with col_l:
            st.markdown(f"**Program**")
            st.markdown(match.get("program") or "—")

            st.markdown("")
            st.markdown(f"**Advisor**")
            st.markdown(match.get("advisor_name") or "Not available")

        with col_r:
            email = match.get("email")
            st.markdown("**Email**")
            if email:
                st.markdown(f"[{email}](mailto:{email})")
            else:
                st.markdown("Not available")

            st.markdown("")
            phone = match.get("phone")
            st.markdown("**Phone**")
            st.markdown(phone if phone else "Not available")

        if match.get("office"):
            st.markdown(f"**Office:** {match['office']}")

    elif suggestions:
        st.markdown("**Did you mean one of these programs?**")
        for i, name in enumerate(suggestions, 1):
            st.markdown(f"{i}. {name}")
        st.caption("Try typing the full program name for a direct match.")

    else:
        # No match, no suggestions — show available programs (doctoral list or full list)
        known = advisor_data.get("known_programs", [])
        if known:
            st.markdown("**Available programs:**")
            for name in known:
                st.markdown(f"- {name}")


# ─────────────────────────────────────────────────────────────────────────────
# Answer panel
# ─────────────────────────────────────────────────────────────────────────────

def _render_answer_panel(response: dict) -> None:
    ans        = response.get("answer")
    confidence = response.get("confidence", "")

    if isinstance(ans, dict) and "question" in ans:
        st.markdown(f"**Q:** {ans['question']}")
        st.markdown(f"**A:** {ans['answer']}")
        src = ans.get("source", "")
        if src:
            st.caption(f"Source: {src}")
    elif isinstance(ans, list):
        for item in ans:
            if isinstance(item, dict):
                st.markdown(f"**Q:** {item.get('question', '')}")
                st.markdown(f"**A:** {item.get('answer', '')}")
                st.divider()
    elif isinstance(ans, str):
        st.markdown(ans)

    if confidence:
        colour = {"high": "green", "medium": "orange", "low": "red"}.get(confidence, "grey")
        st.markdown(
            f'<span style="color:{colour}; font-size:.8rem;">Confidence: {confidence}</span>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tracking panel (mark / pending / progress)
# ─────────────────────────────────────────────────────────────────────────────

def _render_tracking_panel(response: dict) -> None:
    action = response.get("action") or response.get("details", {}).get("action", "")

    # Progress bar
    p = response.get("progress")
    if p and p.get("total", 0) > 0:
        _render_progress_widget(p)
        st.markdown("")

    # Current focus
    focus = response.get("current_focus")
    if focus:
        is_blocked = focus.get("is_blocked")
        icon       = "🔒" if is_blocked else ("🚧" if focus.get("label", "").startswith("🚧") else "⏳")
        st.markdown(f"**{icon} {focus['label']} — Step {focus['step']}: {focus['title']}**")
        if is_blocked:
            for b in focus.get("blocked_by", []):
                st.error(f"⛔ Blocked by Step {b['step']} ({b['title']})")
        elif focus.get("details"):
            st.caption(focus["details"])

    # Next step
    next_step = response.get("next_step")
    if next_step and next_step != "All tasks complete — nothing left to do here.":
        st.info(f"➡️ **Next:** {next_step}")

    # Pending list
    pending_items = response.get("pending") or []
    if pending_items:
        st.markdown("**Pending tasks (by priority):**")
        for item in pending_items:
            is_blocked = item.get("is_blocked")
            title      = item.get("title") or item.get("action", "")
            step_id    = item.get("id", "")
            priority   = item.get("priority", "medium")
            step_num   = item.get("step")
            icon       = "🔒 " if is_blocked else ""
            pri_icon   = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(priority, "")
            st.markdown(
                f"- {icon}**Step {step_num}** — {title} &nbsp;{pri_icon} &nbsp;`{step_id}`",
                unsafe_allow_html=True,
            )
            if is_blocked:
                for b in item.get("blocked_by", []):
                    st.caption(f"    ⛔ Complete Step {b['step']} ({b['title']}) first")

    # Session list
    sessions = response.get("sessions") or []
    if sessions:
        st.markdown("**Saved sessions:**")
        for s in sessions:
            pct = round(100 * s.get("completed", 0) / max(s.get("total", 1), 1))
            st.markdown(
                f"- **{s['session_id']}** — {s['completed']}/{s['total']} ({pct}%)  "
                f"_{s.get('intent', '')}_"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Render a complete response object
# ─────────────────────────────────────────────────────────────────────────────

def _render_response(response: dict, msg_idx: int = 0) -> None:
    route   = response.get("route", "")
    summary = response.get("summary", "")
    action  = response.get("primary_action", "")
    source  = (response.get("source") or {}).get("url", "")

    # Summary + primary action
    if summary:
        st.markdown(
            f'<div class="summary-box">{summary}</div>',
            unsafe_allow_html=True,
        )
    if action:
        st.markdown(
            f'<div class="action-box">'
            f'<span class="action-label">Next step</span>{action}'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Live progress bar (always shown when a session has steps)
    p = _reload_progress()
    if p and p["total"] > 0 and route in ("checklist", "tracking"):
        _render_progress_widget(p)
        st.markdown("")

    # Route-specific content
    if route == "advisor":
        _render_advisor_panel(response)

    elif route == "checklist":
        st.markdown("### Your Checklist")
        _render_checklist_panel(response.get("steps", []))

    elif route == "guidance":
        st.markdown("### Step-by-Step Guidance")
        _render_guidance_panel(response.get("steps", []))

    elif route == "tracking":
        _render_tracking_panel(response)

    elif route == "answer":
        st.markdown("### Answer")
        _render_answer_panel(response)

    # Source link
    if source:
        st.caption(f"Source: [{source}]({source})")

    # Next actions as suggestion chips
    next_actions = response.get("next_actions") or []
    if next_actions:
        st.divider()
        st.markdown(
            '<div class="chip-label">💡 What you can ask next</div>',
            unsafe_allow_html=True,
        )
        cols = st.columns(min(len(next_actions), 3))
        sid = st.session_state["session_id"]
        for i, suggestion in enumerate(next_actions[:3]):
            with cols[i]:
                if st.button(suggestion, key=f"{sid}_msg{msg_idx}_suggest_{i}", use_container_width=True):
                    _submit_query(suggestion)


# ─────────────────────────────────────────────────────────────────────────────
# Query submission
# ─────────────────────────────────────────────────────────────────────────────

def _submit_query(query: str) -> None:
    sid      = st.session_state["session_id"]
    response = orchestrator.run(query, session_id=sid)

    st.session_state["messages"].append({
        "role":     "user",
        "content":  query,
    })
    st.session_state["messages"].append({
        "role":     "assistant",
        "content":  response.get("summary", ""),
        "response": response,
    })
    st.session_state["last_response"] = response
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Main layout
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    _render_sidebar()

    st.title("🎓 CSULB Grad Center Assistant")
    st.caption(f"Session: **{st.session_state['session_id']}**")

    # ── Tabs: Chat | Checklist | Pending ─────────────────────────────────────
    tab_chat, tab_checklist, tab_pending = st.tabs(["💬 Chat", "📋 Full Checklist", "⏳ Pending Tasks"])

    # ── Chat tab ─────────────────────────────────────────────────────────────
    with tab_chat:
        # Render message history
        for i, msg in enumerate(st.session_state["messages"]):
            with st.chat_message(msg["role"]):
                if msg["role"] == "assistant" and "response" in msg:
                    _render_response(msg["response"], msg_idx=i)
                else:
                    st.markdown(msg["content"])

        # Chat input (pinned to bottom)
        if query := st.chat_input("Ask me anything about CSULB grad admissions…"):
            _submit_query(query)

    # ── Full checklist tab ────────────────────────────────────────────────────
    with tab_checklist:
        sid = st.session_state["session_id"]
        record = tracker.load(sid)
        if not record:
            st.info(
                'No checklist yet. Go to the **Chat** tab and ask: '
                '*"Give me a checklist for newly admitted students"*'
            )
        else:
            steps = record.get("steps", [])
            p = _reload_progress()
            if p:
                st.markdown(f"### {record.get('intent', 'Checklist').replace('_', ' ').title()}")
                _render_progress_widget(p)
                st.markdown("")

            # Re-annotate with live blocked status
            completed_ids = {s["id"] for s in steps if s.get("status") == "completed"}
            annotated = [tracker._annotate_step(s, steps, completed_ids) for s in steps]
            _render_checklist_panel(annotated)

    # ── Pending tasks tab ────────────────────────────────────────────────────
    with tab_pending:
        sid = st.session_state["session_id"]
        record = tracker.load(sid)
        if not record:
            st.info(
                'No checklist yet. Go to the **Chat** tab and ask: '
                '*"Give me a checklist for applying"*'
            )
        else:
            st.markdown(f"### Pending — {record.get('intent', '').replace('_', ' ').title()}")
            _render_pending_panel()


if __name__ == "__main__":
    main()

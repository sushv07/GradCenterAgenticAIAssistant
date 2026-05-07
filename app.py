"""
CSULB Graduate Center AI Assistant – Streamlit UI
Navy #003366 · Gold #FFC72C
Run: streamlit run app.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import tracker
import orchestrator


# ─────────────────────────────────────────────────────────────────────────────
# Lazy agent loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_agent():
    try:
        import agent as _agent_mod
        return _agent_mod
    except ImportError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Page config  (must be first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="CSULB Graduate Center AI Assistant",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ═══════════════════════════════════════════════════════════════════════
   CSULB GRADUATE CENTER  –  Production UI
   Navy #003366 · Gold #FFC72C
═══════════════════════════════════════════════════════════════════════ */

/* ── Design tokens ───────────────────────────────────────────────────── */
:root {
    --navy:        #003366;
    --navy-deep:   #002244;
    --navy-mid:    #004080;
    --gold:        #FFC72C;
    --gold-dark:   #e6b000;
    --bg:          #f4f6f9;
    --surface:     #ffffff;
    --text:        #111827;
    --text-sub:    #374151;
    --muted:       #6b7280;
    --border:      #d1d9e0;
    --border-soft: #e5e9f0;
    --radius:      8px;
    --radius-lg:   12px;
    --ease:        cubic-bezier(0.16, 1, 0.3, 1);
    --shadow-xs:   0 1px 2px rgba(0,0,0,0.06);
    --shadow-sm:   0 2px 6px rgba(0,0,0,0.07);
    --shadow-md:   0 4px 16px rgba(0,0,0,0.09);
    --shadow-navy: 0 4px 14px rgba(0,51,102,0.18);
}


/* ══════════════════════════════════════════════════════════════════════
   LAYOUT
══════════════════════════════════════════════════════════════════════ */

.stApp { background: var(--bg) !important; }

/* Wider, grounded content area – removes the "floating card" feel */
.main .block-container {
    padding-top:    0         !important;
    padding-bottom: 4rem      !important;
    padding-left:   2.5rem    !important;
    padding-right:  2.5rem    !important;
    max-width:      100%      !important;
}

/* Streamlit injects a gap above tab panels — collapse it */
.stTabs [data-baseweb="tab-panel"] > div:first-child { padding-top: 0 !important; }


/* ══════════════════════════════════════════════════════════════════════
   SIDEBAR
══════════════════════════════════════════════════════════════════════ */

[data-testid="stSidebar"] {
    background: var(--navy) !important;
    border-right: 3px solid var(--gold);
    box-shadow: 2px 0 12px rgba(0,0,0,0.12);
}

/* Text inside sidebar */
[data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] .stMarkdown h2,
[data-testid="stSidebar"] .stMarkdown h3,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span   { color: rgba(220,228,255,0.88) !important; }
[data-testid="stSidebar"] hr     { border-color: rgba(255,255,255,0.10) !important; margin: 10px 0 !important; }
[data-testid="stSidebar"] .stCaption { color: rgba(255,255,255,0.38) !important; font-size: 0.74rem !important; }

/* Session text input */
[data-testid="stSidebar"] .stTextInput > div > input {
    background:    rgba(255,255,255,0.09) !important;
    border:        1px solid rgba(255,255,255,0.18) !important;
    color:         #ffffff !important;
    border-radius: var(--radius) !important;
    font-size:     0.84rem !important;
    transition:    border-color 0.15s var(--ease), box-shadow 0.15s var(--ease) !important;
}
[data-testid="stSidebar"] .stTextInput > div > input:focus {
    border-color: rgba(255,199,44,0.55) !important;
    box-shadow:   0 0 0 3px rgba(255,199,44,0.12) !important;
}

/* Sidebar buttons (sessions / clear) */
[data-testid="stSidebar"] .stButton > button {
    background:    rgba(255,255,255,0.07) !important;
    color:         rgba(220,228,255,0.82) !important;
    border:        1px solid rgba(255,255,255,0.14) !important;
    border-radius: var(--radius) !important;
    font-size:     0.82rem !important;
    font-weight:   500 !important;
    transition:    background 0.18s var(--ease), color 0.18s var(--ease), border-color 0.18s var(--ease) !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background:    rgba(255,199,44,0.18) !important;
    color:         var(--gold)            !important;
    border-color:  rgba(255,199,44,0.40)  !important;
    font-weight:   600                    !important;
}
[data-testid="stSidebar"] .stToggle { color: rgba(220,228,255,0.88) !important; }


/* ══════════════════════════════════════════════════════════════════════
   SIDEBAR NAV
══════════════════════════════════════════════════════════════════════ */

.sidebar-brand {
    text-align:    center;
    padding:       22px 14px 16px;
    border-bottom: 1px solid rgba(255,255,255,0.10);
    margin-bottom: 12px;
}
.sidebar-brand-logo {
    font-size:     2rem;
    display:       block;
    margin-bottom: 8px;
    line-height:   1;
}
.sidebar-brand-name {
    color:       #ffffff;
    font-size:   0.88rem;
    font-weight: 700;
    display:     block;
    line-height: 1.35;
    letter-spacing: 0.1px;
}
.sidebar-brand-tag {
    display:        inline-block;
    margin-top:     5px;
    color:          var(--gold);
    font-size:      0.62rem;
    font-weight:    700;
    letter-spacing: 1.1px;
    text-transform: uppercase;
    opacity:        0.85;
}

.nav-section-label {
    color:          rgba(255,255,255,0.30) !important;
    font-size:      0.60rem !important;
    font-weight:    700 !important;
    letter-spacing: 1.3px !important;
    text-transform: uppercase !important;
    padding:        0 6px;
    margin-bottom:  5px;
    display:        block;
}

.nav-item {
    display:        flex;
    align-items:    center;
    gap:            10px;
    padding:        9px 12px;
    border-radius:  6px;
    color:          rgba(220,228,255,0.65);
    font-size:      0.85rem;
    font-weight:    400;
    margin-bottom:  2px;
    cursor:         default;
    border-left:    3px solid transparent;
    transition:     background 0.16s var(--ease),
                    color      0.16s var(--ease),
                    border-color 0.16s var(--ease);
}
.nav-item:hover {
    background:      rgba(255,255,255,0.06);
    color:           rgba(255,255,255,0.92);
    border-left-color: rgba(255,199,44,0.35);
}

/* ── Active nav item – clear, decisive, unmistakable ─────────────────── */
.nav-item.active {
    background:      rgba(255,199,44,0.16);
    color:           #ffffff;
    font-weight:     600;
    border-left:     3px solid var(--gold);
    letter-spacing:  0.1px;
}
.nav-item.active span:first-child { opacity: 1; }


/* ══════════════════════════════════════════════════════════════════════
   HEADER  – authority & hierarchy
══════════════════════════════════════════════════════════════════════ */

.csulb-header {
    background:    var(--navy);
    padding:       18px 32px;
    margin:        -1rem -1rem 2rem -1rem;
    display:       flex;
    align-items:   center;
    gap:           16px;
    border-bottom: 4px solid var(--gold);
    /* anchor the header – kills the "floating" band effect */
    box-shadow:    0 2px 8px rgba(0,0,0,0.20);
}
.csulb-header-logo {
    font-size:  2.1rem;
    line-height: 1;
    flex-shrink: 0;
}
.csulb-header-text { flex: 1; min-width: 0; }
.csulb-header-title {
    color:          #ffffff;
    font-size:      1.35rem;
    font-weight:    800;
    letter-spacing: -0.3px;
    margin:         0;
    line-height:    1.15;
    /* subtle lift for readability on dark bg */
    text-shadow:    0 1px 3px rgba(0,0,0,0.25);
}
.csulb-header-sub {
    color:          var(--gold);
    font-size:      0.68rem;
    font-weight:    600;
    letter-spacing: 1.1px;
    text-transform: uppercase;
    margin:         5px 0 0;
    opacity:        0.85;
}
.csulb-header-right {
    text-align:  right;
    flex-shrink: 0;
}
.csulb-header-badge {
    display:        inline-block;
    background:     rgba(255,199,44,0.18);
    color:          #ffffff;
    font-size:      0.70rem;
    font-weight:    700;
    padding:        5px 16px;
    border-radius:  20px;
    letter-spacing: 0.4px;
    border:         1px solid rgba(255,199,44,0.40);
}
.csulb-header-session {
    color:      rgba(255,255,255,0.42);
    font-size:  0.68rem;
    margin-top: 5px;
    letter-spacing: 0.2px;
}


/* ══════════════════════════════════════════════════════════════════════
   MODE BANNER
══════════════════════════════════════════════════════════════════════ */

.mode-banner {
    display:       flex;
    align-items:   center;
    gap:           10px;
    background:    var(--surface);
    color:         var(--text-sub);
    border:        1px solid var(--border-soft);
    border-radius: var(--radius);
    padding:       9px 16px;
    margin-bottom: 20px;
    font-size:     0.83rem;
    font-weight:   400;
    box-shadow:    var(--shadow-xs);
}
.mode-banner-tag {
    margin-left:    auto;
    background:     var(--navy);
    color:          #ffffff;
    font-size:      0.65rem;
    font-weight:    700;
    padding:        3px 10px;
    border-radius:  5px;
    letter-spacing: 0.4px;
    text-transform: uppercase;
}


/* ══════════════════════════════════════════════════════════════════════
   TABS
══════════════════════════════════════════════════════════════════════ */

.stTabs [data-baseweb="tab-list"] {
    background:    transparent;
    border-bottom: 2px solid var(--border-soft);
    gap:           0;
    padding:       0;
}
.stTabs [data-baseweb="tab"] {
    padding:     11px 22px;
    font-weight: 500;
    font-size:   0.87rem;
    color:       var(--muted) !important;
    border-radius: 0 !important;
    background:  transparent !important;
    transition:  color 0.15s var(--ease) !important;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--text-sub) !important; }
.stTabs [aria-selected="true"] {
    color:       var(--navy)  !important;
    font-weight: 700          !important;
    border-bottom: 3px solid var(--gold) !important;
    margin-bottom: -2px;       /* sits on the border-bottom of the tab list */
}
.stTabs [data-baseweb="tab-panel"] {
    background: transparent;
    border:     none;
    padding:    24px 0 0;
}


/* ══════════════════════════════════════════════════════════════════════
   BUTTONS  – micro-interactions
══════════════════════════════════════════════════════════════════════ */

/* Default outlined button */
.stButton > button {
    background:     var(--surface) !important;
    color:          var(--navy)    !important;
    border:         1.5px solid var(--navy) !important;
    font-weight:    500            !important;
    border-radius:  var(--radius)  !important;
    transition:     background   0.16s var(--ease),
                    color        0.16s var(--ease),
                    border-color 0.16s var(--ease),
                    box-shadow   0.16s var(--ease),
                    transform    0.12s var(--ease) !important;
}
.stButton > button:hover {
    background:   var(--navy)    !important;
    color:        #ffffff        !important;
    border-color: var(--navy)    !important;
    box-shadow:   var(--shadow-sm) !important;
    transform:    translateY(-1px) !important;
}
.stButton > button:active { transform: translateY(0) !important; }

/* Primary filled button */
.stButton > button[kind="primary"] {
    background:   var(--navy)     !important;
    color:        #ffffff         !important;
    border-color: var(--navy)     !important;
    font-weight:  600             !important;
    box-shadow:   var(--shadow-xs) !important;
}
.stButton > button[kind="primary"]:hover {
    background:  var(--navy-deep) !important;
    box-shadow:  var(--shadow-navy) !important;
    transform:   translateY(-1px)   !important;
}
.stButton > button[kind="primary"]:active { transform: translateY(0) !important; }

[data-testid="stLinkButton"] > a {
    background:    var(--navy)   !important;
    color:         #ffffff       !important;
    font-weight:   600           !important;
    border-radius: var(--radius) !important;
    transition:    opacity 0.15s !important;
}
[data-testid="stLinkButton"] > a:hover { opacity: 0.88 !important; }


/* ══════════════════════════════════════════════════════════════════════
   CHAT MESSAGES
══════════════════════════════════════════════════════════════════════ */

[data-testid="stChatMessage"] {
    background:    var(--surface);
    border-radius: var(--radius-lg);
    padding:       16px 20px;
    margin:        6px 0;
    border:        1px solid var(--border-soft);
    box-shadow:    var(--shadow-xs);
    transition:    box-shadow 0.18s var(--ease);
}
[data-testid="stChatMessage"]:hover { box-shadow: var(--shadow-sm); }


/* ══════════════════════════════════════════════════════════════════════
   CHAT INPUT  – primary interaction surface
══════════════════════════════════════════════════════════════════════ */

/* Container lift above the page */
[data-testid="stChatInput"] {
    box-shadow: 0 -2px 12px rgba(0,51,102,0.07) !important;
}
/* The textarea itself */
[data-testid="stChatInput"] textarea {
    border:        2px solid var(--border)  !important;
    border-radius: var(--radius-lg)         !important;
    background:    var(--surface)           !important;
    font-size:     0.96rem                  !important;
    line-height:   1.55                     !important;
    min-height:    52px                     !important;
    transition:    border-color 0.18s var(--ease),
                   box-shadow   0.18s var(--ease) !important;
    box-shadow:    var(--shadow-xs)         !important;
}
/* Focus – gold accent ring, decisive navy border */
[data-testid="stChatInput"] textarea:focus {
    border-color: var(--navy)   !important;
    box-shadow:   0 0 0 3px rgba(0,51,102,0.11),
                  var(--shadow-sm) !important;
    outline:      none          !important;
}


/* ══════════════════════════════════════════════════════════════════════
   STREAMLIT WIDGETS
══════════════════════════════════════════════════════════════════════ */

.stProgress > div > div { background: var(--gold) !important; }

[data-testid="stMetric"] {
    background:    var(--surface);
    padding:       14px 18px;
    border-radius: var(--radius);
    border:        1px solid var(--border-soft);
    box-shadow:    var(--shadow-xs);
}

[data-testid="stExpander"] {
    border:        1px solid var(--border-soft) !important;
    border-radius: var(--radius)                !important;
    background:    var(--surface)               !important;
    box-shadow:    var(--shadow-xs)             !important;
}

#MainMenu, footer, [data-testid="stDeployButton"] { visibility: hidden !important; }


/* ══════════════════════════════════════════════════════════════════════
   WELCOME / EMPTY STATE
══════════════════════════════════════════════════════════════════════ */

.welcome-state {
    text-align: center;
    padding:    48px 20px 28px;
}
.welcome-state-icon {
    font-size:     2.8rem;
    display:       block;
    margin-bottom: 18px;
    line-height:   1;
}
.welcome-state-title {
    color:          var(--navy);
    font-size:      1.25rem;
    font-weight:    800;
    margin-bottom:  10px;
    letter-spacing: -0.3px;
    line-height:    1.3;
}
.welcome-state-sub {
    color:       var(--muted);
    font-size:   0.91rem;
    max-width:   460px;
    margin:      0 auto 32px;
    line-height: 1.7;
}
.sample-label {
    color:          var(--gold-dark);
    font-size:      0.70rem;
    font-weight:    700;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom:  12px;
    display:        block;
}


/* ══════════════════════════════════════════════════════════════════════
   RESPONSE COMPONENTS
══════════════════════════════════════════════════════════════════════ */

/* Summary box */
.summary-box {
    background:    #eef4ff;
    border-left:   4px solid var(--navy);
    border-radius: 0 var(--radius) var(--radius) 0;
    padding:       13px 18px;
    margin-bottom: 16px;
    color:         var(--text);
    font-size:     0.95rem;
    line-height:   1.65;
}

/* Next-step action box */
.action-box {
    background:    #fffceb;
    border-left:   4px solid var(--gold-dark);
    border-radius: 0 var(--radius) var(--radius) 0;
    padding:       12px 18px;
    margin-bottom: 16px;
    color:         var(--text);
    font-size:     0.95rem;
    font-weight:   500;
    line-height:   1.55;
}
.action-label {
    display:        inline-block;
    background:     var(--gold);
    color:          var(--navy);
    font-size:      0.62rem;
    font-weight:    800;
    letter-spacing: 0.6px;
    text-transform: uppercase;
    border-radius:  4px;
    padding:        2px 7px;
    margin-right:   8px;
    vertical-align: middle;
}

/* Advisor contact card */
.advisor-card {
    background:    var(--surface);
    border:        1px solid var(--border-soft);
    border-top:    3px solid var(--navy);
    border-radius: var(--radius);
    padding:       18px 22px;
    margin-bottom: 16px;
    box-shadow:    var(--shadow-xs);
}
.advisor-card-header {
    font-size:      0.62rem;
    font-weight:    800;
    color:          var(--navy);
    text-transform: uppercase;
    letter-spacing: 0.9px;
    margin-bottom:  12px;
    padding-bottom: 10px;
    border-bottom:  1px solid var(--border-soft);
}
.advisor-row {
    display:       flex;
    gap:           10px;
    margin-bottom: 7px;
    font-size:     0.9rem;
    line-height:   1.45;
}
.advisor-key   { color: var(--muted); min-width: 68px; font-weight: 500; }
.advisor-val   { color: var(--text);  font-weight: 500; }
.advisor-email { color: #1a56db; text-decoration: none; }
.advisor-email:hover { text-decoration: underline; }

/* Email draft card */
.email-card {
    background:    #f5f9ff;
    border:        1px solid #c5d8f5;
    border-radius: var(--radius);
    padding:       14px 18px;
    margin:        12px 0 16px;
    font-size:     0.9rem;
    line-height:   1.8;
    box-shadow:    var(--shadow-xs);
}
.email-key { color: var(--muted); font-weight: 500; }
.email-val { color: var(--text);  font-weight: 600; }

/* ── Deadline card ──────────────────────────────────────────────────────── */
.deadline-card {
    background:    var(--surface);
    border:        1px solid var(--border-soft);
    border-top:    3px solid var(--navy);
    border-radius: var(--radius);
    padding:       20px 24px 18px;
    margin-bottom: 16px;
    box-shadow:    var(--shadow-sm);
}
.deadline-card-header {
    font-size:      0.62rem;
    font-weight:    800;
    color:          var(--navy);
    text-transform: uppercase;
    letter-spacing: 0.9px;
    margin-bottom:  4px;
    padding-bottom: 10px;
    border-bottom:  1px solid var(--border-soft);
}
.deadline-program-name {
    font-size:   1.05rem;
    font-weight: 700;
    color:       var(--text);
    margin:      0 0 14px 0;
    line-height: 1.3;
}
.deadline-cols {
    display:   flex;
    gap:       24px;
    flex-wrap: wrap;
}
.deadline-col {
    flex:       1;
    min-width:  180px;
}
.deadline-col-label {
    font-size:      0.68rem;
    font-weight:    800;
    letter-spacing: 0.7px;
    text-transform: uppercase;
    color:          var(--navy);
    margin-bottom:  8px;
    opacity:        0.8;
}
.deadline-row {
    display:       flex;
    align-items:   center;
    gap:           10px;
    padding:       6px 0;
    border-bottom: 1px solid var(--border-soft);
    font-size:     0.9rem;
}
.deadline-row:last-child { border-bottom: none; }
.deadline-season {
    min-width:  46px;
    color:      var(--muted);
    font-weight: 500;
    font-size:   0.82rem;
}
.deadline-val {
    font-weight: 600;
    color:       var(--text);
}
.deadline-val.closed {
    color:      #9ca3af;
    font-style: italic;
    font-weight: 400;
}
.deadline-contact {
    margin-top:    14px;
    padding-top:   12px;
    border-top:    1px solid var(--border-soft);
    font-size:     0.85rem;
    color:         var(--text-sub);
    display:       flex;
    flex-wrap:     wrap;
    gap:           16px;
}
.deadline-contact a {
    color:           #1a56db;
    text-decoration: none;
}
.deadline-contact a:hover { text-decoration: underline; }

/* Mini disambiguation card */
.deadline-mini-card {
    background:    var(--surface);
    border:        1px solid var(--border-soft);
    border-left:   3px solid var(--navy);
    border-radius: var(--radius);
    padding:       12px 16px;
    margin-bottom: 8px;
    font-size:     0.88rem;
}
.deadline-mini-program {
    font-weight:  700;
    color:        var(--text);
    margin-bottom: 4px;
}
.deadline-mini-row {
    color:       var(--text-sub);
    font-size:   0.82rem;
    line-height: 1.5;
}

/* Clarification box */
.clarification-box {
    background:    #fffef0;
    border:        1px solid rgba(230,176,0,0.4);
    border-left:   4px solid var(--gold-dark);
    border-radius: var(--radius);
    padding:       14px 18px;
    margin-bottom: 14px;
}

/* Suggestion chips */
.chip-label {
    font-size:   0.80rem;
    font-weight: 600;
    color:       var(--navy);
    margin-bottom: 8px;
}


/* ══════════════════════════════════════════════════════════════════════
   STEP CARDS  (checklist / pending)
══════════════════════════════════════════════════════════════════════ */

.step-card {
    background:    var(--surface);
    border:        1px solid var(--border-soft);
    border-radius: var(--radius);
    padding:       14px 18px;
    margin-bottom: 8px;
    transition:    box-shadow 0.18s var(--ease), transform 0.14s var(--ease);
}
.step-card:hover {
    box-shadow: var(--shadow-md);
    transform:  translateY(-1px);
}
.step-card.blocked {
    background:  #fdfafa;
    border-left: 3px solid #f87171;
}
.step-meta { font-size: 0.74rem; color: var(--muted); margin-bottom: 4px; }

/* Badges */
.badge {
    display:        inline-block;
    padding:        3px 10px;
    border-radius:  12px;
    font-size:      0.71rem;
    font-weight:    700;
    letter-spacing: 0.2px;
}
.badge-pending     { background: #f3f4f6; color: #374151; }
.badge-in_progress { background: #fef3c7; color: #92400e; }
.badge-completed   { background: #d1fae5; color: #065f46; }
.badge-blocked     { background: #fee2e2; color: #991b1b; }

/* Priority labels */
.pri-high   { color: #b91c1c; font-weight: 700; font-size: 0.78rem; }
.pri-medium { color: #c2410c; font-weight: 700; font-size: 0.78rem; }
.pri-low    { color: #15803d; font-weight: 700; font-size: 0.78rem; }

/* Blocked message */
.blocked-msg {
    margin-top:    8px;
    padding:       6px 10px;
    background:    #fff1f2;
    border-radius: 5px;
    color:         #9f1239;
    font-size:     0.81rem;
}


/* ══════════════════════════════════════════════════════════════════════
   FOOTER
══════════════════════════════════════════════════════════════════════ */

.csulb-footer {
    text-align:  center;
    padding:     20px 16px 10px;
    margin-top:  3rem;
    border-top:  1px solid var(--border-soft);
    color:       var(--muted);
    font-size:   0.76rem;
    line-height: 1.6;
}
.csulb-footer a {
    color:           var(--navy);
    font-weight:     600;
    text-decoration: none;
    transition:      opacity 0.15s;
}
.csulb-footer a:hover { opacity: 0.72; text-decoration: underline; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────

def _init_state() -> None:
    defaults: dict = {
        "session_id":     "default",
        "messages":       [],
        "last_response":  None,
        "agent_mode":     False,
        "agent_messages": [],
        "nav_active":     "Ask Assistant",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_STATUS_EMOJI = {"pending": "⏳", "in_progress": "🚧", "completed": "✅"}
_PRI_LABEL    = {"high": "● High", "medium": "● Medium", "low": "● Low"}
_PRI_CLASS    = {"high": "pri-high", "medium": "pri-medium", "low": "pri-low"}

def _badge(status: str, is_blocked: bool = False) -> str:
    if is_blocked:
        return '<span class="badge badge-blocked">🔒 Blocked</span>'
    return (f'<span class="badge badge-{status}">'
            f'{_STATUS_EMOJI.get(status,"")} {status.replace("_"," ").title()}</span>')

def _pri_html(priority: str) -> str:
    return (f'<span class="{_PRI_CLASS.get(priority,"pri-medium")}">'
            f'{_PRI_LABEL.get(priority, priority)}</span>')

def _reload_progress() -> dict | None:
    sid = st.session_state["session_id"]
    try:    return tracker.progress(sid)
    except KeyError: return None

def _mark(step_ref: int | str, status: str) -> None:
    sid = st.session_state["session_id"]
    try:
        tracker.mark(sid, step_ref, status)
        st.toast(f"Step {step_ref} → {status.replace('_',' ')}", icon="✅")
    except Exception as e:
        st.error(str(e))
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────

def _render_header() -> None:
    mode_label = "🤖 Agent Mode" if st.session_state.get("agent_mode") else "💬 AI Assistant"
    sid = st.session_state["session_id"]
    st.markdown(f"""
    <div class="csulb-header">
        <div class="csulb-header-logo">🎓</div>
        <div class="csulb-header-text">
            <div class="csulb-header-title">CSULB Graduate Center AI Assistant</div>
            <div class="csulb-header-sub">California State University, Long Beach</div>
        </div>
        <div class="csulb-header-right">
            <span class="csulb-header-badge">{mode_label}</span>
            <div class="csulb-header-session">Session: {sid}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

_NAV_ITEMS = [
    ("💬", "Ask Assistant"),
    ("📚", "Programs"),
    ("📋", "Admissions"),
    ("👤", "Advisors"),
]

def _render_sidebar() -> None:
    with st.sidebar:
        # Branding
        st.markdown("""
        <div class="sidebar-brand">
            <span class="sidebar-brand-logo">🎓</span>
            <span class="sidebar-brand-name">CSULB Graduate Center</span>
            <span class="sidebar-brand-tag">AI Assistant</span>
        </div>
        """, unsafe_allow_html=True)

        # Navigation
        st.markdown('<span class="nav-section-label">Navigation</span>', unsafe_allow_html=True)
        for icon, label in _NAV_ITEMS:
            active_cls = "active" if st.session_state.get("nav_active") == label else ""
            st.markdown(
                f'<div class="nav-item {active_cls}"><span>{icon}</span><span>{label}</span></div>',
                unsafe_allow_html=True,
            )

        st.markdown("---")

        # Session
        st.markdown('<span class="nav-section-label">Session</span>', unsafe_allow_html=True)
        new_sid = st.text_input(
            "Session ID",
            value=st.session_state["session_id"],
            label_visibility="collapsed",
        )
        if new_sid != st.session_state["session_id"]:
            st.session_state["session_id"]     = new_sid
            st.session_state["messages"]       = []
            st.session_state["last_response"]  = None
            st.session_state["agent_messages"] = []
            st.rerun()

        sessions = tracker.list_sessions()
        if sessions:
            st.markdown('<span class="nav-section-label" style="margin-top:8px;display:block;">Saved Sessions</span>',
                        unsafe_allow_html=True)
            for s in sessions:
                pct    = round(100 * s["completed"] / max(s["total"], 1))
                active = " ←" if s["session_id"] == st.session_state["session_id"] else ""
                if st.button(
                    f"{s['session_id']}  {s['completed']}/{s['total']} ({pct}%){active}",
                    key=f"switch_{s['session_id']}",
                    use_container_width=True,
                ):
                    st.session_state["session_id"]     = s["session_id"]
                    st.session_state["messages"]       = []
                    st.session_state["agent_messages"] = []
                    st.session_state["last_response"]  = None
                    st.rerun()

        if st.button("🗑 Clear history", use_container_width=True,
                     key=f"{st.session_state['session_id']}_clear"):
            st.session_state["messages"]       = []
            st.session_state["agent_messages"] = []
            st.session_state["last_response"]  = None
            st.rerun()

        st.markdown("---")

        # Agent mode
        st.markdown('<span class="nav-section-label">Mode</span>', unsafe_allow_html=True)

        if not os.environ.get("OPENAI_API_KEY"):
            api_key = st.text_input(
                "OpenAI API Key",
                type="password",
                placeholder="sk-…",
                help="Required for Agent Mode",
                key="openai_key_input",
            )
            if api_key:
                os.environ["OPENAI_API_KEY"] = api_key

        has_key  = bool(os.environ.get("OPENAI_API_KEY"))
        agent_on = st.toggle(
            "🌟 Enable Agent Mode",
            value=st.session_state["agent_mode"] if has_key else False,
            key="agent_toggle",
            disabled=not has_key,
            help="Uses OpenAI to look up advisors and draft emails." if has_key
                 else "Enter your OpenAI API Key to enable.",
        )
        if has_key and agent_on != st.session_state["agent_mode"]:
            st.session_state["agent_mode"]     = agent_on
            st.session_state["messages"]       = []
            st.session_state["agent_messages"] = []
            st.session_state["last_response"]  = None
            st.rerun()

        if st.session_state["agent_mode"]:
            st.caption("Agent can look up advisors and draft emails.")
        else:
            st.caption("Standard AI mode: advisors, steps, FAQs.")

        st.markdown("---")
        st.caption("© CSULB Graduate Center")


# ─────────────────────────────────────────────────────────────────────────────
# Progress widget
# ─────────────────────────────────────────────────────────────────────────────

def _render_progress_widget(p: dict) -> None:
    pct      = p["percent_done"]
    total    = p["total"]
    done     = p["completed"]
    blocked  = p.get("blocked", 0)
    in_prog  = p.get("in_progress", 0)
    remaining = total - done
    st.progress(pct / 100, text=f"**{pct}%** complete — {done} of {total} done")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("✅ Done",        f"{done}/{total}")
    c2.metric("🚧 In Progress", in_prog)
    c3.metric("⏳ Remaining",   remaining)
    c4.metric("🔒 Blocked",     blocked)


# ─────────────────────────────────────────────────────────────────────────────
# Step card
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
    completed  = status == "completed"

    card_cls = "step-card blocked" if is_blocked else "step-card"
    blocked_html = ""
    if is_blocked and blocked_by:
        blocked_html = "".join(
            f'<div class="blocked-msg">⛔ Blocked until '
            f'<strong>Step {b["step"]} — {b["title"]}</strong> is completed</div>'
            for b in blocked_by
        )

    st.markdown(f"""
    <div class="{card_cls}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
        <div style="flex:1;min-width:0;">
          <div class="step-meta">Step {step_num} &nbsp;·&nbsp;
            <code style="font-size:.72rem;color:#6b7280;">{step_id}</code></div>
          <strong style="font-size:.97rem;color:#111827;">{title}</strong>
        </div>
        <div style="text-align:right;white-space:nowrap;flex-shrink:0;">
          {_badge(status, is_blocked)}&nbsp;{_pri_html(priority)}
        </div>
      </div>
      {blocked_html}
    </div>
    """, unsafe_allow_html=True)

    sid = st.session_state["session_id"]
    k   = f"{sid}_{view}_{step_id}"
    if not completed and not is_blocked:
        b1, b2, _ = st.columns([1.4, 1.6, 4])
        with b1:
            if status != "in_progress":
                if st.button("▶ Start", key=f"{k}_start", use_container_width=True):
                    _mark(step_num, "in_progress")
        with b2:
            if st.button("✓ Mark complete", key=f"{k}_done",
                         use_container_width=True, type="primary"):
                _mark(step_num, "completed")
    elif completed:
        col_undo, _ = st.columns([1.5, 5])
        with col_undo:
            if st.button("↩ Undo", key=f"{k}_undo", use_container_width=True):
                _mark(step_num, "pending")

    if primary or details or warnings or resources:
        with st.expander("Details", expanded=False):
            if primary:
                st.markdown(
                    f'<div class="action-box" style="margin-bottom:10px;">'
                    f'<span class="action-label">Do this</span>{primary}</div>',
                    unsafe_allow_html=True,
                )
            if details:
                st.markdown(
                    f'<p style="color:#374151;font-size:.9rem;margin:0 0 8px 0;">{details}</p>',
                    unsafe_allow_html=True,
                )
            for w in warnings:
                st.warning(w)
            if resources:
                st.markdown("**Resources:**")
                for r in resources:
                    label = r.get("label", r.get("url", "Link"))
                    url   = r.get("url", "")
                    st.markdown(f"- [{label}]({url})" if url.startswith("http") else f"- {label}: `{url}`")


# ─────────────────────────────────────────────────────────────────────────────
# Panels
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
        f"**{done}/{total} done** &nbsp;·&nbsp; ✅ {ready} ready &nbsp;·&nbsp; 🔒 {blocked} blocked",
        unsafe_allow_html=True,
    )
    st.divider()
    for i, step in enumerate(pending_steps):
        _render_step_card(step, i, view="pending")


def _render_checklist_panel(steps: list[dict]) -> None:
    if not steps:
        st.info("No steps to display.")
        return
    sid = st.session_state["session_id"]
    try:
        record = tracker.load(sid)
        if record:
            id_to_status  = {s["id"]: s["status"] for s in record.get("steps", []) if "id" in s}
            completed_ids = {s["id"] for s in record.get("steps", []) if s.get("status") == "completed"}
            enriched = []
            for step in steps:
                sid_key     = step.get("id", "")
                live_status = id_to_status.get(sid_key, step.get("status", "pending"))
                enriched_step = {**step, "status": live_status}
                enriched_step = tracker._annotate_step(enriched_step, steps, completed_ids)
                enriched.append(enriched_step)
            steps = enriched
    except Exception:
        pass
    for i, step in enumerate(steps):
        _render_step_card(step, i, view="checklist")


def _render_guidance_panel(steps: list[dict]) -> None:
    for step in steps:
        step_num = step.get("number") or step.get("step", "?")
        title    = step.get("do") or step.get("title") or step.get("action", "")
        outcome  = step.get("why") or step.get("outcome", "")
        time_est = step.get("time", "")
        watch    = step.get("watch_out") or (step.get("warnings") or [None])[0]
        link     = step.get("link") or (step.get("resources") or [{}])[0].get("url")
        with st.expander(f"Step {step_num} — {title}", expanded=(step_num == 1)):
            if outcome:  st.markdown(f"**Goal:** {outcome}")
            if time_est: st.caption(f"⏱ {time_est}")
            for h in (step.get("how") or []):  st.markdown(f"- {h}")
            for p in (step.get("prep") or []): st.markdown(f"- {p}")
            if watch: st.warning(f"⚠️ {watch}")
            if link and link.startswith("http"): st.markdown(f"[🔗 Resource]({link})")


def _deadline_val_html(val: str) -> str:
    """Apply .closed styling to 'Not Accepting / Not Applicable / N/A' values."""
    closed_phrases = {"not accepting", "not applicable", "n/a", ""}
    css = "deadline-val closed" if val.lower() in closed_phrases else "deadline-val"
    return f'<span class="{css}">{val}</span>'


def _render_deadline_card(card: dict) -> None:
    """Render one program's deadline data as a structured two-column card."""
    program    = card.get("program", "Unknown Program")
    app        = card.get("application", {})
    acc        = card.get("accept_decline", {})
    contact    = card.get("advisor_contact", {})
    source_url = card.get("source_url", "")

    app_spring  = app.get("spring",  "N/A")
    app_fall    = app.get("fall",    "N/A")
    acc_spring  = acc.get("spring",  "N/A")
    acc_fall    = acc.get("fall",    "N/A")
    email       = contact.get("email",  "")
    phone       = contact.get("phone",  "")
    adv_name    = contact.get("name",   "")

    # Build contact row
    contact_parts: list[str] = []
    if adv_name:
        contact_parts.append(f"<strong>Advisor:</strong> {adv_name}")
    if email:
        contact_parts.append(
            f'<strong>Email:</strong> <a href="mailto:{email}">{email}</a>'
        )
    if phone:
        contact_parts.append(f"<strong>Phone:</strong> {phone}")
    contact_html = (
        '<div class="deadline-contact">' +
        "".join(f"<span>{p}</span>" for p in contact_parts) +
        "</div>"
        if contact_parts else ""
    )

    source_html = (
        f'<a href="{source_url}" target="_blank" style="font-size:.78rem;'
        f'color:var(--navy);">🔗 Official deadlines page</a>'
        if source_url else ""
    )

    st.markdown(f"""
    <div class="deadline-card">
      <div class="deadline-card-header">📅 Application Deadlines</div>
      <div class="deadline-program-name">{program}</div>
      <div class="deadline-cols">
        <div class="deadline-col">
          <div class="deadline-col-label">Application</div>
          <div class="deadline-row">
            <span class="deadline-season">Spring</span>
            {_deadline_val_html(app_spring)}
          </div>
          <div class="deadline-row">
            <span class="deadline-season">Fall</span>
            {_deadline_val_html(app_fall)}
          </div>
        </div>
        <div class="deadline-col">
          <div class="deadline-col-label">Accept / Decline</div>
          <div class="deadline-row">
            <span class="deadline-season">Spring</span>
            {_deadline_val_html(acc_spring)}
          </div>
          <div class="deadline-row">
            <span class="deadline-season">Fall</span>
            {_deadline_val_html(acc_fall)}
          </div>
        </div>
      </div>
      {contact_html}
      {source_html}
    </div>
    """, unsafe_allow_html=True)


def _render_deadline_disambiguation(cards: list[dict], hint: str) -> None:
    """Render a clarification prompt + mini-cards when the query is vague."""
    st.markdown(
        f'<div class="clarification-box">'
        f'<strong>🗓️ Which program are you asking about?</strong><br>'
        f'<span style="font-size:.9rem;color:#374151;">'
        f'Here are the deadlines for all doctoral programs:</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if not cards:
        st.info("No program deadline data found above the relevance threshold.")
        return

    # Show mini-cards in 2-column pairs
    for row_start in range(0, len(cards), 2):
        row_cards = cards[row_start: row_start + 2]
        cols = st.columns(len(row_cards))
        for col, card in zip(cols, row_cards):
            prog  = card.get("program", "Unknown")
            app   = card.get("application", {})
            acc   = card.get("accept_decline", {})
            fall  = app.get("fall",  "N/A")
            afall = acc.get("fall",  "N/A")

            with col:
                st.markdown(f"""
                <div class="deadline-mini-card">
                  <div class="deadline-mini-program">{prog}</div>
                  <div class="deadline-mini-row">
                    <strong>App Fall:</strong> {fall}
                  </div>
                  <div class="deadline-mini-row">
                    <strong>A/D Fall:</strong> {afall}
                  </div>
                </div>
                """, unsafe_allow_html=True)


def _render_topic_panel(response: dict) -> None:
    """
    Render deadline, eligibility, or application-steps tool results.
    Called when route is "deadlines", "eligibility", or "application".
    """
    import sys as _sys, subprocess as _sp

    tool_result   = response.get("tool_result", {})
    route         = response.get("route", "")
    results       = tool_result.get("results", [])
    fallback_data = tool_result.get("fallback_data")
    disclaimer    = tool_result.get("disclaimer", "")

    # ── Deadline route: structured card rendering ────────────────────────────
    if route == "deadlines":
        deadline_card   = tool_result.get("deadline_card")
        deadline_cards  = tool_result.get("deadline_cards", [])
        needs_clarify   = tool_result.get("needs_clarification", False)
        clarify_hint    = tool_result.get("clarification_hint", "")

        if deadline_card:
            # ── Primary deadline card ──────────────────────────────────────
            _render_deadline_card(deadline_card)

            # Show other closely-scored programs as mini hint if any exist
            other_cards = [c for c in deadline_cards if c is not deadline_card]
            if other_cards:
                with st.expander(
                    f"📋 See deadlines for {len(other_cards)} other program(s)",
                    expanded=False,
                ):
                    for card in other_cards:
                        _render_deadline_card(card)

        elif needs_clarify:
            # ── Disambiguation ─────────────────────────────────────────────
            _render_deadline_disambiguation(deadline_cards, clarify_hint)

        else:
            # No cards parsed — fall through to raw results below
            pass

        # Sources / Evidence (always collapsed for deadline route)
        if results:
            with st.expander("📂 Sources / Evidence", expanded=False):
                for i, r in enumerate(results[:6], 1):
                    score_pct = int(r["score"] * 100)
                    title     = r.get("title") or "CSULB"
                    st.markdown(
                        f"**[{i}] {title}** &nbsp; `{score_pct}% match`",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<pre style="font-size:.80rem;white-space:pre-wrap;'
                        f'background:#f8f9fa;padding:8px;border-radius:4px;'
                        f'margin:4px 0 10px;">{r["text"]}</pre>',
                        unsafe_allow_html=True,
                    )
                    url = r.get("url", "")
                    if url:
                        st.caption(f"[🔗 {url}]({url})")

        if disclaimer:
            st.info(disclaimer)
        return
    # ── End deadline route ───────────────────────────────────────────────────

    # ── Eligibility / Application routes: existing behaviour ────────────────
    if results:
        for i, r in enumerate(results[:4], 1):
            score_pct = int(r["score"] * 100)
            title     = r.get("title") or "CSULB"
            with st.expander(
                f"Source {i} — {title}  ·  {score_pct}% match",
                expanded=(i == 1),
            ):
                st.markdown(r["text"])
                url = r.get("url", "")
                if url:
                    st.caption(f"[🔗 {url}]({url})")

    elif fallback_data:
        if isinstance(fallback_data, list):
            # Application steps list of {step, title, details} dicts
            for step in fallback_data:
                st.markdown(
                    f"**Step {step.get('step', '')}: {step.get('title', '')}**"
                )
                details = step.get("details", "")
                if details:
                    st.markdown(
                        f'<p style="color:#374151;font-size:.9rem;margin:0 0 10px 0;">{details}</p>',
                        unsafe_allow_html=True,
                    )
        elif isinstance(fallback_data, dict):
            # Eligibility dict from admissions.json
            min_reqs = fallback_data.get("minimum_requirements", [])
            if min_reqs:
                st.markdown("**Minimum Requirements:**")
                for req in min_reqs:
                    st.markdown(f"- {req}")
            gpa = fallback_data.get("gpa_requirements", {})
            if gpa:
                st.markdown("**GPA Requirements:**")
                for key, val in gpa.items():
                    if key != "note":
                        st.markdown(f"- {val}")
                if gpa.get("note"):
                    st.caption(gpa["note"])
            additional = fallback_data.get("additional", "")
            if additional:
                st.caption(additional)
    else:
        st.info("No specific information found. Please check the source link below.")

    # Supplemental application note (application route only)
    if route == "application" and tool_result.get("has_supplemental"):
        supp = tool_result.get("supplemental_results", [])
        if supp:
            st.warning(
                "⚠️ **Supplemental Application Required** — Most doctoral programs "
                "require an additional supplemental application beyond Cal State Apply. "
                "Contact your program directly to confirm all required materials."
            )
            with st.expander("Supplemental application details", expanded=False):
                for r in supp[:2]:
                    st.markdown(r["text"])
                    url = r.get("url", "")
                    if url:
                        st.caption(f"[🔗 {url}]({url})")

    if disclaimer:
        st.info(disclaimer)


def _render_advisor_panel(response: dict) -> None:
    import sys as _sys, subprocess as _sp

    advisor_data = response.get("advisor_data", {})
    match        = advisor_data.get("match")
    suggestions  = advisor_data.get("suggestions", [])
    if match:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Program**"); st.markdown(match.get("program") or "—")
            st.markdown(""); st.markdown("**Advisor**")
            st.markdown(match.get("advisor_name") or "Not available")
        with c2:
            email = match.get("email")
            st.markdown("**Email**")
            st.markdown(f"[{email}](mailto:{email})" if email else "Not available")
            st.markdown(""); st.markdown("**Phone**")
            st.markdown(match.get("phone") or "Not available")
        if match.get("office"):
            st.markdown(f"**Office:** {match['office']}")

        # ── Auto-generated email draft preview ───────────────────────────────
        email_draft = response.get("email_draft", {})
        if email_draft.get("found"):
            st.markdown("---")
            st.markdown("### 📧 Email Draft Preview")
            st.markdown(
                '<p style="color:#6b7280;font-size:.85rem;margin:-8px 0 10px 0;">'
                "A draft has been prepared for you. Review it before sending."
                "</p>",
                unsafe_allow_html=True,
            )

            to_addr = email_draft.get("to", "")
            subject = email_draft.get("subject", "")
            body    = email_draft.get("body", "")

            # Draft summary card
            st.markdown(
                f'<div class="email-card">'
                f'<span class="email-key">To: </span>'
                f'<strong class="email-val">{to_addr}</strong><br>'
                f'<span class="email-key">Subject: </span>'
                f'<strong class="email-val">{subject}</strong>'
                f'</div>',
                unsafe_allow_html=True,
            )
            with st.expander("📄 View full draft", expanded=False):
                st.text(body)

            # Outlook button — user must click; never auto-opened
            outlook_url = email_draft.get("outlook_url", "")
            st.markdown(
                '<p style="color:#374151;font-size:.9rem;font-weight:500;margin-bottom:8px;">'
                "Would you like to open this draft in Outlook?"
                "</p>",
                unsafe_allow_html=True,
            )
            col_btn, col_copy, _ = st.columns([2.2, 2, 2.8])
            with col_btn:
                if outlook_url and st.button(
                    "📧 Open in Outlook",
                    key=f"adv_outlook_{hash(outlook_url)}",
                    type="primary",
                    use_container_width=True,
                ):
                    try:
                        if _sys.platform == "darwin":
                            _sp.Popen(["open", outlook_url])
                        elif _sys.platform == "win32":
                            _sp.Popen(["rundll32", "url.dll,FileProtocolHandler", outlook_url])
                        else:
                            _sp.Popen(["xdg-open", outlook_url])
                    except Exception as e:
                        st.error(f"Could not open browser: {e}")
            with col_copy:
                if to_addr:
                    st.markdown("**Copy address:**")
                    st.code(to_addr, language=None)

    elif suggestions:
        st.markdown("**Did you mean one of these programs?**")
        for i, name in enumerate(suggestions, 1):
            st.markdown(f"{i}. {name}")
        st.caption("Try typing the full program name for a direct match.")
    else:
        known = advisor_data.get("known_programs", [])
        if known:
            st.markdown("**Available programs:**")
            for name in known: st.markdown(f"- {name}")


def _render_answer_panel(response: dict) -> None:
    ans        = response.get("answer")
    confidence = response.get("confidence", "")
    if isinstance(ans, dict) and "question" in ans:
        st.markdown(f"**Q:** {ans['question']}")
        st.markdown(f"**A:** {ans['answer']}")
        if ans.get("source"): st.caption(f"Source: {ans['source']}")
    elif isinstance(ans, list):
        for item in ans:
            if isinstance(item, dict):
                st.markdown(f"**Q:** {item.get('question','')}")
                st.markdown(f"**A:** {item.get('answer','')}")
                st.divider()
    elif isinstance(ans, str):
        st.markdown(ans)
    if confidence:
        colour = {"high": "green", "medium": "orange", "low": "red"}.get(confidence, "grey")
        st.markdown(f'<span style="color:{colour};font-size:.8rem;">Confidence: {confidence}</span>',
                    unsafe_allow_html=True)


def _render_tracking_panel(response: dict) -> None:
    p = response.get("progress")
    if p and p.get("total", 0) > 0:
        _render_progress_widget(p); st.markdown("")
    focus = response.get("current_focus")
    if focus:
        is_blocked = focus.get("is_blocked")
        icon = "🔒" if is_blocked else ("🚧" if focus.get("label","").startswith("🚧") else "⏳")
        st.markdown(f"**{icon} {focus['label']} — Step {focus['step']}: {focus['title']}**")
        if is_blocked:
            for b in focus.get("blocked_by", []):
                st.error(f"⛔ Blocked by Step {b['step']} ({b['title']})")
        elif focus.get("details"):
            st.caption(focus["details"])
    next_step = response.get("next_step")
    if next_step and next_step != "All tasks complete — nothing left to do here.":
        st.info(f"➡️ **Next:** {next_step}")
    for item in (response.get("pending") or []):
        is_blocked = item.get("is_blocked")
        title      = item.get("title") or item.get("action","")
        priority   = item.get("priority","medium")
        step_num   = item.get("step")
        icon       = "🔒 " if is_blocked else ""
        pri_icon   = {"high":"🔴","medium":"🟡","low":"🟢"}.get(priority,"")
        st.markdown(f"- {icon}**Step {step_num}** — {title} &nbsp;{pri_icon}", unsafe_allow_html=True)
        if is_blocked:
            for b in item.get("blocked_by",[]):
                st.caption(f"    ⛔ Complete Step {b['step']} ({b['title']}) first")
    for s in (response.get("sessions") or []):
        pct = round(100 * s.get("completed",0) / max(s.get("total",1),1))
        st.markdown(f"- **{s['session_id']}** — {s['completed']}/{s['total']} ({pct}%)  _{s.get('intent','')}_")


# ─────────────────────────────────────────────────────────────────────────────
# Agent response helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_advisor_from_history(history: list[dict]) -> dict | None:
    for msg in history:
        if msg.get("role") != "tool": continue
        content = msg.get("content", "")
        if "ADVISOR_NAME:" not in content: continue
        fields: dict[str, str] = {}
        for line in content.splitlines():
            for key in ("ADVISOR_NAME","ADVISOR_EMAIL","PROGRAM","PHONE","OFFICE"):
                if line.startswith(f"{key}:"):
                    fields[key] = line[len(key)+1:].strip()
        if fields: return fields
    return None


def _render_advisor_card(fields: dict) -> None:
    name    = fields.get("ADVISOR_NAME", "—")
    email   = fields.get("ADVISOR_EMAIL", "")
    program = fields.get("PROGRAM", "—")
    phone   = fields.get("PHONE", "")
    office  = fields.get("OFFICE", "")
    email_html = (f'<a href="mailto:{email}" class="advisor-email">{email}</a>'
                  if email else "—")
    extra = ""
    if phone:
        extra += f'<div class="advisor-row"><span class="advisor-key">Phone</span><span class="advisor-val">{phone}</span></div>'
    if office:
        extra += f'<div class="advisor-row"><span class="advisor-key">Office</span><span class="advisor-val">{office}</span></div>'
    st.markdown(f"""
    <div class="advisor-card">
        <div class="advisor-card-header">📋 Advisor Contact</div>
        <div class="advisor-row"><span class="advisor-key">Name</span><strong class="advisor-val">{name}</strong></div>
        <div class="advisor-row"><span class="advisor-key">Program</span><span class="advisor-val">{program}</span></div>
        <div class="advisor-row"><span class="advisor-key">Email</span>{email_html}</div>
        {extra}
    </div>
    """, unsafe_allow_html=True)


def _render_agent_response(response: dict) -> None:
    if response.get("needs_clarification"):
        q = response.get("clarification_question","")
        r = response.get("clarification_reason","")
        st.markdown(
            f'<div class="clarification-box"><strong>🤔 I need a bit more info</strong><br>{q}</div>',
            unsafe_allow_html=True,
        )
        if r: st.caption(f"Reason: {r}")
        return

    if "get_advisor" in response.get("tools_used", []):
        fields = _parse_advisor_from_history(response.get("conversation_history", []))
        if fields:
            _render_advisor_card(fields)

    answer = response.get("answer", "")
    if not answer:
        return

    import re as _re, urllib.parse as _up

    web_match  = _re.search(r'OUTLOOK_WEB_URL:\s*(\S+)', answer)
    mail_match = _re.search(r'MAILTO_URL:\s*(\S+)', answer)
    outlook_web_url = web_match.group(1)  if web_match  else None
    mailto_url      = mail_match.group(1) if mail_match else None
    if not mailto_url:
        md = _re.search(r'\[.*?\]\((mailto:[^)]+)\)', answer)
        if md: mailto_url = md.group(1)

    has_draft = bool(outlook_web_url or mailto_url)

    if has_draft:
        clean = _re.sub(r'OUTLOOK_WEB_URL:\s*\S+\n?', '', answer)
        clean = _re.sub(r'MAILTO_URL:\s*\S+\n?', '', clean)
        clean = _re.sub(r'\[.*?\]\((https://outlook[^)]+|mailto:[^)]+)\)', '', clean).strip()
        if clean: st.markdown(clean)

        _to = _subj = _body = ""
        src = outlook_web_url or mailto_url or ""
        try:
            _parts  = src.split("?", 1)
            _params = dict(_up.parse_qsl(_parts[1])) if len(_parts) > 1 else {}
            _to     = _up.unquote(_params.get("to",""))
            if not _to and "mailto:" in _parts[0]:
                _to = _up.unquote(_parts[0].split("mailto:",1)[1])
            _subj = _params.get("subject","")
            _body = _params.get("body","")
        except Exception:
            pass

        if _to or _subj:
            st.markdown(
                f'<div class="email-card">'
                f'<span class="email-key">To: </span><strong class="email-val">{_to}</strong><br>'
                f'<span class="email-key">Subject: </span><strong class="email-val">{_subj}</strong>'
                f'</div>',
                unsafe_allow_html=True,
            )

        if outlook_web_url:
            if st.button("📧 Open Draft in Outlook Web", key=f"oweb_{hash(outlook_web_url)}",
                         use_container_width=True, type="primary"):
                import sys, subprocess
                try:
                    if sys.platform == "darwin":
                        subprocess.Popen(["open", outlook_web_url])
                    elif sys.platform == "win32":
                        subprocess.Popen(["rundll32","url.dll,FileProtocolHandler", outlook_web_url])
                    else:
                        subprocess.Popen(["xdg-open", outlook_web_url])
                except Exception as e:
                    st.error(f"Could not open browser: {e}")

        st.markdown("**Or copy and paste into Outlook:**")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**To**"); st.code(_to or "—", language=None)
        with c2:
            st.markdown("**Subject**"); st.code(_subj or "—", language=None)
        if _body:
            st.markdown("**Body**"); st.code(_body, language=None)
    else:
        st.markdown(answer)

    tools = response.get("tools_used", [])
    if tools:
        st.caption(f"🔧 Tools: {', '.join(tools)}")


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator response renderer
# ─────────────────────────────────────────────────────────────────────────────

def _render_response(response: dict, msg_idx: int = 0) -> None:
    route   = response.get("route", "")
    summary = response.get("summary", "")
    action  = response.get("primary_action", "")
    source  = (response.get("source") or {}).get("url", "")

    if summary:
        st.markdown(f'<div class="summary-box">{summary}</div>', unsafe_allow_html=True)
    if action:
        if route == "next_steps":
            st.markdown('<div class="action-box"><span class="action-label">Next step</span></div>',
                        unsafe_allow_html=True)
            st.markdown(action)
        else:
            st.markdown(
                f'<div class="action-box"><span class="action-label">Next step</span>{action}</div>',
                unsafe_allow_html=True,
            )

    p = _reload_progress()
    if p and p["total"] > 0 and route in ("checklist","tracking"):
        _render_progress_widget(p); st.markdown("")

    if   route == "advisor":   _render_advisor_panel(response)
    elif route in ("deadlines", "eligibility", "application"):
        _render_topic_panel(response)
    elif route == "checklist":
        st.markdown("### Your Checklist")
        _render_checklist_panel(response.get("steps", []))
    elif route == "guidance":
        st.markdown("### Step-by-Step Guidance")
        _render_guidance_panel(response.get("steps", []))
    elif route == "tracking":  _render_tracking_panel(response)
    elif route == "answer":
        st.markdown("### Answer"); _render_answer_panel(response)

    if source:
        st.caption(f"Source: [{source}]({source})")

    next_actions = response.get("next_actions") or []
    if next_actions:
        st.divider()
        st.markdown('<div class="chip-label">💡 What you can ask next</div>', unsafe_allow_html=True)
        cols = st.columns(min(len(next_actions), 3))
        sid  = st.session_state["session_id"]
        for i, suggestion in enumerate(next_actions[:3]):
            with cols[i]:
                if st.button(suggestion, key=f"{sid}_msg{msg_idx}_sug_{i}", use_container_width=True):
                    _submit_query(suggestion)


# ─────────────────────────────────────────────────────────────────────────────
# Sample questions
# ─────────────────────────────────────────────────────────────────────────────

_SAMPLES = [
    "Who is the advisor for the Computer Science PhD?",
    "What are the steps to apply for graduate school?",
    "Tell me about the DNP program",
    "What GPA do I need for admission?",
    "How do I check my application status?",
    "I don't know where to start",
]

def _render_sample_questions() -> None:
    st.markdown("""
    <div class="welcome-state">
        <span class="welcome-state-icon">🎓</span>
        <div class="welcome-state-title">Welcome to the CSULB Graduate Center AI Assistant</div>
        <div class="welcome-state-sub">
            Ask about programs, admissions requirements, advisors, deadlines, or
            anything related to CSULB graduate studies — and I'll guide you step by step.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<span class="sample-label">✨ Try asking…</span>', unsafe_allow_html=True)
    cols = st.columns(3)
    for i, q in enumerate(_SAMPLES):
        with cols[i % 3]:
            if st.button(q, key=f"sample_{i}", use_container_width=True):
                _submit_query(q)


# ─────────────────────────────────────────────────────────────────────────────
# Query submission
# ─────────────────────────────────────────────────────────────────────────────

def _submit_query(query: str) -> None:
    sid = st.session_state["session_id"]

    if st.session_state.get("agent_mode"):
        agent_mod = _load_agent()
        if not agent_mod:
            st.error("Could not import the agent module. Make sure `openai` is installed.")
            return
        with st.spinner("🤖 Agent is thinking…"):
            history = st.session_state.get("agent_messages", [])
            result  = agent_mod.run_agent(query, session_id=sid, conversation_history=history)
        st.session_state["agent_messages"] = result.get("conversation_history", history)
        result["_mode"] = "agent"
        st.session_state["messages"].append({"role": "user", "content": query})
        st.session_state["messages"].append({
            "role":     "assistant",
            "content":  result.get("answer") or result.get("clarification_question",""),
            "response": result,
        })
        st.session_state["last_response"] = result
    else:
        with st.spinner("Searching for an answer…"):
            response = orchestrator.run(query, session_id=sid)
        st.session_state["messages"].append({"role": "user",  "content": query})
        st.session_state["messages"].append({
            "role":     "assistant",
            "content":  response.get("summary",""),
            "response": response,
        })
        st.session_state["last_response"] = response

    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────────────────────────────────────

def _render_footer() -> None:
    st.markdown("""
    <div class="csulb-footer">
        © <strong>CSULB Graduate Center</strong> &nbsp;·&nbsp; AI Assistant Prototype
        &nbsp;·&nbsp; For official information visit
        <a href="https://www.csulb.edu/graduate-center" target="_blank">csulb.edu/graduate-center</a>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    _render_sidebar()
    _render_header()

    # Mode banner
    if st.session_state.get("agent_mode"):
        st.markdown("""
        <div class="mode-banner">
            <span>🤖</span>
            <span>Agent Mode — I can look up advisors and open email drafts in Outlook Web</span>
            <span class="mode-banner-tag">Agent</span>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="mode-banner">
            <span>💬</span>
            <span>AI Assistant Mode — Ask about programs, advisors, admissions steps, and FAQs</span>
            <span class="mode-banner-tag">Standard</span>
        </div>
        """, unsafe_allow_html=True)

    # Tabs
    tab_chat, tab_checklist, tab_pending = st.tabs([
        "💬  Chat", "📋  Full Checklist", "⏳  Pending Tasks",
    ])

    with tab_chat:
        if not st.session_state["messages"]:
            _render_sample_questions()

        for i, msg in enumerate(st.session_state["messages"]):
            with st.chat_message(msg["role"],
                                 avatar="👤" if msg["role"] == "user" else "🎓"):
                if msg["role"] == "assistant" and "response" in msg:
                    resp = msg["response"]
                    if resp.get("_mode") == "agent":
                        _render_agent_response(resp)
                    else:
                        _render_response(resp, msg_idx=i)
                else:
                    st.markdown(msg["content"])

        if query := st.chat_input("Ask me anything about CSULB grad admissions…"):
            _submit_query(query)

    with tab_checklist:
        sid    = st.session_state["session_id"]
        record = tracker.load(sid)
        if not record:
            st.info('No checklist yet. Go to **Chat** and ask: *"Give me a checklist for admitted students"*')
        else:
            steps = record.get("steps", [])
            p     = _reload_progress()
            if p:
                st.markdown(f"### {record.get('intent','Checklist').replace('_',' ').title()}")
                _render_progress_widget(p); st.markdown("")
            completed_ids = {s["id"] for s in steps if s.get("status") == "completed"}
            annotated     = [tracker._annotate_step(s, steps, completed_ids) for s in steps]
            _render_checklist_panel(annotated)

    with tab_pending:
        sid    = st.session_state["session_id"]
        record = tracker.load(sid)
        if not record:
            st.info('No checklist yet. Go to **Chat** and ask: *"Give me a checklist for applying"*')
        else:
            st.markdown(f"### Pending — {record.get('intent','').replace('_',' ').title()}")
            _render_pending_panel()

    _render_footer()


if __name__ == "__main__":
    main()

"""
CSULB Graduate Center AI Assistant – Streamlit UI
Navy #003366 · Gold #FFC72C
Run: streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import orchestrator
from tools.program_interest_tool import (
    generate_program_specific_response,
    generate_general_interest_response,
)


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
   APPLICATION STEP CARDS
══════════════════════════════════════════════════════════════════════ */

.app-steps-header {
    font-size:      0.68rem;
    font-weight:    800;
    color:          var(--navy);
    text-transform: uppercase;
    letter-spacing: 0.9px;
    margin:         0 0 14px 0;
    padding-bottom: 10px;
    border-bottom:  1px solid var(--border-soft);
}

.app-step-card {
    display:       flex;
    gap:           16px;
    align-items:   flex-start;
    background:    var(--surface);
    border:        1px solid var(--border-soft);
    border-radius: var(--radius);
    padding:       16px 20px;
    margin-bottom: 10px;
    box-shadow:    var(--shadow-xs);
    transition:    box-shadow 0.18s var(--ease), transform 0.14s var(--ease);
}
.app-step-card:hover {
    box-shadow: var(--shadow-md);
    transform:  translateY(-1px);
}

.app-step-num {
    width:          36px;
    height:         36px;
    min-width:      36px;
    border-radius:  50%;
    color:          #ffffff;
    font-weight:    800;
    font-size:      0.95rem;
    display:        flex;
    align-items:    center;
    justify-content:center;
    margin-top:     2px;
    box-shadow:     0 2px 6px rgba(0,0,0,0.15);
}

.app-step-body        { flex: 1; min-width: 0; }
.app-step-cat-badge {
    display:        inline-block;
    background:     #eef4ff;
    color:          var(--navy);
    font-size:      0.67rem;
    font-weight:    700;
    letter-spacing: 0.4px;
    text-transform: uppercase;
    padding:        2px 8px;
    border-radius:  8px;
    margin-bottom:  6px;
}
.app-step-title {
    font-weight: 700;
    font-size:   0.97rem;
    color:       var(--text);
    line-height: 1.35;
    margin-bottom: 5px;
}
.app-step-desc {
    font-size:   0.875rem;
    color:       var(--text-sub);
    line-height: 1.6;
    margin-bottom: 9px;
}
.app-step-content {
    font-size:   0.89rem;
    color:       var(--text-sub);
    line-height: 1.7;
    margin:      8px 0 10px 0;
    word-break:  break-word;
}
.app-step-content p {
    margin: 0 0 6px 0;
}

.app-step-related {
    margin-top:    10px;
    padding-top:   8px;
    border-top:    1px dashed var(--border-soft);
    font-size:     0.80rem;
    color:         var(--muted);
    line-height:   1.8;
}
.app-step-related strong {
    color:       var(--text-sub);
    font-weight: 600;
    display:     block;
    margin-bottom: 3px;
}
.app-step-sublink {
    display:         inline-flex;
    align-items:     center;
    gap:             4px;
    color:           var(--navy);
    text-decoration: none;
    font-weight:     500;
    font-size:       0.80rem;
    background:      #eef4ff;
    padding:         2px 8px;
    border-radius:   5px;
    margin:          2px 4px 2px 0;
    border:          1px solid rgba(0,51,102,0.12);
    transition:      background 0.14s var(--ease), color 0.14s var(--ease);
}
.app-step-sublink:hover {
    background: var(--navy);
    color:      #ffffff;
}

.app-step-source {
    margin-top: 8px;
    font-size:  0.76rem;
    color:      var(--muted);
}
.app-step-source a {
    color:           var(--muted);
    text-decoration: none;
    word-break:      break-all;
}
.app-step-source a:hover { color: var(--navy); text-decoration: underline; }

.app-step-link {
    display:        inline-flex;
    align-items:    center;
    gap:            5px;
    font-size:      0.82rem;
    font-weight:    600;
    color:          var(--navy);
    text-decoration:none;
    border:         1px solid rgba(0,51,102,0.25);
    padding:        4px 11px;
    border-radius:  6px;
    transition:     background 0.15s var(--ease), color 0.15s var(--ease);
}
.app-step-link:hover {
    background: var(--navy);
    color:      #ffffff;
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


/* ══════════════════════════════════════════════════════════════════════
   GRADUATE PROGRAM CONNECT  (Program Interest Response panel)
══════════════════════════════════════════════════════════════════════ */


.pir-info-card {
    background:    var(--surface);
    border:        1px solid var(--border-soft);
    border-left:   4px solid var(--navy);
    border-radius: var(--radius);
    padding:       16px 20px;
    margin-bottom: 18px;
    box-shadow:    var(--shadow-xs);
}
.pir-info-title {
    font-size:   1.0rem;
    font-weight: 700;
    color:       var(--navy);
    margin:      0 0 12px 0;
}
.pir-info-row {
    display:     flex;
    align-items: flex-start;
    gap:         8px;
    font-size:   0.855rem;
    color:       var(--text-sub);
    margin:      5px 0;
    line-height: 1.5;
}
.pir-info-icon { font-size: 0.9rem; flex-shrink: 0; margin-top: 1px; }
.pir-info-label {
    font-weight: 600;
    color:       var(--text);
    white-space: nowrap;
}
.pir-info-row a {
    color:           var(--navy);
    font-weight:     500;
    text-decoration: none;
}
.pir-info-row a:hover { text-decoration: underline; }

.pir-deadline-chips {
    display:     flex;
    gap:         8px;
    flex-wrap:   wrap;
    margin-top:  6px;
}
.pir-deadline-chip {
    background:    #eef4ff;
    border:        1px solid rgba(0,51,102,0.14);
    border-radius: 20px;
    padding:       3px 11px;
    font-size:     0.79rem;
    font-weight:   600;
    color:         var(--navy);
}
.pir-deadline-chip.na {
    background: #f5f5f5;
    border-color: var(--border);
    color: var(--muted);
}

.pir-section-label {
    font-size:      0.68rem;
    font-weight:    800;
    color:          var(--navy);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin:         0 0 12px 0;
    padding-bottom: 8px;
    border-bottom:  1px solid var(--border-soft);
}

.pir-response-body {
    background:    var(--surface);
    border:        1px solid var(--border-soft);
    border-radius: var(--radius);
    padding:       22px 26px;
    font-size:     0.90rem;
    color:         var(--text);
    line-height:   1.75;
    box-shadow:    var(--shadow-xs);
    white-space:   pre-wrap;
    word-break:    break-word;
    margin-bottom: 14px;
}
.pir-response-body p   { margin: 0 0 0.9em 0; }
.pir-response-body ul  { margin: 4px 0 0.9em 18px; padding: 0; }
.pir-response-body li  { margin-bottom: 3px; }
.pir-response-body a   {
    color:           var(--navy);
    font-weight:     500;
    text-decoration: none;
    border-bottom:   1px solid rgba(0,51,102,0.25);
}
.pir-response-body a:hover {
    border-bottom-color: var(--navy);
    text-decoration: none;
}

.pir-sources {
    font-size:  0.77rem;
    color:      var(--muted);
    margin-top: 4px;
}
.pir-sources a {
    color:           var(--navy);
    font-weight:     500;
    text-decoration: none;
}
.pir-sources a:hover { text-decoration: underline; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────

def _init_state() -> None:
    defaults: dict = {
        "session_id":    "default",
        "messages":      [],
        "last_response": None,
        "nav_active":    "Ask Assistant",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────

def _render_header() -> None:
    sid = st.session_state["session_id"]
    st.markdown(f"""
    <div class="csulb-header">
        <div class="csulb-header-logo">🎓</div>
        <div class="csulb-header-text">
            <div class="csulb-header-title">CSULB Graduate Center AI Assistant</div>
            <div class="csulb-header-sub">California State University, Long Beach</div>
        </div>
        <div class="csulb-header-right">
            <span class="csulb-header-badge">💬 AI Assistant</span>
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
            st.session_state["session_id"]    = new_sid
            st.session_state["messages"]      = []
            st.session_state["last_response"] = None
            st.rerun()

        if st.button("🗑 Clear history", use_container_width=True,
                     key=f"{st.session_state['session_id']}_clear"):
            st.session_state["messages"]      = []
            st.session_state["last_response"] = None
            st.rerun()

        st.markdown("---")
        st.caption("© CSULB Graduate Center")


# ─────────────────────────────────────────────────────────────────────────────
# Panels
# ─────────────────────────────────────────────────────────────────────────────

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


_STEP_PRIORITY_COLOR: dict[int, str] = {
    1: "#f97316",   # department_application  — orange
    2: "#8b5cf6",   # supplemental_application — purple
    3: "#003366",   # program_requirements / eligibility — navy
    4: "#0891b2",   # transcript / international — teal
    5: "#64748b",   # generic_application — slate
    6: "#9ca3af",   # overview / unknown — gray
}


def _render_application_steps(workflow_steps: list[dict], program_name: str = "") -> None:
    """
    Render program-specific application steps in the same format as
    _render_guidance_panel(): Goal line, bullets, warning note, related links,
    source link, and collapsed Sources / Evidence.
    """
    if not workflow_steps:
        st.info("No specific steps found. Please visit the official CSULB page.")
        return

    for ws in workflow_steps:
        step_num   = ws.get("step", "?")
        title      = ws.get("title", "")
        goal       = ws.get("goal", "")
        note       = ws.get("note", "")
        points     = ws.get("summary_points", [])
        source_url = ws.get("source_url", "")
        rel_links  = ws.get("related_links", [])
        raw_ev     = ws.get("raw_evidence", "")

        with st.expander(f"Step {step_num} — {title}", expanded=(step_num == 1)):
            # ── Goal (matches _render_guidance_panel style) ───────────────────
            if goal:
                st.markdown(f"**Goal:** {goal}")

            # ── Bullets ───────────────────────────────────────────────────────
            if points:
                for pt in points:
                    st.markdown(f"- {pt}")
            else:
                st.markdown("_Visit the official page for full details._")

            # ── Warning note (matches watch_out in generic steps) ─────────────
            if note:
                st.warning(f"⚠️ {note}")

            # ── Related links ─────────────────────────────────────────────────
            if rel_links:
                st.markdown("**Related links:**")
                for lk in rel_links:
                    url_val = lk.get("url", "")
                    txt_val = lk.get("text", url_val)
                    if url_val.startswith("mailto:"):
                        st.markdown(f"- 📧 [{txt_val}]({url_val})")
                    else:
                        st.markdown(f"- [{txt_val}]({url_val})")

            # ── Official source ───────────────────────────────────────────────
            if source_url:
                st.markdown(f"[🔗 Resource]({source_url})")

            # ── Collapsed evidence ────────────────────────────────────────────
            if raw_ev:
                with st.expander("📄 Sources / Evidence", expanded=False):
                    st.markdown(
                        f"<div style='font-size:0.82em;color:#555;white-space:pre-wrap'>"
                        f"{raw_ev[:1500]}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )


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

    # ── Application route: program-aware rendering ──────────────────────────
    if route == "application":
        program_name     = tool_result.get("program_name")
        program_specific = tool_result.get("program_specific", False)
        content_category = tool_result.get("content_category", "")
        supp_results     = tool_result.get("supplemental_results", [])

        # Program-specific heading + category badge
        if program_name:
            badge_color = "#0ea5e9"
            badge_label = "Program-Specific Steps"
            if content_category == "department_application":
                badge_color = "#f97316"
                badge_label = "Department Portal Required"
            elif content_category == "supplemental_application":
                badge_color = "#8b5cf6"
                badge_label = "Supplemental Application Required"
            elif content_category == "program_requirements":
                badge_color = "#0369a1"
                badge_label = "Admission Requirements"
            elif content_category == "program_eligibility":
                badge_color = "#0891b2"
                badge_label = "Eligibility Criteria"
            elif content_category == "transcript_instructions":
                badge_color = "#059669"
                badge_label = "Transcript Instructions"
            elif content_category == "international_instructions":
                badge_color = "#7c3aed"
                badge_label = "International Student Requirements"
            elif not program_specific:
                badge_color = "#64748b"
                badge_label = "General Info — No Specific Steps Found"

            st.markdown(
                f'<div style="margin-bottom:6px;">'
                f'<span style="font-weight:600;font-size:1.05rem;">'
                f'🎓 {program_name}</span>&nbsp;&nbsp;'
                f'<span style="background:{badge_color};color:#fff;'
                f'font-size:.72rem;font-weight:600;padding:2px 8px;'
                f'border-radius:10px;">{badge_label}</span></div>',
                unsafe_allow_html=True,
            )

        # Department portal warning
        if content_category == "department_application":
            st.warning(
                "⚠️ **Department Application Portal** — This program uses a "
                "department-specific application system (e.g. PTCAS), not Cal State Apply. "
                "Follow the program's instructions and submit through their designated portal."
            )

        # Supplemental form warning
        elif content_category == "supplemental_application":
            st.warning(
                "⚠️ **Supplemental Application Required** — This program requires "
                "a supplemental application (e.g. a Qualtrics form) in addition to "
                "Cal State Apply. Complete both and verify all deadlines with the program."
            )

        # Requirements info box
        elif content_category == "program_requirements":
            st.info(
                "ℹ️ **Admission Requirements** — Review the specific admission requirements "
                "below. Requirements typically include GPA minimums, letters of recommendation, "
                "statement of purpose, and possibly test scores or an interview."
            )

        # Eligibility info box
        elif content_category == "program_eligibility":
            st.info(
                "ℹ️ **Eligibility Criteria** — Check whether you meet this program's "
                "eligibility requirements before beginning your application."
            )

        # Transcript instructions info box
        elif content_category == "transcript_instructions":
            st.info(
                "ℹ️ **Transcript Submission** — Review the instructions below for "
                "submitting official transcripts to this program."
            )

        # International applicant info box
        elif content_category == "international_instructions":
            st.info(
                "ℹ️ **International Applicants** — Additional requirements apply for "
                "international students, including English proficiency test scores "
                "(TOEFL/IELTS) and credential evaluations."
            )

        # ── Main results: step cards ──────────────────────────────────────────
        steps = tool_result.get("steps", [])
        workflow_steps = tool_result.get("workflow_steps", [])
        if workflow_steps:
            _render_application_steps(workflow_steps, program_name or "")
        elif steps:  # fallback to old steps if workflow_steps unavailable
            _render_application_steps(steps, program_name or "")
        elif fallback_data and isinstance(fallback_data, list):
            # Fallback: admissions.json steps (used when RAG is unavailable)
            for fb_step in fallback_data:
                sn      = fb_step.get("step", "?")
                stitle  = fb_step.get("title", "")
                details = fb_step.get("details", "")
                link    = (fb_step.get("resources") or [{}])[0].get("url", "")
                with st.expander(f"Step {sn} — {stitle}", expanded=(sn == 1)):
                    if details:
                        st.markdown(details)
                    if link and link.startswith("http"):
                        st.markdown(f"[🔗 Visit Official Page]({link})")
        elif results:
            # Fallback: render raw RAG chunks if steps list is unexpectedly empty
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
        else:
            st.info("No specific information found. Please check the source link below.")

        # Supplemental / generic context (collapsed by default).
        # Hidden when program-specific workflow steps are already displayed —
        # the "General process for context" card is redundant in that case.
        if supp_results and not workflow_steps:
            label = (
                "📋 General process for context"
                if program_specific
                else "📋 Supplemental application details"
            )
            with st.expander(label, expanded=False):
                for r in supp_results[:3]:
                    supp_url = r.get("url", "")
                    supp_title = r.get("title") or "CSULB"
                    st.markdown(f"**{supp_title}**")
                    st.markdown(r["text"])
                    if supp_url:
                        st.caption(f"[🔗 {supp_url}]({supp_url})")
                    st.divider()
        elif not program_specific and tool_result.get("has_supplemental"):
            st.warning(
                "⚠️ **Supplemental Application Required** — Most doctoral programs "
                "require an additional supplemental application beyond Cal State Apply. "
                "Contact your program directly to confirm all required materials."
            )

        if disclaimer:
            st.info(disclaimer)
        return

    # ── Eligibility route: existing behaviour ────────────────────────────────
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



# ─────────────────────────────────────────────────────────────────────────────
# Agent response helpers
# ─────────────────────────────────────────────────────────────────────────────

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

    if   route == "advisor":   _render_advisor_panel(response)
    elif route in ("deadlines", "eligibility", "application"):
        _render_topic_panel(response)
    elif route in ("guidance", "checklist"):
        st.markdown("### Step-by-Step Guidance")
        _render_guidance_panel(response.get("steps", []))
    elif route == "answer":
        st.markdown("### Answer"); _render_answer_panel(response)
    # tracking route: summary + primary_action rendered above are sufficient

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
    with st.spinner("Searching for an answer…"):
        response = orchestrator.run(query, session_id=sid)
    st.session_state["messages"].append({"role": "user",  "content": query})
    st.session_state["messages"].append({
        "role":     "assistant",
        "content":  response.get("summary", ""),
        "response": response,
    })
    st.session_state["last_response"] = response
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────────────────────────────────────

# ---------------------------------------------------------------------------
# Program Interest Response — helpers
# ---------------------------------------------------------------------------

# Static URL → clean display label mapping used in the formatted response view.
_PIR_URL_LABELS: dict[str, str] = {
    "https://www.csulb.edu/graduate-studies/article/programs-advisors-and-deadlines-masters":
        "Programs, Advisors & Deadlines",
    "https://csulb.qualtrics.com/jfe/form/SV_6XARxv1fwI99C6i":
        "Application Materials Submission Form",
    "https://www.csulb.edu/graduate-center/workshops-events":
        "Graduate Center Workshops & Events",
    "https://www.csulb.edu/graduate-studies":
        "CSULB Graduate Studies",
    "https://www.csulb.edu/graduate-studies-csulb":
        "CSULB Graduate Studies",
}


def _pir_url_label(url: str, program_name: str = "", program_url: str = "") -> str:
    """Return a clean human-readable label for a known URL."""
    if program_url and url == program_url and program_name:
        return f"{program_name} Program Page"
    return _PIR_URL_LABELS.get(url, url)


def _format_clickable_content(message: str, result: dict) -> str:
    """
    Convert raw URLs in the plain-text message to labeled markdown links.

    The source template embeds URLs as:
      • Standalone line:         https://some-url
      • Inline in parens:        text (https://some-url) more text

    Both forms are converted to clean markdown links using display labels
    from _PIR_URL_LABELS (or the program name for the program-specific URL).
    The original plain-text message is unchanged — only the display copy
    returned by this function uses markdown links.
    """
    import re as _re

    prog_url  = (result.get("program_url")  or "").rstrip("/")
    prog_name = (result.get("program_name") or "")

    def label(url: str) -> str:
        return _pir_url_label(url.rstrip("/"), prog_name, prog_url)

    out: list[str] = []
    for line in message.split("\n"):
        stripped = line.strip()
        # Standalone URL line
        if _re.match(r"^https?://\S+$", stripped):
            out.append(f"[{label(stripped)}]({stripped})")
        else:
            # Inline URL wrapped in parentheses:  (https://...)
            def _repl(m: "re.Match") -> str:
                url = m.group(1)
                return f"([{label(url)}]({url}))"
            out.append(_re.sub(r"\((https?://[^\s)]+)\)", _repl, line))

    return "\n".join(out)


def _md_links_to_html(text: str) -> str:
    """
    Convert Markdown link syntax [label](url) to plain HTML anchors.

    Used so that links in the generated response survive Streamlit's rule that
    markdown is not processed inside HTML block elements (e.g. a styled <div>).
    All other text is left as-is; newlines are preserved by the CSS
    white-space:pre-wrap already set on .pir-response-body.
    """
    import re as _re_lh
    return _re_lh.sub(
        r'\[([^\]]+)\]\((https?://[^\)]+)\)',
        r'<a href="\2" target="_blank">\1</a>',
        text,
    )


def _render_program_interest_panel() -> None:
    """
    Graduate Program Connect panel — polished student-support guidance UI.

    Generates outreach responses for prospective students using approved
    templates and official CSULB program data. No LLM required.
    """
    with st.expander("🎓 Graduate Program Guidance — Explore programs, timelines & support", expanded=False):

        # ── Section 1: Inside header ──────────────────────────────────────────
        st.markdown(
            "<h4 style='"
            "margin:0 0 2px 0;"
            "color:var(--navy);"
            "font-size:1.05rem;"
            "font-weight:700;"
            "letter-spacing:-0.01em;"
            "'>🎓 Graduate Program Guidance</h4>"
            "<p style='"
            "color:var(--muted);"
            "font-size:0.85rem;"
            "margin:0 0 18px 0;"
            "line-height:1.5;"
            "'>Explore CSULB graduate programs, review application timelines, "
            "and access Grad Center advising resources.</p>",
            unsafe_allow_html=True,
        )

        # ── Response type selector ────────────────────────────────────────────
        response_type = st.radio(
            "Which type of response would you like to generate?",
            options=["Specific program", "Any graduate program"],
            key="pir_response_type",
            horizontal=True,
        )

        result: dict | None = None

        # ── Program-specific path ─────────────────────────────────────────────
        if response_type == "Specific program":
            col_in, col_btn = st.columns([5, 1], vertical_alignment="bottom")
            with col_in:
                program_input = st.text_input(
                    "Program",
                    placeholder="e.g. DNP nursing, physical therapy DPT, Ed.D. P-12, engineering PhD…",
                    key="pir_program_input",
                    label_visibility="collapsed",
                )
            with col_btn:
                generate_clicked = st.button(
                    "Get Program Guidance",
                    key="pir_generate_specific",
                    type="primary",
                    use_container_width=True,
                )

            if generate_clicked:
                if not program_input.strip():
                    st.warning("Please enter a program name to continue.")
                else:
                    with st.spinner("Looking up program data…"):
                        result = generate_program_specific_response(program_input.strip())
                    st.session_state["pir_last_result"] = result

            result = st.session_state.get("pir_last_result")
            if result and result.get("response_type") != "program_specific":
                result = None
                st.session_state.pop("pir_last_result", None)

        # ── General path ──────────────────────────────────────────────────────
        else:
            if st.button("Get Program Guidance", key="pir_generate_general",
                         type="primary"):
                with st.spinner("Preparing response…"):
                    result = generate_general_interest_response()
                st.session_state["pir_last_result"] = result

            result = st.session_state.get("pir_last_result")
            if result and result.get("response_type") != "general":
                result = None
                st.session_state.pop("pir_last_result", None)

        # ── Nothing generated yet ─────────────────────────────────────────────
        if result is None:
            return

        # ── Error / ambiguous ─────────────────────────────────────────────────
        if not result.get("found"):
            st.error(result.get("error") or "Could not generate a response.")
            suggestions = result.get("suggestions", [])
            if suggestions:
                st.markdown("**Did you mean one of these programs?**")
                for s in suggestions:
                    st.markdown(f"- {s}")
            return

        st.markdown("---")

        # ── Section 4: Program info card ──────────────────────────────────────
        if result.get("response_type") == "program_specific":
            prog_name  = result.get("program_name", "")
            prog_url   = result.get("program_url",  "")
            adv_email  = result.get("advisor_email", "")
            deadlines  = result.get("deadlines") or {}
            fall_dl    = deadlines.get("fall",   "")
            spring_dl  = deadlines.get("spring", "")

            url_html   = (f'<a href="{prog_url}" target="_blank">View Program Page →</a>'
                          if prog_url else "—")
            email_html = (f'<a href="mailto:{adv_email}">{adv_email}</a>'
                          if adv_email else "Refer to the program page for contact information.")
            grad_url   = "https://www.csulb.edu/graduate-studies-csulb"

            # Info card — no deadline HTML embedded here (avoids indentation-as-codeblock bug)
            st.markdown(
                f'<div class="pir-info-card">'
                f'<p class="pir-info-title">🎓 {prog_name}</p>'
                f'<div class="pir-info-row">'
                f'<span class="pir-info-icon">📧</span>'
                f'<span><span class="pir-info-label">Advisor&nbsp;</span>{email_html}</span>'
                f'</div>'
                f'<div class="pir-info-row">'
                f'<span class="pir-info-icon">🔗</span>'
                f'<span><span class="pir-info-label">Program Page&nbsp;</span>{url_html}</span>'
                f'</div>'
                f'<div class="pir-info-row">'
                f'<span class="pir-info-icon">🏫</span>'
                f'<span><span class="pir-info-label">Graduate Studies&nbsp;</span>'
                f'<a href="{grad_url}" target="_blank">CSULB Graduate Studies →</a></span>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # Deadlines rendered as native Streamlit markdown — no HTML injection
            if fall_dl or spring_dl:
                fall_label   = fall_dl   or "—"
                spring_label = spring_dl or "—"
                st.markdown(
                    '<p class="pir-section-label" style="margin-top:4px;">Application Deadlines</p>',
                    unsafe_allow_html=True,
                )
                col_f, col_s = st.columns(2)
                col_f.markdown(f"🍂 **Fall**\n\n{fall_label}")
                col_s.markdown(f"🌱 **Spring**\n\n{spring_label}")

        # ── Guidance content ───────────────────────────────────────────────────
        formatted_md = _format_clickable_content(result["message"], result)

        # Render the template message as markdown so links are clickable.
        # _md_links_to_html converts [label](url) to <a> tags before injection
        # into the styled div because Streamlit does not process markdown inside
        # HTML block elements.
        response_html = _md_links_to_html(formatted_md)
        st.markdown(
            f'<div class="pir-response-body">{response_html}</div>',
            unsafe_allow_html=True,
        )

        # ── Sources ───────────────────────────────────────────────────────────
        sources = result.get("sources", [])
        if sources:
            label_map = {
                "https://www.csulb.edu/graduate-studies-csulb": "CSULB Graduate Studies",
                "https://www.csulb.edu/graduate-studies":       "CSULB Graduate Studies",
            }
            prog_url  = result.get("program_url",  "") or ""
            prog_name = result.get("program_name", "") or ""
            if prog_url and prog_name:
                label_map[prog_url] = f"{prog_name} Program Page"
            parts = [
                f'<a href="{s}" target="_blank">{label_map.get(s, s)}</a>'
                for s in sources
            ]
            st.markdown(
                f'<p class="pir-sources">Sources: {" · ".join(parts)}</p>',
                unsafe_allow_html=True,
            )


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
    st.markdown("""
    <div class="mode-banner">
        <span>💬</span>
        <span>AI Assistant Mode — Ask about programs, advisors, admissions steps, and FAQs</span>
        <span class="mode-banner-tag">Standard</span>
    </div>
    """, unsafe_allow_html=True)

    if not st.session_state["messages"]:
        _render_sample_questions()

    for i, msg in enumerate(st.session_state["messages"]):
        with st.chat_message(msg["role"],
                             avatar="👤" if msg["role"] == "user" else "🎓"):
            if msg["role"] == "assistant" and "response" in msg:
                _render_response(msg["response"], msg_idx=i)
            else:
                st.markdown(msg["content"])

    if query := st.chat_input("Ask me anything about CSULB grad admissions…"):
        _submit_query(query)

    st.markdown("---")
    _render_program_interest_panel()
    _render_footer()


if __name__ == "__main__":
    main()

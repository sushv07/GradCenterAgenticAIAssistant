"""
CSULB Graduate Center AI Assistant – Streamlit UI
Navy #003366 · Gold #FFC72C
Run: streamlit run app.py
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
from services.api_client import ApiClient, BackendError
from tools.program_interest_tool import (
    generate_program_specific_response,
    generate_general_interest_response,
)

_client = ApiClient()


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
   CSULB GRADUATE CENTER  –  Production UI  v2
   Gold #FFC72C · Navy #003366  |  warm gold-first palette
═══════════════════════════════════════════════════════════════════════ */

/* ── Design tokens ───────────────────────────────────────────────────── */
:root {
    --navy:        #111111;
    --navy-deep:   #000000;
    --navy-mid:    #333333;
    --gold:        #F0A800;
    --gold-dark:   #C98A00;
    --gold-light:  #FFF3CC;
    --gold-mid:    #F5C040;
    --bg:          #fafaf7;
    --surface:     #ffffff;
    --text:        #111827;
    --text-sub:    #374151;
    --muted:       #6b7280;
    --border:      #ddd8cc;
    --border-soft: #ede8da;
    --radius:      8px;
    --radius-lg:   12px;
    --ease:        cubic-bezier(0.16, 1, 0.3, 1);
    --shadow-xs:   0 1px 2px rgba(0,0,0,0.05);
    --shadow-sm:   0 2px 6px rgba(0,0,0,0.07);
    --shadow-md:   0 4px 16px rgba(0,0,0,0.09);
    --shadow-gold: 0 4px 14px rgba(201,138,0,0.32);
}


/* ══════════════════════════════════════════════════════════════════════
   LAYOUT  –  strip every top offset Streamlit injects for the header
══════════════════════════════════════════════════════════════════════ */

.stApp { background: var(--bg) !important; }

/* Override the CSS variable Streamlit uses to size the fixed header.
   Setting it to 0 causes any rule that reads var(--header-height) to
   resolve to 0, eliminating the reserved space. */
:root {
    --header-height:            0px !important;
    --header-decoration-height: 0px !important;
    --header-decoration-top:    0px !important;
}

/* Collapse the Streamlit toolbar to zero height so it stops
   reserving space at the top. The sidebar collapsed-control button
   lives OUTSIDE this element so sidebar remains unaffected. */
[data-testid="stHeader"] {
    height:     0   !important;
    min-height: 0   !important;
    padding:    0   !important;
    overflow:   visible !important;
    background: transparent !important;
    box-shadow: none !important;
    border:     none !important;
}

/* Strip the padding-top that Streamlit injects to clear the fixed header.
   Target every layer — Streamlit can set it on any of these. */
[data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] > section,
[data-testid="stAppViewContainer"] > section > div,
[data-testid="stMain"],
[data-testid="stMain"] > div,
[data-testid="stMain"] > div > div,
.main {
    padding-top: 0 !important;
    margin-top:  0 !important;
}
[data-testid="stMain"],
.main {
    overflow-y: auto   !important;
    overflow-x: hidden !important;
}

.main .block-container {
    padding-top:    0        !important;
    padding-bottom: 0.1rem   !important;
    padding-left:   1.5rem   !important;
    padding-right:  1.5rem   !important;
    max-width:      100%     !important;
    overflow:       visible  !important;
}

/* Strip margins Streamlit adds on its own wrapper divs so the banner
   sits flush at the very top of the content column. */
[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"]:first-child,
[data-testid="stVerticalBlock"] > div:first-child {
    margin-top:  0 !important;
    padding-top: 0 !important;
}
[data-testid="stElementContainer"]:first-child,
[data-testid="stMarkdown"]:first-child {
    margin-top:  0 !important;
    padding-top: 0 !important;
}

.stTabs [data-baseweb="tab-panel"] > div:first-child { padding-top: 0 !important; }


/* ══════════════════════════════════════════════════════════════════════
   SIDEBAR  –  amber gold background, navy text
══════════════════════════════════════════════════════════════════════ */

[data-testid="stSidebar"] [data-testid="stSidebarContent"],
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"],
[data-testid="stSidebar"] > div,
[data-testid="stSidebar"] > div > div,
[data-testid="stSidebar"] > div > div > div {
    padding-top: 0 !important;
    margin-top:  0 !important;
}

[data-testid="stSidebar"] {
    background:   linear-gradient(180deg, var(--gold) 0%, var(--gold-mid) 55%, var(--gold-dark) 100%) !important;
    border-right: 2px solid var(--gold-dark);
    box-shadow:   2px 0 10px rgba(0,0,0,0.12);
}

[data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] .stMarkdown h2,
[data-testid="stSidebar"] .stMarkdown h3,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span { color: var(--navy) !important; }
[data-testid="stSidebar"] hr   { border-color: rgba(0,51,102,0.18) !important; margin: 5px 0 !important; }
[data-testid="stSidebar"] .stCaption { color: rgba(0,51,102,0.62) !important; font-size: 0.74rem !important; }

[data-testid="stSidebar"] .stTextInput > div > input {
    background:    rgba(255,255,255,0.55) !important;
    border:        1px solid rgba(0,51,102,0.22) !important;
    color:         var(--navy)            !important;
    border-radius: var(--radius)          !important;
    font-size:     0.84rem                !important;
    transition:    border-color 0.15s var(--ease), box-shadow 0.15s var(--ease) !important;
}
[data-testid="stSidebar"] .stTextInput > div > input:focus {
    border-color: var(--navy)                       !important;
    box-shadow:   0 0 0 3px rgba(0,51,102,0.14)     !important;
}

[data-testid="stSidebar"] .stButton > button {
    background:    rgba(255,255,255,0.40) !important;
    color:         var(--navy)            !important;
    border:        1px solid rgba(0,51,102,0.20) !important;
    border-radius: var(--radius)          !important;
    font-size:     0.82rem                !important;
    font-weight:   500                    !important;
    transition:    background 0.18s var(--ease), border-color 0.18s var(--ease) !important;
    box-shadow:    none                   !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background:   rgba(255,255,255,0.65) !important;
    border-color: rgba(0,51,102,0.35)    !important;
    font-weight:  600                    !important;
    transform:    none                   !important;
}


/* ══════════════════════════════════════════════════════════════════════
   SIDEBAR BRAND & NAV
══════════════════════════════════════════════════════════════════════ */

.sidebar-brand {
    text-align:    center;
    padding:       0 14px 10px;
    margin-top:    -2.8rem !important;
    border-bottom: 1px solid rgba(0,0,0,0.12);
    margin-bottom: 6px;
    background:    transparent;
}
.sidebar-brand-logo {
    display:       block;
    margin:        0 auto 12px;
    width:         290px;
    height:        290px;
    object-fit:    contain;
    border-radius: 50%;
    box-shadow:    0 4px 14px rgba(0,0,0,0.22);
}
.sidebar-brand-name {
    color:          var(--navy);
    font-size:      1.8rem;
    font-weight:    800;
    display:        block;
    line-height:    1.3;
    letter-spacing: -0.2px;
    white-space:    normal;
    text-align:     center;
}
.sidebar-brand-tag {
    display:        inline-block;
    margin-top:     8px;
    background:     rgba(0,0,0,0.10);
    color:          var(--navy);
    font-size:      1.1rem;
    font-weight:    800;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    border-radius:  20px;
    padding:        6px 20px;
    border:         1px solid rgba(0,0,0,0.18);
}

.nav-section-label {
    color:          rgba(0,51,102,0.60) !important;
    font-size:      0.58rem             !important;
    font-weight:    700                 !important;
    letter-spacing: 1.3px               !important;
    text-transform: uppercase           !important;
    padding:        0 6px;
    margin-bottom:  3px;
    display:        block;
}

.nav-item {
    display:        flex;
    align-items:    center;
    gap:            8px;
    padding:        7px 10px;
    border-radius:  6px;
    color:          var(--navy);
    font-size:      0.82rem;
    font-weight:    500;
    margin-bottom:  2px;
    cursor:         default;
    border-left:    3px solid transparent;
    transition:     background 0.15s var(--ease), border-color 0.15s var(--ease);
}
.nav-item:hover {
    background:        rgba(255,255,255,0.30);
    border-left-color: rgba(0,51,102,0.35);
}
.nav-item.active {
    background:    rgba(255,255,255,0.50);
    color:         var(--navy);
    font-weight:   700;
    border-left:   3px solid var(--navy);
}
.nav-item.active span:first-child { opacity: 1; }


/* ══════════════════════════════════════════════════════════════════════
   HEADER  –  warm gold gradient, navy text
══════════════════════════════════════════════════════════════════════ */

.csulb-header {
    background:    linear-gradient(135deg, var(--gold) 0%, var(--gold-mid) 100%);
    padding:       clamp(14px, 2.2vh, 28px) clamp(28px, 4vw, 60px);
    margin:        -5rem -1rem 0.1rem -1rem;
    margin-top:    -5rem !important;
    display:       flex;
    align-items:   center;
    gap:           clamp(14px, 2vw, 30px);
    border-bottom: 4px solid var(--gold-dark);
    box-shadow:    0 3px 12px rgba(0,0,0,0.13);
    position:      sticky;
    top:           0;
    z-index:       100;
}
.csulb-header-logo {
    font-size:   clamp(4rem, 6.5vw, 7rem);
    line-height: 1;
    flex-shrink: 0;
}
.csulb-header-text { flex: 1; min-width: 0; }
.csulb-header-title {
    color:          var(--navy);
    font-size:      clamp(2.2rem, 4vw, 4rem);
    font-weight:    800;
    letter-spacing: -0.5px;
    margin:         0;
    line-height:    1.15;
}
.csulb-header-sub {
    color:          var(--navy-mid);
    font-size:      clamp(1.1rem, 1.7vw, 1.7rem);
    font-weight:    600;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    margin:         8px 0 0;
    opacity:        0.78;
}
.csulb-header-lb-logo {
    height:        clamp(72px, 10vw, 130px);
    width:         clamp(72px, 10vw, 130px);
    object-fit:    contain;
    flex-shrink:   0;
    margin-left:   14px;
    border-radius: 50%;
    box-shadow:    0 4px 14px rgba(0,0,0,0.22);
}


/* ══════════════════════════════════════════════════════════════════════
   MODE BANNER
══════════════════════════════════════════════════════════════════════ */

.mode-banner {
    display:       flex;
    align-items:   center;
    gap:           10px;
    background:    var(--gold-light);
    color:         var(--navy);
    border:        1px solid rgba(230,168,0,0.22);
    border-radius: var(--radius);
    padding:       8px 16px;
    margin-bottom: 10px;
    font-size:     0.83rem;
    font-weight:   400;
    box-shadow:    var(--shadow-xs);
}
.mode-banner-tag {
    margin-left:    auto;
    background:     var(--gold);
    color:          var(--navy);
    font-size:      0.65rem;
    font-weight:    700;
    padding:        3px 10px;
    border-radius:  5px;
    letter-spacing: 0.4px;
    text-transform: uppercase;
    border:         1px solid var(--gold-dark);
}


/* ══════════════════════════════════════════════════════════════════════
   TABS
══════════════════════════════════════════════════════════════════════ */

.stTabs [data-baseweb="tab-list"] {
    background:    transparent;
    border-bottom: 2px solid var(--border-soft);
    gap: 0; padding: 0;
}
.stTabs [data-baseweb="tab"] {
    padding:       11px 22px;
    font-weight:   500;
    font-size:     0.87rem;
    color:         var(--muted) !important;
    border-radius: 0           !important;
    background:    transparent !important;
    transition:    color 0.15s var(--ease) !important;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--text-sub) !important; }
.stTabs [aria-selected="true"] {
    color:         var(--navy)  !important;
    font-weight:   700          !important;
    border-bottom: 3px solid var(--gold) !important;
    margin-bottom: -2px;
}
.stTabs [data-baseweb="tab-panel"] { background: transparent; border: none; padding: 24px 0 0; }


/* ══════════════════════════════════════════════════════════════════════
   BUTTONS  –  gold primary, warm outlined default
══════════════════════════════════════════════════════════════════════ */

.stButton > button {
    background:    linear-gradient(135deg, var(--gold) 0%, var(--gold-mid) 100%) !important;
    color:         var(--navy)              !important;
    border:        1.5px solid var(--gold-dark) !important;
    font-weight:   600                      !important;
    border-radius: var(--radius)            !important;
    transition:    background 0.16s var(--ease), color 0.16s var(--ease),
                   border-color 0.16s var(--ease), box-shadow 0.16s var(--ease),
                   transform 0.12s var(--ease) !important;
}
.stButton > button:hover {
    background:   linear-gradient(135deg, var(--gold-dark) 0%, var(--gold) 100%) !important;
    color:        var(--navy)        !important;
    border-color: var(--gold-dark)   !important;
    box-shadow:   var(--shadow-gold) !important;
    transform:    translateY(-1px)   !important;
}
.stButton > button:active { transform: translateY(0) !important; }

/* Primary — black fill, gold text */
.stButton > button[kind="primary"] {
    background:   #111111          !important;
    color:        var(--gold)      !important;
    border-color: #111111          !important;
    font-weight:  700              !important;
    box-shadow:   var(--shadow-xs) !important;
}
.stButton > button[kind="primary"]:hover {
    background:  #000000           !important;
    color:       var(--gold-mid)   !important;
    box-shadow:  0 4px 14px rgba(0,0,0,0.30) !important;
    transform:   translateY(-1px)  !important;
}
.stButton > button[kind="primary"]:active { transform: translateY(0) !important; }

[data-testid="stLinkButton"] > a {
    background:    var(--gold)       !important;
    color:         var(--navy)       !important;
    font-weight:   700               !important;
    border-radius: var(--radius)     !important;
    transition:    opacity 0.15s     !important;
}
[data-testid="stLinkButton"] > a:hover { opacity: 0.88 !important; }


/* ══════════════════════════════════════════════════════════════════════
   CHAT MESSAGES
══════════════════════════════════════════════════════════════════════ */

[data-testid="stChatMessage"] {
    background:    var(--surface);
    border-radius: var(--radius-lg);
    padding:       14px 18px;
    margin:        5px 0;
    border:        1px solid var(--border-soft);
    box-shadow:    var(--shadow-xs);
    transition:    box-shadow 0.18s var(--ease);
}
[data-testid="stChatMessage"]:hover { box-shadow: var(--shadow-sm); }


/* ══════════════════════════════════════════════════════════════════════
   CHAT INPUT
══════════════════════════════════════════════════════════════════════ */

[data-testid="stChatInput"] {
    box-shadow: 0 -2px 10px rgba(230,168,0,0.08) !important;
}
[data-testid="stChatInput"] textarea {
    border:        2px solid var(--border)  !important;
    border-radius: var(--radius-lg)         !important;
    background:    var(--surface)           !important;
    font-size:     0.96rem                  !important;
    line-height:   1.55                     !important;
    min-height:    52px                     !important;
    transition:    border-color 0.18s var(--ease), box-shadow 0.18s var(--ease) !important;
    box-shadow:    var(--shadow-xs)         !important;
}
[data-testid="stChatInput"] textarea:focus {
    border-color: var(--gold-dark)                  !important;
    box-shadow:   0 0 0 3px rgba(255,199,44,0.18),
                  var(--shadow-sm)                  !important;
    outline: none !important;
}

/* Chat send button — gold fill */
[data-testid="stChatInput"] button {
    background:    var(--gold)       !important;
    color:         var(--navy)       !important;
    border-color:  var(--gold-dark)  !important;
    border-radius: 8px               !important;
}
[data-testid="stChatInput"] button:hover {
    background:  var(--gold-dark) !important;
    box-shadow:  var(--shadow-gold) !important;
}
[data-testid="stChatInput"] button svg {
    fill:   var(--navy) !important;
    stroke: var(--navy) !important;
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
    border:        1.5px solid var(--gold-dark)                               !important;
    border-radius: var(--radius)                                              !important;
    background:    linear-gradient(135deg, var(--gold) 0%, var(--gold-mid) 100%) !important;
    box-shadow:    var(--shadow-xs)                                           !important;
}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span,
[data-testid="stExpander"] [data-testid="stExpanderToggleIcon"] ~ div,
[data-testid="stExpander"] details summary div p {
    font-weight: 800     !important;
    color:       #111111 !important;
    font-size:   1.15rem !important;
}
[data-testid="stExpander"] details summary,
[data-testid="stExpander"] > details > summary {
    padding-top:    10px !important;
    padding-bottom: 10px !important;
    min-height:     44px !important;
}
[data-testid="stExpander"] summary:hover {
    background: linear-gradient(135deg, var(--gold-dark) 0%, var(--gold) 100%) !important;
}
/* Keep the expanded content area white for readability */
[data-testid="stExpander"] > div:last-child {
    background:    var(--surface)               !important;
    border-top:    1.5px solid var(--gold-dark) !important;
}

/* Radio label inside the Graduate Program Guidance expander */
[data-testid="stRadio"] > label,
[data-testid="stRadio"] > div > label,
[data-testid="stRadio"] p {
    font-size:   0.97rem !important;
    font-weight: 600     !important;
    color:       var(--navy) !important;
}

#MainMenu  { visibility: hidden !important; }
footer     { visibility: hidden !important; }


/* Deploy button — hidden */
[data-testid="stDeployButton"],
[data-testid="stDeployButton"] *,
[class*="deployButton"],
button[kind="header"] {
    visibility:     hidden !important;
    opacity:        0      !important;
    pointer-events: none   !important;
}


/* ══════════════════════════════════════════════════════════════════════
   WELCOME / EMPTY STATE  –  compact for all screen sizes
══════════════════════════════════════════════════════════════════════ */

.welcome-state {
    text-align: center;
    padding:    28px 20px clamp(6px, 0.8vh, 12px);
}
.welcome-state-icon {
    font-size:     clamp(6rem, 10vw, 9rem);
    display:       block;
    margin-top:    0;
    margin-bottom: clamp(10px, 1.2vh, 18px);
    line-height:   1;
}
.welcome-state-title {
    color:          var(--navy);
    font-size:      clamp(1.6rem, 2.6vh, 2.2rem);
    font-weight:    800;
    margin-bottom:  8px;
    letter-spacing: -0.4px;
    line-height:    1.2;
}
.welcome-state-sub {
    color:       var(--muted);
    font-size:   clamp(1.05rem, 1.5vh, 1.3rem);
    max-width:   620px;
    margin:      0 auto clamp(12px, 1.5vh, 20px);
    line-height: 1.6;
}
.sample-label {
    color:          var(--gold-dark);
    font-size:      0.70rem;
    font-weight:    700;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-top:     4px;
    margin-bottom:  8px;
    display:        block;
}


/* ══════════════════════════════════════════════════════════════════════
   RESPONSE COMPONENTS
══════════════════════════════════════════════════════════════════════ */

/* Summary box */
.summary-box {
    background:    var(--gold-light);
    border-left:   4px solid var(--gold-dark);
    border-radius: 0 var(--radius) var(--radius) 0;
    padding:       12px 18px;
    margin-bottom: 14px;
    color:         var(--text);
    font-size:     0.95rem;
    line-height:   1.65;
}

/* Next-step action box */
.action-box {
    background:    #fffceb;
    border-left:   4px solid var(--gold-dark);
    border-radius: 0 var(--radius) var(--radius) 0;
    padding:       11px 18px;
    margin-bottom: 14px;
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
    border-top:    3px solid var(--gold-dark);
    border-radius: var(--radius);
    padding:       16px 20px;
    margin-bottom: 14px;
    box-shadow:    var(--shadow-xs);
}
.advisor-card-header {
    font-size:      0.62rem;
    font-weight:    800;
    color:          var(--navy);
    text-transform: uppercase;
    letter-spacing: 0.9px;
    margin-bottom:  10px;
    padding-bottom: 8px;
    border-bottom:  1px solid var(--border-soft);
}
.advisor-row {
    display:       flex;
    gap:           10px;
    margin-bottom: 6px;
    font-size:     0.9rem;
    line-height:   1.45;
}
.advisor-key   { color: var(--muted); min-width: 68px; font-weight: 500; }
.advisor-val   { color: var(--text);  font-weight: 500; }
.advisor-email { color: #1a56db; text-decoration: none; }
.advisor-email:hover { text-decoration: underline; }

/* Email draft card */
.email-card {
    background:    var(--gold-light);
    border:        1px solid rgba(230,168,0,0.22);
    border-radius: var(--radius);
    padding:       14px 18px;
    margin:        10px 0 14px;
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
    border-top:    3px solid var(--gold-dark);
    border-radius: var(--radius);
    padding:       18px 22px 16px;
    margin-bottom: 14px;
    box-shadow:    var(--shadow-sm);
}
.deadline-card-header {
    font-size:      0.62rem;
    font-weight:    800;
    color:          var(--navy);
    text-transform: uppercase;
    letter-spacing: 0.9px;
    margin-bottom:  4px;
    padding-bottom: 8px;
    border-bottom:  1px solid var(--border-soft);
}
.deadline-program-name {
    font-size:   1.05rem;
    font-weight: 700;
    color:       var(--text);
    margin:      0 0 12px 0;
    line-height: 1.3;
}
.deadline-cols { display: flex; gap: 24px; flex-wrap: wrap; }
.deadline-col  { flex: 1; min-width: 180px; }
.deadline-col-label {
    font-size:      0.68rem;
    font-weight:    800;
    letter-spacing: 0.7px;
    text-transform: uppercase;
    color:          var(--navy);
    margin-bottom:  8px;
    opacity:        0.75;
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
.deadline-season { min-width: 46px; color: var(--muted); font-weight: 500; font-size: 0.82rem; }
.deadline-val { font-weight: 600; color: var(--text); }
.deadline-val.closed { color: #9ca3af; font-style: italic; font-weight: 400; }
.deadline-contact {
    margin-top:  12px; padding-top: 10px;
    border-top:  1px solid var(--border-soft);
    font-size:   0.85rem; color: var(--text-sub);
    display:     flex; flex-wrap: wrap; gap: 16px;
}
.deadline-contact a { color: #1a56db; text-decoration: none; }
.deadline-contact a:hover { text-decoration: underline; }

/* Mini disambiguation card */
.deadline-mini-card {
    background:    var(--surface);
    border:        1px solid var(--border-soft);
    border-left:   3px solid var(--gold-dark);
    border-radius: var(--radius);
    padding:       10px 14px;
    margin-bottom: 7px;
    font-size:     0.88rem;
}
.deadline-mini-program { font-weight: 700; color: var(--text); margin-bottom: 4px; }
.deadline-mini-row { color: var(--text-sub); font-size: 0.82rem; line-height: 1.5; }

/* Clarification box */
.clarification-box {
    background:    var(--gold-light);
    border:        1px solid rgba(230,168,0,0.35);
    border-left:   4px solid var(--gold-dark);
    border-radius: var(--radius);
    padding:       13px 18px;
    margin-bottom: 13px;
}


/* ══════════════════════════════════════════════════════════════════════
   DISCOVERY / PROGRAM RECOMMENDATION CARDS
══════════════════════════════════════════════════════════════════════ */

.disc-behavior-banner {
    display:        inline-block;
    font-size:      0.62rem;
    font-weight:    800;
    letter-spacing: 0.7px;
    text-transform: uppercase;
    color:          var(--navy);
    background:     var(--gold-light);
    border:         1px solid rgba(230,168,0,0.35);
    border-radius:  5px;
    padding:        3px 10px;
    margin-bottom:  12px;
}
.disc-program-card {
    background:    var(--surface);
    border:        1px solid var(--border-soft);
    border-top:    3px solid var(--gold-dark);
    border-radius: var(--radius);
    padding:       16px 20px 14px;
    margin-bottom: 12px;
    box-shadow:    var(--shadow-xs);
}
.disc-program-name {
    font-size:   1.05rem;
    font-weight: 700;
    color:       var(--text);
    margin:      0 0 8px 0;
    line-height: 1.35;
}
.disc-confidence-badge {
    display:        inline-block;
    font-size:      0.67rem;
    font-weight:    700;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    border:         1.5px solid currentColor;
    border-radius:  4px;
    padding:        2px 8px;
    margin-bottom:  10px;
}
.disc-rows { margin-top: 8px; }
.disc-row {
    display:       flex;
    gap:           10px;
    padding:       5px 0;
    border-bottom: 1px solid var(--border-soft);
    font-size:     0.9rem;
    line-height:   1.45;
}
.disc-row:last-child { border-bottom: none; }
.disc-key { color: var(--muted); min-width: 100px; font-weight: 500; flex-shrink: 0; }
.disc-val { color: var(--text);  font-weight: 500; }
.disc-val a { color: #1a56db; text-decoration: none; }
.disc-val a:hover { text-decoration: underline; }


/* ══════════════════════════════════════════════════════════════════════
   APPLICATION STEP CARDS
══════════════════════════════════════════════════════════════════════ */

.app-steps-header {
    font-size:      0.68rem;
    font-weight:    800;
    color:          var(--navy);
    text-transform: uppercase;
    letter-spacing: 0.9px;
    margin:         0 0 12px 0;
    padding-bottom: 8px;
    border-bottom:  1px solid var(--border-soft);
}

.app-step-card {
    display:       flex;
    gap:           14px;
    align-items:   flex-start;
    background:    var(--surface);
    border:        1px solid var(--border-soft);
    border-radius: var(--radius);
    padding:       14px 18px;
    margin-bottom: 8px;
    box-shadow:    var(--shadow-xs);
    transition:    box-shadow 0.18s var(--ease), transform 0.14s var(--ease);
}
.app-step-card:hover { box-shadow: var(--shadow-md); transform: translateY(-1px); }

.app-step-num {
    width:           34px; height: 34px; min-width: 34px;
    border-radius:   50%;
    color:           var(--navy);
    background:      var(--gold);
    font-weight:     800;
    font-size:       0.90rem;
    display:         flex;
    align-items:     center;
    justify-content: center;
    margin-top:      2px;
    box-shadow:      0 2px 5px rgba(230,168,0,0.30);
}

.app-step-body { flex: 1; min-width: 0; }
.app-step-cat-badge {
    display:        inline-block;
    background:     var(--gold-light);
    color:          var(--navy);
    font-size:      0.67rem;
    font-weight:    700;
    letter-spacing: 0.4px;
    text-transform: uppercase;
    padding:        2px 8px;
    border-radius:  8px;
    margin-bottom:  5px;
}
.app-step-title   { font-weight: 700; font-size: 0.97rem; color: var(--text);     line-height: 1.35; margin-bottom: 4px; }
.app-step-desc    { font-size: 0.875rem; color: var(--text-sub); line-height: 1.6; margin-bottom: 8px; }
.app-step-content { font-size: 0.89rem;  color: var(--text-sub); line-height: 1.7; margin: 7px 0 9px; word-break: break-word; }
.app-step-content p { margin: 0 0 6px 0; }

.app-step-related {
    margin-top:  9px; padding-top: 7px;
    border-top:  1px dashed var(--border-soft);
    font-size:   0.80rem; color: var(--muted); line-height: 1.8;
}
.app-step-related strong { color: var(--text-sub); font-weight: 600; display: block; margin-bottom: 3px; }

.app-step-sublink {
    display:         inline-flex;
    align-items:     center;
    gap:             4px;
    color:           var(--navy);
    text-decoration: none;
    font-weight:     500;
    font-size:       0.80rem;
    background:      var(--gold-light);
    padding:         2px 8px;
    border-radius:   5px;
    margin:          2px 4px 2px 0;
    border:          1px solid rgba(230,168,0,0.25);
    transition:      background 0.14s var(--ease), color 0.14s var(--ease);
}
.app-step-sublink:hover { background: var(--navy); color: #ffffff; }

.app-step-source { margin-top: 7px; font-size: 0.76rem; color: var(--muted); }
.app-step-source a { color: var(--muted); text-decoration: none; word-break: break-all; }
.app-step-source a:hover { color: var(--navy); text-decoration: underline; }

.app-step-link {
    display:         inline-flex;
    align-items:     center;
    gap:             5px;
    font-size:       0.82rem;
    font-weight:     600;
    color:           var(--navy);
    text-decoration: none;
    border:          1px solid rgba(230,168,0,0.35);
    padding:         4px 11px;
    border-radius:   6px;
    background:      var(--gold-light);
    transition:      background 0.15s var(--ease), color 0.15s var(--ease);
}
.app-step-link:hover { background: var(--navy); color: #ffffff; border-color: var(--navy); }


/* ══════════════════════════════════════════════════════════════════════
   FOOTER
══════════════════════════════════════════════════════════════════════ */

.csulb-footer {
    text-align:  center;
    padding:     10px 16px 6px;
    margin-top:  0.8rem;
    border-top:  1px solid var(--border-soft);
    color:       var(--muted);
    font-size:   0.76rem;
    line-height: 1.6;
}
.csulb-footer a { color: var(--navy); font-weight: 600; text-decoration: none; transition: opacity 0.15s; }
.csulb-footer a:hover { opacity: 0.72; text-decoration: underline; }


/* ══════════════════════════════════════════════════════════════════════
   GRADUATE PROGRAM GUIDANCE  (Program Interest panel)
══════════════════════════════════════════════════════════════════════ */

.pir-info-card {
    background:    var(--surface);
    border:        1px solid var(--border-soft);
    border-left:   4px solid var(--gold-dark);
    border-radius: var(--radius);
    padding:       14px 18px;
    margin-bottom: 16px;
    box-shadow:    var(--shadow-xs);
}
.pir-info-title {
    font-size:   1.0rem;
    font-weight: 700;
    color:       var(--navy);
    margin:      0 0 10px 0;
}
.pir-info-row {
    display:     flex;
    align-items: flex-start;
    gap:         8px;
    font-size:   0.855rem;
    color:       var(--text-sub);
    margin:      4px 0;
    line-height: 1.5;
}
.pir-info-icon { font-size: 0.9rem; flex-shrink: 0; margin-top: 1px; }
.pir-info-label { font-weight: 600; color: var(--text); white-space: nowrap; }
.pir-info-row a { color: var(--navy); font-weight: 500; text-decoration: none; }
.pir-info-row a:hover { text-decoration: underline; }

.pir-deadline-chips { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
.pir-deadline-chip {
    background:    var(--gold-light);
    border:        1px solid rgba(230,168,0,0.30);
    border-radius: 20px;
    padding:       3px 11px;
    font-size:     0.79rem;
    font-weight:   600;
    color:         var(--navy);
}
.pir-deadline-chip.na { background: #f5f5f5; border-color: var(--border); color: var(--muted); }

.pir-section-label {
    font-size:      0.68rem;
    font-weight:    800;
    color:          #111111;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin:         0 0 10px 0;
    padding-bottom: 7px;
    border-bottom:  1px solid var(--border-soft);
}

.pir-response-body {
    background:    var(--surface);
    border:        1px solid var(--border-soft);
    border-left:   3px solid var(--gold);
    border-radius: var(--radius);
    padding:       20px 24px;
    font-size:     0.90rem;
    color:         var(--text);
    line-height:   1.75;
    box-shadow:    var(--shadow-xs);
    white-space:   pre-wrap;
    word-break:    break-word;
    margin-bottom: 12px;
}
.pir-response-body p  { margin: 0 0 0.9em 0; }
.pir-response-body ul { margin: 4px 0 0.9em 18px; padding: 0; }
.pir-response-body li { margin-bottom: 3px; }
.pir-response-body a  {
    color:           var(--navy);
    font-weight:     500;
    text-decoration: none;
    border-bottom:   1px solid rgba(230,168,0,0.45);
}
.pir-response-body a:hover { border-bottom-color: var(--gold-dark); text-decoration: none; }

.pir-sources { font-size: 0.77rem; color: var(--muted); margin-top: 4px; }
.pir-sources a { color: var(--navy); font-weight: 500; text-decoration: none; }
.pir-sources a:hover { text-decoration: underline; }


/* ══════════════════════════════════════════════════════════════════════
   RESPONSIVE  –  MacBook Pro / smaller laptops
══════════════════════════════════════════════════════════════════════ */

@media screen and (max-height: 980px) {
    /* Header */
    .csulb-header        { padding: 10px 28px !important; }
    .csulb-header-logo   { font-size: 3.5rem  !important; }
    .csulb-header-title  { font-size: 2.1rem  !important; }
    .csulb-header-sub    { font-size: 1.05rem !important; }
    .csulb-header-lb-logo{ height: 68px !important; width: 68px !important; }
    /* Welcome */
    .welcome-state       { padding: 6px 20px 4px !important; }
    .welcome-state-icon  { font-size: 5.5rem !important; margin-bottom: 10px !important; }
    .welcome-state-title { font-size: 1.6rem  !important; }
    .welcome-state-sub   { font-size: 1.05rem !important; margin-bottom: 12px !important; }
    /* Sidebar */
    .sidebar-brand       { padding: 8px 12px 8px  !important; }
    .sidebar-brand-logo  { width: 245px !important; height: 245px !important; margin-bottom: 8px !important; }
    .sidebar-brand-name  { font-size: 1.55rem !important; }
    .sidebar-brand-tag   { font-size: 0.96rem !important; padding: 5px 16px !important; margin-top: 6px !important; }
    .nav-item            { padding: 5px 8px !important; font-size: 0.78rem !important; }
}

@media screen and (max-height: 820px) {
    /* Header */
    .csulb-header        { padding: 8px 22px !important; }
    .csulb-header-logo   { font-size: 2.9rem  !important; }
    .csulb-header-title  { font-size: 1.8rem  !important; }
    .csulb-header-sub    { font-size: 0.95rem !important; }
    .csulb-header-lb-logo{ height: 56px !important; width: 56px !important; }
    /* Welcome */
    .welcome-state       { padding: 4px 20px 2px !important; }
    .welcome-state-icon  { font-size: 4.5rem  !important; margin-bottom: 8px !important; }
    .welcome-state-title { font-size: 1.45rem !important; margin-bottom: 6px !important; }
    .welcome-state-sub   { font-size: 0.98rem !important; margin-bottom: 10px !important; }
    /* Sidebar */
    .sidebar-brand       { padding: 6px 10px 6px !important; }
    .sidebar-brand-logo  { width: 210px !important; height: 210px !important; margin-bottom: 6px !important; }
    .sidebar-brand-name  { font-size: 1.4rem !important; white-space: normal !important; }
    .sidebar-brand-tag   { font-size: 0.88rem !important; padding: 4px 14px !important; margin-top: 4px !important; }
    .nav-item            { padding: 4px 7px !important; font-size: 0.75rem !important; }
    .nav-section-label   { font-size: 0.5rem !important; }
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────

def _init_state() -> None:
    defaults: dict = {
        "session_id":     str(uuid.uuid4()),
        "messages":       [],
        "last_response":  None,
        "nav_active":     "Ask Assistant",
        "backend_status": "unknown",
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

def _load_image_b64(filename: str) -> str:
    """Return a base64 data URI for any file in the static/ folder."""
    import base64
    static_dir = Path(__file__).parent / "static"
    path = static_dir / filename
    if not path.exists():
        return ""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _load_logo_b64() -> str:
    """
    Read the LB logo from static/lb_logo.png and return a base64 data URI.
    Returns an empty string if the file is missing (logo is simply hidden).
    """
    import base64
    # Look for any image file in static/ (supports renamed files)
    static_dir = Path(__file__).parent / "static"
    logo_path  = None
    for ext in ("png", "jpg", "jpeg", "webp", "gif"):
        candidate = static_dir / f"lb-circle.{ext}"
        if candidate.exists():
            logo_path = candidate
            break
    if logo_path is None:
        return ""
    mime = "image/png" if logo_path.suffix == ".png" else "image/jpeg"
    b64  = base64.b64encode(logo_path.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


def _render_header() -> None:
    sid      = st.session_state["session_id"]
    logo_src = _load_logo_b64()
    logo_tag = (
        f'<img src="{logo_src}" class="csulb-header-lb-logo" alt="CSULB LB Logo" />'
        if logo_src else ""
    )
    st.markdown(f"""
    <div class="csulb-header">
        <div class="csulb-header-logo">🎓</div>
        <div class="csulb-header-text">
            <div class="csulb-header-title">CSULB Graduate Center AI Assistant</div>
            <div class="csulb-header-sub">California State University, Long Beach</div>
        </div>
        {logo_tag}
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
        # Branding — use base64 LB logo; fall back to emoji if file missing
        logo_src = _load_logo_b64()
        logo_el  = (
            f'<img src="{logo_src}" class="sidebar-brand-logo" alt="CSULB LB Logo" />'
            if logo_src
            else '<span class="sidebar-brand-logo" style="font-size:6rem;display:block;">🎓</span>'
        )
        st.markdown(f"""
        <div class="sidebar-brand">
            {logo_el}
            <span class="sidebar-brand-name">CSULB Graduate Center</span>
            <span class="sidebar-brand-tag">AI Assistant</span>
        </div>
        """, unsafe_allow_html=True)


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

        # Elbee mascot above footer
        elbee_src = _load_image_b64("ES - Elbee Circle.png")
        if elbee_src:
            st.markdown(
                f'<div style="text-align:center;padding:10px 0 6px;">'
                f'<img src="{elbee_src}" alt="Elbee" '
                f'style="width:220px;height:220px;object-fit:contain;'
                f'border-radius:50%;box-shadow:0 3px 12px rgba(0,0,0,0.22);" />'
                f'</div>',
                unsafe_allow_html=True,
            )

        # Backend status — probe once on first load, cache in session state
        if st.session_state["backend_status"] == "unknown":
            try:
                _client.health()
                st.session_state["backend_status"] = "ok"
            except BackendError:
                st.session_state["backend_status"] = "unreachable"

        _bs = st.session_state["backend_status"]
        _bs_icon = "🟢" if _bs == "ok" else "🔴"
        st.caption(f"{_bs_icon} Backend: {_bs}")

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
    3: "#111111",   # program_requirements / eligibility
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
# Discovery / program recommendation panel
# ─────────────────────────────────────────────────────────────────────────────

_PROGRAM_NAMES: dict[str, str] = {
    "drph-public-health":                 "Doctor of Public Health (DrPH)",
    "dnp-nursing":                        "Doctor of Nursing Practice (DNP)",
    "dpt-physical-therapy":               "Doctor of Physical Therapy (DPT)",
    "edd-educational-leadership-cc":      "EdD — Educational Leadership (Community College)",
    "edd-educational-leadership-p12":     "EdD — Educational Leadership (P-12 Schools)",
    "phd-engineering-computational-math": "PhD — Engineering & Computational Mathematics",
}

_BEHAVIOR_LABELS: dict[str, str] = {
    "recommend":                 "Recommended Program",
    "multi_recommend":           "Recommended Programs",
    "partial_match_with_caveat": "Potential Match — Review Carefully",
    "clarify":                   "More Information Needed",
}

_CONF_COLORS: dict[str, str] = {
    "high":   "#16a34a",
    "medium": "#d97706",
    "low":    "#dc2626",
}

_SCORE_BASIS_LABELS: dict[str, str] = {
    "degree_type":     "Explicit degree type match",
    "orientation_match": "Orientation matches program focus",
}


def _readable_basis(factor: str) -> str:
    """Convert a raw score_basis token to a short human-readable phrase."""
    if factor.startswith("unique_career:"):
        tag = factor.split(":", 1)[1].replace("_", " ")
        return f"Career goal: {tag} (unique to this program)"
    if factor.startswith("shared_career:"):
        tag = factor.split(":", 1)[1].replace("_", " ")
        return f"Career goal: {tag}"
    if factor.startswith("interests_3plus:"):
        tags = factor.split(":", 1)[1].replace("_", " ")
        return f"3+ interest matches: {tags}"
    if factor.startswith("interests_2:"):
        tags = factor.split(":", 1)[1].replace("_", " ")
        return f"2 interest matches: {tags}"
    if factor.startswith("interest_1:"):
        tag = factor.split(":", 1)[1].replace("_", " ")
        return f"Interest: {tag}"
    if factor.startswith("background_2plus:"):
        tags = factor.split(":", 1)[1].replace("_", " ")
        return f"2+ background matches: {tags}"
    if factor.startswith("background_1:"):
        tag = factor.split(":", 1)[1].replace("_", " ")
        return f"Academic background: {tag}"
    if factor.startswith("orientation_match:"):
        orient = factor.split(":", 1)[1]
        return f"Orientation match: {orient}"
    if factor.startswith("orientation_mismatch:"):
        return "Orientation mismatch (penalty applied)"
    return _SCORE_BASIS_LABELS.get(factor, factor.replace("_", " "))


def _render_discovery_panel(response: dict) -> None:
    """
    Render Phase D program recommendation results for route='discovery'.
    Falls back silently when program_matches is absent (clarify / redirect paths).
    """
    program_matches = response.get("program_matches") or []
    behavior        = response.get("behavior", "")
    confidence      = response.get("confidence", "")

    # ── Clarify / no-match paths: nothing extra to render ─────────────────
    if not program_matches:
        return

    # ── Behavior label banner ──────────────────────────────────────────────
    label = _BEHAVIOR_LABELS.get(behavior, "Program Match")
    st.markdown(
        f'<div class="disc-behavior-banner">{label}</div>',
        unsafe_allow_html=True,
    )

    # ── Per-program cards ──────────────────────────────────────────────────
    for match in program_matches:
        prog_id    = match.get("program_id", "")
        conf       = match.get("confidence", confidence)
        email      = match.get("advisor_email", "")
        deadline   = match.get("deadline_fall", "")
        basis      = match.get("score_basis") or []
        prog_name  = _PROGRAM_NAMES.get(prog_id, prog_id.replace("-", " ").title())
        conf_color = _CONF_COLORS.get(conf, "#6b7280")

        # Card header
        email_html = (
            f'<a href="mailto:{email}">{email}</a>'
            if email else "—"
        )
        st.markdown(
            f'<div class="disc-program-card">'
            f'<div class="disc-program-name">{prog_name}</div>'
            f'<span class="disc-confidence-badge" style="color:{conf_color};border-color:{conf_color};">'
            f'Confidence: {conf.capitalize()}'
            f'</span>'
            f'<div class="disc-rows">'
            f'<div class="disc-row">'
            f'  <span class="disc-key">Advisor email</span>'
            f'  <span class="disc-val">{email_html}</span>'
            f'</div>'
            f'<div class="disc-row">'
            f'  <span class="disc-key">Fall deadline</span>'
            f'  <span class="disc-val">{deadline or "—"}</span>'
            f'</div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Score basis — collapsible
        if basis:
            readable = [_readable_basis(f) for f in basis]
            with st.expander("Why this program matched", expanded=False):
                for item in readable:
                    st.markdown(f"- {item}")

    # ── Caveat note for partial matches ───────────────────────────────────
    if behavior == "partial_match_with_caveat":
        st.markdown(
            '<p style="color:#d97706;font-size:.85rem;margin-top:4px;">'
            "⚠️ This is a potential match based on limited signal. "
            "Contact the program advisor to confirm fit before applying."
            "</p>",
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator response renderer
# ─────────────────────────────────────────────────────────────────────────────

def _render_response(response: dict) -> None:
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
    elif route == "guidance":
        st.markdown("### Step-by-Step Guidance")
        _render_guidance_panel(response.get("steps", []))
    elif route == "answer":
        st.markdown("### Answer"); _render_answer_panel(response)
    elif route == "discovery":
        _render_discovery_panel(response)

    if source:
        st.caption(f"Source: [{source}]({source})")


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
        try:
            response = _client.query(query, session_id=sid)
        except BackendError as exc:
            st.error(f"⚠️ {exc.message}")
            return

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
    with st.expander("🎓 Click here for Graduate Program Guidance - Explore programs, timelines & support", expanded=False):

        # ── Section 1: Inside header ──────────────────────────────────────────
        st.markdown(
            "<h4 style='"
            "margin:0 0 6px 0;"
            "color:var(--navy);"
            "font-size:1.25rem;"
            "font-weight:800;"
            "letter-spacing:-0.01em;"
            "'>🎓 Graduate Program Guidance</h4>"
            "<p style='"
            "color:#111111;"
            "font-size:0.97rem;"
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
    # JS for padding-fix + sidebar expand is injected inline via the
    # <img onerror> tag inside _render_header() — no iframe needed here.

    if not st.session_state["messages"]:
        _render_sample_questions()

    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"],
                             avatar="👤" if msg["role"] == "user" else "🎓"):
            if msg["role"] == "assistant" and "response" in msg:
                _render_response(msg["response"])
            else:
                st.markdown(msg["content"])

    if query := st.chat_input("Ask me anything about CSULB grad admissions…"):
        _submit_query(query)

    st.markdown("---")
    _render_program_interest_panel()
    _render_footer()


if __name__ == "__main__":
    main()

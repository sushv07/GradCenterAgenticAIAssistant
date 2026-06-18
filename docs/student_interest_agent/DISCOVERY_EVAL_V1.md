# Discovery Evaluation Framework — V1

**Phase:** A2d  
**Status:** Baseline design artifact — evaluation runner not yet implemented  
**Taxonomy version:** 1.0  
**Created:** 2026-06-16  
**Branch:** feature/student-interest-agent-foundation

---

## 1. Executive Summary

This document defines the evaluation framework for the Student Interest Journey Agent's discovery path. It establishes how the agent will be measured before any implementation begins, following evaluation-first development practice.

The framework covers six doctoral programs currently in `data/program_taxonomy.json`:

| Program ID | Program | Coverage |
|---|---|---|
| `drph-public-health` | Public Health (DrPH) | partial |
| `dnp-nursing` | Nursing (DNP) | partial |
| `dpt-physical-therapy` | Physical Therapy (DPT) | partial |
| `edd-educational-leadership-cc` | Ed Leadership — CC (Ed.D.) | partial |
| `edd-educational-leadership-p12` | Ed Leadership — P-12 (Ed.D.) | partial |
| `phd-engineering-computational-math` | Engineering & Comp. Math (PhD) | partial |

**50-case breakdown:**

| Category | Count | Purpose |
|---|---|---|
| clear_match | 20 | Validate single-program recommendation at correct confidence |
| multi_match | 10 | Validate multi-program surfacing and differentiation |
| ambiguous | 10 | Validate clarification trigger (do not recommend) |
| edge_case | 10 | Validate out-of-scope rejection, adjacent mismatches, failure modes |

**Key assumption challenges:**

- High confidence on a wrong recommendation is worse than low confidence on a correct one. Calibration is the primary signal, not raw accuracy.
- 50 cases is a minimum viable seed set, not a sufficient production set. The eval set must grow as real queries are logged.
- "Clear match" does not always mean returning one program — surfacing two programs with differentiation is sometimes the correct outcome.
- Engineering PhD has null `career_goal_tags`. Career-signal queries will not match this program. Three cases are marked `known_gap: true` and are expected to fail until the taxonomy gap is resolved.

---

## 2. Evaluation Philosophy

### P1 — Correctness over completeness

A wrong recommendation is worse than no recommendation. The agent should surface fewer programs with higher accuracy rather than hedging with all six. Precision is the primary quality signal; recall is secondary.

### P2 — Calibrated confidence, not maximized confidence

Stated confidence must correlate with actual accuracy. A high-confidence recommendation that is wrong is a calibration failure. Evaluation must measure calibration (does high confidence correlate with high accuracy?) not just accuracy.

### P3 — Safe ambiguity handling

When the agent cannot form a high-confidence recommendation, the correct behavior is to ask a clarifying question — not guess. Clarification is a success state, not a failure state. Evaluation must reward correct clarification decisions.

### P4 — Taxonomy boundary awareness

The agent must know what it does not know. When a query falls outside the taxonomy (masters, non-CSULB, unlisted fields), the agent must redirect rather than fabricate a match. Hallucinated recommendations are the most severe failure mode.

### P5 — Advisor accuracy is non-negotiable

Advisor contact information surfaced via a recommendation must be correct. Incorrect advisor data produces real-world harm (student contacts wrong person, misses deadline, loses trust). Advisor accuracy is evaluated separately and expected to be 100%.

### P6 — Eval cases document taxonomy gaps

Cases that are expected to fail (e.g., career-based Engineering queries) are explicitly marked `known_gap: true`. A case passing unexpectedly is as important to investigate as a case failing unexpectedly. The eval set is a living audit of taxonomy completeness.

### Success definition per behavior type

| Expected behavior | Success condition | Failure condition |
|---|---|---|
| `recommend` | Expected program in top-1 at expected confidence level | Wrong program at top-1, or correct program at inflated/deflated confidence |
| `multi_recommend` | All expected programs surfaced; differentiation language present | Only one of N expected programs surfaced |
| `clarify` | Clarifying question asked before any recommendation made | Recommendation made without sufficient signal (over-recommending) |
| `redirect` | Out-of-scope acknowledged; redirected to appropriate resource | Recommendation made for non-doctoral or non-CSULB program |
| `partial_match_with_caveat` | Nearest program surfaced at low confidence with explicit caveat and advisor handoff | High-confidence recommendation on weak adjacent match |

---

## 3. Evaluation Categories

### Category definitions

| Category | Definition | Expected behavior | Min cases |
|---|---|---|---|
| `clear_match` | Query maps unambiguously to one program via strong career, interest, or background signal | `recommend` at high or medium confidence | 20 |
| `multi_match` | Query maps to 2+ programs with equal or near-equal signal strength | `multi_recommend` with differentiation; may trigger clarification if confidence too low | 10 |
| `ambiguous` | Query lacks sufficient tag signal — vague, orientation-only, or domain-too-broad | `clarify` — no recommendation until additional signal gathered | 10 |
| `edge_case` | Out-of-scope, adjacent-field, conflicting signals, or unusual student situations | `redirect`, `partial_match_with_caveat`, or `clarify` depending on sub-type | 10 |

### Sub-categories

| Sub-category | Parent | Example trigger |
|---|---|---|
| `career_based` | clear_match | "I want to become a physical therapist" |
| `interest_based` | clear_match | "I'm passionate about health informatics" |
| `background_based` | clear_match | "I'm a BSN RN and want a doctoral degree" |
| `degree_explicit` | clear_match | "I want to get a DNP" |
| `ambiguous_specialization` | multi_match | "I want educational leadership" (CC vs. P-12) |
| `domain_overlap` | multi_match | "I want to lead a healthcare organization" |
| `vague` | ambiguous | "I want to help people" |
| `orientation_only` | ambiguous | "I want to do research" |
| `domain_too_broad` | ambiguous | "I'm interested in health" |
| `term_ambiguity` | ambiguous | "I want to be a doctor" |
| `out_of_scope_degree` | edge_case | "I want an MBA" |
| `out_of_scope_level` | edge_case | "I want a master's in engineering" |
| `taxonomy_gap` | edge_case | "I want to study quantum computing" |
| `conflicting_signals` | edge_case | "I'm interested in nursing AND engineering" |
| `adjacent_field` | edge_case | "I want to study computational biology" |

---

## 4. discovery_eval_cases Schema

### File structure

```json
{
  "_schema_version": "1.0",
  "_scope": "doctoral_discovery",
  "_taxonomy_version": "1.0",
  "_created": "2026-06-16",
  "_notes": "Evaluation cases for the Student Interest Journey Agent discovery path. Cases are ordered by category then case_id. Known-gap cases are flagged with known_gap: true and are expected to fail until taxonomy or agent work resolves the gap.",
  "cases": [ ... ]
}
```

### Per-case schema

```json
{
  "case_id": "DISC-001",
  "query": "I want to become a physical therapist.",
  "category": "clear_match",
  "sub_category": "career_based",
  "expected_programs": ["dpt-physical-therapy"],
  "expected_confidence": "high",
  "expected_behavior": "recommend",
  "expected_clarification": false,
  "match_basis": ["career_goal_tags"],
  "rationale": "physical_therapist career goal maps uniquely to DPT.",
  "notes": null,
  "known_gap": false,
  "gap_description": null,
  "taxonomy_fields_required": {
    "dpt-physical-therapy": ["career_goal_tags"]
  }
}
```

### Field definitions

| Field | Type | Allowed values | Purpose |
|---|---|---|---|
| `case_id` | string | DISC-NNN | Stable identifier for referencing in test reports |
| `query` | string | free text | The student query to evaluate against |
| `category` | enum | clear_match \| multi_match \| ambiguous \| edge_case | Primary case classification |
| `sub_category` | enum | see section 3 | Secondary classification for failure mode analysis |
| `expected_programs` | string[] | program_ids or [] | Programs the agent must surface; [] = none expected |
| `expected_confidence` | enum | high \| medium \| low \| none | Confidence level required for the recommendation |
| `expected_behavior` | enum | recommend \| multi_recommend \| clarify \| redirect \| partial_match_with_caveat | Required agent action |
| `expected_clarification` | bool | true \| false | Whether a clarifying question must precede any recommendation |
| `match_basis` | string[] | interest_tags \| career_goal_tags \| academic_background_tags \| degree_type \| program_name \| orientation | Which taxonomy fields drive the match |
| `rationale` | string | free text | Human-readable explanation of expected outcome |
| `notes` | string\|null | free text | Edge case notes, failure mode documentation |
| `known_gap` | bool | true \| false | True = case expected to fail until a specific gap is resolved |
| `gap_description` | string\|null | free text | Describes the gap; required when known_gap=true |
| `taxonomy_fields_required` | object | {program_id: [fields]} | Documents which taxonomy fields the case depends on |

---

## 5. 50-Case Evaluation Dataset

### Clear match cases (20)

| ID | Query | Expected program(s) | Confidence | Basis |
|---|---|---|---|---|
| DISC-001 | "I want to become a physical therapist." | dpt-physical-therapy | high | career_goal_tags: physical_therapist |
| DISC-002 | "I'm interested in rehabilitation science and biomechanics." | dpt-physical-therapy | high | interest_tags: rehabilitation, biomechanics |
| DISC-003 | "I'm a registered nurse and I want to become a family nurse practitioner." | dnp-nursing | high | career_goal_tags: nurse_practitioner + background: nursing |
| DISC-004 | "I want to advance my nursing career into a clinical leadership role." | dnp-nursing | high | career_goal_tags: clinical_leader + interest_tags: healthcare_leadership |
| DISC-005 | "I'm passionate about mental health nursing and want an advanced practice degree." | dnp-nursing | high | interest_tags: mental_health, nursing |
| DISC-006 | "I want to work in public health policy and global health initiatives." | drph-public-health | high | interest_tags: health_policy, global_health |
| DISC-007 | "I want to become a public health director or executive." | drph-public-health | high | career_goal_tags: public_health_leader |
| DISC-008 | "I'm interested in health informatics and community health programs." | drph-public-health | high | interest_tags: health_informatics, community_health |
| DISC-009 | "I want to become a school superintendent." | edd-educational-leadership-p12 | high | career_goal_tags: school_administrator |
| DISC-010 | "I want to lead K-12 school reform and improve education policy." | edd-educational-leadership-p12 | high | interest_tags: k12_education, school_reform, education_policy |
| DISC-011 | "I'm a school principal and I want to advance into district leadership." | edd-educational-leadership-p12 | high | career_goal_tags: school_administrator + background: education |
| DISC-012 | "I want to become a community college dean or vice president." | edd-educational-leadership-cc | high | career_goal_tags: college_administrator + interest_tags: community_college |
| DISC-013 | "I work in community college administration and want a doctorate in community college leadership." | edd-educational-leadership-cc | high | interest_tags: higher_education, institutional_leadership + explicit context |
| DISC-014 | "I'm interested in engineering research combined with mathematical modeling." | phd-engineering-computational-math | medium | interest_tags: engineering, computational_mathematics, applied_mathematics |
| DISC-015 | "I have an engineering background and want to pursue a research doctorate." | phd-engineering-computational-math | medium | background: engineering + orientation: research |
| DISC-016 | "I want to get a Doctor of Nursing Practice." | dnp-nursing | high | degree_type: DNP (explicit) |
| DISC-017 | "I want to apply for the DPT program at CSULB." | dpt-physical-therapy | high | program_name: DPT (explicit) |
| DISC-018 | "I want to work in pediatric care and become a nurse practitioner." | dnp-nursing | high | career_goal_tags: nurse_practitioner + interest_tags: pediatric_care |
| DISC-019 | "I'm passionate about improving student outcomes in urban public schools." | edd-educational-leadership-p12 | high | interest_tags: k12_education, school_reform (extracted from context) |
| DISC-020 | "I want to address health disparities in underserved communities." | drph-public-health | high | interest_tags: community_health, health_policy |

**Notes on DISC-014 and DISC-015:** Medium confidence (not high) because Engineering PhD has `career_goal_tags: null`. The agent can match on interest/background but cannot confirm career alignment. Advisor handoff is mandatory for these cases.

### Multi-match cases (10)

| ID | Query | Expected programs | Confidence | Behavior |
|---|---|---|---|---|
| DISC-021 | "I want to pursue educational leadership." | EdD-CC + EdD-P12 | medium | multi_recommend — differentiate CC vs. P-12 by sector |
| DISC-022 | "I want to become an educational leader in a school or institution." | EdD-CC + EdD-P12 | medium | multi_recommend — 'school' hints P-12, 'institution' hints CC |
| DISC-023 | "I work in education and want a doctoral degree to advance my career." | EdD-CC + EdD-P12 | medium | multi_recommend — education background, no sector signal |
| DISC-024 | "I want to lead a healthcare organization." | DrPH + DNP | medium | multi_recommend — public health org vs. clinical practice |
| DISC-025 | "I have a healthcare background and want a doctoral degree." | DrPH + DNP + DPT | low | clarify — 3 programs, no field distinction |
| DISC-026 | "I want to become a professor." ⚠ | DrPH + DNP + PhD-Engineering | medium | multi_recommend — **known_gap**: PhD Engineering invisible due to null career_goal_tags |
| DISC-027 | "I'm interested in healthcare and doing research." | DrPH + DNP + DPT | low | clarify — research + health = 3 programs |
| DISC-028 | "I want to advance in education and do research." | EdD-CC + EdD-P12 + PhD-Engineering | low | clarify — conflicting domain signals |
| DISC-029 | "I want a clinical doctoral degree in health." | DNP + DPT | medium | multi_recommend — clinical orientation, differentiate by background prereqs |
| DISC-030 | "I want to do research and advance my career in a health profession." | DrPH + DNP | low | clarify — research + health career without specificity |

### Ambiguous cases (10)

| ID | Query | Expected behavior | Clarification type |
|---|---|---|---|
| DISC-031 | "I want to help people." | clarify | field_exploration |
| DISC-032 | "I want to make a difference in society." | clarify | field_exploration |
| DISC-033 | "I want a doctoral degree." | clarify | field_exploration |
| DISC-034 | "I'm interested in leadership." | clarify | field_exploration — leadership spans 4 programs |
| DISC-035 | "I want to do research." ⚠ | clarify | orientation_only — **known_gap**: PhD Engineering is the only research doctoral program but career_goal_tags null prevents confident match |
| DISC-036 | "I'm interested in health." | clarify | domain_too_broad — spans DrPH + DNP + DPT |
| DISC-037 | "I want to advance my career." | clarify | vague |
| DISC-038 | "I want to work with students." | clarify | domain_too_broad — spans K-12, college, nursing, PT contexts |
| DISC-039 | "I want to be a doctor." | clarify | term_ambiguity — MD vs. clinical doctoral degree |
| DISC-040 | "I'm passionate about education." | clarify | domain_too_broad — teaching vs. Ed leadership vs. education research |

**Critical note on DISC-039:** "I want to be a doctor" is a high-frequency query. The agent must ask: "Are you interested in becoming a medical doctor (MD), or an advanced clinical/practice doctoral degree such as a Doctor of Nursing Practice (DNP) or Doctor of Physical Therapy (DPT)?" CSULB does not offer an MD program. Recommending DNP or DPT without this disambiguation damages trust.

### Edge cases (10)

| ID | Query | Expected behavior | Rationale |
|---|---|---|---|
| DISC-041 | "I want an MBA." | redirect | Masters degree, not doctoral. Redirect to CSULB MBA programs. |
| DISC-042 | "I want a master's degree in engineering." | redirect | Master's level, not doctoral. Redirect to graduate programs directory. |
| DISC-043 | "I want to study quantum computing and artificial intelligence." ⚠ | redirect | **known_gap**: quantum_computing not in vocabulary; AI rejected from interest_tags in A2c audit. Must NOT hallucinate a match. |
| DISC-044 | "I'm interested in both nursing and engineering." | clarify | Conflicting signals: clinical (DNP) vs. research (PhD Engineering). Acknowledge both; ask which direction. |
| DISC-045 | "I already have a PhD and want to continue my education." | clarify | Unusual background — second doctorate is rare. Flag and ask clarifying questions before entering discovery flow. |
| DISC-046 | "I want to go to USC for graduate school, not CSULB." | redirect | Explicit non-CSULB institution. Clarify agent scope. |
| DISC-047 | "What's the easiest doctoral program to get into?" | redirect | Admission-difficulty framing is not answerable from taxonomy. Redirect to fit-based discovery. |
| DISC-048 | "I want to study computational biology." | partial_match_with_caveat | Adjacent to computational_mathematics (Engineering PhD) but distinct field. Low confidence + explicit caveat + advisor handoff. |
| DISC-049 | "I want a clinical doctoral degree but I'm not sure which health profession." | multi_recommend | Clinical orientation → DNP + DPT. Present both with background prerequisites as differentiators. |
| DISC-050 | "I have an undergraduate degree in psychology and want to continue in healthcare." | partial_match_with_caveat | Psychology = social_sciences → DrPH (low confidence). DNP excluded (requires BSN+RN). Advisor handoff required. |

### Known-gap summary

Three cases are expected to fail until specified taxonomy work is completed:

| Case | Gap | Required fix |
|---|---|---|
| DISC-026 — "I want to become a professor" | Engineering PhD invisible to professor career queries | Populate `career_goal_tags` via Joint PhD Handbook or Dr. Janoyan outreach |
| DISC-035 — "I want to do research" | Orientation-only match too weak without career confirmation | `career_goal_tags` needed to confirm research_scientist/professor path |
| DISC-043 — "quantum computing and AI" | `ai` and `quantum_computing` not in interest_tags vocabulary | Vocabulary expansion or advisor redirect logic |

---

## 6. Clarification Strategy

### When to clarify vs. recommend

| Condition | Action | Threshold |
|---|---|---|
| No tag match across any program | Clarify | 0 matching tags total |
| Only orientation signal present (research/clinical/professional) with no field | Clarify | orientation only, 0 field tags |
| Max confidence across all programs < 0.40 | Clarify | < 0.40 max confidence |
| 3+ programs have equal confidence within 0.05 of each other | Clarify or multi_recommend with differentiation | confidence spread < 0.05 |
| Top program has career_goal_tags=null AND query is career-based | Partial match + advisor handoff | career query + null career_goal_tags |
| Query uses "doctor" without clinical context | Clarify — MD vs. clinical doctorate disambiguation | "doctor" with no other health-professional signal |

### Clarification question taxonomy — 5 types

- **Q1 — Field/domain exploration:** "What field or area are you most drawn to studying or working in?" Triggers when: no field tags match.
- **Q2 — Career goal exploration:** "What kind of role do you envision in your career in 5–10 years?" Triggers when: no career_goal_tags match and query is career-vague.
- **Q3 — Background verification:** "What is your current educational background and professional experience?" Triggers when: admission-gated programs (DNP requires BSN+RN; DPT requires pre-PT sciences) are candidates and background is unknown.
- **Q4 — Orientation clarification:** "Are you looking for a program focused on academic research, professional practice, or clinical work?" Triggers when: 2+ programs with different orientations are equally likely candidates.
- **Q5 — Term disambiguation:** "When you say [term], do you mean [interpretation A] or [interpretation B]?" Triggers when: "doctor", "leadership", "education" used in ways that span multiple distinct programs.

### Clarification stopping rule

Stop asking clarifying questions when: (1) at least one program reaches medium confidence or above, OR (2) at least 2 meaningful non-vague signals have been collected across turns, OR (3) the student explicitly names a program or degree type.

Never ask more than 3 clarifying questions before surfacing a recommendation or redirecting to the advisor. If 3 questions have not resolved ambiguity, surface the closest match at low confidence with an explicit advisor handoff.

---

## 7. Failure Modes

| Mode | Description | Example | Severity |
|---|---|---|---|
| `over_recommend` | Agent makes a recommendation when clarification should be requested | "I want to help people" → DrPH at high confidence | High |
| `hallucination` | Agent recommends a program not in the taxonomy, invents concentrations, or fabricates career outcomes | "I want to study computational neuroscience" → "CSULB offers a PhD in Computational Neuroscience" | Critical |
| `confidence_inflation` | Agent claims high confidence on a weak or inferred match | Single interest tag match reported as high confidence | High |
| `career_gap_invisibility` | Engineering PhD never surfaced for career-goal queries because career_goal_tags=null | "I want to become a research professor in engineering" → only DrPH returned | Medium |
| `clinical_bleed` | DNP recommended to a student who does not meet RN license requirement | "I want a clinical doctoral degree" (no nursing background) → DNP at high confidence | Medium |
| `edd_conflation` | Agent returns only one Ed.D. when query matches both, or returns wrong specialization | "I'm a school principal" → EdD-CC returned instead of EdD-P12 | Medium |
| `md_confusion` | Student asking to "become a doctor" receives clinical doctoral program without MD disambiguation | "I want to be a doctor" → DPT at high confidence | Medium |
| `advisor_mismatch` | Correct program recommended but wrong advisor contact surfaced | Engineering PhD recommended → DrPH advisor email returned | High |

---

## 8. Confidence Framework

### High confidence — threshold ≥ 0.85

**Conditions (any one sufficient):**
- Career goal tag exact match AND the career goal is unique to one program (e.g., `physical_therapist` → DPT only)
- Degree type explicitly named in query (e.g., "I want a DNP")
- Program name explicitly referenced
- 3+ interest/background tags match a single program with none matching other programs

**Production target:** Top-1 accuracy in high-confidence bucket must exceed 90%.

### Medium confidence — threshold 0.60–0.84

**Conditions (any one sufficient):**
- 2+ interest tags match, no career signal
- Career goal matches but is not unique across programs (e.g., `university_educator` appears in DrPH and DNP)
- Background + interest combination with no career goal signal
- Partial-coverage program (Engineering PhD) with interest_tags match but null career_goal_tags
- Multi-match scenario where two programs score within 0.10 of each other

**Production target:** Top-N recall (N = expected program count) must exceed 80%.

### Low confidence — threshold 0.40–0.59

**Conditions (any one sufficient):**
- Single interest tag match only
- Background match but no interest or career signal
- Orientation match without field signal
- Adjacent-field query (e.g., computational biology → Engineering PhD is nearest but not exact)

**Required behavior:** Always accompanied by explicit caveat language and advisor handoff. Never surfaced without a "contact the advisor to confirm fit" instruction.

### Clarify / none — threshold < 0.40

No recommendation made. Clarifying question required per section 6.

### Calibration requirement

Confidence levels must be evaluated for calibration, not just accuracy. Group eval cases by stated confidence bucket and measure per-bucket accuracy. Divergence > 0.15 between stated and actual accuracy is a calibration failure requiring agent tuning.

---

## 9. Metrics

### Core metrics

| Metric | Formula | Target | Scope |
|---|---|---|---|
| Top-1 Accuracy (T1A) | # cases where top rec = expected_programs[0] / # recommend cases | > 85% | clear_match |
| Top-N Recall (TNR) | # cases where all expected_programs in top N / # multi_match cases | > 80% | multi_match |
| Precision@K (P@K) | # expected programs in top K / K | > 0.75 at K=2 | multi_match + clear_match |
| Clarification Precision (CP) | # ambiguous cases correctly triggering clarify / # ambiguous cases | > 90% | ambiguous |
| False Recommendation Rate (FRR) | # ambiguous cases incorrectly receiving a recommendation / # ambiguous cases | < 10% | ambiguous |
| Out-of-Scope Detection (ODR) | # edge_case out-of-scope correctly rejected or redirected / # out-of-scope edge cases | > 95% | edge_case |
| Advisor Accuracy (AA) | # recommended programs with correct advisor contact / # recommended programs | 100% | all recommend |

### Composite eval score (CES)

```
CES = (T1A × 0.30) + (TNR × 0.20) + (CP × 0.20) + ((1-FRR) × 0.15) + (ODR × 0.10) + (AA × 0.05)
```

Weights reflect priority: correctness (T1A) > safe ambiguity (CP, FRR) > multi-program recall (TNR) > scope detection (ODR) > advisor accuracy (AA, deterministic so low weight).

**Target CES ≥ 0.80 for Phase B acceptance.**

Known-gap cases (DISC-026, DISC-035, DISC-043) are excluded from CES calculation but tracked separately.

### How to run evaluation

1. **Baseline run:** Run all 50 cases through the agent. Record: top recommendation, confidence, behavior type, advisor returned. Compare against expected values.
2. **Gap tracking run:** Run the 3 known_gap cases separately. Document actual vs. expected failure. If a known_gap case passes, investigate whether it passed correctly or by coincidence.
3. **Calibration check:** Group results by stated confidence bucket. Measure per-bucket T1A. Flag any bucket with calibration divergence > 15pp.
4. **Advisor spot-check:** For all recommend cases, verify advisor name, email, and phone match `data/program_taxonomy.json` exactly. Should be deterministic — 0 failures expected.

---

## 10. Readiness Verdict

**Verdict: proceed to Phase B.**

The doctoral taxonomy is sufficiently complete to begin Phase B structural work (JourneyState, DiscoveryResponse, Branch 1.5 router signals). Three specific Engineering PhD cases will be known failures — this is acceptable and documented.

### Phase B readiness checklist

| Criterion | Status | Evidence |
|---|---|---|
| 5/6 programs at partial coverage or better | Pass | DrPH, DNP, DPT, EdD-CC, EdD-P12, PhD-Engineering all partial as of 2026-06-17 |
| All programs have advisor + deadline data | Pass | Sourced from programs.json, confirmed in taxonomy |
| All programs have orientation confirmed | Pass | research / clinical / applied / professional all set |
| Evaluation framework designed before implementation | Pass | This document (Phase A2d) |
| Known taxonomy gaps documented | Pass | 3 known_gap cases; Engineering career_goal_tags gap documented |
| Schema stable at v1.0 | Pass | No breaking changes expected for Phase B |

### What Phase B must NOT attempt

Phase B is structural only. The recommendation scoring algorithm belongs in Phase D after the eval framework is wired to CI. Do not attempt recommendation matching for masters programs using the doctoral taxonomy — masters get graceful degradation via `generate_general_interest_response()`.

---

## 11. Phase B Scope

Phase B delivers three structural artifacts only. No recommendation logic.

### B1 — JourneyState TypedDict

**Location:** `contracts/journey_state.py`

Fields: `interests`, `orientation`, `degree_type`, `academic_background`, `work_experience`, `funding_priority`, `modality_pref`, `recommended_programs`, `phase`, `turn_count`, `last_question_asked`, `delegated_routes`

### B2 — DiscoveryResponse TypedDict

**Location:** `contracts/response_types.py` (extend existing file)

Fields: `session_id`, `recommended_programs` (list of program_ids), `confidence`, `behavior` (recommend/multi_recommend/clarify/redirect), `clarification_question` (nullable), `next_steps`

### B3 — Branch 1.5 discovery signals in router.py

**Location:** `routing/router.py`

New frozenset `_DISCOVERY_SIGNALS`: `"interested in"`, `"which program"`, `"help me choose"`, `"want to become"`, `"looking for a doctoral"`, `"what programs"`, `"recommend a program"`, `"career in"`, `"I want to study"`

Insert between Branch 1 (empty query) and Branch 2 (deadlines) in the priority chain. Returns `route="discovery"`.

### Deferred items

| Item | Phase | Dependency |
|---|---|---|
| `journey_agent.py` state machine | C | JourneyState (B1) |
| Gap identification and question selection logic | C | JourneyState (B1), eval cases (A2d) |
| Session persistence | C | JourneyState (B1) |
| Recommendation scoring algorithm | D | Journey agent (C), eval framework wired to CI |
| Doctoral-full recommendation (taxonomy-backed) | D | Phase C, eval baseline passing |
| Masters graceful fallback | D | Phase C |
| Engineering `career_goal_tags` enrichment | A2e / human curation | Joint PhD Handbook / Dr. Janoyan outreach |

---

*Baseline document — do not implement eval runner until Phase C is complete.*

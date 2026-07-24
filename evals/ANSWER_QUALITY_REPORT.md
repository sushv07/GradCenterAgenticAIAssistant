# Answer-Quality Evaluation — v1 baseline vs v2 candidate (Phase 10)

Deterministic property scoring over the answer-quality golden set (`evals/answer_quality_eval_cases.json`). No LLM, no embeddings, no network. `expect` thresholds are checked against the candidate answer.

## Summary

| metric | v1 baseline | v2 candidate |
| --- | --- | --- |
| cases | 8 | 8 |
| expectations passed | 0/8 | **8/8** |
| mean grounding rate | 0.5092 | 0.6667 |
| citation fidelity rate | 1.0 | 1.0 |
| hallucinated URLs (total) | 0 | 0 |
| mean length (chars) | 404.5 | 269.6 |
| mean repetition rate | 0.0607 | 0.0 |

## Per-case (candidate)

| case | category | grounding | fidelity | chars | repetition | passed |
| --- | --- | --- | --- | --- | --- | --- |
| AQ-001 | admissions | 1.0 | ok | 326 | 0.0 | yes |
| AQ-002 | eligibility | 1.0 | ok | 340 | 0.0 | yes |
| AQ-003 | deadlines | 1.0 | ok | 136 | 0.0 | yes |
| AQ-004 | program_specific | 1.0 | ok | 291 | 0.0 | yes |
| AQ-005 | advisor | 0.8 | ok | 128 | 0.0 | yes |
| AQ-006 | unknown | 0.0 | ok | 243 | 0.0 | yes |
| AQ-007 | ambiguous | 0.3333 | ok | 239 | 0.0 | yes |
| AQ-008 | deadlines | 0.2 | ok | 454 | 0.0 | yes |

## Candidate expectation failures

(none)

## Before/after examples

### AQ-001 — admissions: What do I need to submit to apply to the MPA program?

**v1 baseline** (grounding 0.5, 747 chars, repetition 0.0):

> Thank you for your interest in the Master of Public Administration program at the CSULB Graduate Center. The College of Health and Human Services offers this program and there are several things you will want to be aware of as you prepare your application materials. To apply to the MPA program you must submit a completed Cal State Apply application, you must submit official transcripts, you must s

**v2 candidate** (grounding 1.0, 326 chars, repetition 0.0):

> To apply to the MPA program, submit: - A completed Cal State Apply application - Official transcripts - A statement of purpose - Two letters of recommendation  A minimum cumulative GPA of 3.0 is required. Source: https://www.csulb.edu/college-of-health-human-services/public-policy-and-administration/admissions-to-our-program

### AQ-002 — eligibility: Who is eligible for the Emergency Services Administration master's?

**v1 baseline** (grounding 0.75, 422 chars, repetition 0.0):

> Eligibility for admission is an important consideration and there are a number of criteria that the program looks at when reviewing applicants. Eligible applicants hold a bachelor's degree from an accredited institution. Applicants should note that professional experience is valued. The main requirement is a bachelor's degree. See https://www.csulb.edu/college-of-health-human-services/emergency-se

**v2 candidate** (grounding 1.0, 340 chars, repetition 0.0):

> You are eligible for the Emergency Services Administration master's if you: - Hold a bachelor's degree from an accredited institution - Have a minimum 2.5 GPA in your last 60 units - Have professional experience in an emergency-services field  Source: https://www.csulb.edu/college-of-health-human-services/emergency-services-administration

### AQ-003 — deadlines: When is the Fall application deadline for the MBA?

**v1 baseline** (grounding 0.4, 414 chars, repetition 0.2):

> Deadlines are a very important part of the graduate application process and you will want to make sure you keep track of them carefully as you prepare your materials for submission. The Fall priority application deadline is March 1. You should apply by this date. The Fall priority application deadline is March 1. More information can be found at https://www.csulb.edu/cob-graduate-programs/applicat

**v2 candidate** (grounding 1.0, 136 chars, repetition 0.0):

> The Fall priority application deadline for the MBA is March 1. Source: https://www.csulb.edu/cob-graduate-programs/application-deadlines


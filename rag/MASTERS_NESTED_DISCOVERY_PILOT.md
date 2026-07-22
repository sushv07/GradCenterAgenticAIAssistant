# Master's Nested Page Discovery — Pilot Report

## Crawl statistics

- pilot programs: 5
- total unique pages: 29 (seed 5 · nested 24)
- avg pages per program: 7.6
- shared pages (>1 program): 4
- programs skipped (no seed): 0

## Pages by classification

- international_instructions: 7
- overview_only: 3
- program_requirements: 14
- supplemental_application: 5

## Per-program

### Linguistics (MA)
- seed: https://cla.csulb.edu/departments/linguistics/ma-program/
- reused shared seed: False
- pages accepted: 5 · max depth: 1
- classifications: {'supplemental_application': 1, 'program_requirements': 3, 'overview_only': 1}

### Business Administration (Evening MBA)
- seed: https://www.csulb.edu/cob-graduate-programs/mba-programs/evening-mba
- reused shared seed: False
- pages accepted: 14 · max depth: 1
- classifications: {'supplemental_application': 2, 'program_requirements': 5, 'international_instructions': 7}

### Public Administration (MPA)
- seed: https://www.csulb.edu/college-of-health-human-services/public-policy-and-administration
- reused shared seed: False
- pages accepted: 4 · max depth: 1
- classifications: {'supplemental_application': 1, 'program_requirements': 2, 'overview_only': 1}

### Museum Studies (MA)
- seed: https://www.csulb.edu/school-of-art/graduate-studies
- reused shared seed: False
- pages accepted: 10 · max depth: 1
- classifications: {'supplemental_application': 4, 'program_requirements': 6}

### Political Science (MA)
- seed: http://cla.csulb.edu/departments/polisci/master-of-arts/
- reused shared seed: False
- pages accepted: 5 · max depth: 1
- classifications: {'supplemental_application': 1, 'program_requirements': 3, 'overview_only': 1}

## Shared pages (crawled once, multiple programs)

- `https://www.csulb.edu/admissions` [supplemental_application] → ['Linguistics (MA)', 'Business Administration (Evening MBA)', 'Public Administration (MPA)', 'Museum Studies (MA)', 'Political Science (MA)']
- `http://www.ccpe.csulb.edu/international/?utm_source=website&utm_medium=homepage&utm_content=menulink&utm_campaign=JumboMenu` [program_requirements] → ['Linguistics (MA)', 'Public Administration (MPA)', 'Museum Studies (MA)', 'Political Science (MA)']
- `https://www.cpace.csulb.edu/courses/degree-programs/master-of-science-in-geographic-information-science` [program_requirements] → ['Linguistics (MA)', 'Political Science (MA)']
- `https://www.cpace.csulb.edu/courses/degree-programs/master-of-arts-in-international-affairs` [program_requirements] → ['Linguistics (MA)', 'Political Science (MA)']

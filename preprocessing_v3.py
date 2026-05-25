"""
preprocessing_v3.py — NLRB Company Name Preprocessing
======================================================

Changelog vs. preprocessing_v2.py (based on trace_weird_names.ipynb analysis):

1. SLASH → SPACE  (fixes 16,298 slash-collapse names)
   - Common slash abbreviations (a/k/a, f/k/a, c/o, d/b/a) are handled first.
   - Then remaining slashes are replaced with spaces, so "CVS/Pharmacy"
     becomes "cvs pharmacy" instead of "cvspharmacy".

2. TRIMMED STOP WORD LIST  (fixes ~5,200 weird names)
   - Removed descriptive words whose damage far exceeded their dedup value:
     center, service, services, division, div, department, facility,
     international, systems, america, usa, group, industries, industry,
     association, indiv, corporat.
   - Kept only legal suffixes (Inc, LLC, Corp, Co, Corporation, Company,
     Incorporated, Ltd) + "the" + "et al".

3. HYPHEN-SKIP GUARD on remaining stop words  (fixes hyphen-joined damage)
   - Stop words are no longer removed when they sit next to a hyphen.
   - "Co-op" keeps its "Co", "Inc.-MAT" keeps its "Inc.", etc.
   - Pattern: (?<!-)\\bword\\b\\.?(?!-)

4. ORPHAN-HYPHEN CLEANUP after digit removal  (fixes ~242 weird names)
   - After removing digit sequences, leftover leading/trailing hyphens
     and space-adjacent hyphens are cleaned up.

5. OCR LEADING-0 FIX  (fixes 4 names)
   - A leading "0" followed by an uppercase letter is replaced with "O"
     (e.g., "0VERTON" → "OVERTON") before lowercasing.

6. CASE-NUMBER PRE-FILTER  (utility function, not part of preprocess_employer)
   - filter_case_numbers() removes rows where company_name is actually
     an NLRB case number. Call this from your pipeline before preprocessing.

The embedding model (text-embedding-3-large) naturally handles variation
in descriptive words like "Services", "Center", "Division", so removing
them from the stop list does not significantly hurt blocking recall.
"""

import re
import unicodedata


# =============================================================================
# STOP WORDS — trimmed to legal suffixes + "the" + "et al"
# =============================================================================
# These are the only words with a favorable cost-benefit ratio (high dedup
# power relative to damage). Descriptive words (center, service, division,
# group, systems, etc.) are intentionally excluded — their removal caused
# far more damage than deduplication benefit per the trace_weird_names
# analysis (Section 17).
#
# DBA variants (d/b/a, dba, d.b.a., doing business as) are handled by
# dedicated regex patterns earlier in the pipeline, not as stop words.
# =============================================================================

stop_words = [
    # Legal suffixes
    "LLC", "LTD", "Inc", "Corp", "Co",
    "Corporation", "Company", "Incorporated",
    # Articles / misc
    "the",
    # Legal annotations
    "et al", "et al.",
]


def preprocess_employer(name):
    """
    Preprocess a company name for embedding-based entity resolution.

    The goal is to normalize formatting while preserving meaningful content.
    Aggressive removal is avoided — the embedding model handles semantic
    similarity for words like "Services", "Center", "Division".
    """

    # -----------------------------------------------------------------
    # OCR FIX: leading "0" that should be "O"
    # (must happen before lowercasing to detect the uppercase letter)
    # Examples: "0VERTON" → "OVERTON", "0Health" → "OHealth"
    # -----------------------------------------------------------------
    name = re.sub(r'^0([A-Z])', r'O\1', name)

    # -----------------------------------------------------------------
    # BASIC NORMALIZATION
    # -----------------------------------------------------------------
    name = name.lower()
    name = name.strip()
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ASCII')

    # -----------------------------------------------------------------
    # DBA REMOVAL — all variants, handled early before slash conversion
    # -----------------------------------------------------------------
    name = re.sub(r'\bd/b/a\b\.?\s*', ' ', name)    # d/b/a
    name = re.sub(r'\bd\.b\.a\.?\s*', ' ', name)     # d.b.a. / d.b.a
    name = re.sub(r'\bdba\b\.?\s*', ' ', name)        # dba
    name = re.sub(r'\bdoing\s+business\s+as\b', ' ', name)

    # -----------------------------------------------------------------
    # SLASH-BASED ABBREVIATIONS — handle before general slash→space
    # -----------------------------------------------------------------
    name = re.sub(r'\ba/k/a\b', 'aka', name)    # "also known as"
    name = re.sub(r'\bf/k/a\b', 'fka', name)    # "formerly known as"
    name = re.sub(r'\bn/k/a\b', 'nka', name)    # "now known as"
    name = re.sub(r'\bc/o\b', ' ', name)         # "care of" — remove

    # -----------------------------------------------------------------
    # SLASH → SPACE  (NEW in v3)
    # Prevents word concatenation: "CVS/Pharmacy" → "cvs pharmacy"
    # (not "cvspharmacy" as in v2)
    # -----------------------------------------------------------------
    name = name.replace('/', ' ')

    # -----------------------------------------------------------------
    # LOCAL + NUMBER REMOVAL
    # e.g., "Local 32BJ", "Local 166M", "Local 8A-28A", "Local # 6"
    # -----------------------------------------------------------------
    name = re.sub(
        r'\blocal\s*(?:no\.?\s*)?#?\s*\d+[a-z]*(?:\s*-\s*\d+[a-z]*)*',
        '', name, flags=re.IGNORECASE
    )

    # -----------------------------------------------------------------
    # "NO" + NUMBER REMOVAL  (e.g., "no 200", "No. 35")
    # -----------------------------------------------------------------
    name = re.sub(r'\bno\.?\s+\d+\b', '', name)

    # -----------------------------------------------------------------
    # DIGIT SEQUENCE REMOVAL
    # Removes sequences of 2+ digits (and hyphenated digit chains).
    # This collapses store numbers: "Safeway #590" and "Safeway #1007"
    # both become "safeway".
    # -----------------------------------------------------------------
    name = re.sub(r'(?:\b|-)\d{2,}(?:-\d+)*(?:\b|-)', ' ', name)

    # -----------------------------------------------------------------
    # ORPHAN-HYPHEN CLEANUP  (NEW in v3)
    # After digit removal, hyphens may be left dangling:
    #   "24-hour fitness" → " -hour fitness"
    #   "1-800-flowers"   → "1 -flowers"
    # Clean up hyphens at string boundaries and adjacent to spaces.
    # -----------------------------------------------------------------
    name = re.sub(r'^\s*-\s*', '', name)       # leading hyphen
    name = re.sub(r'\s*-\s*$', '', name)       # trailing hyphen
    name = re.sub(r'\s+-\s+', ' ', name)       # space-hyphen-space → space
    name = re.sub(r'\s+-(?=\S)', ' ', name)    # space-hyphen before word → space
    name = re.sub(r'(?<=\S)-\s+', ' ', name)   # hyphen-space after word → space

    # -----------------------------------------------------------------
    # CORPORATE TERM NORMALIZATION
    # Fixes malformed concatenations — does NOT remove words.
    # e.g., "healthservices" → "health", "corporationx" → "corporation"
    # -----------------------------------------------------------------
    safe_to_clean = [
        'corporation', 'incorporated', 'association', 'industries',
        'company', 'services', 'industry', 'group'
    ]

    for term in safe_to_clean:
        # 1. Garbage prefix (1 char) + term → just term
        name = re.sub(f'\\b[a-z]{term}\\b', term, name)
        # 2. Term + garbage suffix (1 char) → just term
        name = re.sub(f'\\b{term}[a-z0-9]\\b', term, name)
        # 3. Meaningful prefix (2+ chars) + term → just prefix
        name = re.sub(f'\\b([a-z]{{2,}}){term}\\b', r'\1', name)
        # 4. Term + meaningful suffix (2+ chars) → just suffix
        name = re.sub(f'\\b{term}([a-z]{{2,}})\\b', r'\1', name)
        # 5. Term + longer garbage suffix (2+ chars) → just term
        name = re.sub(f'\\b{term}[a-z0-9]{{2,}}\\b', term, name)

    # -----------------------------------------------------------------
    # STOP WORD REMOVAL — with hyphen-skip guard  (CHANGED in v3)
    #
    # The negative lookaround (?<!-) ... (?!\.-|-) prevents removal
    # when the stop word is hyphen-joined to adjacent text.
    #
    # The lookahead (?!\.-|-) checks for BOTH ".-" and bare "-" BEFORE
    # the optional period is consumed. This prevents the regex engine
    # from backtracking past the period: without this, "Inc.-West"
    # would match "Inc" alone (skipping the "."), see "." as non-hyphen,
    # and incorrectly remove "Inc".
    #
    # ✓ "Smith, Inc."       → "smith"            (removed — standalone)
    # ✓ "Smith Inc.-West"   → "smith inc.-west"  (kept — hyphen-joined)
    # ✓ "Co-op Markets"     → "co-op markets"    (kept — hyphen-joined)
    # ✓ "Smith Co."         → "smith"            (removed — standalone)
    # -----------------------------------------------------------------
    for word in stop_words:
        pattern = r'(?<!-)' + r'\b' + re.escape(word.lower()) + r'\b' + r'(?!\.-|-)' + r'\.?'
        name = re.sub(pattern, '', name)

    # -----------------------------------------------------------------
    # SYMBOL AND ABBREVIATION NORMALIZATION
    # -----------------------------------------------------------------
    name = name.replace('&', 'and')
    name = re.sub(r'\bbros?\b', 'brothers', name)

    # -----------------------------------------------------------------
    # PUNCTUATION REMOVAL
    # Keep hyphens (meaningful in company names) and apostrophes (removed next)
    # -----------------------------------------------------------------
    name = re.sub(r'[^\w\s\'-]', '', name)

    # Remove apostrophes
    name = re.sub(r"'", "", name)

    # -----------------------------------------------------------------
    # FINAL CLEANUP
    # -----------------------------------------------------------------
    name = re.sub(r'\s+', ' ', name).strip()

    return name


# =============================================================================
# CASE-NUMBER PRE-FILTER  (utility — call from your pipeline, not here)
# =============================================================================

def filter_case_numbers(df, column='company_name'):
    """
    Remove rows where the company_name is actually an NLRB case number.

    NLRB case numbers follow the pattern: DD-XX-DDDDDD
    (1–2 digits, hyphen, 2 letters, hyphen, digits)
    e.g., "12-CA-234392", "29-CA-097013"

    Call this in your pipeline BEFORE preprocessing:

        r_cases = filter_case_numbers(r_cases, column='company_name')
        c_cases = filter_case_numbers(c_cases, column='company_name')

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame containing company names.
    column : str
        Name of the column to check (default: 'company_name').

    Returns
    -------
    pd.DataFrame
        DataFrame with case-number rows removed.
    """
    case_pattern = r'^\d{1,2}-[A-Z]{2}-\d+$'
    mask = df[column].str.match(case_pattern, na=False)
    n_removed = mask.sum()
    if n_removed > 0:
        print(f"  filter_case_numbers: removed {n_removed} rows matching "
              f"NLRB case-number pattern from '{column}'")
    return df[~mask].copy()


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    test_cases = [
        # --- Slash handling (NEW in v3) ---
        ("CVS/Pharmacy",                         "cvs pharmacy"),
        ("Care/Control",                         "care control"),
        ("Quad/Graphics, Inc.",                  "quad graphics"),
        ("PRINCETON UNIVERSITY/PRINCETON PLASMA", "princeton university princeton plasma"),
        ("First Transit/Transdev",               "first transit transdev"),

        # --- Slash abbreviations preserved ---
        ("Care for the Homeless a/k/a Care Found Here",
         "care for homeless aka care found here"),
        ("Allegion f/k/a Stanley",               "allegion fka stanley"),
        ("Run For Something c/o Katz, LLC",      "run for something katz"),

        # --- DBA handling (moved to regex, before slash→space) ---
        ("Smith Inc. d/b/a Jones Store",         "smith jones store"),
        ("Smith Inc. DBA Jones Store",           "smith jones store"),
        ("Smith Inc. d.b.a. Jones Store",        "smith jones store"),
        ("Smith Inc. doing business as Jones",   "smith jones"),

        # --- Co- prefix preserved (hyphen guard) ---
        ("CO-OP MARKETS",                        "co-op markets"),
        ("Co-op School",                         "co-op school"),
        ("Co-Mo Electric Cooperative, Inc.",      "co-mo electric cooperative"),
        ("Co-Freight, Inc.",                     "co-freight"),
        ("Co-Builder Associates",                "co-builder associates"),

        # --- Other stop words preserved when hyphen-joined ---
        ("Knife River Corporation-North Central", "knife river corporation-north central"),
        ("ABM Services-West",                    "abm services-west"),
        ("24-Hour Fitness",                      "hour fitness"),
        ("CENTER-FOR ANIMAL CARE/CONTROL",       "center-for animal care control"),
        ("Systems-Tech, Inc.",                   "systems-tech"),
        ("SERVICE-LINK, INC.",                   "service-link"),
        ("USA-IT",                               "usa-it"),
        ("Aggregate Industries, Inc.-Grand Valley Division",
         "aggregate industries inc-grand valley division"),
        ("Bruckner Truck Sales Inc.-Okla",       "bruckner truck sales inc-okla"),
        ("Laidlaw Transit, Inc.-MAT-SU",         "laidlaw transit inc-mat-su"),
        ("ABM Lakeside Inc.-HDC Partners",       "abm lakeside inc-hdc partners"),
        ("Emerson & Cuming Inc.-Grace Composites",
         "emerson and cuming inc-grace composites"),

        # --- Stop words removed when standalone ---
        ("Smith, Inc.",                          "smith"),
        ("Jones Corporation",                    "jones"),
        ("Acme Company LLC",                     "acme"),
        ("The Big Store",                        "big store"),
        ("Doe et al.",                           "doe"),
        ("Smith Co.",                            "smith"),

        # --- Digit removal + orphan-hyphen cleanup ---
        ("1-800-FLOWERS",                        "1 flowers"),
        ("1-800-PACK-RAT, LLC",                  "1 pack-rat"),
        ("31-W Insulation Company, Inc.",         "w insulation"),
        ("Safeway Store #590",                   "safeway store"),
        ("Kroger Store No. 644",                 "kroger store"),

        # --- OCR leading-0 fix ---
        ("0VERTON, MOORE & ASSOCIATES, INC.",    "overton moore and associates"),
        ("0Health Care Services Group Inc.",      "ohealth care services group"),
        ("0Reliant Realty Services, Inc.",        "oreliant realty services"),

        # --- Bros → Brothers ---
        ("Smith Bros. Trucking",                 "smith brothers trucking"),

        # --- Local + number removal ---
        ("Teamsters Local 32BJ",                 "teamsters"),
        ("Local 166M workers",                   "workers"),

        # --- Corporate term normalization ---
        ("healthservices of america",            "health of america"),

        # --- Should NOT change much ---
        ("Walmart",                              "walmart"),
        ("Target",                               "target"),
        ("general motors",                       "general motors"),
    ]

    print("=" * 70)
    print("PREPROCESSING V3 SELF-TEST")
    print("=" * 70)

    passed = 0
    failed = 0

    for input_name, expected in test_cases:
        result = preprocess_employer(input_name)
        if result == expected:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL Input:    '{input_name}'")
            print(f"       Expected: '{expected}'")
            print(f"       Got:      '{result}'")
            print()

    print(f"\nResults: {passed} passed, {failed} failed out of {len(test_cases)} tests")
    if failed == 0:
        print("All tests passed!")
    else:
        print("\nNote: Some test expectations may need adjusting —")
        print("review FAIL cases to confirm whether the output or")
        print("the expected value is wrong.")

    # --- Comparison with v2 for key problem cases ---
    print("\n" + "=" * 70)
    print("KEY IMPROVEMENTS OVER V2")
    print("=" * 70)

    improvements = [
        ("CO-OP MARKETS",         "Co- prefix"),
        ("24-Hour Fitness",       "Digit + orphan hyphen"),
        ("1-800-FLOWERS",         "Digit + orphan hyphen"),
        ("CVS/Pharmacy",          "Slash → space"),
        ("CENTER-FOR ANIMAL CARE/CONTROL (HERNANDEZ)",  "Hyphen guard + slash"),
        ("Systems-Tech, Inc.",    "Hyphen guard"),
        ("0VERTON, MOORE & ASSOCIATES, INC.",  "OCR fix"),
        ("Knife River Corporation-North Central", "Hyphen guard"),
        ("SERVICE-LINK, INC.",    "Hyphen guard"),
        ("Aggregate Industries, Inc.-Grand Valley Division", "Hyphen guard (Inc.-)"),
        ("Bruckner Truck Sales Inc.-Okla",       "Hyphen guard (Inc.-)"),
        ("ABM Lakeside Inc.-HDC Partners",       "Hyphen guard (Inc.-)"),
    ]

    try:
        from preprocessing_v2 import preprocess_employer as v2_preprocess
        has_v2 = True
    except ImportError:
        has_v2 = False

    for name, fix_type in improvements:
        v3_result = preprocess_employer(name)
        line = f"  {name:<55} → v3: \"{v3_result}\""
        if has_v2:
            v2_result = v2_preprocess(name)
            if v2_result != v3_result:
                line += f"  (was v2: \"{v2_result}\")"
            else:
                line += f"  (same as v2)"
        print(line)
"""
Company Name Standardization for NLRB Entity Resolution
========================================================

For known high-frequency firms, this module replaces the ENTIRE preprocessed
name with a single canonical form. If a name contains any variant of a known
firm core, the whole string becomes just that firm's canonical name —
regardless of prefixes, suffixes, spelling, or abbreviation.

Example: ALL of these become "united states postal service":
  - "united states postal sacramento district"
  - "us postal south florida panddc"
  - "u s postal bulk mail"
  - "londonderry vermont united states post office"
  - "usps-jersey citynj"
  - "usps north metro pdandc"
  - "u s p s - post office"
  - "uspostal"
  - "united state postal"       (misspelling)
  - "untied states postal"      (misspelling)
  - "united postal pgh bulk mail cntr"  (truncated)

SELECTION CRITERIA (from name_core_discovery_simplified.ipynb)
-------------------------------------------------------------
1. HIGH FREQUENCY: Name core appears in >= 200 unique name strings.

2. HIGH COHESION: N-gram identifies a single entity, not an industry
   descriptor (e.g., "nursing home") or franchise brand (e.g., "holiday inn").

3. UNAMBIGUOUS: The name core does NOT appear as a substring inside a
   different company's name in the notebook samples. If it does (e.g.,
   "casella waste management" contains "waste management"), the firm is
   excluded entirely rather than handled with complex workarounds.

EXCLUDED AND WHY
----------------
- "nursing home" (2,039): Industry descriptor — many unrelated companies.
- "holiday inn" (512): Franchise — each entry is a different operator.
- "waste management" (483): "casella waste management" in notebook samples
    is a different company (Casella Waste Systems).
- "beverly enterprises" (414): Ownership changes (Beverly Healthcare,
    Golden Living) create ambiguity; needs further investigation.
- "allied waste" (221): "corvallis disposal allied waste of corvallis" in
    notebook samples shows the core embedded in another entity's name.
- "shop n save" (214): "roundys - pick n save" in notebook samples is a
    different chain.
- "coca cola" collapsing: Bottlers are often independent franchise operations.
    (Hyphen normalization "coca-cola" -> "coca cola" IS applied as a
    formatting fix, but the name is not collapsed to a single canonical form.)

EVIDENCE SOURCE
---------------
All evidence: name_core_discovery_simplified.ipynb, Steps 7, 9, 10.
"""

import re
from typing import List, Tuple


# =============================================================================
# FIRM DEFINITIONS
# =============================================================================
# Each firm has:
#   - canonical: the single string all variants are replaced with
#   - patterns: regex patterns that identify this firm (any match -> replace all)
#   - evidence: notebook data supporting inclusion
#
# If ANY pattern matches ANYWHERE in the name, the ENTIRE name is replaced
# with the canonical form.
# =============================================================================

FIRMS = [

    # =========================================================================
    # UNITED STATES POSTAL SERVICE
    # =========================================================================
    # Notebook evidence (Steps 7, 9, 10):
    #   "united states postal" — 2,150 names (Step 10, trigram)
    #   "us postal"            —   780 names (Step 10, bigram)
    #   "u s postal"           —   209 names (Step 9, search 'postal')
    #   "post office" with US  —   480 names (Step 10, bigram; filtered below)
    #
    # Additional variants found during blocking QA:
    #   "usps" abbreviation    — appears with location/facility suffixes
    #       e.g., "usps-jersey citynj", "usps posc", "usps north metro pdandc"
    #   "u s p s"              — spaced-out abbreviation
    #       e.g., "u s p s - post office"
    #   "uspostal"             — concatenated (no space between "us" and "postal")
    #       e.g., "uspostal"
    #   "united state postal"  — misspelling (missing trailing 's')
    #   "untied states postal" — misspelling (transposed 'n' and 'i')
    #   "united postal"        — truncated (dropped 'states')
    #       e.g., "united postal pgh bulk mail cntr"
    #       Safe because union names are already filtered by is_union_name.
    #
    # Largest entity family in the dataset. All variants refer to the
    # US Postal Service with location/facility suffixes or prefixes.
    # =========================================================================
    {
        "canonical": "united states postal service",
        "patterns": [
            # --- canonical and common expansions ---
            r'\bunited\s+states\s+postal\b',
            r'\bunites?\s+states\s+postal\b',
            r'\bus\s+postal\b',
            r'\bu\s+s\s+postal\b',
            r'\bunited\s+states\s+post\s+office\b',
            r'\bus\s+post\s+office\b',
            r'\bu\s+s\s+post\s+office\b',
            # --- abbreviation "USPS" and spaced variants ---
            r'\busps\b',
            r'\bu\s+s\s+p\s+s\b',
            # --- concatenated "uspostal" (no space) ---
            r'\buspostal\b',
            # --- misspellings found during blocking QA ---
            r'\bunited\s+state\s+postal\b',      # missing trailing 's'
            r'\buntied\s+states?\s+postal\b',     # transposed 'n' and 'i'
            # --- truncated "united postal" (dropped 'states') ---
            r'\bunited\s+postal\b',               # investigate_separation.py evidence
        ],
        "evidence": {
            "united states postal": 2150,
            "us postal": 780,
            "u s postal": 209,
        },
    },

    # =========================================================================
    # GENERAL MOTORS
    # =========================================================================
    # Notebook evidence (Step 10):
    #   "general motors" — 487 names
    #   Samples: "general motors powertrai", "general motors atc",
    #            "general motors parts operation"
    # =========================================================================
    {
        "canonical": "general motors",
        "patterns": [
            r'\bgeneral\s+motors?\b',
        ],
        "evidence": {
            "general motors": 487,
        },
    },

    # =========================================================================
    # KAISER PERMANENTE
    # =========================================================================
    # Notebook evidence (Step 9 — search_ngrams('kaiser')):
    #   "kaiser permanente"           — 265 names
    #   "kaiser foundation"           — 171 names
    #   "kaiser foundation hospitals" —  97 names
    #   "kaiser foundation health"    —  70 names
    #
    # "kaiser foundation" and "kaiser permanente" are the same integrated
    # healthcare system. Other Kaiser companies (e.g., Kaiser Aluminum) do
    # not match because the regex requires "permanente" or "foundation".
    # =========================================================================
    {
        "canonical": "kaiser permanente",
        "patterns": [
            r'\bkaiser\s+permanente\b',
            r'\bkaiser\s+foundation\b',
        ],
        "evidence": {
            "kaiser permanente": 265,
            "kaiser foundation": 171,
        },
    },

    # =========================================================================
    # FORD MOTOR
    # =========================================================================
    # Notebook evidence (Step 10):
    #   "ford motor" — 218 names
    #   Samples: "ford motor", "ford motor dist", "ford motor credit"
    # =========================================================================
    {
        "canonical": "ford motor",
        "patterns": [
            r'\bford\s+motors?\b',
        ],
        "evidence": {
            "ford motor": 218,
        },
    },

    # =========================================================================
    # AMERICAN RED CROSS
    # =========================================================================
    # Notebook evidence (Step 10):
    #   "american red cross" — 270 names (trigram)
    #   "american red"       — 306 names (bigram; ~36 extra = legal name variant)
    #   Samples: "american red cross", "american red cross blood midwest region"
    #
    # "American National Red Cross" is the official legal name.
    # =========================================================================
    {
        "canonical": "american red cross",
        "patterns": [
            r'\bamerican\s+(?:national\s+)?red\s+cross\b',
        ],
        "evidence": {
            "american red cross": 270,
            "american red (bigram)": 306,
        },
    },
]


# =============================================================================
# FORMATTING FIXES (applied before firm matching)
# =============================================================================
# These normalize formatting inconsistencies but do NOT collapse the name.
# Currently: coca-cola hyphen normalization only.
#
# Notebook evidence (Step 10):
#   "coca cola" — 257 names (no hyphen)
#   "coca-cola bottling" — 242 names (with hyphen)
# Bottlers may be independent franchises, so we only fix the hyphen.
# =============================================================================

FORMATTING_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'\bcoca[\s]*-[\s]*cola\b', re.IGNORECASE), 'coca cola'),
]


# =============================================================================
# COMPILE FIRM PATTERNS
# =============================================================================

_COMPILED_FIRMS = []
for firm in FIRMS:
    combined = '|'.join(firm["patterns"])
    _COMPILED_FIRMS.append((
        re.compile(combined, re.IGNORECASE),
        firm["canonical"],
    ))


# =============================================================================
# PUBLIC API
# =============================================================================

def standardize_company_name(preprocessed_name: str) -> str:
    """
    Standardize a preprocessed employer name.

    If the name contains any known firm core (in any spelling variant),
    the entire name is replaced with that firm's canonical form.

    Call AFTER preprocess_employer() and BEFORE embedding / LSH blocking.

    Parameters
    ----------
    preprocessed_name : str
        Output of preprocess_employer(raw_company_name).

    Returns
    -------
    str
        Standardized name.

    Examples
    --------
    >>> standardize_company_name("us postal south florida panddc")
    'united states postal service'
    >>> standardize_company_name("usps north metro pdandc")
    'united states postal service'
    >>> standardize_company_name("united state postal")
    'united states postal service'
    >>> standardize_company_name("united postal pgh bulk mail cntr")
    'united states postal service'
    >>> standardize_company_name("general motors powertrain")
    'general motors'
    >>> standardize_company_name("coca-cola bottling of wisconsin")
    'coca cola bottling of wisconsin'
    >>> standardize_company_name("casella waste management")
    'casella waste management'
    """
    if not preprocessed_name or not isinstance(preprocessed_name, str):
        return preprocessed_name

    result = preprocessed_name.strip()

    # Step 1: Formatting fixes (don't collapse, just normalize)
    for pattern, replacement in FORMATTING_RULES:
        result = pattern.sub(replacement, result)

    # Step 2: Firm matching — if any firm pattern matches, replace entire name
    for pattern, canonical in _COMPILED_FIRMS:
        if pattern.search(result):
            return canonical

    return result


def standardize_series(series):
    """Apply standardization to a pandas Series of preprocessed names."""
    return series.apply(standardize_company_name)


def get_evidence_table():
    """Return evidence as list of dicts for a paper appendix."""
    rows = []
    for firm in FIRMS:
        rows.append({
            "canonical_name": firm["canonical"],
            "n_variant_patterns": len(firm["patterns"]),
            "total_frequency": sum(firm["evidence"].values()),
            "notebook_entries": firm["evidence"],
        })
    return rows


def preview_standardization(names: list, max_show: int = 50) -> list:
    """Preview which names would change. Returns list of (original, new) tuples."""
    changes = []
    for name in names:
        standardized = standardize_company_name(name)
        if standardized != name:
            changes.append((name, standardized))

    print(f"Total names examined: {len(names):,}")
    print(f"Names changed: {len(changes):,} ({100*len(changes)/len(names):.1f}%)")
    print(f"\nSample changes (showing {min(max_show, len(changes))} of {len(changes):,}):")
    print("-" * 90)
    for orig, std in changes[:max_show]:
        print(f"  {orig}")
        print(f"  -> {std}")
        print()

    return changes


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    test_cases = [
        # --- USPS: all variants, with prefixes and suffixes ---
        ("united states postal",                          "united states postal service"),
        ("united states postal sacramento district",      "united states postal service"),
        ("united states postal - west station",           "united states postal service"),
        ("us postal south florida panddc",                "united states postal service"),
        ("u s postal bulk mail",                          "united states postal service"),
        ("united states post office",                     "united states postal service"),
        ("londonderry vermont united states post office",  "united states postal service"),
        # --- USPS: abbreviation and spaced variants ---
        ("usps jersey citynj",                            "united states postal service"),
        ("usps posc",                                     "united states postal service"),
        ("usps north metro pdandc",                       "united states postal service"),
        ("u s p s - post office",                         "united states postal service"),
        ("usps",                                          "united states postal service"),
        # --- USPS: concatenated ---
        ("uspostal",                                      "united states postal service"),
        # --- USPS: misspellings ---
        ("united state postal",                           "united states postal service"),
        ("untied states postal",                          "united states postal service"),
        ("untied state postal",                           "united states postal service"),
        # --- USPS: truncated "united postal" (dropped 'states') ---
        ("united postal pgh bulk mail cntr",              "united states postal service"),
        ("united postal",                                 "united states postal service"),

        # --- General Motors ---
        ("general motors",                "general motors"),
        ("general motors powertrai",      "general motors"),
        ("general motors atc",            "general motors"),
        ("general motors parts operation", "general motors"),

        # --- Kaiser Permanente (both naming patterns) ---
        ("kaiser permanente",                             "kaiser permanente"),
        ("kaiser foundation hospitals",                   "kaiser permanente"),
        ("kaiser foundation health plan",                 "kaiser permanente"),
        ("kaiser permanente - southern california",       "kaiser permanente"),
        ("maui health system a kaiser foundation hospitals", "kaiser permanente"),

        # --- Ford Motor ---
        ("ford motor",        "ford motor"),
        ("ford motor credit", "ford motor"),
        ("ford motor dist",   "ford motor"),

        # --- American Red Cross ---
        ("american red cross",                       "american red cross"),
        ("american national red cross",              "american red cross"),
        ("american red cross blood midwest region",  "american red cross"),

        # --- Coca-Cola: hyphen fix only, name NOT collapsed ---
        ("coca-cola bottling of wisconsin",  "coca cola bottling of wisconsin"),
        ("coca-cola lehigh valley",          "coca cola lehigh valley"),
        ("coca cola bottling",               "coca cola bottling"),

        # --- Should NOT change (different entities / descriptors) ---
        ("some random company",              "some random company"),
        ("nursing home of brooklyn",         "nursing home of brooklyn"),
        ("casella waste management",         "casella waste management"),
        ("post office pavilion joint venture", "post office pavilion joint venture"),
        ("kaiser aluminum",                  "kaiser aluminum"),
        ("pepsi cola bottling",              "pepsi cola bottling"),
        ("roundys - pick n save",            "roundys - pick n save"),
        ("waste management of washington",   "waste management of washington"),
        ("beverly enterprises",              "beverly enterprises"),
        ("bedford motors",                   "bedford motors"),
        ("united parcel service",             "united parcel service"),
    ]

    print("=" * 70)
    print("STANDARDIZATION SELF-TEST")
    print("=" * 70)

    passed = 0
    failed = 0

    for input_name, expected in test_cases:
        result = standardize_company_name(input_name)
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

    # Summary
    print("\n" + "=" * 70)
    print("FIRMS STANDARDIZED (5)")
    print("=" * 70)
    for firm in FIRMS:
        total = sum(firm["evidence"].values())
        variants = ", ".join(f"'{k}' ({v})" for k, v in firm["evidence"].items())
        print(f"\n  '{firm['canonical']}'")
        print(f"    Notebook evidence: {variants}")

    print("\n" + "=" * 70)
    print("FORMATTING FIXES (1)")
    print("=" * 70)
    print("  'coca-cola' -> 'coca cola' (hyphen normalization; no collapsing)")

    print("\n" + "=" * 70)
    print("EXCLUDED")
    print("=" * 70)
    print("  beverly enterprises (414) — ownership changes create ambiguity")
    print("  waste management (483) — 'casella waste management' is a different firm")
    print("  allied waste (221) — 'corvallis disposal allied waste...' is a different entity")
    print("  shop n save (214) — 'roundys - pick n save' is a different chain")
    print("  holiday inn (512) — franchise; each entry is an independent operator")
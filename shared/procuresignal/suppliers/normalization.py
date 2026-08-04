"""Name normalization for supplier resolution."""

import re

# Legal forms, normalized, stripped only from the end of a name.
#
# Deliberately excludes "group", "holding", and "holdings". Those are corporate
# descriptors rather than legal forms, and stripping them would derive the same alias
# for "Volkswagen Group" and "Volkswagen AG" — two different registrants, one of which
# would then be unregisterable.
LEGAL_FORMS = frozenset(
    {
        # German-speaking
        "ag",
        "gmbh",
        "mbh",
        "se",
        "kg",
        "kgaa",
        "ohg",
        "gbr",
        # United States
        "inc",
        "corp",
        "corporation",
        "co",
        "company",
        "llc",
        "lp",
        "llp",
        # United Kingdom and Ireland
        "ltd",
        "limited",
        "plc",
        # France, Spain, Portugal
        "sa",
        "sas",
        "sarl",
        "sca",
        "sl",
        "sau",
        # Low Countries
        "nv",
        "bv",
        "cv",
        # Italy
        "spa",
        "srl",
        "snc",
        # Nordics
        "ab",
        "as",
        "asa",
        "oy",
        "oyj",
        "aps",
        # Asia-Pacific
        "pty",
        "pte",
        "bhd",
        "sdn",
    }
)

# Longest legal form measured in tokens once punctuation has become whitespace:
# "S.p.A." normalizes to "s p a".
_MAXIMUM_FORM_TOKENS = 3

# Automatically derived aliases shorter than this are a guess not worth making. An
# operator can still add a short alias deliberately through the registry; this governs
# only what is generated without anyone asking for it.
MINIMUM_DERIVED_ALIAS_LENGTH = 3

_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize(name: str | None) -> str:
    """Lower-case, turn punctuation into spaces, collapse whitespace.

    Deliberately keeps the legal form: this produces `Supplier.normalized_name`, where
    the legal form is exactly what distinguishes one entity from another.
    """

    return _NON_WORD.sub(" ", (name or "").lower()).strip()


def strip_legal_form(normalized: str) -> str:
    """Remove trailing legal forms.

    Trailing only: "AG Barr" is a company name rather than a legal form followed by a
    word, so a leading match is left alone.

    Repeated, because "Co., Ltd." is the standard pairing across much of East Asia and
    shedding only one of the two leaves "foxconn technology co". Stripping stops before
    the name would disappear, so "Company Co" yields "company" rather than nothing.

    Punctuated forms arrive already split — "S.p.A." became "s p a" — so the last few
    tokens are also tried joined together, longest first.
    """

    parts = normalized.split()

    while True:
        for size in range(min(_MAXIMUM_FORM_TOKENS, len(parts) - 1), 0, -1):
            if "".join(parts[-size:]) in LEGAL_FORMS:
                parts = parts[:-size]
                break
        else:
            return " ".join(parts)


def alias_forms(canonical_name: str) -> list[str]:
    """Normalized spellings that should resolve to this supplier.

    Returns the canonical form, plus the legal-form-stripped variant when it differs and
    is long enough to be worth deriving.
    """

    canonical = normalize(canonical_name)
    if not canonical:
        return []

    forms = [canonical]

    stripped = strip_legal_form(canonical)
    if stripped != canonical and len(stripped) >= MINIMUM_DERIVED_ALIAS_LENGTH:
        forms.append(stripped)

    return forms

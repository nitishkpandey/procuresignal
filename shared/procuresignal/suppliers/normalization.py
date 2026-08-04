"""Name normalization for supplier resolution."""

import re
import unicodedata

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

# Anything that is not a letter or digit in any script becomes a separator. An
# ASCII-only class would delete the accented and non-Latin characters that European
# and sanctioned entity names are full of: "Škoda" became "koda", "Ørsted" became
# "rsted", and every one of those was a silently corrupted identity.
_NON_ALPHANUMERIC = re.compile(r"[\W_]+", re.UNICODE)

# Latin letters that carry no combining accent to strip, so NFD leaves them alone.
_UNDECOMPOSABLE = str.maketrans(
    {
        "ø": "o",
        "Ø": "o",
        "æ": "ae",
        "Æ": "ae",
        "œ": "oe",
        "Œ": "oe",
        "đ": "d",
        "Đ": "d",
        "ð": "d",
        "Ð": "d",
        "ł": "l",
        "Ł": "l",
        "þ": "th",
        "Þ": "th",
        "ħ": "h",
        "ı": "i",
        "ŋ": "n",
        "ĸ": "k",
    }
)


def normalize(name: str | None) -> str:
    """Case-fold, turn punctuation into spaces, collapse whitespace.

    NFKC first, so a full-width or ligature spelling does not become a second identity.
    Then case-folding rather than lower-casing, which is what handles "ß" against "ss".

    Accents are preserved: this produces `Supplier.normalized_name`, the precise
    identity. The accent-folded spelling becomes an alias instead.

    Deliberately keeps the legal form, which is what distinguishes one entity from
    another.
    """

    text = unicodedata.normalize("NFKC", name or "").casefold()
    return " ".join(_NON_ALPHANUMERIC.sub(" ", text).split())


def fold_accents(normalized: str) -> str:
    """Strip diacritics, so "Société" also answers to "Societe".

    News copy routinely drops them, and a buyer typing without the key should still
    reach their supplier. Used only to generate an extra alias, never for the canonical
    name, so it widens matching without merging companies that differ by more than an
    accent.
    """

    translated = normalized.translate(_UNDECOMPOSABLE)
    decomposed = unicodedata.normalize("NFD", translated)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(unicodedata.normalize("NFC", stripped).split())


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

    # Accent-folded spellings, added only when they differ from what is already there.
    for form in list(forms):
        folded = fold_accents(form)
        if folded != form and len(folded) >= MINIMUM_DERIVED_ALIAS_LENGTH:
            forms.append(folded)

    return forms

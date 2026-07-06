_SYNONYMS = {
    "jumper": "hoodie",
    "sweater": "hoodie",
    "sweatshirt": "hoodie",
    "pullover": "hoodie",
    "t-shirt": "tee",
    "tshirt": "tee",
    "shirt": "tee",
    "bag": "tote",
}


def singularize(s):
    s = s.strip().lower()
    return s[:-1] if s.endswith("s") and not s.endswith("ss") else s


def name_matches(query_name, candidate_name):
    q = singularize(query_name)
    c = singularize(candidate_name)
    if q in c or c in q:
        return True
    canonical = _SYNONYMS.get(q)
    return canonical is not None and canonical in c

def singularize(s):
    s = s.strip().lower()
    return s[:-1] if s.endswith("s") and not s.endswith("ss") else s


def name_matches(query_name, candidate_name):
    q = singularize(query_name)
    c = singularize(candidate_name)
    return q in c or c in q

"""The scoring model and the merge rules, on made-up comparison data with a known answer."""
import numpy as np
import pandas as pd

from halden.identity import matching, resolve


def simulated_pairs(n=20_000, share=0.3, seed=1):
    """Comparison levels drawn from known m and u, so EM has a right answer to find."""
    rng = np.random.default_rng(seed)
    is_match = rng.random(n) < share
    m = {f: np.r_[np.full(k - 1, 0.1 / (k - 1)), 0.9] for f, k in matching.N_LEVELS.items()}
    u = {f: np.r_[0.9, np.full(k - 1, 0.1 / (k - 1))] for f, k in matching.N_LEVELS.items()}
    df = pd.DataFrame({f: np.where(is_match, rng.choice(k, n, p=m[f]), rng.choice(k, n, p=u[f])).astype(float)
                       for f, k in matching.N_LEVELS.items()})
    # Training blocks: every pair in a block agrees on that block's fields.
    df["found_by"] = np.where(df["phone"] == 1, "phone", "")
    nc = (df["last_name"] == 3) & (df["first_name"] == 3) & (df["city"] == 1)
    df.loc[nc, "found_by"] = df.loc[nc, "found_by"] + ",name_city"
    return df, is_match, m, u


def test_em_recovers_the_match_rate_and_m():
    df, is_match, m_true, u = simulated_pairs()
    m, lam = matching.fit_em(df, u)
    assert abs(lam - is_match.mean()) < 0.02
    for f in matching.N_LEVELS:
        assert abs(m[f][-1] - m_true[f][-1]) < 0.05, f


def _pair(**levels):
    base = {f: 0.0 for f in matching.N_LEVELS}
    base.update(levels)
    return pd.DataFrame([{"left_id": "C1", "right_id": "C2", **base, "match_probability": 0.9999,
                          "match_weight": 20.0}])


def test_name_and_town_alone_never_merge():
    p = _pair(last_name=3, first_name=3, city=1)
    assert resolve.decide(p).iloc[0] == "review"


def test_shared_phone_with_high_probability_merges():
    assert resolve.decide(_pair(phone=1, last_name=3, first_name=3)).iloc[0] == "merge"


def test_same_home_counts_as_strong_but_initial_does_not():
    assert resolve.decide(_pair(street=2, postcode=1, first_name=3)).iloc[0] == "merge"
    assert resolve.decide(_pair(street=2, postcode=1, first_name=1)).iloc[0] == "review"


def test_missing_field_is_not_agreement():
    p = _pair(last_name=3, first_name=3)
    p["phone"] = np.nan
    assert resolve.decide(p).iloc[0] == "review"


def test_clusters_are_transitive_and_respect_legacy_ids():
    acc = pd.DataFrame({"customer_id": ["C1", "C2", "C3", "C4", "C5"],
                        "legacy_id": ["L1", None, None, "L2", None]})
    scored = pd.DataFrame({"left_id": ["C1", "C2", "C3", "C1"], "right_id": ["C2", "C3", "C4", "C5"],
                           "match_weight": [30, 25, 10, 20], "decision": ["merge", "merge", "merge", "no"]})
    persons, blocked = resolve.cluster(acc, scored)
    key = dict(zip(persons["customer_id"], persons["person_key"]))
    assert key["C1"] == key["C2"] == key["C3"] == "C1"   # A=B, B=C, so A=C
    assert key["C4"] == "C4" and blocked == 1             # would join two legacy IDs: the weakest link is cut
    assert key["C5"] == "C5"


def test_review_decisions_override_the_model():
    acc = pd.DataFrame({"customer_id": ["C1", "C2", "C3", "C4"], "legacy_id": [None] * 4})
    scored = pd.DataFrame({"left_id": ["C1", "C2"], "right_id": ["C2", "C3"], "match_weight": [30.0, 25.0],
                           "match_probability": [1.0, 1.0], "found_by": ["phone", "phone"],
                           "decision": ["merge", "merge"]})
    reviews = pd.DataFrame({"left_id": ["C3", "C4"], "right_id": ["C1", "C1"], "decision": ["different", "same"]})
    reviews = reviews.assign(left_id=reviews[["left_id", "right_id"]].min(axis=1),
                             right_id=reviews[["left_id", "right_id"]].max(axis=1))
    out, different = resolve.apply_review(scored, reviews)
    persons, blocked = resolve.cluster(acc, out, different)
    key = dict(zip(persons["customer_id"], persons["person_key"]))
    # C1-C3 is "different", so the chain C1=C2=C3 must break at its weaker link, C2-C3.
    assert key["C1"] == key["C2"] == key["C4"] and key["C3"] != key["C1"] and blocked == 1


def test_review_file_rejects_unknown_decisions(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("# comment\nleft_id,right_id,decision\nC2,C1,maybe\n")
    import pytest
    with pytest.raises(ValueError, match="same' or 'different"):
        resolve.load_review_decisions(p)
    p.write_text("left_id,right_id,decision\nC2,C1,same\n")
    d = resolve.load_review_decisions(p)
    assert (d.loc[0, "left_id"], d.loc[0, "right_id"]) == ("C1", "C2")

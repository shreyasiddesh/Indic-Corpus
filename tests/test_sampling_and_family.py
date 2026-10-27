import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from indic_corpus.config import Config  # noqa: E402
from indic_corpus.dedup import NearDedup, shingle_ids, tokenize  # noqa: E402
from indic_corpus.evalset import EvalCandidates  # noqa: E402
from indic_corpus.stage1 import sampled_in  # noqa: E402


def test_sampling_is_deterministic_and_close_to_fraction():
    ids = [f"doc{i}" for i in range(20000)]
    a = [sampled_in(i, 0.05) for i in ids]
    assert a == [sampled_in(i, 0.05) for i in ids]
    assert 0.04 < sum(a) / len(a) < 0.06


def test_family_members_are_excluded_from_eval_candidates():
    cfg = Config()
    base = "यह गाँव उत्तराखण्ड राज्य के अन्तर्गत गढ़वाल मण्डल के पौड़ी जिले का एक गाँव है जो तहसील में स्थित है और यहाँ की जनसंख्या बहुत कम है " * 2
    nd = NearDedup(0.99, cfg.num_perm, cfg.minhash_seed, cfg.pair_log_min)
    nd.query_and_add("a", shingle_ids(tokenize(base + " राम"), 5))
    nd.query_and_add("b", shingle_ids(tokenize(base + " श्याम"), 5))
    nd.query_and_add("c", shingle_ids(tokenize("बिल्कुल अलग लेख जिसमें कोई समान वाक्य नहीं है और यह काफी लम्बा है " * 3), 5))
    assert nd.family == {"a", "b"}
    cands = EvalCandidates(cfg)
    for i in "abc":
        cands.offer(i, "hi", "s", "शब्द " * 60 + i)
    assert cands.exclude(nd.family) == 2
    assert [d for _, d, _, _ in cands.ordered("hi")] == ["c"]

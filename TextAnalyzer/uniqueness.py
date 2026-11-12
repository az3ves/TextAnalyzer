import re
from collections import Counter

import config
from errors import TextTooShortError
from text_utils import cosine, prose_sentences

SHINGLE_LEN = config.SHINGLE_LEN


def tokens(text, name):
    return re.findall(r"\w+", " ".join(prose_sentences(text, name)).lower())


def shingles(words, name):
    if len(words) < SHINGLE_LEN:
        raise TextTooShortError(f"{name}: для проверки нужно хотя бы "
                                f"{SHINGLE_LEN} слова, а их {len(words)}.")
    count = len(words) - SHINGLE_LEN + 1
    return {tuple(words[i:i + SHINGLE_LEN]) for i in range(count)}


def check(text, reference):
    words = tokens(text, "Проверяемый текст")
    ref_words = tokens(reference, "Эталонный текст")
    mine = shingles(words, "Проверяемый текст")
    ref = shingles(ref_words, "Эталонный текст")

    common = mine & ref
    borrowed = len(common) / len(mine)    # доля наших шинглов, найденных в эталоне

    counts, ref_counts = Counter(words), Counter(ref_words)
    vocab = sorted(set(counts) | set(ref_counts))
    topic = cosine([counts[w] for w in vocab], [ref_counts[w] for w in vocab])

    return {"uniqueness": round((1 - borrowed) * 100, 1),
            "shingles": len(mine), "common": len(common),
            "topic_similarity": round(topic, 3)}

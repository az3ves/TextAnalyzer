from collections import Counter

import config
from errors import NotATextError, TextTooShortError
from text_utils import cosine, find_words, prose_sentences

STOP_WORDS = ("и в не на я что он с как а это по но они к у мы из за вы так же "
              "от для о его все бы то да только мне было вот меня ли если уже или "
              "когда до при без ни нет был ты быть чтобы даже").split()
PUNCTUATION = ',.;:-—()«»"!?'

MIN_WORDS = config.STYLO_MIN_WORDS
RELIABLE_WORDS = config.STYLO_RELIABLE_WORDS
SAME_AUTHOR = config.STYLO_SAME
UNSURE = config.STYLO_UNSURE


def build_profile(text, name):
    sentences = prose_sentences(text, name)
    prose = " ".join(sentences)
    words = [w.lower() for w in find_words(prose)]
    n = len(words)
    if n < MIN_WORDS:
        raise TextTooShortError(
            f"{name}: для стилометрии нужно хотя бы {MIN_WORDS} слов, а их {n}.")

    counts = Counter(words)
    stop_freq = [counts[w] / n for w in STOP_WORDS]
    punct_freq = [prose.count(p) / len(prose) for p in PUNCTUATION]
    vector = stop_freq + punct_freq
    if not any(vector):
        raise NotATextError(f"{name}: нет ни служебных слов, ни знаков препинания.")

    sample = words[:1000]    # TTR зависит от длины, поэтому берём первые 1000 слов
    return {"words": n,
            "ttr": round(len(set(sample)) / len(sample), 3),
            "avg_word": round(sum(map(len, words)) / n, 2),
            "avg_sentence": round(n / len(sentences), 2),
            "vector": vector}


def compare(profile_a, profile_b):
    similarity = cosine(profile_a["vector"], profile_b["vector"])
    if similarity >= SAME_AUTHOR:
        verdict = "высокое сходство профилей стиля"
    elif similarity >= UNSURE:
        verdict = "вывод неоднозначен"
    else:
        verdict = "низкое сходство профилей стиля"
    shortest = min(profile_a["words"], profile_b["words"])
    return {"similarity": round(similarity, 3), "verdict": verdict,
            "reliable": shortest >= RELIABLE_WORDS}

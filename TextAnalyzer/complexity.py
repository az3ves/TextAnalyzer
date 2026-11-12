import math

from text_utils import find_words, prose_sentences

VOWELS = set("аеёиоуыэюяaeiouy")


def count_syllables(word):
    return sum(ch in VOWELS for ch in word.lower())


def describe_level(fre):
    if fre >= 90:
        return "очень лёгкий"
    if fre >= 60:
        return "лёгкий / средний"
    if fre >= 30:
        return "сложный"
    return "очень сложный"


def analyze(text):
    sentences = prose_sentences(text)
    words = find_words(" ".join(sentences))
    s = len(sentences)
    w = len(words)
    syllables = [count_syllables(word) for word in words]
    letters = sum(ch.isalpha() for word in words for ch in word)
    polysyllabic = sum(1 for n in syllables if n >= 3)

    asl = w / s                   # слов в предложении
    asw = sum(syllables) / w      # слогов в слове

    fre = 206.835 - 1.3 * asl - 60.1 * asw
    fkgl = 0.5 * asl + 8.4 * asw - 15.59
    smog = 1.043 * math.sqrt(polysyllabic * 30 / s) + 3.1291
    cli = 0.0588 * (letters / w * 100) - 0.296 * (s / w * 100) - 15.8

    return {"sentences": s, "words": w,
            "fre": round(fre, 1), "fkgl": round(fkgl, 1),
            "smog": round(smog, 1), "cli": round(cli, 1),
            "level": describe_level(fre)}

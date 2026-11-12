import re
import threading
from functools import lru_cache
from bisect import bisect_right

import config
from errors import DependencyError

PATTERNS = {kind: re.compile(rx) for kind, rx in {
    "EMAIL": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "PHONE": r"(?<!\d)(?:\+7|8)[ ()-]*\d{3}[ ()-]*\d{3}[ -]*\d{2}[ -]*\d{2}(?!\d)",
    "SNILS": r"(?<!\d)\d{3}-\d{3}-\d{3}[ -]\d{2}(?!\d)",
    "PASSPORT": r"(?<!\d)\d{2} ?\d{2} ?\d{6}(?!\d)",
    "CARD": r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)",
}.items()}

LABELS = {"EMAIL": "[EMAIL]", "PHONE": "[ТЕЛЕФОН]", "SNILS": "[СНИЛС]",
          "PASSPORT": "[ПАСПОРТ]", "CARD": "[КАРТА]", "FIO": "[ФИО]"}

HIDDEN = re.compile("[\u200b-\u200d\u2060\ufeff\u202a-\u202e\u2066-\u2069]")
ODD_SPACES = re.compile("[\u00a0\u2000-\u200a\u202f\u205f\u3000]")

CHUNK_SIZE = config.CHUNK_SIZE
NER_LOCK = threading.RLock()


@lru_cache(maxsize=1)
def ner_tools():
    # Морфологический анализатор MorphVocab (pymorphy2) для NER не требуется.
    from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter
    return Doc, Segmenter(), NewsNERTagger(NewsEmbedding())


def luhn_ok(number):
    digits = [int(c) for c in number if c.isdigit()]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def snils_ok(number):
    d = [int(c) for c in number if c.isdigit()]
    total = sum(v * (9 - i) for i, v in enumerate(d[:9]))
    control = total % 101
    if control == 100:
        control = 0
    return control == d[9] * 10 + d[10]


def split_chunks(text):
    """Режет текст на куски до CHUNK_SIZE символов по границам строк, а если
    строка длиннее — по пробелам. Возвращает пары (смещение, кусок)."""
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        if end < len(text):
            cut = text.rfind("\n", start, end)
            if cut <= start:
                cut = text.rfind(" ", start, end)
            if cut > start:
                end = cut
        yield start, text[start:end]
        if end == len(text):
            break
        start = max(start + 1, end - 100)  # перекрытие: имя на границе фрагментов


def find_names(text):
    names = set()
    try:
        with NER_LOCK:
            Doc, segmenter, tagger = ner_tools()
            for offset, chunk in split_chunks(text):
                doc = Doc(chunk)
                doc.segment(segmenter)
                doc.tag_ner(tagger)
                names.update((offset + s.start, offset + s.stop)
                             for s in doc.spans if s.type == "PER")
    except Exception as error:
        raise DependencyError("Поиск ФИО недоступен: не удалось запустить Natasha. "
                              "Проверьте установку requirements.txt. Остальные типы данных проверены.") from error
    return sorted(names)


def scan_pii(text, warnings=None):
    spans = {}
    for kind, pattern in PATTERNS.items():
        for m in pattern.finditer(text):
            if kind == "CARD" and not luhn_ok(m.group()):
                continue
            if kind == "SNILS" and not snils_ok(m.group()):
                continue
            spans[(m.start(), m.end())] = kind
    try:
        for start, end in find_names(text):
            spans[(start, end)] = "FIO"
    except DependencyError as error:
        if warnings is None:
            raise
        warnings.append(str(error))

    findings, last_end = [], 0
    # сначала те, что начинаются раньше; при равном начале — более длинная
    newlines = [m.start() for m in re.finditer("\n", text)]
    ordered = sorted(spans.items(), key=lambda s: (s[0][0], -s[0][1]))
    for (start, end), kind in ordered:
        if start < last_end:      # пересекается с уже принятой находкой
            continue
        findings.append({
            "id": len(findings) + 1, "type": kind, "value": text[start:end],
            "start": start, "end": end,
            "line": bisect_right(newlines, start) + 1,
            "context": text[max(start - 25, 0):end + 25].replace("\n", " ")})
        last_end = end
    return findings


def find_hidden(text):
    found = []
    newlines = [m.start() for m in re.finditer("\n", text)]
    kinds = (("скрытый символ", HIDDEN), ("необычный пробел", ODD_SPACES))
    for kind, pattern in kinds:
        for m in pattern.finditer(text):
            found.append({"kind": kind, "code": f"U+{ord(m.group()):04X}",
                          "position": m.start(),
                          "line": bisect_right(newlines, m.start()) + 1})
    return sorted(found, key=lambda f: f["position"])


def analyze(text):
    warnings = []
    findings = scan_pii(text, warnings)
    return {"findings": findings, "hidden": find_hidden(text), "warnings": warnings}


def sanitize(text, findings, excluded):
    """Заменяет находки метками с конца текста, чтобы позиции не сдвигались."""
    for f in sorted(findings, key=lambda f: f["start"], reverse=True):
        if f["id"] not in excluded:
            text = text[:f["start"]] + LABELS[f["type"]] + text[f["end"]:]
    return text


def remove_hidden(text):
    return ODD_SPACES.sub(" ", HIDDEN.sub("", text))

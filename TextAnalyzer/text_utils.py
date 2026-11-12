import math
import re

from errors import EmptyTextError, NotATextError

WORD = re.compile(r"[А-Яа-яЁёA-Za-z]+(?:-[А-Яа-яЁёA-Za-z]+)*")

# Сокращения, после которых точка не заканчивает предложение
ABBREVIATIONS = re.compile(
    r"(?<!\w)(?:т\. ?д|т\. ?п|т\. ?е|т\. ?к|см|рис|стр|ул|им|г)\.", re.IGNORECASE)

SENTENCE_END = re.compile(r"[.!?…][»\"')\]]*$")
DOT_LEADERS = re.compile(r"\.{4,}|…{2,}")
STRUCTURE = re.compile(r"^(?:#{1,6}\s|[-*+•]\s|\d+[.)]\s|```|[|])")
MIN_LETTER_SHARE = 0.6        # доля букв в строке, чтобы считать её предложением
MIN_TEXT_LETTER_SHARE = 0.5   # доля букв во всём тексте


def find_words(text):
    return WORD.findall(text)


def split_sentences(text):
    """Делит один абзац на предложения; фрагменты без слов отбрасываются."""
    protected = ABBREVIATIONS.sub(lambda m: m.group().replace(".", "\x00"), text)
    # Кавычки после точки принадлежат предыдущему предложению.
    parts = re.split(r"(?<=[.!?…])\s+|(?<=[.!?…][»\"')\]])\s+", protected)
    sentences = [p.replace("\x00", ".") for p in parts]
    return [s for s in sentences if WORD.search(s)]


def split_blocks(text):
    """Делит текст на строки-блоки. Если строка оборвана переносом (следующая
    начинается с маленькой буквы), она склеивается со следующей. Строка после
    «;» или «:» с маленькой буквы — пункт списка, он остаётся отдельным."""
    blocks = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if STRUCTURE.search(line) or "\t" in line or " | " in line:
            blocks.append(line)
        elif (blocks and line[0].islower() and not STRUCTURE.search(blocks[-1])
              and blocks[-1].endswith((";", ":"))):
            blocks.append(line.rstrip(".") + ";")    # пункт списка, не предложение
        elif (blocks and line[0].islower()
                and not SENTENCE_END.search(blocks[-1])
                and not STRUCTURE.search(blocks[-1]) and "\t" not in blocks[-1]):
            blocks[-1] += " " + line                 # перенос внутри предложения
        else:
            blocks.append(line)
    return blocks


def is_prose(block):
    """Связный текст: блок кончается точкой, ! или ? и в нём в основном буквы.
    Заголовки, строки оглавления, пункты списков, подписи, таблицы и код
    под это не подходят."""
    if (not SENTENCE_END.search(block) or DOT_LEADERS.search(block)
            or STRUCTURE.search(block) or "\t" in block or " | " in block):
        return False
    chars = [c for c in block if not c.isspace()]
    return sum(c.isalpha() for c in chars) / len(chars) >= MIN_LETTER_SHARE


def skipped_blocks(text):
    return [b for b in split_blocks(text) if not is_prose(b)]


def prose_sentences(text, name="Текст"):
    sentences = [s for block in split_blocks(text) if is_prose(block)
                 for s in split_sentences(block)]
    if not sentences:
        raise NotATextError(
            f"{name}: нет ни одного законченного предложения. Строки без точки "
            "в конце считаются заголовками, оглавлением, таблицей или кодом.")
    return sentences


def check_text(text):
    """Проверка при отправке: текст не пустой, это не куча символов и в нём
    есть хотя бы одно законченное предложение."""
    if not text.strip():
        raise EmptyTextError("Поле пустое. Вставьте текст или добавьте файл.")
    chars = [c for c in text if not c.isspace()]
    share = sum(c.isalpha() for c in chars) / len(chars)
    if share < MIN_TEXT_LETTER_SHARE:
        raise NotATextError(
            f"Это больше похоже на набор символов: букв только {share:.0%}. "
            "Для проверки нужен обычный текст.")
    prose_sentences(text)


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)

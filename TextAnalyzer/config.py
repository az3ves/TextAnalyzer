import os
import shutil
from pathlib import Path

# Сервер (на хостинге порт и адрес приходят из переменных окружения)
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "5000"))

# Хранилище истории
DB_PATH = os.getenv("TEXTANALYZER_DB", os.path.join(
    Path(__file__).resolve().parent, "instance", "history.db"))
HISTORY_LIMIT = 50           # записей истории на одного пользователя

# Ввод
MAX_FILE_MB = 20
MAX_CHARS = 2_000_000
OCR_LANGS = os.getenv("OCR_LANGS", "rus+eng")
TESSERACT_PATH = os.getenv("TESSERACT_PATH", shutil.which("tesseract") or (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe" if os.name == "nt"
    else "tesseract"))

# Уникальность и стилометрия
SHINGLE_LEN = 4
STYLO_SAME, STYLO_UNSURE = 0.90, 0.80
STYLO_MIN_WORDS = 50         # меньше — профиль строить нельзя
STYLO_RELIABLE_WORDS = 500   # меньше — результат ненадёжен

# Безопасность
CHUNK_SIZE = 10000           # Natasha получает текст кусками по стольку символов

# Проверка в интернете
SEARCH_MODE = os.getenv("SEARCH_MODE", "manual")  # manual — без API и серверных запросов
SEARCH_URL = os.getenv("SEARCH_URL", "https://html.duckduckgo.com/html/")
SEARCH_TIMEOUT = 10          # секунд на один запрос
SEARCH_PAUSE = 1.0           # пауза между запросами, чтобы не вызвать блокировку
SEARCH_LINES = 6             # сколько предложений искать из разных частей текста
LINE_MIN_WORDS = 8           # короче строки для поиска не берутся
QUERY_WORDS = 12             # сколько первых слов строки уходит в запрос
MATCH_WORDS = 6              # сколько слов подряд должно совпасть со сниппетом

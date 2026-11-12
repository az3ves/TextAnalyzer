import uuid
import re
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

import complexity
import config
import plagiarism
import readers
import security
import storage
import stylometry
import text_utils
import uniqueness
from errors import (InvalidChoiceError, NothingToCompareError, TextAnalyzerError,
                    TextTooLongError)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = (config.MAX_FILE_MB + 1) * 1024 * 1024


def run_security(text, reference):
    return security.analyze(text)


def run_stylometry(text, reference):
    a = stylometry.build_profile(text, "Проверяемый текст")
    b = stylometry.build_profile(reference, "Второй текст")
    result = stylometry.compare(a, b)
    for key, profile in (("first", a), ("second", b)):
        result[key] = {k: v for k, v in profile.items() if k != "vector"}
    return result


CHECKS = {
    "complexity": lambda text, reference: complexity.analyze(text),
    "uniqueness": lambda text, reference: uniqueness.check(text, reference),
    "plagiarism": lambda text, reference: plagiarism.check(text),
    "stylometry": run_stylometry,
    "security": run_security,
}
NEED_REFERENCE = ("uniqueness", "stylometry")


def error_body(error):
    return {"title": error.title, "message": str(error), "level": error.level}


def run_check(name, text, reference):
    """Результат одной проверки. Ошибка проверки не мешает остальным."""
    try:
        if name in NEED_REFERENCE and not reference.strip():
            raise NothingToCompareError(
                "Для этой проверки нужен второй текст. Вставьте его или добавьте файл.")
        if name in NEED_REFERENCE:
            text_utils.check_text(reference)
        return {"status": "ok", "data": CHECKS[name](text, reference)}
    except TextAnalyzerError as e:
        return {"status": "error", "error": error_body(e)}
    except Exception:
        app.logger.exception("Сбой проверки %s", name)
        return {"status": "error", "error": {
            "title": "Проверка не выполнена", "level": "error",
            "message": "Внутренняя ошибка этой проверки. Остальные результаты доступны."}}


def load_entry(entry_id):
    entry = storage.get(g.owner, entry_id)
    if entry is None:
        raise InvalidChoiceError("Такой записи нет в истории.")
    return entry


@app.before_request
def identify_owner():
    g.owner = request.cookies.get("owner")
    g.new_owner = not bool(re.fullmatch(r"[0-9a-f]{32}", g.owner or ""))
    if g.new_owner:
        g.owner = uuid.uuid4().hex
    if request.method in ("POST", "DELETE") and request.headers.get("Origin"):
        if urlsplit(request.headers["Origin"]).netloc != request.host:
            return jsonify(error={"title": "Запрос отклонён", "level": "error",
                                  "message": "Откройте приложение в отдельной вкладке."}), 403


@app.after_request
def remember_owner(response):
    if getattr(g, "new_owner", False):
        response.set_cookie("owner", g.owner, max_age=365 * 24 * 3600,
                            httponly=True, samesite="Lax", secure=request.is_secure)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
    return response


@app.errorhandler(TextAnalyzerError)
def handle_error(error):
    return jsonify(error=error_body(error)), 400


@app.errorhandler(413)
def handle_too_large(_):
    return handle_error(TextTooLongError(f"Файл больше {config.MAX_FILE_MB} МБ."))


@app.errorhandler(HTTPException)
def handle_http(error):
    return jsonify(error={"title": "Некорректный запрос", "level": "error",
                          "message": "Проверьте адрес, формат и размер запроса."}), error.code


@app.errorhandler(Exception)
def handle_unexpected(error):
    app.logger.exception("Необработанная ошибка запроса")
    return jsonify(error={"title": "Ошибка программы", "level": "error",
                          "message": "Не удалось выполнить запрос. Повторите позже."}), 500


def json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise InvalidChoiceError("Ожидается JSON-объект с параметрами запроса.")
    return body


def text_field(body, key, default=None):
    value = body.get(key, default)
    if not isinstance(value, str):
        raise InvalidChoiceError("Поле текста должно содержать строку.")
    if len(value) > config.MAX_CHARS:
        raise TextTooLongError(f"В тексте больше {config.MAX_CHARS:,} символов.")
    return value


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/history")
def history():
    return jsonify(storage.listing(g.owner))


@app.delete("/api/history")
def clear_history():
    storage.clear(g.owner)
    return jsonify(ok=True)


@app.post("/api/extract")
def extract():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise InvalidChoiceError("Файл не выбран.")
    return jsonify(text=readers.read_file(upload.filename, upload.read()))


@app.post("/api/texts")
def submit_text():
    text = text_field(json_body(), "text")
    text_utils.check_text(text)
    skipped = text_utils.skipped_blocks(text)
    sentences = text_utils.prose_sentences(text)
    return jsonify(
        id=storage.add(g.owner, text),
        sentences=len(sentences),
        words=len(text_utils.find_words(" ".join(sentences))),
        skipped=len(skipped),
        skipped_examples=[b[:60] for b in skipped[:3]], skipped_blocks=skipped)


@app.get("/api/texts/<int:entry_id>")
def open_entry(entry_id):
    entry = load_entry(entry_id)
    entry["skipped_blocks"] = text_utils.skipped_blocks(entry["text"])
    return jsonify(entry)


@app.delete("/api/texts/<int:entry_id>")
def delete_entry(entry_id):
    load_entry(entry_id)
    storage.delete(g.owner, entry_id)
    return jsonify(ok=True)


@app.post("/api/texts/<int:entry_id>/check")
def check_entry(entry_id):
    entry = load_entry(entry_id)
    body = json_body()
    names = body.get("checks")
    if (not isinstance(names, list) or not names or len(names) > len(CHECKS)
            or any(not isinstance(n, str) or n not in CHECKS for n in names)):
        raise InvalidChoiceError("Выберите хотя бы одну проверку из списка.")
    reference = text_field(body, "reference", "")
    results = {name: run_check(name, entry["text"], reference) for name in dict.fromkeys(names)}
    storage.save_results(g.owner, entry_id, results)
    return jsonify(results)


@app.post("/api/texts/<int:entry_id>/sanitize")
def sanitize_entry(entry_id):
    entry = load_entry(entry_id)
    body = json_body()
    saved = entry["results"].get("security", {})
    if saved.get("status") != "ok":
        raise InvalidChoiceError("Сначала выполните проверку безопасности.")
    findings = saved["data"]["findings"]
    known = {f["id"] for f in findings}
    excluded = body.get("excluded", [])
    if (not isinstance(excluded, list) or any(type(i) is not int for i in excluded)
            or type(body.get("remove_hidden", False)) is not bool):
        raise InvalidChoiceError("Некорректные параметры очистки.")
    excluded = set(excluded)
    if not excluded <= known:
        raise InvalidChoiceError("Такой находки нет в списке.")
    text = security.sanitize(entry["text"], findings, excluded)
    if body.get("remove_hidden", False):
        text = security.remove_hidden(text)
    return jsonify(text=text)

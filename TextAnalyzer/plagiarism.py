"""Поиск совпадений в HTML-выдаче DuckDuckGo. Это выборочная проверка сниппетов."""
import time
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

import config
from errors import NoInternetError, SearchError, TextTooShortError
from text_utils import find_words, prose_sentences

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TextAnalyzer/1.0)"}


def real_url(href):
    if href.startswith("//"):
        href = "https:" + href
    target = parse_qs(urlparse(href).query).get("uddg")
    url = target[0] if target else href
    parsed = urlparse(url)
    return url if parsed.scheme in ("http", "https") and parsed.hostname else None


def parse_results(page):
    soup = BeautifulSoup(page, "html.parser")
    if soup.select_one(".anomaly-modal, form[action*='anomaly']") or "bots use DuckDuckGo too" in soup.get_text():
        raise SearchError("Поисковик запросил CAPTCHA. Проверка не выполнена; повторите позже.")
    results = []
    seen = set()
    for link in soup.select("a.result__a, a.result-link"):
        url = real_url(link.get("href", ""))
        parent = link.find_parent(class_="result")
        if parent:
            snippet = parent.select_one(".result__snippet")
        else:  # lite.duckduckgo.com: сниппет лежит в следующей строке таблицы
            row = link.find_parent("tr")
            next_row = row.find_next_sibling("tr") if row else None
            snippet = next_row.select_one(".result-snippet") if next_row else None
        if url and snippet is not None and url not in seen:
            seen.add(url)
            results.append({"url": url, "title": link.get_text(" ", strip=True),
                            "snippet": snippet.get_text(" ", strip=True)})
    if not results and not soup.select_one(".no-results, .no-results__message"):
        raise SearchError("Не удалось разобрать выдачу. Поисковик мог изменить страницу "
                          "или ограничить запросы; это не означает отсутствие совпадений.")
    return results


def search(query):
    try:
        response = requests.get(config.SEARCH_URL, params={"q": query},
                                headers=HEADERS, timeout=config.SEARCH_TIMEOUT)
    except requests.Timeout as error:
        raise SearchError(f"Поисковик не ответил за {config.SEARCH_TIMEOUT} с.") from error
    except requests.ConnectionError as error:
        raise NoInternetError("Не удалось подключиться к поисковику. Возможны отсутствие сети "
                              "или блокировка соединения. Остальные проверки работают без сети.") from error
    except requests.RequestException as error:
        raise SearchError("Ошибка сетевого запроса к поисковику.") from error
    if response.status_code != 200:
        raise SearchError(f"Поисковик ответил кодом {response.status_code}. "
                          "Проверка не выполнена. Повторите позже.")
    return parse_results(response.text)


def normalize(text):
    return [w.casefold().replace("ё", "е") for w in find_words(text)]


def matches(line_words, snippet):
    n = config.MATCH_WORDS
    snippet_words = normalize(snippet)
    fragments = {tuple(snippet_words[i:i + n]) for i in range(len(snippet_words) - n + 1)}
    return any(tuple(line_words[i:i + n]) in fragments for i in range(len(line_words) - n + 1))


def pick_lines(sentences):
    # Стабильная выборка равномерно по тексту: повторы не отнимают поисковые запросы.
    candidates = list(dict.fromkeys(s for s in sentences
                                   if len(find_words(s)) >= config.LINE_MIN_WORDS))
    if not candidates:
        raise TextTooShortError(f"Для поиска нужны предложения не короче {config.LINE_MIN_WORDS} слов.")
    count = min(config.SEARCH_LINES, len(candidates))
    return [candidates[round(i * (len(candidates) - 1) / max(count - 1, 1))] for i in range(count)]


def check(text):
    lines = pick_lines(prose_sentences(text))
    if config.SEARCH_MODE == "manual":
        return {"mode": "manual", "checked": 0, "requested": len(lines),
                "found": None, "failed": 0, "found_percent": None,
                "lines": [{"line": line, "found": None, "sources": []} for line in lines]}
    report = []
    for i, line in enumerate(lines):
        if i:
            time.sleep(config.SEARCH_PAUSE)
        # Поиск нечувствителен к регистру; такой же запрос получает локальный тестовый сервер.
        query = '"' + " ".join(normalize(line)[:config.QUERY_WORDS]) + '"'
        try:
            sources = [{"title": r["title"], "url": r["url"]}
                       for r in search(query) if matches(normalize(line), r["snippet"])]
            report.append({"line": line, "found": bool(sources), "sources": sources})
        except (NoInternetError, SearchError) as error:
            report.append({"line": line, "found": None, "sources": [], "error": str(error)})
    checked = sum(r["found"] is not None for r in report)
    found = sum(r["found"] is True for r in report)
    return {"checked": checked, "requested": len(report), "failed": len(report) - checked,
            "found": found, "found_percent": round(found / checked * 100) if checked else None,
            "lines": report}

const $ = (id) => document.getElementById(id);
const textBox = $("text"), refBox = $("reference");
let current = null;   // id открытой записи истории
let busy = false;

function changedText() {
  current = null;
  $("choose").hidden = true;
  $("results").replaceChildren();
  updateCounter();
  document.querySelectorAll("#history li").forEach(li => li.classList.remove("active"));
}

function displayDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ru-RU");
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function alertBox(level, title, message) {
  const box = el("div", "alert " + level);
  box.append(el("b", "", title), el("span", "", message));
  return box;
}

function showAlert(error) {
  $("alerts").replaceChildren(alertBox(error.level, error.title, error.message));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function api(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw { level: "error", title: "Нет связи с программой",
            message: "Сервер не отвечает. Проверьте, что программа запущена." };
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw (data && data.error) || { level: "error", title: "Ошибка программы",
                                    message: "Что-то пошло не так на сервере." };
  }
  return data;
}

function postJson(url, body) {
  return api(url, { method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(body) });
}

async function guarded(button, action) {
  if (busy) return;
  busy = true;
  const controls = [...document.querySelectorAll("button, input, textarea")];
  controls.forEach(control => { control.disabled = true; });
  $("busy-status").hidden = false;
  document.querySelector("main").setAttribute("aria-busy", "true");
  try {
    await action();
  } catch (error) {
    showAlert(error);
  } finally {
    busy = false;
    controls.forEach(control => { control.disabled = false; });
    $("busy-status").hidden = true;
    document.querySelector("main").removeAttribute("aria-busy");
  }
}

/* ---------- ввод текста и файлов ---------- */

function updateCounter() {
  $("counter").textContent = textBox.value.length.toLocaleString("ru") + " символов";
}
textBox.addEventListener("input", changedText);

function attachFile(input, target) {
  input.addEventListener("change", async () => {
    const file = input.files[0];
    input.value = "";
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    await guarded(input, async () => {
      target.value = (await api("/api/extract", { method: "POST", body: form })).text;
      $("alerts").replaceChildren();
      if (target === textBox) changedText();
      updateCounter();
    });
  });
}
attachFile($("file"), textBox);
attachFile($("ref-file"), refBox);

$("send").addEventListener("click", () => guarded($("send"), async () => {
  const info = await postJson("/api/texts", { text: textBox.value });
  $("alerts").replaceChildren();
  $("results").replaceChildren();
  openChoice(info.id, info);
  await loadHistory();
}));

function openChoice(id, info) {
  current = id;
  $("choose").hidden = false;
  let summary = `Принято: ${info.sentences} предложений, ${info.words} слов.`;
  if (info.skipped) {
    summary += ` Исключено структурных или незавершённых строк: ${info.skipped}.`;
  }
  $("summary").textContent = summary;
  $("skipped-details").hidden = !info.skipped_blocks?.length;
  $("skipped-text").textContent = (info.skipped_blocks || []).join("\n");
  document.querySelectorAll("#history li").forEach(
    (li) => li.classList.toggle("active", Number(li.dataset.id) === id));
}

$("choices").addEventListener("change", () => {
  const picked = selectedChecks();
  $("reference-box").hidden = !(picked.includes("uniqueness") || picked.includes("stylometry"));
});

function selectedChecks() {
  return [...document.querySelectorAll("#choices input:checked")].map((i) => i.value);
}

document.querySelectorAll(".choice-help").forEach(button => {
  button.addEventListener("click", () => {
    const key = button.dataset.check;
    const body = $("check-help-body");
    $("check-help-title").textContent = $("check-name-" + key).textContent;
    body.replaceChildren($("help-" + key).content.cloneNode(true));
    $("check-help").showModal();
    body.scrollTop = 0;
  });
});

$("run").addEventListener("click", () => guarded($("run"), async () => {
  const results = await postJson(`/api/texts/${current}/check`,
                                 { checks: selectedChecks(), reference: refBox.value });
  $("alerts").replaceChildren();
  renderResults(results);
  await loadHistory();
}));

/* ---------- история ---------- */

async function loadHistory() {
  const items = await api("/api/history");
  const list = $("history");
  list.replaceChildren();
  $("history-empty").hidden = items.length > 0;
  for (const item of items) {
    const li = el("li");
    li.dataset.id = item.id;
    li.classList.toggle("active", item.id === current);
    const meta = el("div", "meta");
    meta.append(el("div", "when", displayDate(item.created)), el("div", "preview", item.preview));
    if (item.checks.length) meta.append(el("div", "tags", item.checks.map((c) => NAMES[c]).join(", ")));
    const del = el("button", "del", "×");
    del.title = "Удалить";
    del.addEventListener("click", (event) => {
      event.stopPropagation();
      removeEntry(item.id);
    });
    li.append(meta, del);
    li.tabIndex = 0;
    li.setAttribute("role", "button");
    li.setAttribute("aria-label", "Открыть текст: " + item.preview);
    li.addEventListener("click", () => { if (!busy) openEntry(item.id); });
    li.addEventListener("keydown", event => {
      if (event.target === li && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        if (!busy) openEntry(item.id);
      }
    });
    list.append(li);
  }
}

async function openEntry(id) {
  await guarded($("new-text"), async () => {
    const entry = await api(`/api/texts/${id}`);
    textBox.value = entry.text;
    updateCounter();
    $("alerts").replaceChildren();
    $("summary").textContent = "";
    refBox.value = "";
    document.querySelectorAll("#choices input").forEach(box => { box.checked = false; });
    $("reference-box").hidden = true;
    openChoice(id, { sentences: "", words: "", skipped: 0, skipped_blocks: entry.skipped_blocks });
    $("summary").textContent = `Запись от ${displayDate(entry.created)}. Второй текст в истории не сохраняется.`;
    renderResults(entry.results);
  });
}

async function removeEntry(id) {
  await guarded($("new-text"), async () => {
    await api(`/api/texts/${id}`, { method: "DELETE" });
    if (id === current) newText();
    await loadHistory();
  });
}

$("clear-history").addEventListener("click", () => $("clear-dialog").showModal());
$("cancel-clear").addEventListener("click", () => $("clear-dialog").close());
$("confirm-clear").addEventListener("click", () => guarded($("confirm-clear"), async () => {
    $("clear-dialog").close();
    await api("/api/history", { method: "DELETE" });
    newText();
    await loadHistory();
}));

function newText() {
  current = null;
  textBox.value = refBox.value = "";
  updateCounter();
  $("choose").hidden = true;
  $("results").replaceChildren();
  $("alerts").replaceChildren();
  document.querySelectorAll("#choices input").forEach(box => { box.checked = false; });
  $("reference-box").hidden = true;
  document.querySelectorAll("#history li").forEach(li => li.classList.remove("active"));
}
$("new-text").addEventListener("click", newText);

/* ---------- результаты ---------- */

const NAMES = { complexity: "Сложность", plagiarism: "Антиплагиат", uniqueness: "Уникальность",
                stylometry: "Стилометрия", security: "Безопасность" };

function table(rows, head) {
  const t = el("table");
  if (head) {
    const tr = el("tr");
    head.forEach((h) => tr.append(el("th", "", h)));
    t.append(tr);
  }
  for (const row of rows) {
    const tr = el("tr");
    row.forEach((cell) => tr.append(cell instanceof Node ? cell : el("td", "", cell)));
    t.append(tr);
  }
  return t;
}

function bar(percent) {
  const outer = el("div", "bar");
  const inner = el("i");
  inner.style.width = Math.max(0, Math.min(100, percent)) + "%";
  outer.append(inner);
  return outer;
}

function renderComplexity(d) {
  return [el("div", "big", d.level),
    el("p", "muted", `${d.sentences} предложений, ${d.words} слов`),
    table([["Flesch Reading Ease (адаптация для русского)", d.fre],
           ["Flesch–Kincaid Grade Level", d.fkgl],
           ["SMOG", d.smog],
           ["Coleman–Liau", d.cli]], ["Индекс", "Значение"]),
    el("p", "muted", "Оценки ориентировочные. SMOG и Coleman–Liau рассчитаны по исходным англоязычным формулам; школьный класс для русского текста они не определяют.")];
}

function renderUniqueness(d) {
  return [el("div", "big", d.uniqueness + " %"), bar(d.uniqueness),
    el("p", "muted", `Совпало ${d.common} из ${d.shingles} четырёхсловных фрагментов.`),
    table([["Тематическая близость (0…1)", d.topic_similarity]])];
}

function manualSearchLinks(text) {
  const words = text.match(/[А-Яа-яЁёA-Za-z]+(?:-[А-Яа-яЁёA-Za-z]+)*/g) || [];
  const query = '"' + words.slice(0, 12).join(" ") + '"';
  const row = el("div", "manual-search");
  for (const [name, base] of [["Найти в Яндексе", "https://yandex.ru/search/?text="],
                              ["Найти в Google", "https://www.google.com/search?q="]]) {
    const link = el("a", "search-link", name);
    link.href = base + encodeURIComponent(query);
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    row.append(link);
  }
  return row;
}

function renderPlagiarism(d) {
  const manual = d.mode === "manual";
  const unavailable = !manual && d.checked === 0;
  const nodes = [el("div", "big", manual ? "Поиск источников вручную" : unavailable ? "Поиск недоступен" : `${d.found} из ${d.checked}`),
    el("p", "muted", manual
      ? "Подготовлено фрагментов: " + d.lines.length + ". Нажмите кнопку под фрагментом и посмотрите источники в поисковике. Автоматическая проверка и процент плагиата не рассчитываются."
      : "Совпадения оцениваются по сниппетам выдачи. Отсутствие совпадений не доказывает оригинальность.")];
  nodes.push(el("p", "muted", "По кнопке первые 12 слов фрагмента отправятся выбранному поисковику в новой вкладке. Начните с одного фрагмента. Если точная фраза не найдена, сократите её в поисковой строке."));
  if (d.failed) nodes.push(alertBox("warning", unavailable ? "Автоматический поиск не выполнен" : "Часть поиска не выполнена",
    `Не проверено предложений: ${d.failed} из ${d.requested}. Их нельзя считать оригинальными.`));
  for (const line of d.lines) {
    const item = el("div", "item");
    const badge = el("span", "badge " + (manual || line.error ? "pending" : line.found ? "found" : "none"),
                     manual ? "проверьте по ссылке" : line.error ? "не проверено" : line.found ? "найдено" : "не найдено");
    item.append(badge, el("p", "line-text", line.line));
    if (line.error) item.append(el("p", "muted", line.error));
    const sources = el("div", "sources");
    for (const s of line.sources) {
      const a = el("a", "", s.title || s.url);
      a.href = s.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      sources.append(a);
    }
    item.append(sources);
    item.append(manualSearchLinks(line.line));
    nodes.push(item);
  }
  return nodes;
}

function renderStylometry(d) {
  const nodes = [el("div", "big", d.verdict),
    el("p", "muted", `Косинусное сходство профилей: ${d.similarity}. Это эвристика сходства стиля, она не устанавливает авторство.`)];
  if (!d.reliable) {
    nodes.push(alertBox("warning", "Вывод ненадёжен",
      "В одном из текстов меньше 500 слов, стилометрия на коротких текстах ошибается."));
  }
  const row = (label, key) => [label, d.first[key], d.second[key]];
  nodes.push(table([row("Слов", "words"), row("Разнообразие словаря (TTR)", "ttr"),
                    row("Средняя длина слова", "avg_word"),
                    row("Средняя длина предложения, слов", "avg_sentence")],
                   ["", "Текст", "Второй текст"]));
  return nodes;
}

const PII_NAMES = { EMAIL: "Почта", PHONE: "Телефон", SNILS: "СНИЛС", PASSPORT: "Паспорт",
                    CARD: "Банковская карта", FIO: "ФИО" };

function renderSecurity(d) {
  const entryId = current;
  const nodes = (d.warnings || []).map(message => alertBox("warning", "Проверка выполнена частично", message));
  nodes.push(el("p", "muted", "Автоматический поиск может пропустить данные или ошибиться. Проверьте находки перед заменой."));
  if (!d.findings.length && !d.hidden.length) {
    nodes.push(alertBox("ok", "Совпадений не найдено", "В проверенных категориях нет находок."));
    return nodes;
  }
  const boxes = [];
  if (d.findings.length) {
    const rows = d.findings.map((f) => {
      const box = el("input");
      box.type = "checkbox";
      box.checked = true;
      box.value = f.id;
      box.setAttribute("aria-label", "Заменить " + f.value);
      boxes.push(box);
      const cell = el("td");
      cell.append(box);
      return [cell, PII_NAMES[f.type], f.value, "строка " + f.line, "…" + f.context + "…"];
    });
    nodes.push(el("h3", "", `Персональные данные: ${d.findings.length}`),
               el("p", "muted", "Отмеченные находки будут заменены метками."),
               table(rows, ["", "Тип", "Значение", "Где", "Контекст"]));
  }
  if (d.hidden.length) {
    nodes.push(el("h3", "", `Скрытые символы и необычные пробелы: ${d.hidden.length}`),
      table(d.hidden.map((h) => [h.kind, h.code, "строка " + h.line])));
  }
  const hiddenBox = el("input");
  hiddenBox.type = "checkbox";
  hiddenBox.checked = d.hidden.length > 0;
  const hiddenLabel = el("label", "muted");
  hiddenLabel.append(hiddenBox, " убрать скрытые символы");
  const button = el("button", "", "Очистить текст");
  const output = el("textarea");
  output.id = "clean-text";
  output.hidden = true;
  output.readOnly = true;
  button.addEventListener("click", () => guarded(button, async () => {
    const excluded = boxes.filter((b) => !b.checked).map((b) => Number(b.value));
    const data = await postJson(`/api/texts/${entryId}/sanitize`,
                                { excluded, remove_hidden: hiddenBox.checked });
    output.value = data.text;
    output.hidden = false;
  }));
  const row = el("div", "row");
  row.append(button, hiddenLabel);
  nodes.push(row, output);
  return nodes;
}

const RENDERERS = { complexity: renderComplexity, uniqueness: renderUniqueness,
                    plagiarism: renderPlagiarism, stylometry: renderStylometry,
                    security: renderSecurity };

function renderResults(results) {
  const box = $("results");
  box.replaceChildren();
  for (const [name, result] of Object.entries(results)) {
    const card = el("section", "card");
    card.append(el("h2", "", NAMES[name]));
    if (result.status === "ok") {
      card.append(...RENDERERS[name](result.data));
    } else {
      card.append(alertBox(result.error.level, result.error.title, result.error.message));
    }
    box.append(card);
  }
}

loadHistory().catch(showAlert);

"""Извлечение текста из файлов с ограничениями размера и понятными ошибками."""
import io
import os
import zipfile

import docx
from docx.table import Table
from lxml.etree import XMLSyntaxError
import pypdf
import pytesseract
from PIL import Image, UnidentifiedImageError

import config
from errors import (DependencyError, FileReadError, OCRError, TextAnalyzerError,
                    TextTooLongError, UnsupportedFileError)

TEXT_TYPES = {".txt", ".md"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_PATH


def read_txt(data):
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = data.decode("cp1251")
            except UnicodeDecodeError as error:
                raise FileReadError("Не удалось определить кодировку. Сохраните файл в UTF-8.") from error
    if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        raise FileReadError("В файле двоичные данные. Загрузите обычный текст UTF-8 или Windows-1251.")
    return text


def read_docx(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(f.file_size for f in archive.infolist()) > 100 * 1024 * 1024:
            raise FileReadError("Распакованный документ Word слишком большой (более 100 МБ).")
    document = docx.Document(io.BytesIO(data))
    lines = []
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            lines.extend("| " + " | ".join(cell.text for cell in row.cells) + " |" for row in item.rows)
        else:
            # Сохраняем порядок абзацев и таблиц; метка исключает заголовки из метрик.
            heading = item.style and item.style.name.lower().startswith(("heading", "title"))
            lines.append(("# " if heading else "") + item.text)
    return "\n".join(lines)


def read_pdf(data):
    reader = pypdf.PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise FileReadError("PDF защищён паролем. Загрузите незашифрованную копию.")
    if len(reader.pages) > 500:
        raise FileReadError("В PDF больше 500 страниц. Разделите документ на части.")
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
        if sum(map(len, pages)) > config.MAX_CHARS:
            raise TextTooLongError("Текст PDF превышает допустимый размер.")
    if any(not page.strip() for page in pages):
        raise FileReadError("В одной или нескольких страницах PDF нет текстового слоя. "
                            "Возможно, это скан: загрузите эти страницы как фото, "
                            "чтобы не пропустить их содержимое.")
    return "\n".join(pages)


def read_image(data):
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 25_000_000:
                raise FileReadError("Изображение слишком большое: не более 25 млн пикселей.")
            if getattr(image, "n_frames", 1) > 1:
                raise FileReadError("Загрузите каждую страницу многостраничного изображения отдельно.")
            langs = pytesseract.get_languages(config="")
            missing = set(config.OCR_LANGS.split("+")) - set(langs)
            if missing:
                raise DependencyError("В Tesseract отсутствуют языки: " + ", ".join(sorted(missing)) +
                                      ". Установите языковые данные или измените OCR_LANGS.")
            text = pytesseract.image_to_string(image.convert("RGB"), lang=config.OCR_LANGS, timeout=30)
    except pytesseract.TesseractNotFoundError as error:
        raise DependencyError("Для распознавания фото нужна программа Tesseract OCR "
                              "с языками rus и eng. Установите её или вставьте текст вручную.") from error
    except pytesseract.TesseractError as error:
        raise OCRError("Tesseract не смог прочитать изображение. Проверьте снимок и языковые данные.") from error
    except RuntimeError as error:
        raise OCRError("Распознавание заняло больше 30 секунд. Уменьшите фото и повторите.") from error
    if not text.strip():
        raise OCRError("Текст на фото не распознан. Нужен чёткий снимок без наклона.")
    return text


def read_file(name, data):
    ext = os.path.splitext(name)[1].lower()
    if len(data) > config.MAX_FILE_MB * 1024 * 1024:
        raise TextTooLongError(f"Файл больше {config.MAX_FILE_MB} МБ.")
    readers = {**dict.fromkeys(TEXT_TYPES, read_txt), ".docx": read_docx, ".pdf": read_pdf,
               **dict.fromkeys(IMAGE_TYPES, read_image)}
    if ext not in readers:
        raise UnsupportedFileError("Поддерживаются .txt, .md, .docx, .pdf и фото (png, jpg, bmp, tiff, webp).")
    if not data:
        raise FileReadError("Файл пустой.")
    try:
        text = readers[ext](data)
    except TextAnalyzerError:
        raise
    except (OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile,
            XMLSyntaxError, pypdf.errors.PyPdfError, Image.DecompressionBombError,
            UnidentifiedImageError) as error:
        raise FileReadError("Файл повреждён или его содержимое не соответствует расширению.") from error
    if len(text) > config.MAX_CHARS:
        raise TextTooLongError(f"В файле больше {config.MAX_CHARS:,} символов.")
    return text

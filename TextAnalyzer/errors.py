class TextAnalyzerError(Exception):
    """Общий предок ошибок программы. title — заголовок предупреждения в окне,
    level — «error» (действие не выполнено) или «warning» (проверка недоступна)."""
    title = "Ошибка"
    level = "error"


class EmptyTextError(TextAnalyzerError):
    title = "Нечего проверять"


class NotATextError(TextAnalyzerError):
    title = "Это не текст"


class TextTooShortError(TextAnalyzerError):
    title = "Текст слишком короткий"
    level = "warning"


class TextTooLongError(TextAnalyzerError):
    title = "Текст слишком большой"


class UnsupportedFileError(TextAnalyzerError):
    title = "Такой файл не поддерживается"


class FileReadError(TextAnalyzerError):
    title = "Файл не удалось прочитать"


class OCRError(TextAnalyzerError):
    title = "На фото нет читаемого текста"


class DependencyError(TextAnalyzerError):
    title = "Не хватает программы или библиотеки"
    level = "warning"


class NoInternetError(TextAnalyzerError):
    title = "Нет подключения к интернету"
    level = "warning"


class SearchError(TextAnalyzerError):
    title = "Поисковая система не ответила"
    level = "warning"


class NothingToCompareError(TextAnalyzerError):
    title = "Не с чем сравнивать"
    level = "warning"


class InvalidChoiceError(TextAnalyzerError):
    title = "Неверный выбор"

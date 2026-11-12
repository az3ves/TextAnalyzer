import pytest
import config

@pytest.fixture(autouse=True)
def automatic_search_for_existing_regressions(monkeypatch):
    # Старые тесты продолжают проверять серверный режим; новые явно включают manual.
    monkeypatch.setattr(config, 'SEARCH_MODE', 'duckduckgo')

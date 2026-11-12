import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
from docx import Document
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

import app as web
import config
import plagiarism
import readers
import security
import storage
import text_utils
from errors import DependencyError, FileReadError, SearchError

TEXT = 'Этот простой текст содержит достаточно слов для проверки основных возможностей программы. Он завершается точкой.'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', str(tmp_path / 'history.db'))
    web.app.config.update(TESTING=True)
    return web.app.test_client()


def submit(client, text=TEXT):
    response = client.post('/api/texts', json={'text': text})
    assert response.status_code == 200, response.json
    return response.json['id']


@pytest.mark.parametrize('body', [None, [], {}, {'text': None}, {'text': 3}, {'text': []}, {'text': ''}, {'text': '12345 @@@'}, {'text': 'Только заголовок'}])
def test_invalid_input_is_json(client, body):
    response = client.post('/api/texts', json=body)
    assert response.status_code == 400
    assert 'message' in response.json['error']


def test_bad_json_and_method(client):
    assert client.post('/api/texts', data='{', content_type='application/json').status_code == 400
    assert client.put('/api/history').status_code == 405
    assert client.get('/missing').status_code == 404


@pytest.mark.parametrize('checks', [None, [], {}, 'complexity', [1], [[]], ['missing']])
def test_invalid_checks(client, checks):
    entry_id = submit(client)
    assert client.post(f'/api/texts/{entry_id}/check', json={'checks': checks}).status_code == 400


def test_reference_limit(client, monkeypatch):
    entry_id = submit(client)
    monkeypatch.setattr(config, 'MAX_CHARS', 100)
    response = client.post(f'/api/texts/{entry_id}/check', json={'checks':['uniqueness'], 'reference':'а'*101})
    assert response.status_code == 400


def test_isolated_failure_and_saved_results(client, monkeypatch):
    entry_id = submit(client)
    def fail(*args):
        raise RuntimeError('test failure')
    monkeypatch.setitem(web.CHECKS, 'plagiarism', fail)
    response = client.post(f'/api/texts/{entry_id}/check', json={'checks':['plagiarism','complexity','uniqueness']})
    assert response.status_code == 200
    assert response.json['complexity']['status'] == 'ok'
    assert response.json['plagiarism']['status'] == 'error'
    assert response.json['uniqueness']['status'] == 'error'
    assert client.get(f'/api/texts/{entry_id}').json['results'] == response.json


def test_history_ownership_deletion_and_merge(client):
    entry_id = submit(client)
    other = web.app.test_client()
    assert other.get('/api/history').json == []
    assert other.get(f'/api/texts/{entry_id}').status_code == 400
    assert other.delete(f'/api/texts/{entry_id}').status_code == 400
    for check in ['complexity', 'uniqueness']:
        client.post(f'/api/texts/{entry_id}/check', json={'checks':[check], 'reference':TEXT})
    entry = client.get(f'/api/texts/{entry_id}').json
    assert set(entry['results']) == {'complexity', 'uniqueness'}
    assert entry['results']['uniqueness']['data']['uniqueness'] == 0
    assert client.delete('/api/history').status_code == 200
    assert client.get('/api/history').json == []


def test_concurrent_sqlite_updates(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', str(tmp_path / 'history.db'))
    entry_id = storage.add('owner', TEXT)
    def update(i):
        storage.save_results('owner', entry_id, {str(i): {'status':'ok'}})
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(update, range(20)))
    assert len(storage.get('owner', entry_id)['results']) == 20


def test_history_limit(client, monkeypatch):
    monkeypatch.setattr(config, 'HISTORY_LIMIT', 3)
    for _ in range(5):
        submit(client)
    assert len(client.get('/api/history').json) == 3


def test_cross_origin_rejected(client):
    assert client.post('/api/texts', json={'text':TEXT}, headers={'Origin':'https://other.example'}).status_code == 403


def test_security_real_natasha_and_cleanup(client):
    text = 'Иван Иванович Иванов отправил сообщение на test@example.com. Это скрытый\u200b знак в тексте.'
    entry_id = submit(client, text)
    response = client.post(f'/api/texts/{entry_id}/check', json={'checks':['security']})
    data = response.json['security']['data']
    assert not data['warnings']
    assert {'FIO','EMAIL'} <= {f['type'] for f in data['findings']}
    assert data['hidden'][0]['code'] == 'U+200B'
    excluded = [f['id'] for f in data['findings'] if f['type'] == 'EMAIL']
    clean = client.post(f'/api/texts/{entry_id}/sanitize', json={'excluded':excluded, 'remove_hidden':True})
    assert '[ФИО]' in clean.json['text'] and 'test@example.com' in clean.json['text']
    assert '\u200b' not in clean.json['text']
    assert client.get(f'/api/texts/{entry_id}').json['text'] == text


def test_missing_natasha_is_partial(client, monkeypatch):
    def unavailable(*args):
        raise DependencyError('Natasha недоступна')
    monkeypatch.setattr(security, 'find_names', unavailable)
    data = security.analyze('Письмо отправлено на test@example.com.')
    assert data['warnings'] and data['findings'][0]['type'] == 'EMAIL'


@pytest.mark.parametrize('name,data', [('bad.docx',b'broken'),('bad.pdf',b'broken'),('bad.png',b'broken'),('bad.exe',b'broken'),('empty.txt',b''),('binary.txt',b'\x00\x01')])
def test_invalid_uploads(client, name, data):
    response = client.post('/api/extract', data={'file':(io.BytesIO(data), name)})
    assert response.status_code == 400
    assert response.is_json


@pytest.mark.parametrize('encoding', ['utf-8-sig','cp1251','utf-16'])
def test_text_encodings(client, encoding):
    response = client.post('/api/extract', data={'file':(io.BytesIO(TEXT.encode(encoding)), 'sample.txt')})
    assert response.json['text'] == TEXT


def test_docx_order_and_structure(client):
    doc = Document()
    doc.add_heading('Заголовок с точкой.', 1)
    doc.add_paragraph(TEXT)
    table = doc.add_table(rows=1, cols=2)
    table.cell(0,0).text = 'Строка таблицы'
    table.cell(0,1).text = 'Значение.'
    doc.add_paragraph('Последнее предложение идёт после таблицы.')
    data = io.BytesIO()
    doc.save(data)
    response = client.post('/api/extract', data={'file':(io.BytesIO(data.getvalue()),'sample.docx')})
    text = response.json['text']
    assert text.index('Строка таблицы') < text.index('Последнее предложение')
    assert len(text_utils.skipped_blocks(text)) == 2
    entry_id = submit(client, text)
    assert len(client.get(f'/api/texts/{entry_id}').json['skipped_blocks']) == 2


def pdf_bytes(text=True):
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    if text:
        font = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 50 750 Td (A readable PDF document contains a complete sentence.) Tj ET')
        page[NameObject('/Contents')] = stream
    data = io.BytesIO()
    writer.write(data)
    return data.getvalue()


def test_pdf_text_and_scan(client):
    response = client.post('/api/extract', data={'file':(io.BytesIO(pdf_bytes()),'sample.pdf')})
    assert 'A readable PDF' in response.json['text']
    response = client.post('/api/extract', data={'file':(io.BytesIO(pdf_bytes(False)),'scan.pdf')})
    assert response.status_code == 400 and 'текстового слоя' in response.json['error']['message']


def test_image_missing_tesseract(client, monkeypatch):
    data = io.BytesIO()
    Image.new('RGB',(120,60),'white').save(data,format='PNG')
    monkeypatch.setattr(readers.pytesseract.pytesseract, 'tesseract_cmd', 'absent-tesseract-for-test')
    response = client.post('/api/extract',data={'file':(io.BytesIO(data.getvalue()),'photo.png')})
    assert response.status_code == 400 and 'Tesseract' in response.json['error']['message']


def test_image_ocr_language_and_extraction(client, monkeypatch):
    data = io.BytesIO()
    Image.new('RGB',(120,60),'white').save(data,format='PNG')
    monkeypatch.setattr(readers.pytesseract,'get_languages',lambda **kwargs:['eng'])
    response = client.post('/api/extract',data={'file':(io.BytesIO(data.getvalue()),'photo.png')})
    assert response.status_code == 400 and 'rus' in response.json['error']['message']
    monkeypatch.setattr(readers.pytesseract,'get_languages',lambda **kwargs:['eng','rus'])
    monkeypatch.setattr(readers.pytesseract,'image_to_string',lambda *args,**kwargs:TEXT)
    response = client.post('/api/extract',data={'file':(io.BytesIO(data.getvalue()),'photo.png')})
    assert response.json['text'] == TEXT  # only adapter tested, not real OCR


def test_structure_and_quoted_sentences():
    text = '# Заголовок.\nпервое предложение идёт отдельно.\n| Название | Значение. |\n- Пункт списка.\n«Второе предложение закончилось.» Третье предложение тоже закончилось.'
    assert len(text_utils.skipped_blocks(text)) == 3
    assert len(text_utils.prose_sentences(text)) == 3


HTML = '''<div class="result results_links"><h2><a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Farticle" class="extra result__a">Пример</a></h2><div class="result__snippet">Этот <b>простой</b> текст содержит достаточно слов для проверки основных возможностей программы.</div></div>'''


def test_parser_and_exact_words():
    assert plagiarism.parse_results(HTML)[0]['url'] == 'https://example.org/article'
    assert plagiarism.matches(plagiarism.normalize(TEXT), 'ЭТОТ ПРОСТОЙ ТЕКСТ СОДЕРЖИТ ДОСТАТОЧНО СЛОВ')
    assert not plagiarism.matches(['а','б','в','г','д','е'], 'за б в г д еж')
    assert plagiarism.real_url('javascript:alert(1)') is None
    assert plagiarism.parse_results('<div class="no-results">Nothing</div>') == []
    with pytest.raises(SearchError):
        plagiarism.parse_results('<html>Changed markup</html>')
    with pytest.raises(SearchError):
        plagiarism.parse_results('<form action="/anomaly.js">captcha</form>')


def test_live_local_search_case_regression(monkeypatch):
    queries = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)['q'][0]
            queries.append(query)
            self.send_response(200)
            self.end_headers()
            # Deliberately case-sensitive, reproduces the original suspected test bug.
            page = HTML if 'этот' in query else '<div class="no-results">Nothing</div>'
            self.wfile.write(page.encode('utf-8'))
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    monkeypatch.setattr(config,'SEARCH_URL',f'http://127.0.0.1:{server.server_port}/search')
    try:
        result = plagiarism.check(TEXT.split('. ')[0] + '.')
        assert result['found'] == 1 and result['checked'] == 1
        assert queries[0] == queries[0].lower()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_partial_search_preserves_success(monkeypatch):
    calls = []
    def search(query):
        calls.append(query)
        if len(calls) == 1:
            return [{'title':'Пример','url':'https://example.org','snippet':TEXT}]
        raise SearchError('HTTP 202')
    monkeypatch.setattr(plagiarism,'search',search)
    monkeypatch.setattr(config,'SEARCH_PAUSE',0)
    result = plagiarism.check(TEXT + ' Совсем другое длинное предложение содержит ещё достаточно слов для второго запроса.')
    assert result['checked'] == 1 and result['found'] == 1 and result['failed'] == 1
    assert result['lines'][1]['found'] is None


def test_manual_search_never_calls_network(monkeypatch):
    monkeypatch.setattr(config, 'SEARCH_MODE', 'manual')
    def forbidden(*args, **kwargs):
        raise AssertionError('Manual mode must not call the network')
    monkeypatch.setattr(plagiarism.requests, 'get', forbidden)
    result = plagiarism.check(TEXT)
    assert result['mode'] == 'manual'
    assert result['checked'] == 0 and result['found'] is None
    assert result['found_percent'] is None and result['failed'] == 0
    assert result['lines'] and result['lines'][0]['found'] is None

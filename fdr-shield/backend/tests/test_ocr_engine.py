import asyncio
import base64
import json
from io import BytesIO
from types import SimpleNamespace

import httpx
from PIL import Image

from app.integrations.ocr import get_engine
from app.integrations.ocr.ollama_vision_engine import FIELDS, OllamaVisionEngine
from app.schemas.verification import OcrResult
from app.services import ocr_service


def jpeg(size=(80, 40), color='white'):
    out=BytesIO();Image.new('RGB',size,color).save(out,format='JPEG');return out.getvalue()


def fields(**overrides):
    result={key:None for key in FIELDS}
    result.update({'fdr_number':'SBI100001','bank_name':'SBI','holder_name':'ABC Institute of Technology','amount':1000000,'issue_date':'2026-03-31','maturity_date':'2027-03-31'})
    result.update({'format_match':'sbi','format_reason':'Matches the SBI reference layout.'})
    result.update(overrides)
    return result


def settings(**overrides):
    base={'ollama_base_url':'http://ollama.test','ollama_model':'gemma4:cloud','ollama_api_key':'','ollama_timeout':2,
          'ocr_format_check':True,'ocr_reference_dir':'reference_formats'}
    base.update(overrides)
    return SimpleNamespace(**base)


def test_ollama_vision_valid_json_and_image_resize(monkeypatch):
    seen={}
    async def handler(request):
        seen['request']=request
        return httpx.Response(200,json={'message':{'content':json.dumps(fields())}})
    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings(ollama_api_key='test-key'))
    engine=OllamaVisionEngine(httpx.MockTransport(handler))
    result=asyncio.run(engine.extract([jpeg((1900,1700))]))
    request=seen['request'];body=json.loads(request.content)
    assert result['fdr_number']=='SBI100001'
    assert request.url.path=='/api/chat'
    assert request.headers['authorization']=='Bearer test-key'
    assert body['stream'] is False and body['options']['temperature']==0
    assert set(body['format']['properties'])==set(FIELDS)|{'format_match','format_reason'}
    assert body['model']=='gemma4:cloud' and len(body['messages'][0]['images'])==4
    assert 'Reference 1: genuine SBI format' in body['messages'][0]['content']
    assert 'Reference 2: genuine HDFC format' in body['messages'][0]['content']
    assert 'Reference 3: genuine PNB format' in body['messages'][0]['content']
    image=Image.open(BytesIO(base64.b64decode(body['messages'][0]['images'][-1])))
    assert max(image.size)<=1600 and image.format=='JPEG'
    assert 'untrusted' in body['messages'][0]['content'].lower()
    assert 'tools' not in body


def test_vision_source_spans_are_schema_checked_and_document_is_untrusted(monkeypatch):
    seen={}
    span_payload={key:{'page':1,'quote':f'{key}: SBI100001'} for key in FIELDS}
    async def handler(request):
        seen['body']=json.loads(request.content)
        return httpx.Response(200,json={'message':{'content':json.dumps(span_payload)}})
    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings())
    spans=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract_source_spans([jpeg()],fields()))
    assert spans['fdr_number']=={'page':1,'quote':'fdr_number: SBI100001','trust':'extracted'}
    assert 'UNTRUSTED DATA' in seen['body']['messages'][0]['content']
    assert 'tools' not in seen['body']


def test_invalid_json_is_retried_once_then_succeeds(monkeypatch):
    count={'calls':0}
    async def handler(request):
        count['calls']+=1
        content='not json' if count['calls']==1 else json.dumps(fields())
        return httpx.Response(200,json={'message':{'content':content}})
    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings())
    result=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([jpeg()]))
    assert count['calls']==2 and result['amount']==1000000


def test_none_format_match_clears_all_fields(monkeypatch):
    from app.integrations.ocr.reference_formats import clear_reference_cache
    clear_reference_cache()
    async def handler(request):
        payload=fields(format_match='none',format_reason='Does not resemble a bank format.')
        assert payload['format_match'] == 'none'
        assert len(json.loads(request.content)['messages'][0]['images']) == 4
        assert json.loads(request.content)['format']['properties']['format_match']['enum'] == ['sbi','hdfc','pnb','none']
        return httpx.Response(200,json={'message':{'content':json.dumps(payload)}})
    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings())
    result=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([jpeg()]))
    assert set(result)==set(FIELDS) and all(value is None for value in result.values())
    clear_reference_cache()


def test_negative_sample_short_circuits_model(monkeypatch):
    from pathlib import Path
    from app.integrations.ocr.reference_formats import is_known_negative, clear_reference_cache
    negative=Path('reference_formats/negative_samples/sample-sbi.png').read_bytes()
    assert is_known_negative(negative)
    async def handler(request): raise AssertionError('known negative must not call Ollama')
    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings())
    result=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([negative]))
    assert set(result)==set(FIELDS) and all(value is None for value in result.values())
    clear_reference_cache()


def test_missing_references_warn_and_fall_back_to_plain_extraction(monkeypatch, tmp_path, caplog):
    payload=fields()
    from app.integrations.ocr.reference_formats import clear_reference_cache
    clear_reference_cache()
    async def handler(request):
        body=json.loads(request.content)
        assert len(body['messages'][0]['images'])==1
        assert 'format_match' not in body['messages'][0]['content']
        return httpx.Response(200,json={'message':{'content':json.dumps(payload)}})
    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings(ocr_reference_dir=str(tmp_path)))
    monkeypatch.setattr('app.integrations.ocr.reference_formats.get_settings',lambda:settings(ocr_reference_dir=str(tmp_path)))
    result=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([jpeg()]))
    assert result['fdr_number']=='SBI100001'
    assert 'OCR reference format missing' in caplog.text
    clear_reference_cache()


def test_format_check_disabled_uses_plain_six_field_prompt(monkeypatch):
    async def handler(request):
        body=json.loads(request.content)
        assert len(body['messages'][0]['images'])==1
        assert 'Reference 1' not in body['messages'][0]['content']
        assert set(body['format']['properties'])==set(FIELDS)
        return httpx.Response(200,json={'message':{'content':json.dumps(fields())}})
    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings(ocr_format_check=False))
    assert asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([jpeg()]))['fdr_number']=='SBI100001'


def test_ocr_public_signatures_remain_unchanged():
    import inspect
    from app.integrations.ocr.base import FdrExtractor
    assert str(inspect.signature(ocr_service.extract_fdr_fields)) == "(file_bytes: 'bytes', content_type: 'str', *, raise_errors: 'bool' = False) -> 'OcrResult'"
    assert str(inspect.signature(FdrExtractor.extract)) == "(self, pages: list[bytes]) -> app.integrations.ocr.base.FdrFields"


def test_json_markdown_fence_is_normalized_without_retry(monkeypatch):
    count={'calls':0}
    async def handler(request):
        count['calls']+=1
        return httpx.Response(200,json={'message':{'content':'```json\n'+json.dumps(fields())+'\n```'}})
    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings())
    result=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([jpeg()]))
    assert count['calls']==1 and result['fdr_number']=='SBI100001'


def test_http_error_returns_empty_result(monkeypatch):
    async def handler(request): return httpx.Response(503,json={'error':'offline'})
    engine=OllamaVisionEngine(httpx.MockTransport(handler))
    monkeypatch.setattr(ocr_service,'get_engine',lambda:engine)
    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings())
    result=asyncio.run(ocr_service.extract_fdr_fields(jpeg(),'image/jpeg'))
    assert isinstance(result,OcrResult) and result.confidence==0 and result.fdr_number is None


def test_corrupt_pdf_degrades_to_unextracted_result(monkeypatch):
    class FakeEngine:
        async def extract(self,pages): return fields()
    monkeypatch.setattr(ocr_service,'get_engine',lambda:FakeEngine())
    result=asyncio.run(ocr_service.extract_fdr_fields(b'not a pdf','application/pdf'))
    assert result.confidence==0 and result.fdr_number is None


def test_pdf_is_converted_and_only_first_two_pages_sent(monkeypatch):
    from pdf2image import convert_from_bytes
    calls={}
    def convert(data,**kwargs):
        calls.update(kwargs)
        return [Image.new('RGB',(40,20),'white') for _ in range(3)]
    class FakeEngine:
        async def extract(self,pages):
            calls['page_count']=len(pages)
            return fields()
    monkeypatch.setattr('pdf2image.convert_from_bytes',convert)
    monkeypatch.setattr(ocr_service,'get_engine',lambda:FakeEngine())
    result=asyncio.run(ocr_service.extract_fdr_fields(b'%PDF-fake','application/pdf'))
    assert calls['first_page']==1 and calls['last_page']==2 and calls['page_count']==2
    assert result.confidence==1 and result.issue_date.isoformat()=='2026-03-31'


def test_engine_selection_uses_ocr_engine_environment(monkeypatch):
    from app.core.config import get_settings as settings_factory
    get_engine.cache_clear();settings_factory.cache_clear()
    monkeypatch.setenv('OCR_ENGINE','ollama_vision')
    assert isinstance(get_engine(),OllamaVisionEngine)
    get_engine.cache_clear();settings_factory.cache_clear()
    monkeypatch.setenv('OCR_ENGINE','easyocr')
    from app.integrations.ocr.easyocr_engine import EasyOcrEngine
    assert isinstance(get_engine(),EasyOcrEngine)
    get_engine.cache_clear();settings_factory.cache_clear()


def test_disabled_ocr_does_not_call_a_provider_and_returns_manual_entry_fields(monkeypatch):
    get_engine.cache_clear()
    from app.core.config import get_settings as settings_factory
    settings_factory.cache_clear()
    monkeypatch.setenv('OCR_ENGINE','disabled')
    result=asyncio.run(ocr_service.extract_fdr_fields(jpeg(),'image/jpeg'))
    assert result.confidence==0
    assert all(getattr(result,key) is None for key in FIELDS)
    get_engine.cache_clear();settings_factory.cache_clear()

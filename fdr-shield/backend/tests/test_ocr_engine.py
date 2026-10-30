import asyncio
import base64
import json
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from PIL import Image
from starlette.requests import Request

from app.integrations.ocr import get_engine
from app.integrations.ocr.ollama_vision_engine import FIELDS, OllamaVisionEngine
from app.schemas.verification import OcrResult
from app.services import ocr_service


def jpeg(size=(80, 40), color='white'):
    out=BytesIO();Image.new('RGB',size,color).save(out,format='JPEG');return out.getvalue()


def fields(**overrides):
    result={key:None for key in FIELDS}
    result.update({'fdr_number':'SBI100001','bank_name':'SBI','branch':'Main Branch','holder_name':'ABC Institute of Technology','amount':1000000,'issue_date':'2026-03-31','maturity_date':'2027-03-31'})
    result.update({'document_format':'fdr_like','format_reason':'A structured deposit receipt layout is visible.'})
    result.update(overrides)
    return result


def settings(**overrides):
    base={'ollama_base_url':'http://ollama.test','ollama_model':'gemma4:31b','ollama_api_key':'','ollama_timeout':2,
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
    assert result['branch']=='Main Branch'
    assert request.url.path=='/api/chat'
    assert request.headers['authorization']=='Bearer test-key'
    assert body['stream'] is False and body['options']['temperature']==0
    assert set(body['format']['properties'])==set(FIELDS)|{'document_format','format_reason'}
    assert body['format']['properties']['document_format']['enum']==['fdr_like','not_fdr_like','uncertain']
    assert body['model']=='gemma4:31b' and len(body['messages'][0]['images'])==1
    assert 'bank-neutral' in body['messages'][0]['content']
    assert 'cannot establish' in body['messages'][0]['content']
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


def test_omitted_fields_are_null_and_other_extracted_values_are_kept(monkeypatch, caplog):
    payload=fields()
    del payload['bank_name']
    del payload['maturity_date']
    calls={'count':0}

    async def handler(request):
        calls['count']+=1
        return httpx.Response(200,json={'message':{'content':json.dumps(payload)}})

    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings())
    result=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([jpeg()]))

    assert calls['count']==1
    assert result['fdr_number']=='SBI100001'
    assert result['bank_name'] is None
    assert result['amount']==1000000
    assert result['maturity_date'] is None
    assert 'Ollama OCR response omitted fields' in caplog.text


@pytest.mark.parametrize(('raw_amount', 'expected'), [
    ('₹ 12,34,567.50', '1234567.50'),
    ('Rs. 1,234,567.50', '1234567.50'),
    ('INR 25000', '25000'),
    ('1.5 lakh', None),
])
def test_amount_text_is_normalized_without_discarding_other_fields(monkeypatch, raw_amount, expected):
    payload=fields(amount=raw_amount)

    async def handler(request):
        return httpx.Response(200,json={'message':{'content':json.dumps(payload)}})

    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings())
    result=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([jpeg()]))

    assert result['fdr_number']=='SBI100001'
    assert result['amount']==expected


def test_not_fdr_like_format_assessment_preserves_readable_fields(monkeypatch):
    from app.integrations.ocr.reference_formats import clear_reference_cache
    clear_reference_cache()
    async def handler(request):
        payload=fields(document_format='not_fdr_like',format_reason='Document layout is unclear.')
        assert payload['document_format'] == 'not_fdr_like'
        assert len(json.loads(request.content)['messages'][0]['images']) == 1
        assert json.loads(request.content)['format']['properties']['document_format']['enum'] == ['fdr_like','not_fdr_like','uncertain']
        return httpx.Response(200,json={'message':{'content':json.dumps(payload)}})
    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings())
    result=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([jpeg()]))
    assert result['fdr_number']=='SBI100001'
    assert result['amount']==1000000
    assert result['document_format']=='not_fdr_like'
    assert result['format_reason']=='Document layout is unclear.'
    assert set(result)==set(FIELDS)|{'document_format','format_reason'}
    clear_reference_cache()


def test_generic_format_check_does_not_require_bank_template_or_infer_bank(monkeypatch):
    payload=fields(bank_name='ICICI Bank',document_format='fdr_like')

    async def handler(request):
        body=json.loads(request.content)
        assert len(body['messages'][0]['images'])==1
        assert 'ICICI' not in body['messages'][0]['content']
        assert 'State Bank of India' not in body['messages'][0]['content']
        return httpx.Response(200,json={'message':{'content':json.dumps(payload)}})

    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings())
    result=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([jpeg()]))

    assert result['bank_name']=='ICICI Bank'
    assert result['document_format']=='fdr_like'


def test_invalid_format_metadata_does_not_discard_extracted_fields(monkeypatch, caplog):
    async def handler(request):
        return httpx.Response(200,json={'message':{'content':json.dumps(
            fields(document_format='genuine', format_reason=None))}})

    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings())
    result=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([jpeg()]))
    assert result['fdr_number']=='SBI100001'
    assert result['document_format']=='uncertain'
    assert result['format_reason']=='The OCR provider did not return a usable format assessment.'
    assert 'preserving extracted fields' in caplog.text


def test_unsupported_provider_fields_are_ignored_without_failing_preview(monkeypatch, caplog):
    payload=fields(provider_confidence=0.93,issuer_category='bank')

    async def handler(request):
        return httpx.Response(200,json={'message':{'content':json.dumps(payload)}})

    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings())
    result=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([jpeg()]))

    assert result['fdr_number']=='SBI100001'
    assert result['document_format']=='fdr_like'
    warning=next(record for record in caplog.records if 'unsupported fields' in record.message)
    assert warning.unexpected_fields==['issuer_category','provider_confidence']


def test_common_bank_receipt_field_aliases_are_normalized(monkeypatch):
    payload={
        'fdr_no':'FDIN3021456789',
        'bank':'ICICI Bank',
        'branch_name':'Mumbai Main',
        'customer_name':'MR. ROHIT MEHRA / MRS. NEHA MEHRA',
        'principal_amount':'500000',
        'opening_date':'2024-01-15',
        'date_of_maturity':'2026-01-15',
        'document_format':'fdr_like',
        'format_reason':'Structured term-deposit receipt layout.',
        'provider_confidence':0.99,
    }

    async def handler(request):
        body=json.loads(request.content)
        assert 'common labels' in body['messages'][0]['content']
        assert body['format']['additionalProperties'] is False
        return httpx.Response(200,json={'message':{'content':json.dumps(payload)}})

    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings())
    result=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([jpeg()]))

    assert result['fdr_number']=='FDIN3021456789'
    assert result['bank_name']=='ICICI Bank'
    assert result['branch']=='Mumbai Main'
    assert result['holder_name']=='MR. ROHIT MEHRA / MRS. NEHA MEHRA'
    assert result['amount']=='500000'
    assert result['issue_date']=='2024-01-15'
    assert result['maturity_date']=='2026-01-15'
    assert result['document_format']=='fdr_like'


def test_negative_sample_short_circuits_model(monkeypatch):
    from pathlib import Path
    from app.integrations.ocr.reference_formats import is_known_negative, clear_reference_cache
    negative=Path('reference_formats/negative_samples/sample-sbi.png').read_bytes()
    assert is_known_negative(negative)
    async def handler(request): raise AssertionError('known negative must not call Ollama')
    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings())
    result=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([negative]))
    assert all(result[key] is None for key in FIELDS)
    assert result['document_format']=='not_fdr_like'
    clear_reference_cache()


def test_generic_format_check_does_not_need_reference_images(monkeypatch, tmp_path):
    payload=fields(document_format='uncertain')
    from app.integrations.ocr.reference_formats import clear_reference_cache
    clear_reference_cache()
    async def handler(request):
        body=json.loads(request.content)
        assert len(body['messages'][0]['images'])==1
        assert 'bank-neutral' in body['messages'][0]['content']
        assert body['format']['properties']['document_format']['enum']==['fdr_like','not_fdr_like','uncertain']
        return httpx.Response(200,json={'message':{'content':json.dumps(payload)}})
    monkeypatch.setattr('app.integrations.ocr.ollama_vision_engine.get_settings',lambda:settings(ocr_reference_dir=str(tmp_path)))
    monkeypatch.setattr('app.integrations.ocr.reference_formats.get_settings',lambda:settings(ocr_reference_dir=str(tmp_path)))
    result=asyncio.run(OllamaVisionEngine(httpx.MockTransport(handler)).extract([jpeg()]))
    assert result['fdr_number']=='SBI100001'
    assert result['document_format']=='uncertain'
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


def test_extract_preview_reports_provider_failures(monkeypatch):
    from app.api.v1.fdrs import extract_preview

    async def allow_rate_limit(*args, **kwargs):
        return None

    async def allow_upload_scan(data):
        return {}

    async def fail_extraction(*args, **kwargs):
        assert kwargs == {'raise_errors': True}
        raise httpx.ConnectError('offline')

    monkeypatch.setattr('app.core.config.get_settings', lambda: SimpleNamespace(
        rate_limit_ocr_per_minute=10, trusted_proxy_ips=''))
    monkeypatch.setattr('app.services.rate_limit_service.enforce_rate_limit', allow_rate_limit)
    monkeypatch.setattr('app.integrations.upload_scanner.scan_upload', allow_upload_scan)
    monkeypatch.setattr(ocr_service, 'extract_fdr_fields', fail_extraction)

    request = Request({
        'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
        'method': 'POST', 'scheme': 'http', 'path': '/api/v1/fdrs/extract-preview',
        'raw_path': b'/api/v1/fdrs/extract-preview', 'query_string': b'',
        'headers': [], 'client': ('127.0.0.1', 1234), 'server': ('127.0.0.1', 8000),
    })

    class FakeUpload:
        content_type = 'image/jpeg'

        async def read(self):
            return b'\xff\xd8\xfftest'

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(extract_preview(request, FakeUpload(), SimpleNamespace(id=1)))

    assert exc_info.value.status_code == 502
    assert 'Check the backend log' in exc_info.value.detail


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


def test_text_ocr_extracts_explicit_branch_label():
    result=asyncio.run(ocr_service.parse_fdr_text(
        'Fixed Deposit Receipt\nBank: SBI\nBranch Name: Park Street\nAccount No: SBI100001'
    ))
    assert result.branch=='Park Street'


def test_extract_fdr_fields_preserves_branch_and_counts_it_in_confidence(monkeypatch):
    class FakeEngine:
        async def extract(self, pages): return fields()

    monkeypatch.setattr(ocr_service, 'get_engine', lambda: FakeEngine())
    result=asyncio.run(ocr_service.extract_fdr_fields(jpeg(), 'image/jpeg'))

    assert result.branch=='Main Branch'
    assert result.confidence==1


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

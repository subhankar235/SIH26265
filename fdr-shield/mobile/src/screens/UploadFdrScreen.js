import { useMemo, useState } from 'react';
import { Text, View } from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import { router, Stack } from 'expo-router';
import { api } from '../lib/api';
import { Badge, Button, Card, Field, Screen, colors, styles } from '../components/ui';

const FIELDS = [
  { key: 'fdr_number', label: 'FDR number', required: true, minLength: 3 },
  { key: 'bank_name', label: 'Bank name', required: true },
  { key: 'branch', label: 'Branch', required: false },
  { key: 'amount', label: 'Amount', required: true, keyboardType: 'decimal-pad' },
  { key: 'issue_date', label: 'Issue date', required: true, placeholder: 'YYYY-MM-DD' },
  { key: 'maturity_date', label: 'Maturity date', required: true, placeholder: 'YYYY-MM-DD' },
  { key: 'holder', label: 'Account holder', required: false },
];
const ACCEPTED = ['application/pdf', 'image/jpeg', 'image/png'];
const MAX_BYTES = 10 * 1024 * 1024;
const LOW_CONFIDENCE = 0.7;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function buildFile(asset) {
  return { uri: asset.uri, name: asset.name || 'fdr-scan', type: asset.mimeType || 'application/octet-stream' };
}

export default function UploadFdrScreen() {
  const [asset, setAsset] = useState(null);
  const [preview, setPreview] = useState(null);
  const [values, setValues] = useState({});
  const [edited, setEdited] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [created, setCreated] = useState(null);

  const threshold = preview?.low_confidence_threshold ?? LOW_CONFIDENCE;

  async function pickFile() {
    setError('');
    setNotice('');
    setPreview(null);
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: ACCEPTED, copyToCacheDirectory: true, multiple: false,
      });
      if (result.canceled || !result.assets?.length) return;
      const picked = result.assets[0];
      if (!ACCEPTED.includes(picked.mimeType)) {
        setError('Choose a PDF, JPEG, or PNG scan of the deposit receipt.');
        return;
      }
      if (picked.size && picked.size > MAX_BYTES) {
        setError('The file must be smaller than 10 MB.');
        return;
      }
      setAsset(picked);
      setCreated(null);
      setValues({});
      setEdited({});
      await extract(picked);
    } catch (e) {
      setError(e.message || 'The file could not be opened.');
    }
  }

  async function extract(picked) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const form = new FormData();
      form.append('file', buildFile(picked));
      const result = await api('/fdrs/extract-preview', { method: 'POST', body: form });
      const fields = result.fields || {};
      setPreview(result);
      setValues(Object.fromEntries(FIELDS.map(field => [field.key, fields[field.key] == null ? '' : String(fields[field.key])])));
      const weak = FIELDS.filter(field => !fields[field.key] || (result.confidence?.[field.key] ?? 0) < threshold);
      if (weak.length) setNotice(`${weak.length} field${weak.length > 1 ? 's need' : ' needs'} your attention before submission.`);
    } catch (e) {
      setPreview(null);
      setValues(Object.fromEntries(FIELDS.map(field => [field.key, ''])));
      setNotice('Automatic extraction is unavailable for this file. Enter every field manually — the scan is still attached to your submission.');
      setError(e.message || 'Extraction failed. You can still enter the fields manually.');
    } finally {
      setBusy(false);
    }
  }

  const validation = useMemo(() => {
    if (!asset) return 'Choose a scan to begin.';
    for (const field of FIELDS) {
      const value = String(values[field.key] || '').trim();
      if (field.required && !value) return `${field.label} is required.`;
      if (field.minLength && value && value.length < field.minLength) return `${field.label} must be at least ${field.minLength} characters.`;
    }
    const amount = Number(values.amount);
    if (!Number.isFinite(amount) || amount <= 0) return 'Amount must be a number greater than zero.';
    for (const key of ['issue_date', 'maturity_date']) {
      const value = String(values[key] || '').trim();
      if (value && !DATE_PATTERN.test(value)) return `${key === 'issue_date' ? 'Issue' : 'Maturity'} date must use YYYY-MM-DD.`;
      if (value && Number.isNaN(new Date(value).getTime())) return 'One of the dates is not a real calendar date.';
    }
    if (values.issue_date && values.maturity_date && values.maturity_date < values.issue_date) {
      return 'Maturity date cannot be before the issue date.';
    }
    return '';
  }, [asset, values]);

  async function submit() {
    if (validation || busy) return;
    setBusy(true);
    setError('');
    try {
      const payload = Object.fromEntries(FIELDS.map(field => [field.key, String(values[field.key] || '').trim()]));
      const provenance = Object.fromEntries(FIELDS.map(field => {
        const value = payload[field.key];
        const confidence = Number(preview?.confidence?.[field.key] ?? 0);
        const extracted = !edited[field.key] && value !== '' && confidence >= threshold;
        return [field.key, extracted ? 'EXTRACTED' : 'DECLARED'];
      }));
      const form = new FormData();
      FIELDS.forEach(field => form.append(field.key, payload[field.key]));
      form.append('confirmed_fields', JSON.stringify(FIELDS.map(field => field.key)));
      form.append('field_provenance', JSON.stringify(provenance));
      form.append('file', buildFile(asset));
      const result = await api('/fdrs', { method: 'POST', body: form });
      setCreated(result);
    } catch (e) {
      setError(e.message || 'The FDR could not be submitted.');
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return <Screen title="FDR submitted" subtitle="Your deposit receipt is now in the verification workflow.">
      <Stack.Screen options={{ title: 'Submitted' }}/>
      <Card>
        <View style={styles.row}>
          <Text style={[styles.sectionTitle, { flex: 1 }]}>Case created</Text>
          <Badge tone="amber">{String(created.lifecycle_state || created.status || '').replaceAll('_', ' ')}</Badge>
        </View>
        <Text style={styles.muted}>Reference #{created.fdr_id ?? created.id}. The document is scanned, compared with your declared fields, and then queued for AICTE scrutiny.</Text>
        <Button title="Open case file" onPress={() => router.replace(`/(portal)/case/${created.fdr_id ?? created.id}`)}/>
        <Button title="Submit another FDR" secondary onPress={() => { setCreated(null); setAsset(null); setPreview(null); setValues({}); setEdited({}); setNotice(''); }}/>
      </Card>
    </Screen>;
  }

  return <Screen title="Submit an FDR" subtitle="Upload the deposit receipt, verify the extracted fields, then submit for scrutiny.">
    <Stack.Screen options={{ title: 'Submit FDR' }}/>
    <Card>
      <Text style={styles.sectionTitle}>1. Upload the receipt</Text>
      <Text style={styles.muted}>PDF, JPEG, or PNG up to 10 MB. The file is virus-scanned before any field is read.</Text>
      <Button title={asset ? `Selected: ${asset.name}` : 'Choose scan file'} onPress={pickFile} disabled={busy}/>
      {asset ? <Button title="Re-scan this file" secondary compact onPress={() => extract(asset)} disabled={busy}/> : null}
    </Card>

    <Card>
      <Text style={styles.sectionTitle}>2. Confirm the details</Text>
      {notice ? <View style={styles.notice}><Text style={styles.noticeText}>{notice}</Text></View> : null}
      {preview ? <Text style={styles.small}>
        Format check: {preview.format_check?.status || 'unknown'}{preview.format_check?.reason ? ` · ${preview.format_check.reason}` : ''}
      </Text> : null}
      {FIELDS.map(field => {
        const confidence = Number(preview?.confidence?.[field.key] ?? 0);
        const showConfidence = Boolean(preview) && String(values[field.key] || '').trim() !== '';
        const weak = showConfidence && confidence < threshold;
        return <View key={field.key}>
          <Field label={field.label} value={values[field.key] || ''}
            onChangeText={value => { setValues(current => ({ ...current, [field.key]: value })); setEdited(current => ({ ...current, [field.key]: true })); }}
            keyboardType={field.keyboardType} autoCapitalize="none" placeholder={field.placeholder}/>
          {showConfidence
            ? <Text style={[styles.small, { marginTop: -6, marginBottom: 8, color: weak ? colors.amber : colors.green }]}>
                {weak ? 'Low extraction confidence — verify against the scan' : `Extracted with ${Math.round(confidence * 100)}% confidence`}
              </Text>
            : null}
        </View>;
      })}
      {error ? <Text style={{ color: colors.red, fontSize: 13 }}>{error}</Text> : null}
      <Button title={busy ? 'Working…' : 'Submit for verification'} onPress={submit} disabled={busy || Boolean(validation)}/>
      {validation && asset ? <Text style={styles.small}>{validation}</Text> : null}
    </Card>
  </Screen>;
}

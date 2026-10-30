import { useCallback, useMemo, useState } from 'react';
import { Modal, Text, View } from 'react-native';
import * as Linking from 'expo-linking';
import { router, Stack } from 'expo-router';
import { api } from '../lib/api';
import { Badge, Button, Card, ErrorMessage, Field, Loading, Screen, colors, styles, useApiResource } from '../components/ui';
import { useAuth } from '../providers/AuthProvider';

const idempotencyKey = () => `${Date.now()}-${Math.random().toString(36).slice(2, 18)}`;
const COMPARE_FIELDS = ['fdr_number', 'bank_name', 'branch', 'amount', 'issue_date', 'maturity_date', 'holder'];
const OFFICIAL_NEXT = {
  submitted: [['Start scrutiny', 'under_scrutiny'], ['Verify case', 'verified'], ['Request correction', 'mismatch']],
  under_scrutiny: [['Verify case', 'verified'], ['Request correction', 'mismatch']],
  mismatch: [['Re-open scrutiny', 'under_scrutiny'], ['Verify case', 'verified']],
};

function statusTone(status) {
  const value = String(status || '').toLowerCase();
  if (['verified', 'released', 'completed', 'accepted', 'renewed'].includes(value)) return 'green';
  if (['mismatch', 'expired', 'failed', 'blocked'].includes(value)) return 'red';
  return 'amber';
}

function Row({ label, value }) {
  return <View style={styles.row}>
    <Text style={[styles.small, { flex: 1 }]}>{label}</Text>
    <Text style={[styles.small, { color: colors.ink, fontWeight: '600', flexShrink: 1, textAlign: 'right' }]}
      numberOfLines={2}>{value === null || value === undefined || value === '' ? '—' : String(value)}</Text>
  </View>;
}

function DecisionModal({ title, fields, submitLabel, error, busy, onClose, onSubmit }) {
  const [values, setValues] = useState(() => Object.fromEntries(fields.map(field => [field.key, field.initial || ''])));
  const invalid = fields.some(field => field.required && !String(values[field.key] || '').trim());
  return <Modal visible transparent animationType="slide" onRequestClose={onClose}>
    <View style={styles.modalBackdrop}>
      <View style={[styles.modal, { maxHeight: '88%' }]}>
        <Text style={styles.modalTitle}>{title}</Text>
        {fields.map(field => <Field key={field.key} label={field.label} value={values[field.key]}
          onChangeText={value => setValues(current => ({ ...current, [field.key]: value }))}
          keyboardType={field.keyboardType} multiline={field.multiline} autoCapitalize="none"
          placeholder={field.placeholder}/>)}
        {error ? <Text style={{ color: colors.red, fontSize: 13 }}>{error}</Text> : null}
        <View style={{ flexDirection: 'row', gap: 9 }}>
          <View style={{ flex: 1 }}><Button title="Cancel" secondary onPress={onClose} disabled={busy}/></View>
          <View style={{ flex: 1 }}><Button title={busy ? 'Saving…' : submitLabel} disabled={busy || invalid}
            onPress={() => onSubmit(values)}/></View>
        </View>
      </View>
    </View>
  </Modal>;
}

export default function CaseDetailScreen({ fdrId }) {
  const { user } = useAuth();
  const [dialog, setDialog] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [scanState, setScanState] = useState('idle');

  const loadFdr = useCallback(() => api(`/fdrs/${fdrId}`), [fdrId]);
  const loadReport = useCallback(() => api(`/verification/${fdrId}/report`), [fdrId]);
  const fdr = useApiResource(loadFdr);
  const report = useApiResource(loadReport);
  const record = fdr.data;
  const reportData = report.data;

  const comparisons = useMemo(() => {
    if (!record) return [];
    const declared = record.declared_data || {};
    const ocr = record.ocr_data || {};
    const keys = [...new Set([...COMPARE_FIELDS, ...Object.keys(declared), ...Object.keys(ocr)])]
      .filter(key => !key.startsWith('_') && key !== '_confirmed_fields' && key !== '_field_provenance');
    return keys.slice(0, 18).map(key => ({
      key,
      declared: declared[key] ?? declared[String(key)] ?? null,
      extracted: ocr[key] ?? null,
    }));
  }, [record]);

  async function submitDialog(values) {
    if (!dialog || busy) return;
    setBusy(true);
    setError('');
    try {
      if (dialog.type === 'status') {
        await api(`/fdrs/${fdrId}/status`, {
          method: 'PATCH',
          body: { status: dialog.status, remarks: values.remarks.trim() },
        });
      }
      if (dialog.type === 'renewal') {
        await api(`/fdrs/${fdrId}/renewal`, { method: 'POST', body: {
          new_fdr_number: values.new_fdr_number.trim(),
          new_maturity_date: values.new_maturity_date.trim(),
          amount: values.amount.trim(),
        } });
      }
      if (dialog.type === 'release') {
        await api('/refunds', { method: 'POST', body: { fdr_id: Number(fdrId), reason: values.reason.trim() } });
      }
      if (dialog.type === 'resolve') {
        await api(`/verification/discrepancies/${dialog.row.id}/resolve?remarks=${encodeURIComponent(values.remarks.trim())}`,
          { method: 'POST' });
      }
      setDialog(null);
      await Promise.all([fdr.refresh(true), report.refresh(true)]);
    } catch (e) {
      setError(e.message || 'This action could not be completed.');
    } finally {
      setBusy(false);
    }
  }

  async function runVerification() {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await api(`/verification/${fdrId}/run`, { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey() } });
      await Promise.all([fdr.refresh(true), report.refresh(true)]);
    } catch (e) {
      setError(e.message || 'Verification could not be started.');
    } finally {
      setBusy(false);
    }
  }

  async function openScan() {
    if (scanState === 'loading') return;
    setScanState('loading');
    setError('');
    try {
      const result = await api(`/fdrs/${fdrId}/presigned-url`);
      if (result?.url) await Linking.openURL(result.url);
      else throw new Error('No document link is available for this case.');
      setScanState('idle');
    } catch (e) {
      setScanState('error');
      setError(e.message || 'The document link could not be opened.');
    }
  }

  const isOfficial = user.role === 'aicte_official';
  const isOwner = user.role === 'institution';
  const status = record?.status;
  const lifecycle = String(record?.lifecycle_state || status || '').toLowerCase();
  const releaseEligible = status === 'verified' && record?.maturity_date && new Date(record.maturity_date) <= new Date();
  const renewalEligible = ['verified', 'accepted', 'renewal_required'].includes(lifecycle);
  const maturity = record?.maturity_date ? Math.ceil((new Date(record.maturity_date) - new Date()) / 86400000) : null;

  const dialogFields = dialog?.type === 'renewal'
    ? [
        { key: 'new_fdr_number', label: 'New FDR number', required: true },
        { key: 'new_maturity_date', label: 'New maturity date', required: true, placeholder: 'YYYY-MM-DD' },
        { key: 'amount', label: 'Renewed amount', required: true, keyboardType: 'decimal-pad' },
      ]
    : dialog?.type === 'release'
      ? [{ key: 'reason', label: 'Release reason', required: true, multiline: true }]
      : [{ key: 'remarks', label: 'Decision rationale (recorded in the audit trail)', required: true, multiline: true }];

  return <Screen title={record ? `FDR ${record.fdr_number}` : `Case #${fdrId}`}
    subtitle={record ? `${record.bank_name || ''} · ${record.branch || ''}` : 'Fixed deposit case file'}
    onRefresh={() => { fdr.refresh(true); report.refresh(true); }}
    refreshing={fdr.refreshing || report.refreshing}>
    <Stack.Screen options={{ title: record ? record.fdr_number : 'Case file' }}/>

    {fdr.loading
      ? <Loading label="Loading case file"/>
      : fdr.error
        ? <ErrorMessage message={fdr.error} onRetry={() => fdr.refresh(true)}/>
        : <>
          <Card>
            <View style={styles.row}>
              <Text style={[styles.sectionTitle, { flex: 1 }]}>{record.fdr_number}</Text>
              <Badge tone={statusTone(status)}>{String(status || '').replaceAll('_', ' ')}</Badge>
            </View>
            <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
              <Badge tone={record.trust_badge === 'self_declared' ? 'amber' : 'green'}>
                {String(record.trust_badge || '').replaceAll('_', ' ')}
              </Badge>
              {record.is_synthetic ? <Badge tone="amber">Sample data</Badge> : null}
              {maturity !== null ? <Badge tone={maturity <= 0 ? 'green' : maturity <= 30 ? 'amber' : 'neutral'}>
                {maturity <= 0 ? 'Matured' : `Matures in ${maturity} days`}
              </Badge> : null}
            </View>
          </Card>

          <Card>
            <Text style={styles.sectionTitle}>Deposit details</Text>
            <Row label="Bank" value={record.bank_name}/>
            <Row label="Branch" value={record.branch}/>
            <Row label="Amount" value={record.amount != null ? `₹${Number(record.amount).toLocaleString('en-IN')}` : null}/>
            <Row label="Issue date" value={record.issue_date}/>
            <Row label="Maturity date" value={record.maturity_date}/>
            <Row label="Holder" value={record.declared_data?.holder}/>
            <Row label="Institution ID" value={record.institution_id}/>
            <Row label="Replaces case" value={record.replaces_fdr_id ? `FDR #${record.replaces_fdr_id}` : null}/>
          </Card>

          <Card>
            <Text style={styles.sectionTitle}>Case state</Text>
            <Row label="Status" value={record.status}/>
            <Row label="Lifecycle" value={record.lifecycle_state}/>
            <Row label="Execution" value={record.execution_state}/>
            <Row label="Authorization" value={record.authorization_state}/>
            <Row label="Verification level" value={record.verification_level}/>
            <Button title={scanState === 'loading' ? 'Opening scan…' : 'Open uploaded scan'} secondary
              onPress={openScan} disabled={scanState === 'loading'}/>
          </Card>

          <Card>
            <Text style={styles.sectionTitle}>Declared vs extracted</Text>
            <Text style={styles.muted}>Self-declared values are compared with the values read from the uploaded scan.</Text>
            {comparisons.map(item => {
              const differs = item.declared != null && item.extracted != null
                && String(item.declared) !== String(item.extracted);
              return <View key={item.key} style={{ paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.line }}>
                <Text style={styles.label}>{String(item.key).replaceAll('_', ' ')}</Text>
                <Text style={styles.small}>Declared: {item.declared ?? '—'}</Text>
                <Text style={[styles.small, differs && { color: colors.red }]}>
                  Extracted: {item.extracted ?? '—'}{differs ? ' · differs' : ''}
                </Text>
              </View>;
            })}
          </Card>

          {report.loading
            ? <Loading label="Loading verification report"/>
            : report.error
              ? <ErrorMessage message={report.error} onRetry={() => report.refresh(true)}/>
              : <>
                {reportData?.processing ? <Card>
                  <Text style={styles.sectionTitle}>Workflow progress</Text>
                  <Row label="Execution" value={reportData.processing.execution_state}/>
                  <Row label="Current node" value={reportData.processing.current_node}/>
                  <Row label="Last node" value={reportData.processing.last_node}/>
                  <Row label="Extraction" value={reportData.processing.extraction_status}/>
                  <Row label="Confidence" value={reportData.processing.extraction_confidence}/>
                  {reportData.processing.last_error_code
                    ? <Text style={{ color: colors.red, fontSize: 13 }}>{reportData.processing.last_error_code}</Text> : null}
                </Card> : null}

                {reportData?.review_assessment ? <Card>
                  <Text style={styles.sectionTitle}>Advisory review assessment</Text>
                  <Badge tone={reportData.review_assessment.assessment === 'high_risk' ? 'red' : 'amber'}>
                    {String(reportData.review_assessment.assessment || '').replaceAll('_', ' ')}
                  </Badge>
                  <Text style={styles.muted}>{reportData.review_assessment.summary}</Text>
                  <Text style={styles.small}>Advisory only — the official decision is recorded separately.</Text>
                </Card> : null}

                <Card>
                  <Text style={styles.sectionTitle}>Findings ({(reportData?.discrepancies || []).length})</Text>
                  {(reportData?.discrepancies || []).length === 0
                    ? <Text style={styles.muted}>No discrepancies are recorded for this case.</Text>
                    : (reportData.discrepancies).map(item => <View key={item.id}
                        style={{ paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.line }}>
                        <View style={styles.row}>
                          <Text style={[styles.tileTitle, { flex: 1 }]}>{String(item.field).replaceAll('_', ' ')}</Text>
                          <Badge tone={item.resolved ? 'green' : item.severity === 'high' ? 'red' : 'amber'}>
                            {item.resolved ? 'reviewed' : item.severity}
                          </Badge>
                        </View>
                        <Text style={styles.small}>Declared: {item.declared_value ?? '—'} · Extracted: {item.extracted_value ?? '—'} · {item.source}</Text>
                        {isOfficial && !item.resolved
                          ? <Button title="Mark reviewed" compact secondary
                              onPress={() => { setError(''); setDialog({ type: 'resolve', row: item }); }}/>
                          : null}
                      </View>)}
                </Card>
              </>}

          <Card>
            <Text style={styles.sectionTitle}>Actions</Text>
            {error ? <Text style={{ color: colors.red, fontSize: 13 }}>{error}</Text> : null}
            {isOfficial ? <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
              <Button title="Run verification" secondary onPress={runVerification} disabled={busy}/>
              {(OFFICIAL_NEXT[status] || []).map(([label, next]) => <Button key={next} title={label}
                danger={next === 'mismatch'} secondary={next === 'under_scrutiny'}
                onPress={() => { setError(''); setDialog({ type: 'status', status: next, title: label }); }}
                disabled={busy}/>)}
            </View> : null}
            {isOwner ? <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
              {releaseEligible ? <Button title="Request release" onPress={() => { setError(''); setDialog({ type: 'release' }); }} disabled={busy}/> : null}
              {renewalEligible ? <Button title="Request renewal" secondary onPress={() => { setError(''); setDialog({ type: 'renewal' }); }} disabled={busy}/> : null}
              {!releaseEligible && !renewalEligible
                ? <Text style={styles.muted}>Release and renewal become available once this case is verified.</Text>
                : null}
            </View> : null}
            {!isOfficial && !isOwner ? <Text style={styles.muted}>This account has read-only access to case files.</Text> : null}
            <Button title="Back to portal" secondary onPress={() => router.back()}/>
          </Card>
        </>}

    {dialog ? <DecisionModal
      key={`${dialog.type}-${dialog.row?.id || dialog.status || ''}`}
      title={dialog.type === 'renewal' ? 'Request renewal'
        : dialog.type === 'release' ? 'Request release'
        : dialog.type === 'resolve' ? 'Mark finding as reviewed'
        : dialog.title}
      fields={dialogFields}
      submitLabel={dialog.type === 'status' && dialog.status === 'mismatch' ? 'Request correction' : 'Confirm'}
      error={error} busy={busy}
      onClose={() => { setDialog(null); setError(''); }}
      onSubmit={submitDialog}/> : null}
  </Screen>;
}

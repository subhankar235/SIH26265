import { useCallback, useMemo, useState } from 'react';
import { Alert, Modal, ScrollView, Text, View } from 'react-native';
import { router } from 'expo-router';
import { api } from '../lib/api';
import { extractRows, recordSubtitle, recordTitle } from '../lib/screens';
import { Badge, Button, Card, Empty, ErrorMessage, Field, Loading, Screen, colors, styles, useApiResource } from '../components/ui';

const idempotencyKey = () => `${Date.now()}-${Math.random().toString(36).slice(2, 18)}`;

const OPEN_STATES = ['submitted', 'extraction_pending', 'extracting', 'validation_pending', 'validation_failed',
  'correction_required', 'awaiting_institution', 'under_scrutiny', 'under_review', 'mismatch',
  'ready_for_scrutiny', 'awaiting_official_decision'];

function statusTone(status) {
  const value = String(status || '').toLowerCase();
  if (['active', 'approved', 'resolved', 'completed', 'succeeded', 'verified', 'queued', 'delivered', 'healthy'].includes(value)) return 'green';
  if (['failed', 'rejected', 'dead', 'mismatch', 'disabled', 'suspended', 'expired', 'critical'].includes(value)) return 'red';
  if (!value) return 'neutral';
  return 'amber';
}

function ActionModal({ title, reasonLabel, reasonRequired = true, onClose, onSubmit, busy, error }) {
  const [reason, setReason] = useState('');
  const disabled = busy || (reasonRequired && reason.trim().length < 4);
  return <Modal visible transparent animationType="slide" onRequestClose={onClose}>
    <View style={styles.modalBackdrop}>
      <View style={styles.modal}>
        <Text style={styles.modalTitle}>{title}</Text>
        {reasonRequired ? <Field label={reasonLabel || 'Reason (recorded in the audit trail)'} value={reason}
          onChangeText={setReason} multiline/> : null}
        {error ? <Text style={{ color: colors.red, fontSize: 13 }}>{error}</Text> : null}
        <View style={{ flexDirection: 'row', gap: 9 }}>
          <View style={{ flex: 1 }}><Button title="Cancel" secondary onPress={onClose} disabled={busy}/></View>
          <View style={{ flex: 1 }}><Button title={busy ? 'Saving…' : 'Confirm'} disabled={disabled} onPress={() => onSubmit(reason.trim())}/></View>
        </View>
      </View>
    </View>
  </Modal>;
}

function ScalarDetails({ row }) {
  const entries = Object.entries(row)
    .filter(([key, value]) => !['id', 'label', 'status'].includes(key)
      && ['string', 'number', 'boolean'].includes(typeof value) && value !== null && value !== '')
    .slice(0, 14);
  if (!entries.length) return null;
  return <View style={{ gap: 3 }}>
    {entries.map(([key, value]) => <View key={key} style={styles.row}>
      <Text style={[styles.small, { flex: 1 }]}>{String(key).replaceAll('_', ' ')}</Text>
      <Text style={[styles.small, { color: colors.ink, fontWeight: '600', flexShrink: 1, textAlign: 'right' }]}>
        {String(value)}
      </Text>
    </View>)}
  </View>;
}

function ItemCard({ row, kind, onAction }) {
  const title = recordTitle(row, kind);
  const subtitle = recordSubtitle(row);
  const buttons = [];
  const openCase = () => router.push({ pathname: '/(portal)/case/[id]', params: { id: String(row.fdr_id ?? row.id) } });

  if (['fdrs', 'queue', 'renewals'].includes(kind) && (row.fdr_id || row.id != null)) buttons.push(['Open case', openCase]);
  if (kind === 'renewals') buttons.push(['Request renewal', openCase]);
  if (kind === 'discrepancies') {
    if (row.fdr_id) buttons.push(['Open case', openCase]);
    if (!row.resolved) buttons.push(['Mark reviewed', () => onAction({ kind: 'resolve-discrepancy', row })]);
  }
  if (kind === 'releases' && row.fdr_id) buttons.push(['Open case', openCase]);
  if (['registrations', 'registrations-admin', 'official-registrations'].includes(kind)) {
    const resource = kind === 'registrations' ? 'institution' : kind === 'registrations-admin' ? 'institution-admin' : 'official-admin';
    buttons.push(['Approve', () => onAction({ kind: 'registration', row, resource, decision: 'approve' })]);
    buttons.push(['Reject', () => onAction({ kind: 'registration', row, resource, decision: 'reject' })]);
  }
  if (kind === 'approvals' && String(row.status).toLowerCase() === 'pending') {
    buttons.push(['Approve release', () => onAction({ kind: 'refund-decision', row, decision: 'approve' })]);
    buttons.push(['Reject release', () => onAction({ kind: 'refund-decision', row, decision: 'reject' })]);
  }
  if (kind === 'users') {
    if (row.status === 'active') buttons.push(['Disable', () => onAction({ kind: 'user-action', row, action: 'disable' })]);
    else if (['disabled', 'suspended'].includes(row.status)) buttons.push(['Enable', () => onAction({ kind: 'user-action', row, action: 'enable' })]);
    if (row.status === 'locked') buttons.push(['Unlock', () => onAction({ kind: 'user-action', row, action: 'unlock' })]);
  }
  if (kind === 'jobs' && row.row_type === 'outbox' && row.id != null) {
    buttons.push(['Requeue', () => Alert.alert('Requeue failed work?',
      `Requeue outbox event ${row.id}? It will be scheduled for another attempt.`, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Requeue', onPress: () => onAction({ kind: 'requeue', row }) },
      ])]);
  }
  if (kind === 'alerts' && row.notification_id && String(row.status).toLowerCase() === 'failed') {
    buttons.push(['Retry delivery', () => onAction({ kind: 'retry-notification', row })]);
  }
  if (kind === 'exceptions') {
    if (row.status === 'open') buttons.push(['Claim', () => onAction({ kind: 'claim-exception', row })]);
    if (row.status === 'claimed') {
      buttons.push(['Approve', () => onAction({ kind: 'decide-exception', row, decision: 'approve' })]);
      buttons.push(['Request correction', () => onAction({ kind: 'decide-exception', row, decision: 'request_correction' })]);
      buttons.push(['Escalate', () => onAction({ kind: 'decide-exception', row, decision: 'escalate' })]);
    }
  }

  const showScalars = kind === 'health' || (!subtitle && !row.field
    && Object.values(row).some(value => ['string', 'number', 'boolean'].includes(typeof value)));

  return <Card>
    <View style={styles.row}>
      <Text style={[styles.sectionTitle, { flex: 1 }]}>{title}</Text>
      {row.status ? <Badge tone={statusTone(row.status)}>{String(row.status).replaceAll('_', ' ')}</Badge> : null}
    </View>
    {subtitle ? <Text style={styles.muted}>{subtitle}</Text> : null}
    {row.description ? <Text style={styles.muted}>{row.description}</Text> : null}
    {row.message ? <Text style={styles.muted}>{row.message}</Text> : null}
    {row.recipient ? <Text style={styles.small}>{row.channel ? `${String(row.channel).toUpperCase()} · ` : ''}{row.recipient}</Text> : null}
    {row.recommendation ? <View style={styles.notice}><Text style={styles.noticeText}>{row.recommendation} · advisory only</Text></View> : null}
    {row.error_message ? <Text style={{ color: colors.red, fontSize: 13 }}>{row.error_message}</Text> : null}
    {row.error ? <Text style={{ color: colors.red, fontSize: 13 }}>{row.error}</Text> : null}
    {row.last_error ? <Text style={{ color: colors.red, fontSize: 13 }}>{row.last_error}</Text> : null}
    {row.field ? <Text style={styles.muted}>Declared: {row.declared_value ?? 'Not recorded'} · Found: {row.extracted_value ?? 'Not recorded'} · {row.source}</Text> : null}
    {showScalars ? <ScalarDetails row={row}/> : null}
    {row.created_at || row.scheduled_at || row.finished_at || row.sent_at
      ? <Text style={styles.small}>{new Date(row.created_at || row.scheduled_at || row.finished_at || row.sent_at).toLocaleString()}</Text> : null}
    {buttons.length > 0 ? <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 7, marginTop: 3 }}>
      {buttons.map(([label, onPress], index) => <Button key={`${label}-${index}`} title={label} onPress={onPress}
        compact secondary={!['Reject release', 'Reject', 'Disable', 'Escalate'].includes(label)}
        danger={['Reject release', 'Reject', 'Disable', 'Escalate'].includes(label)}/>)}
    </View> : null}
  </Card>;
}

function CreateRecordModal({ kind, onClose, onDone }) {
  const [values, setValues] = useState({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const fields = kind === 'users'
    ? [['full_name', 'Full name'], ['email', 'Email address'], ['role', 'Role (institution / aicte_official / admin)'], ['institution_id', 'Institution ID (required for institution accounts)']]
    : kind === 'institutions'
      ? [['aicte_id', 'AICTE institution ID'], ['name', 'Institution name'], ['state', 'State'], ['head_name', 'Contact person'],
        ['contact_email', 'Contact email'], ['contact_phone', 'Contact phone']]
      : kind === 'rules'
        ? [['rule_key', 'Rule key'], ['description', 'Description'], ['policy', 'Policy JSON']]
        : [['recipient', 'Recipient email address']];
  const required = fields.filter(([key]) => !(kind === 'users' && key === 'institution_id'));

  async function submit() {
    setBusy(true);
    setError('');
    try {
      if (kind === 'users') {
        await api('/admin/users', { method: 'POST', body: {
          full_name: values.full_name.trim(),
          email: values.email.trim(),
          role: values.role.trim(),
          institution_id: values.institution_id ? Number(values.institution_id) : null,
        } });
      }
      if (kind === 'institutions') await api('/institutions', { method: 'POST', body: values });
      if (kind === 'rules') {
        let policy;
        try { policy = JSON.parse(values.policy || '{}'); } catch { throw new Error('Policy must be valid JSON.'); }
        await api('/admin/rules', { method: 'POST', body: { rule_key: values.rule_key, description: values.description, policy } });
      }
      if (kind === 'alerts') {
        await api('/admin/operations/actions/send-test-alert', { method: 'POST', body: {
          channel: 'email', recipient: values.recipient.trim(), confirmed: true,
        } });
      }
      onDone();
    } catch (e) {
      setError(e.message || 'This record could not be saved.');
    } finally {
      setBusy(false);
    }
  }

  const heading = kind === 'users' ? 'Invite a portal account' : kind === 'institutions' ? 'Create an institution'
    : kind === 'rules' ? 'Create an automation rule' : 'Send a test alert';

  return <Modal visible transparent animationType="slide" onRequestClose={onClose}>
    <View style={styles.modalBackdrop}>
      <View style={[styles.modal, { maxHeight: '88%' }]}>
        <Text style={styles.modalTitle}>{heading}</Text>
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: 2 }}>
          {fields.map(([key, label]) => <Field key={key} label={label} value={values[key] || ''}
            onChangeText={value => setValues(current => ({ ...current, [key]: value }))}
            multiline={key === 'policy'}
            keyboardType={['email', 'contact_email', 'recipient'].includes(key) ? 'email-address' : 'default'}
            autoCapitalize="none"/>)}
          {error ? <Text style={{ color: colors.red, fontSize: 13 }}>{error}</Text> : null}
          <View style={{ flexDirection: 'row', gap: 9, marginTop: 6 }}>
            <View style={{ flex: 1 }}><Button title="Cancel" secondary onPress={onClose} disabled={busy}/></View>
            <View style={{ flex: 1 }}>
              <Button title={busy ? 'Saving…' : 'Save'} disabled={busy || required.some(([key]) => !String(values[key] || '').trim())}
                onPress={submit}/>
            </View>
          </View>
        </ScrollView>
      </View>
    </View>
  </Modal>;
}

export default function RecordScreen({ screenKey, definition, user }) {
  const load = useCallback(() => api(definition.endpoint), [definition.endpoint]);
  const resource = useApiResource(load, screenKey === 'queue' ? 10000 : 0);
  const [action, setAction] = useState(null);
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState(false);
  const [create, setCreate] = useState(false);

  const rows = useMemo(() => extractRows(resource.data, definition.kind), [resource.data, definition.kind]);
  const visible = screenKey === 'queue'
    ? rows.filter(row => OPEN_STATES.includes(String(row.lifecycle_state || row.status || '').toLowerCase()))
    : definition.kind === 'renewals'
      ? rows.filter(row => ['verified', 'accepted', 'renewal_required']
        .includes(String(row.lifecycle_state || row.status || '').toLowerCase())
        && !rows.some(other => other.replaces_fdr_id === row.id))
      : rows;

  async function runAction(reason = '') {
    if (!action) return;
    setBusy(true);
    setActionError('');
    const { row } = action;
    try {
      if (action.kind === 'resolve-discrepancy') {
        await api(`/verification/discrepancies/${row.id}/resolve?remarks=${encodeURIComponent(reason || 'Reviewed in the mobile portal')}`,
          { method: 'POST' });
      }
      if (action.kind === 'registration') {
        if (action.resource === 'institution') {
          await api(`/institutions/registrations/${row.id}/decision`, {
            method: 'POST', body: { decision: action.decision, reason },
          });
        } else {
          await api(`/admin/${action.resource === 'institution-admin' ? 'registrations' : 'official-registrations'}/${row.id}/${action.decision}`,
            { method: 'POST', body: { reason } });
        }
      }
      if (action.kind === 'refund-decision') {
        await api(`/refunds/${row.id}/decision`, {
          method: 'POST',
          body: { decision: action.decision === 'approve' ? 'approved' : 'rejected', remarks: reason, idempotency_key: idempotencyKey() },
        });
      }
      if (action.kind === 'user-action') {
        await api(`/admin/users/${row.id}/${action.action}`, { method: 'POST' });
      }
      if (action.kind === 'requeue') {
        await api('/admin/operations/actions/requeue-failed-job', {
          method: 'POST', body: { outbox_id: Number(row.id), confirmed: true },
        });
      }
      if (action.kind === 'retry-notification') {
        await api(`/notifications/${row.notification_id}/retry`, {
          method: 'POST', headers: { 'Idempotency-Key': idempotencyKey() },
        });
      }
      if (action.kind === 'claim-exception') {
        await api(`/workflows/exceptions/${row.id}/claim`, {
          method: 'POST', body: { reason: reason || 'Claimed from the mobile portal', idempotency_key: idempotencyKey() },
        });
      }
      if (action.kind === 'decide-exception') {
        await api(`/workflows/exceptions/${row.id}/decision`, {
          method: 'POST',
          body: { decision: action.decision, rationale: reason, idempotency_key: idempotencyKey() },
        });
      }
      setAction(null);
      await resource.refresh(true);
    } catch (e) {
      setActionError(e.message || 'This action could not be completed.');
    } finally {
      setBusy(false);
    }
  }

  const createLabels = {
    users: 'Invite account',
    institutions: 'Create institution',
    rules: 'Create rule',
    alerts: 'Send test alert',
  };
  const canCreate = ['users', 'institutions', 'rules', 'alerts'].includes(screenKey) && user.role === 'admin';

  const actionTitles = {
    'resolve-discrepancy': 'Mark finding as reviewed',
    'refund-decision': `${action?.decision === 'approve' ? 'Approve' : 'Reject'} release request`,
    registration: `${action?.decision === 'approve' ? 'Approve' : 'Reject'} application`,
    'user-action': `${action?.action === 'enable' ? 'Enable' : action?.action === 'unlock' ? 'Unlock' : 'Disable'} account`,
    requeue: 'Requeue failed work',
    'retry-notification': 'Retry notification delivery',
    'claim-exception': 'Claim exception',
    'decide-exception': 'Record exception decision',
  };

  return <Screen title={definition.title} subtitle={definition.description}
    onRefresh={() => resource.refresh(true)} refreshing={resource.refreshing}>
    {canCreate ? <Button title={createLabels[screenKey]} secondary onPress={() => setCreate(true)}/> : null}
    {resource.loading
      ? <Loading label={`Loading ${definition.title.toLowerCase()}`}/>
      : resource.error
        ? <ErrorMessage message={resource.error} onRetry={() => resource.refresh(true)}/>
        : visible.length === 0
          ? <Empty title={`No ${definition.title.toLowerCase()} to show`}
              message={screenKey === 'queue'
                ? 'Cases awaiting official scrutiny appear here as institutions submit them.'
                : 'Nothing is currently returned for your account.'}/>
          : visible.slice(0, 100).map((row, index) => <ItemCard key={row.id ?? row.attempt_id ?? row.fdr_id ?? index}
              row={row} kind={definition.kind} onAction={setAction}/>)}
    {action && <ActionModal key={`${action.kind}-${action.row?.id}-${action.decision || action.action || ''}`}
      title={actionTitles[action.kind] || 'Confirm action'}
      reasonLabel={action.kind === 'claim-exception' ? 'Why are you claiming this exception?' : undefined}
      reasonRequired={!['user-action', 'requeue', 'retry-notification'].includes(action.kind)}
      error={actionError}
      busy={busy}
      onClose={() => { setAction(null); setActionError(''); }}
      onSubmit={runAction}/>}
    {create && <CreateRecordModal kind={screenKey} onClose={() => setCreate(false)}
      onDone={() => { setCreate(false); resource.refresh(true); }}/>}
  </Screen>;
}

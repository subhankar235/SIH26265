import { useState } from 'react';
import { Text, View } from 'react-native';
import { api } from '../lib/api';
import { Button, Card, Field, Screen, colors, styles } from '../components/ui';

const idempotencyKey = () => `${Date.now()}-${Math.random().toString(36).slice(2, 18)}`;

export default function CommandScreen() {
  const [command, setCommand] = useState('');
  const [plan, setPlan] = useState(null);
  const [reply, setReply] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function interpret() {
    const text = command.trim();
    if (!text || busy) return;
    setBusy(true);
    setError('');
    try {
      const result = await api('/commands/interpret', {
        method: 'POST',
        body: { text, idempotency_key: idempotencyKey() },
      });
      if (result.mode === 'chat') {
        setReply(result.reply);
        setPlan(null);
      } else {
        setReply('');
        setPlan(result);
      }
    } catch (e) {
      setError(e.message || 'The request could not be interpreted.');
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!plan || busy) return;
    setBusy(true);
    setError('');
    try {
      const result = await api(`/commands/${plan.command_id}/confirm`, {
        method: 'POST',
        body: { plan_hash: plan.plan_hash },
      });
      setReply(result.result_summary || `Command status: ${result.status}`);
      setPlan(null);
      setCommand('');
    } catch (e) {
      setError(e.message || 'The command could not be confirmed.');
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!plan || busy) return;
    setBusy(true);
    setError('');
    try {
      await api(`/commands/${plan.command_id}/cancel`, {
        method: 'POST',
        body: { reason: 'Cancelled from the mobile portal.' },
      });
      setPlan(null);
    } catch (e) {
      setError(e.message || 'The command could not be cancelled.');
    } finally {
      setBusy(false);
    }
  }

  return <Screen title="Command Center" subtitle="Commands are checked against your role and may require confirmation before anything runs.">
    <Card>
      <Field label="What would you like to do?" value={command} onChangeText={setCommand}
        multiline placeholder="Ask about an FDR, list maturing cases, or request an allowed action"/>
      <Button title={busy ? 'Checking…' : 'Review request'} onPress={interpret} disabled={busy || !command.trim()}/>
      {reply ? <View style={styles.notice}><Text style={styles.noticeText}>{reply}</Text></View> : null}
      {plan ? <View style={styles.notice}>
        <Text style={[styles.noticeText, { fontWeight: '700' }]}>Proposed actions</Text>
        <Text style={[styles.noticeText, { marginTop: 4 }]}>Status: {String(plan.status).replaceAll('_', ' ')}</Text>
        {(plan.plan || []).map((step, index) => <View key={index} style={{ marginTop: 6 }}>
          <Text style={styles.noticeText}>
            {index + 1}. {step.effect_summary || step.tool} · {step.requires_confirmation ? 'Confirmation required' : 'Read only'}
          </Text>
          {(step.resolved_targets || []).map((target, targetIndex) => <Text key={targetIndex} style={[styles.noticeText, { marginTop: 2 }]}>
            · {target.fdr_number || (target.fdr_id != null && `FDR #${target.fdr_id}`) || target.workflow_id != null && `Workflow #${target.workflow_id}` || target.error || 'Matched record'}
            {target.lifecycle_state ? ` · ${String(target.lifecycle_state).replaceAll('_', ' ')}` : ''}
            {target.error ? ` · ${target.error}` : ''}
          </Text>)}
        </View>)}
        {(plan.warnings || []).map((warning, index) => <Text key={`w${index}`} style={{ color: colors.amber, marginTop: 6, fontSize: 13 }}>{warning}</Text>)}
        {plan.result_summary ? <View style={[styles.notice, { marginTop: 6 }]}><Text style={styles.noticeText}>{plan.result_summary}</Text></View> : null}
        <View style={{ flexDirection: 'row', gap: 8, marginTop: 6 }}>
          {plan.requires_confirmation ? <>
            <View style={{ flex: 1 }}><Button title="Cancel" secondary onPress={cancel} disabled={busy}/></View>
            <View style={{ flex: 1 }}><Button title="Confirm and run" onPress={confirm} disabled={busy}/></View>
          </> : <View style={{ flex: 1 }}>
            <Button title="Done" secondary onPress={() => { setPlan(null); setCommand(''); }} disabled={busy}/>
          </View>}
        </View>
      </View> : null}
      {error ? <Text style={{ color: colors.red, fontSize: 13 }}>{error}</Text> : null}
    </Card>
    <Text style={styles.muted}>Read-only questions answer immediately. Actions are staged as a plan first, so nothing changes without your confirmation.</Text>
  </Screen>;
}

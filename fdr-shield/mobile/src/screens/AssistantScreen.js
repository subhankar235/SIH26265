import { useState } from 'react';
import { Text, View } from 'react-native';
import { api } from '../lib/api';
import { Button, Card, Field, Screen, colors, styles } from '../components/ui';

export default function AssistantScreen() {
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function send() {
    const current = message.trim();
    if (!current || busy) return;
    setError('');
    setMessage('');
    setMessages(items => [...items, { role: 'user', text: current }]);
    setBusy(true);
    try {
      const result = await api('/institution/assistant/messages', { method: 'POST', body: { message: current } });
      setMessages(items => [...items, { role: 'assistant', text: result.reply, next_action: result.next_action }]);
    } catch (e) {
      setError(e.message || 'The assistant could not answer right now.');
    } finally {
      setBusy(false);
    }
  }

  return <Screen title="Institution assistant" subtitle="Answers are scoped to your own institution’s cases.">
    <Card>
      {messages.length === 0
        ? <Text style={styles.muted}>Ask about your FDR status, recorded discrepancies, maturity deadlines, renewals, or release requirements.</Text>
        : messages.map((item, index) => <View key={index} style={[styles.notice, { backgroundColor: item.role === 'user' ? '#F1F4F8' : '#EBF3FF' }]}>
            <Text style={styles.noticeText}>{item.text}</Text>
            {item.next_action ? <Text style={[styles.small, { marginTop: 6 }]}>Next action: {item.next_action}</Text> : null}
          </View>)}
      <Field label="Message" value={message} onChangeText={setMessage} multiline placeholder="Ask about one of your cases"/>
      {error ? <Text style={{ color: colors.red, fontSize: 13 }}>{error}</Text> : null}
      <Button title={busy ? 'Checking records…' : 'Send'} onPress={send} disabled={busy || !message.trim()}/>
    </Card>
    <Text style={styles.muted}>The assistant never makes decisions on your behalf; every case change still goes through the audited portal workflow.</Text>
  </Screen>;
}

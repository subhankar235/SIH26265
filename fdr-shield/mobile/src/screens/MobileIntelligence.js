import { useCallback } from 'react';
import { Pressable, Text, View } from 'react-native';
import { router } from 'expo-router';
import { api } from '../lib/api';
import { Badge, Button, Card, ErrorMessage, Loading, Screen, colors, styles, useApiResource } from '../components/ui';

export default function MobileIntelligence() {
  const loadCapabilities = useCallback(() => api('/admin/intelligence/capabilities'), []);
  const loadFindings = useCallback(() => api('/verification/discrepancies?real_only=true&resolved=false&page=1&size=20'), []);
  const capabilities = useApiResource(loadCapabilities, 30000);
  const findings = useApiResource(loadFindings, 30000);
  const items = findings.data?.items || [];

  return <Screen title="ML Governance" subtitle="FDR verification assistance with official review and decisions preserved."
    onRefresh={() => { capabilities.refresh(true); findings.refresh(true); }}
    refreshing={capabilities.refreshing || findings.refreshing}>
    {capabilities.loading
      ? <Loading label="Loading capability status"/>
      : capabilities.error
        ? <ErrorMessage message={capabilities.error} onRetry={() => capabilities.refresh(true)}/>
        : <View style={styles.grid}>{(capabilities.data?.capabilities || []).map(item => <Card key={item.id} style={{ width: '48%' }}>
            <Text style={styles.sectionTitle}>{String(item.id).replaceAll('_', ' ')}</Text>
            <Badge tone={item.status === 'available' ? 'green' : item.status === 'unknown' ? 'amber' : 'neutral'}>{item.status}</Badge>
            <Text style={styles.small}>{item.message}</Text>
          </Card>)}</View>}

    <Card>
      <Text style={styles.sectionTitle}>Recent case findings</Text>
      {findings.loading
        ? <Loading label="Loading recent findings"/>
        : findings.error
          ? <ErrorMessage message={findings.error} onRetry={() => findings.refresh(true)}/>
          : items.length === 0
            ? <Text style={styles.muted}>No unresolved real-origin findings are currently available.</Text>
            : items.map(item => <Pressable key={item.id} onPress={() => router.push(`/(portal)/case/${item.fdr_id}`)}
                style={{ paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.line }}>
                <Text style={styles.tileTitle}>{item.fdr_number} · {String(item.field).replaceAll('_', ' ')}</Text>
                <Text style={styles.muted}>{item.institution_name} · {item.severity} · {item.resolved ? 'Reviewed' : 'Pending review'}</Text>
              </Pressable>)}
    </Card>

    <Card>
      <Text style={styles.sectionTitle}>Responsible review</Text>
      <Text style={styles.muted}>Findings support review; authorized officials retain every decision. When automated analysis is unavailable, the established manual scrutiny workflow remains in force.</Text>
      <Button title="Refresh findings" secondary onPress={() => { capabilities.refresh(true); findings.refresh(true); }}/>
    </Card>
  </Screen>;
}

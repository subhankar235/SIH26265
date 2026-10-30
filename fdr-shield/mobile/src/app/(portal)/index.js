import { useCallback } from 'react';
import { Pressable, Text, View } from 'react-native';
import { router } from 'expo-router';
import { api } from '../../lib/api';
import { menuForRole, ROLE_LABELS } from '../../lib/portal';
import { Badge, Button, Card, ErrorMessage, Loading, Screen, colors, styles, useApiResource } from '../../components/ui';
import { useAuth } from '../../providers/AuthProvider';

const METRIC_KEYS = [
  ['total_active_value', 'Active deposit value', true],
  ['expiring_30d', 'Maturing in 30 days'],
  ['pending_verifications', 'Pending verification'],
  ['discrepancies_flagged', 'Flagged discrepancies'],
  ['synthetic_records', 'Sample records'],
  ['unclassified_records', 'Unclassified records'],
];

function ChartList({ label, points, money }) {
  if (!Array.isArray(points) || !points.length) return null;
  return <View style={{ gap: 4 }}>
    <Text style={styles.label}>{label}</Text>
    {points.slice(0, 8).map(point => <View key={point.label} style={styles.row}>
      <Text style={[styles.small, { flex: 1 }]}>{String(point.label).replaceAll('_', ' ')}</Text>
      <Text style={[styles.small, { color: colors.ink, fontWeight: '700' }]}>
        {money ? `₹${Number(point.value).toLocaleString('en-IN')}` : point.value}
      </Text>
    </View>)}
  </View>;
}

function DashboardMetrics({ data }) {
  const metrics = data?.metrics || {};
  const entries = METRIC_KEYS.filter(([key]) => metrics[key] !== undefined);
  const breakdown = Array.isArray(data?.status_breakdown) ? data.status_breakdown : [];
  return <>
    {entries.length
      ? <View style={styles.grid}>{entries.map(([key,label,money]) => <View key={key} style={styles.kpi}>
          <Text style={styles.kpiValue}>{money ? `₹${Number(metrics[key]).toLocaleString('en-IN')}` : String(metrics[key])}</Text>
          <Text style={styles.kpiLabel}>{label}</Text>
        </View>)}</View>
      : <Text style={styles.muted}>Portal metrics are not available right now.</Text>}
    <ChartList label="Cases by status" points={breakdown}/>
    <ChartList label="Value by bank" points={data?.value_by_bank} money/>
    <ChartList label="Maturity timeline" points={data?.maturity_timeline}/>
  </>;
}

export default function PortalHome() {
  const { user, signOut } = useAuth();
  const endpoint = user?.role === 'institution' ? '/dashboard/institution' : '/dashboard/bureau';
  const load = useCallback(() => api(endpoint), [endpoint]);
  const dashboard = useApiResource(load, 30000);
  const items = menuForRole(user?.role).filter(item => item.key !== 'home');
  const groups = [...new Set(items.map(item => item.group))];

  return <Screen title="Security Deposit Portal" subtitle={`${ROLE_LABELS[user?.role]||'Portal'} · Hello, ${user?.full_name||user?.email||'User'}`}
    onRefresh={() => dashboard.refresh(true)} refreshing={dashboard.refreshing}>
    <View style={{flexDirection:'row',alignItems:'center',justifyContent:'space-between'}}><Badge tone="green">Signed in · {user?.role}</Badge><Pressable onPress={signOut}><Text style={{color:colors.blue,fontWeight:'700'}}>Sign out</Text></Pressable></View>
    {dashboard.loading?<Loading label="Loading your current portal data"/>:dashboard.error?<ErrorMessage message={dashboard.error} onRetry={() => dashboard.refresh(true)}/>:<Card><Text style={styles.sectionTitle}>Portfolio overview</Text><DashboardMetrics data={dashboard.data}/></Card>}
    {groups.map(group=><View key={group} style={{gap:9}}><Text style={styles.sectionTitle}>{group}</Text>{items.filter(item=>item.group===group).map(item=><Pressable key={item.key} onPress={()=>item.key==='upload'?router.push('/(portal)/upload'):router.push({pathname:'/(portal)/screen/[key]',params:{key:item.key}})} style={({pressed})=>[styles.card,pressed&&{opacity:.75}]}><View style={styles.row}><Text style={styles.tileTitle}>{item.title}</Text><Text style={styles.link}>Open ›</Text></View><Text style={styles.muted}>{item.description}</Text></Pressable>)}</View>)}
    {user?.must_change_password&&<Button title="Change required password" onPress={()=>router.push('/change-password')}/>}
  </Screen>;
}

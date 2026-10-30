import { getRoleScreens } from './portal';

export function menuForRole(role) {
  const roleScreens = getRoleScreens(role);
  const common = [{ key: 'home', title: 'Overview', description: 'Your portal summary and quick actions.', group: 'Home' }];
  if (role === 'institution') common.push({ key: 'upload', title: 'Submit FDR', description: 'Upload a receipt, verify extracted fields, and submit.', group: 'FDR services' });
  return [...common, ...roleScreens];
}

export const SCREEN_CONFIG = {
  fdrs: { endpoint: '/fdrs', title: 'FDR records', roles: ['institution','aicte_official','admin'], kind: 'fdrs' },
  queue: { endpoint: '/fdrs', title: 'Scrutiny queue', roles: ['aicte_official','admin'], kind: 'queue' },
  discrepancies: { endpoint: '/verification/discrepancies', title: 'Discrepancy board', roles: ['aicte_official','admin'], kind: 'discrepancies' },
  registrations: { endpoint: '/institutions/registrations', title: 'Institution applications', roles: ['aicte_official'], kind: 'registrations' },
  approvals: { endpoint: '/refunds?status=pending', title: 'Release approvals', roles: ['aicte_official'], kind: 'approvals' },
  releases: { endpoint: '/refunds', title: 'Release requests', roles: ['institution'], kind: 'releases' },
  notifications: { endpoint: '/notifications', title: 'Notifications', roles: ['institution'], kind: 'notifications' },
  renewals: { endpoint: '/fdrs', title: 'Renewals', roles: ['institution'], kind: 'renewals' },
  institutions: { endpoint: '/institutions', title: 'Institutions', roles: ['aicte_official','admin'], kind: 'institutions' },
  users: { endpoint: '/admin/users', title: 'User accounts', roles: ['admin'], kind: 'users' },
  roles: { endpoint: '/admin/users', title: 'Role assignments', roles: ['admin'], kind: 'users' },
  'admin-institutions': { endpoint: '/admin/registrations?include_decided=true', title: 'Institution applications', roles: ['admin'], kind: 'registrations-admin' },
  'admin-officials': { endpoint: '/admin/official-registrations?include_decided=true', title: 'Official applications', roles: ['admin'], kind: 'official-registrations' },
  rules: { endpoint: '/admin/rules', title: 'Automation rules', roles: ['admin'], kind: 'rules' },
  alerts: { endpoint: '/admin/notification-deliveries', title: 'Alerts and delivery', roles: ['admin'], kind: 'alerts' },
  jobs: { endpoint: '/admin/operations/failed-jobs', title: 'Failed jobs', roles: ['admin'], kind: 'jobs' },
  health: { endpoint: '/admin/operations/health', title: 'System health', roles: ['admin'], kind: 'health' },
  'ops-agent': { endpoint: '/admin/operations/recovery-recommendations', title: 'Recovery recommendations', roles: ['admin'], kind: 'ops' },
  audit: { endpoint: '/audit', title: 'Audit trail', roles: ['aicte_official','admin'], kind: 'audit' },
  workflows: { endpoint: '/workflows/control-room/summary', title: 'Workflow control room', roles: ['aicte_official','admin'], kind: 'workflows' },
  exceptions: { endpoint: '/workflows/exceptions?status=open', title: 'Exception inbox', roles: ['aicte_official','admin'], kind: 'exceptions' },
  'ml-governance': { endpoint: '/admin/intelligence/capabilities', title: 'ML Governance', roles: ['admin'], kind: 'ml-governance' },
  assistant: { title: 'Institution assistant', roles: ['institution'], kind: 'assistant' },
  command: { title: 'Command Center', roles: ['institution','aicte_official','admin'], kind: 'command' },
  password: { title: 'Change password', roles: ['institution','aicte_official','admin'], kind: 'password' },
};

export function extractRows(data, kind) {
  if (Array.isArray(data)) return data;
  if (!data || typeof data !== 'object') return [];
  if (kind === 'jobs') {
    const outbox = (Array.isArray(data.dead_outbox_events) ? data.dead_outbox_events : [])
      .map(row => ({ ...row, row_type: 'outbox' }));
    const nodes = (Array.isArray(data.failed_node_executions) ? data.failed_node_executions : [])
      .map(row => ({ ...row, row_type: 'node' }));
    if (outbox.length || nodes.length) return [...outbox, ...nodes];
  }
  if (Array.isArray(data.items)) return data.items;
  if (Array.isArray(data.recommendations)) return data.recommendations;
  if (Array.isArray(data.failed_node_executions)) return data.failed_node_executions;
  if (kind === 'health') {
    const summary = {
      id: 'health-summary',
      label: 'System health',
      status: String(data.status || (data.healthy ? 'HEALTHY' : 'ATTENTION')).toLowerCase(),
      breach_count: data.breach_count,
      ...(data.metrics && typeof data.metrics === 'object'
        ? Object.fromEntries(Object.entries(data.metrics).filter(([, value]) => typeof value === 'number'))
        : {}),
    };
    const breaches = (Array.isArray(data.breaches) ? data.breaches : []).map((breach, index) => ({
      ...breach, id: breach.id ?? `breach-${index}`, label: breach.rule,
      status: String(breach.severity || '').toLowerCase(),
    }));
    return [summary, ...breaches];
  }
  if (Array.isArray(data.breaches)) return data.breaches;
  if (Array.isArray(data.capabilities)) return data.capabilities;
  if (kind === 'workflows' && data.execution_state_counts && typeof data.execution_state_counts === 'object') {
    const totals = Object.entries(data)
      .filter(([, value]) => typeof value === 'number')
      .map(([key, value]) => ({ id: key, label: key.replaceAll('_', ' '), value }));
    const counts = Object.entries(data.execution_state_counts)
      .map(([key, value]) => ({ id: `state-${key}`, label: `${key.replaceAll('_', ' ')} workflows`, value }));
    return [...totals, ...counts];
  }
  if (data.metrics && typeof data.metrics === 'object') {
    return Object.entries(data.metrics).filter(([, value]) => typeof value === 'number')
      .map(([label, value]) => ({ id: label, label: label.replaceAll('_', ' '), value }));
  }
  if (data.workflow_counts && typeof data.workflow_counts === 'object') {
    return Object.entries(data.workflow_counts).map(([label, value]) => ({ id: label, label, value }));
  }
  return [data];
}

export function recordTitle(row, kind) {
  return row.fdr_number || row.full_name || row.name || row.email || row.rule_key || row.event_type ||
    row.node_key || row.stage || row.reason_code || row.action || row.field || row.label || row.subject ||
    row.title || row.recipient || row.channel ||
    (row.workflow_id != null && `Workflow ${row.workflow_id}`) ||
    (row.fdr_id != null && `FDR #${row.fdr_id}`) ||
    (row.id != null && `Record #${row.id}`) || kind.replaceAll('-', ' ');
}

export function recordSubtitle(row) {
  return [row.status, row.lifecycle_state, row.bank_name, row.state,
    row.maturity_date ? `Matures ${row.maturity_date}` : null,
    row.amount != null ? `₹${Number(row.amount).toLocaleString('en-IN')}` : null,
    row.role, row.execution_state].filter(Boolean).slice(0,3).join(' · ');
}

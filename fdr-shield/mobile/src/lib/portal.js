export const ROLE_LABELS = {
  institution: 'Institution portal',
  aicte_official: 'AICTE Official workspace',
  admin: 'Super Admin portal',
};

export const ROLE_PORTALS = [
  { value: 'institution', label: 'Institution' },
  { value: 'official', label: 'AICTE Official' },
  { value: 'admin', label: 'Administrator' },
];

const screens = {
  institution: [
    { key: 'fdrs', title: 'My FDRs', description: 'Review submitted deposits and verification status.', group: 'My account' },
    { key: 'renewals', title: 'Renewals', description: 'Request replacement deposits and follow renewal status.', group: 'My account' },
    { key: 'releases', title: 'Release requests', description: 'Request release of eligible matured deposits.', group: 'My account' },
    { key: 'notifications', title: 'Notifications', description: 'View maturity and case updates.', group: 'My account' },
    { key: 'assistant', title: 'Institution assistant', description: 'Ask about your institution’s cases and next steps.', group: 'Help' },
    { key: 'command', title: 'Command Center', description: 'Use the portal’s authorized command workflows.', group: 'Help' },
    { key: 'password', title: 'Change password', description: 'Update your sign-in password.', group: 'Account' },
  ],
  aicte_official: [
    { key: 'queue', title: 'Scrutiny queue', description: 'Open cases awaiting official review.', group: 'FDR scrutiny' },
    { key: 'discrepancies', title: 'Discrepancies', description: 'Review recorded document and verification mismatches.', group: 'FDR scrutiny' },
    { key: 'registrations', title: 'Institution applications', description: 'Review institution applications.', group: 'Administration' },
    { key: 'approvals', title: 'Release approvals', description: 'Review pending release decisions.', group: 'Administration' },
    { key: 'institutions', title: 'Institutions', description: 'Browse registered institutions.', group: 'Administration' },
    { key: 'audit', title: 'Audit trail', description: 'Review recorded case and officer actions.', group: 'Administration' },
    { key: 'workflows', title: 'Workflow control room', description: 'Inspect workflow progress and case execution.', group: 'Operations' },
    { key: 'exceptions', title: 'Exception inbox', description: 'Claim and review workflow exceptions.', group: 'Operations' },
    { key: 'command', title: 'Command Center', description: 'Prepare and confirm authorized portal actions.', group: 'Operations' },
    { key: 'password', title: 'Change password', description: 'Update your sign-in password.', group: 'Account' },
  ],
  admin: [
    { key: 'users', title: 'User accounts', description: 'Invite and administer portal accounts.', group: 'Administration' },
    { key: 'roles', title: 'Role assignments', description: 'Review and update account role assignments.', group: 'Administration' },
    { key: 'admin-institutions', title: 'Institution applications', description: 'Review institution registration history.', group: 'Administration' },
    { key: 'admin-officials', title: 'Official applications', description: 'Review AICTE Official applications.', group: 'Administration' },
    { key: 'institutions', title: 'Institutions', description: 'Browse and create institution records.', group: 'Administration' },
    { key: 'rules', title: 'Automation rules', description: 'Review versioned portal rules.', group: 'Administration' },
    { key: 'ml-governance', title: 'ML Governance', description: 'Review available FDR intelligence capabilities and findings.', group: 'Administration' },
    { key: 'alerts', title: 'Alerts and delivery', description: 'Review delivery attempts and notification status.', group: 'Operations' },
    { key: 'jobs', title: 'Failed jobs', description: 'Review failed workflow and outbox work.', group: 'Operations' },
    { key: 'health', title: 'System health', description: 'Review actual operations health and threshold breaches.', group: 'Operations' },
    { key: 'ops-agent', title: 'Operations recommendations', description: 'Review recovery recommendations before action.', group: 'Operations' },
    { key: 'command', title: 'Command Center', description: 'Prepare and confirm authorized portal actions.', group: 'Operations' },
    { key: 'audit', title: 'Audit trail', description: 'Review audit records and audit-chain status.', group: 'Operations' },
    { key: 'password', title: 'Change password', description: 'Update your sign-in password.', group: 'Account' },
  ],
};

export function getRoleScreens(role) { return screens[role] || []; }

export function getScreen(role, key) { return getRoleScreens(role).find(item => item.key === key); }

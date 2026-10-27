const allowedRoles = new Set(['institution', 'aicte_official', 'admin']);

export function promptRoleAssignment(email, currentRole, currentInstitutionId, nextRole) {
  if (!allowedRoles.has(nextRole)) return null;

  let institutionId = null;
  if (nextRole === 'institution') {
    const input = window.prompt(
      `Institution ID for ${email}`,
      currentInstitutionId == null ? '' : String(currentInstitutionId),
    );
    if (input === null) return null;
    institutionId = Number(input.trim());
    if (!Number.isSafeInteger(institutionId) || institutionId < 1) {
      window.alert('Enter a valid positive institution ID.');
      return null;
    }
  }

  if (!window.confirm(`Change ${email} from ${currentRole} to ${nextRole}?`)) return null;
  return { role: nextRole, institution_id: institutionId };
}

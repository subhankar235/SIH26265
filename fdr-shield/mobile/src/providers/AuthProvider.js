import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, authApi, clearSession as clearStoredSession, restoreSession, saveSession, setAccessToken } from '../lib/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState('loading');
  const [mfa, setMfa] = useState(null);
  const [restoreError, setRestoreError] = useState('');

  const loadSession = useCallback(async () => {
    try {
      const restored = await restoreSession();
      return { kind: restored ? 'authenticated' : 'anonymous', user: restored };
    } catch (error) {
      if (error.status === 401) {
        await clearStoredSession().catch(() => {});
        return { kind: 'anonymous', user: null };
      }
      return { kind: 'unavailable', user: null };
    }
  }, []);

  const applySession = useCallback(outcome => {
    setUser(outcome.user);
    setMfa(null);
    setStatus(outcome.kind);
    setRestoreError(outcome.kind === 'unavailable'
      ? 'Could not contact the sign-in service. Check your connection and retry.'
      : '');
    return outcome.user;
  }, []);

  const restore = useCallback(async () => applySession(await loadSession()), [loadSession, applySession]);

  const retry = useCallback(async () => {
    setStatus('loading');
    setRestoreError('');
    return applySession(await loadSession());
  }, [loadSession, applySession]);

  useEffect(() => {
    let active = true;
    loadSession().then(outcome => { if (active) applySession(outcome); });
    return () => { active = false; };
  }, [loadSession, applySession]);

  const signIn = useCallback(async (email, password, portal) => {
    const result = await authApi.login({ email, password, portal });
    if (result.mfa_required) {
      setMfa({ token: result.mfa_token, portal: result.portal });
      return { mfaRequired: true };
    }
    setUser(await saveSession(result));
    setMfa(null);
    setStatus('authenticated');
    return { mfaRequired: false };
  }, []);

  const verifyMfa = useCallback(async code => {
    if (!mfa) throw new Error('The verification session expired. Sign in again.');
    const result = await authApi.verifyMfa({ mfa_token: mfa.token, portal: mfa.portal, code });
    setUser(await saveSession(result));
    setMfa(null);
    setStatus('authenticated');
  }, [mfa]);

  const signOut = useCallback(async () => {
    try { await clearStoredSession(); }
    finally { setAccessToken(null); setUser(null); setMfa(null); setStatus('anonymous'); }
  }, []);

  const changePassword = useCallback(async (currentPassword, newPassword) => {
    await api('/auth/change-password', { method: 'POST', body: {
      current_password: currentPassword, new_password: newPassword,
    } });
    await signOut();
  }, [signOut]);

  const value = useMemo(() => ({ user, status, mfa, restoreError, signIn,
    verifyMfa, signOut, restore, retry, changePassword }),
  [user, status, mfa, restoreError, signIn, verifyMfa, signOut, restore, retry, changePassword]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used within AuthProvider');
  return value;
}

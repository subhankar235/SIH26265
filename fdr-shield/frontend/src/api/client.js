import axios from 'axios';
import { useAuthStore } from '../store/authStore';

const baseURL = import.meta.env.VITE_API_URL || '/api/v1';
export const client = axios.create({ baseURL, withCredentials: true });
const refreshClient = axios.create({ baseURL, withCredentials: true });
let refreshInFlight = null;
let csrfValue = '';

function csrfToken() {
  if (csrfValue) return csrfValue;
  if (typeof document === 'undefined') return '';
  const entry = document.cookie.split('; ').find((item) => item.startsWith('csrf_token='));
  return entry ? decodeURIComponent(entry.slice('csrf_token='.length)) : '';
}

function rememberCsrf(response) {
  if (typeof response?.data?.csrf_token === 'string') csrfValue = response.data.csrf_token;
  return response;
}

function isCsrfFailure(error) {
  const body = error.response?.data;
  return body?.error === 'CSRF_VALIDATION_FAILED' || body?.error?.code === 'CSRF_VALIDATION_FAILED';
}

async function bootstrapCsrf() {
  const { data } = await refreshClient.get('/auth/csrf');
  if (typeof data?.csrf_token === 'string') csrfValue = data.csrf_token;
  return csrfValue;
}

function isAuthEndpoint(url = '') {
  return /\/auth\/(?:login(?:\/|$)|mfa\/verify(?:\/|$)|logout(?:\/|$)|refresh(?:\/|$)|csrf(?:\/|$)|register(?:\/|$)|verify-email(?:\/|$)|accept-invite(?:\/|$)|forgot-password(?:\/|$)|reset-password(?:\/|$))/.test(url);
}

function isCsrfExemptEndpoint(url = '') {
  return /\/auth\/(?:register(?:\/|$)|verify-email(?:\/|$)|accept-invite(?:\/|$)|forgot-password(?:\/|$)|reset-password(?:\/|$))/.test(url);
}

function portalForPath(path) {
  if (path.startsWith('/institution/')) return 'institution';
  if (path === '/institution') return 'institution';
  if (path.startsWith('/admin/')) return 'admin';
  if (path === '/admin') return 'admin';
  if (path.startsWith('/official/') || path === '/official' || path.startsWith('/bureau/')) return 'official';
  return '';
}

function redirectForExpiredSession() {
  if (typeof window === 'undefined') return;
  const { pathname, search, hash } = window.location;
  const portal = portalForPath(pathname);
  if (!portal || pathname === '/login' || pathname === '/mfa') return;
  const query = new URLSearchParams({ portal, expired: '1', returnTo: `${pathname}${search}${hash}` });
  window.location.assign(`/login?${query.toString()}`);
}

async function refreshUnderBrowserLock() {
  const execute = async () => {
    // A different tab may have rotated the cookies while this tab waited for the lock.
    try {
      const response = await refreshClient.get('/auth/me');
      useAuthStore.getState().setUser(response.data);
      return response.data;
    } catch (error) {
      if (error.response?.status !== 401) throw error;
    }

    let csrf = await bootstrapCsrf();
    try {
      const { data } = await refreshClient.post('/auth/refresh', {}, {
        headers: { 'X-CSRF-Token': csrf },
      });
      rememberCsrf({ data });
      if (data.user) useAuthStore.getState().setUser(data.user);
      return data.user;
    } catch (error) {
      if (!isCsrfFailure(error)) throw error;
      csrf = await bootstrapCsrf();
      const { data } = await refreshClient.post('/auth/refresh', {}, {
        headers: { 'X-CSRF-Token': csrf },
      });
      rememberCsrf({ data });
      if (data.user) useAuthStore.getState().setUser(data.user);
      return data.user;
    }
  };

  if (typeof navigator !== 'undefined' && navigator.locks?.request) {
    return navigator.locks.request('fdr-shield-auth-refresh', execute);
  }
  return execute();
}

function refreshSession() {
  if (!refreshInFlight) {
    refreshInFlight = refreshUnderBrowserLock().finally(() => { refreshInFlight = null; });
  }
  return refreshInFlight;
}

client.interceptors.request.use(async (config) => {
  const method = (config.method || 'get').toLowerCase();
  if (['post', 'put', 'patch', 'delete'].includes(method) && !isCsrfExemptEndpoint(config.url)) {
    let token = csrfToken();
    if (!token) token = await bootstrapCsrf();
    if (token) config.headers['X-CSRF-Token'] = token;
  }
  return config;
});

client.interceptors.response.use((response) => rememberCsrf(response), async (error) => {
  const request = error.config;
  if (error.response?.status === 403 && isCsrfFailure(error) && request && !request._csrfRetried) {
    request._csrfRetried = true;
    try {
      const token = await bootstrapCsrf();
      request.headers['X-CSRF-Token'] = token;
      return client(request);
    } catch {
      return Promise.reject(error);
    }
  }

  const url = request?.url || '';
  if (error.response?.status !== 401 || !request || request._authRetried || isAuthEndpoint(url)) {
    return Promise.reject(error);
  }
  request._authRetried = true;
  try {
    await refreshSession();
    return client(request);
  } catch (refreshError) {
    // Only a definitive invalid/expired refresh session should log the user out.
    // Network failures, 5xx responses, and authorization failures are transient/non-auth errors.
    if (refreshError.response?.status === 401) {
      useAuthStore.getState().clearSession();
      redirectForExpiredSession();
    }
    return Promise.reject(refreshError);
  }
});

export const __authClientInternals = { isCsrfFailure, portalForPath, csrfToken };

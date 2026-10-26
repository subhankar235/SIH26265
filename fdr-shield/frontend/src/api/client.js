import axios from 'axios';
import { useAuthStore } from '../store/authStore';

const baseURL = import.meta.env.VITE_API_URL || '/api/v1';
export const client = axios.create({ baseURL, withCredentials: true });
const refreshClient = axios.create({ baseURL, withCredentials: true });
let refreshInFlight = null;

function csrfToken() {
  if (typeof document === 'undefined') return '';
  const entry = document.cookie.split('; ').find((item) => item.startsWith('csrf_token='));
  return entry ? decodeURIComponent(entry.slice('csrf_token='.length)) : '';
}

client.interceptors.request.use((config) => {
  const method = (config.method || 'get').toLowerCase();
  if (['post', 'put', 'patch', 'delete'].includes(method)) {
    const token = csrfToken();
    if (token) config.headers['X-CSRF-Token'] = token;
  }
  return config;
});

client.interceptors.response.use((response) => response, async (error) => {
  const request = error.config;
  const url = request?.url || '';
  const publicRequest = /\/auth\/(?:login(?:\/|$)|mfa\/verify(?:\/|$)|register(?:\/|$)|verify-email(?:\/|$)|accept-invite(?:\/|$)|forgot-password(?:\/|$)|reset-password(?:\/|$))/.test(url);
  if (error.response?.status !== 401 || !request || request._retried || publicRequest || url.includes('/auth/refresh')) {
    return Promise.reject(error);
  }
  request._retried = true;
  try {
    if (!refreshInFlight) {
      refreshInFlight = refreshClient.post('/auth/refresh', {}, { headers: { 'X-CSRF-Token': csrfToken() } })
        .finally(() => { refreshInFlight = null; });
    }
    await refreshInFlight;
    return client(request);
  } catch (refreshError) {
    useAuthStore.getState().clearSession();
    if (typeof window !== 'undefined' && !window.location.pathname.endsWith('/login')) {
      window.location.assign('/login?expired=1');
    }
    return Promise.reject(refreshError);
  }
});

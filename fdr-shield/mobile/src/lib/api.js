import * as SecureStore from 'expo-secure-store';

const REFRESH_KEY = 'fdr_mobile_refresh_token';
const API_URL_KEY = 'fdr_mobile_api_url';
let apiBaseUrl = (process.env.EXPO_PUBLIC_API_URL || 'http://10.0.2.2:8000/api/v1').replace(/\/+$/, '');
let accessToken = null;
let refreshPromise = null;

export function getApiBaseUrl() { return apiBaseUrl; }

export async function configureApiBaseUrl(value) {
  const normalized = String(value || '').trim().replace(/\/+$/, '');
  if (!/^https?:\/\//i.test(normalized) || !normalized.endsWith('/api/v1')) {
    throw new Error('Enter a valid server URL ending in /api/v1.');
  }
  if (normalized.startsWith('http://') && !/localhost|127\.0\.0\.1|10\.0\.2\.2|192\.168\.|10\./.test(normalized)) {
    throw new Error('Use HTTPS for non-local server URLs.');
  }
  apiBaseUrl = normalized;
  await SecureStore.setItemAsync(API_URL_KEY, normalized);
  return normalized;
}

export class ApiError extends Error {
  constructor(status, message, body) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

async function parseResponse(response) {
  if (response.status === 204) return null;
  const text = await response.text();
  if (!text) return null;
  try { return JSON.parse(text); } catch { return { message: text }; }
}

async function rawRequest(path, options = {}, token = null) {
  const headers = { Accept: 'application/json', ...(options.headers || {}) };
  let body = options.body;
  if (body && typeof body === 'object' && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(body);
  }
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: options.method || 'GET', headers, body,
  });
  const data = await parseResponse(response);
  if (!response.ok) {
    const detail = data?.detail || data?.error?.message || data?.error || data?.message;
    throw new ApiError(response.status, typeof detail === 'string' ? detail : `Request failed (${response.status})`, data);
  }
  return data;
}

async function rotateMobileSession() {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const refreshToken = await SecureStore.getItemAsync(REFRESH_KEY);
      if (!refreshToken) throw new ApiError(401, 'Session expired. Sign in again.');
      const data = await rawRequest('/auth/mobile/refresh', {
        method: 'POST', body: { refresh_token: refreshToken },
      });
      await saveSession(data);
      return data;
    })().finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

export async function api(path, options = {}) {
  const token = options.auth === false ? null : accessToken;
  try {
    return await rawRequest(path, options, token);
  } catch (error) {
    if (error.status !== 401 || options.auth === false || options.retryAuth === false) throw error;
    await rotateMobileSession();
    return rawRequest(path, options, accessToken);
  }
}

export async function saveSession(data) {
  accessToken = data.access_token;
  await SecureStore.setItemAsync(REFRESH_KEY, data.refresh_token);
  return data.user;
}

export async function restoreSession() {
  const savedApiUrl = await SecureStore.getItemAsync(API_URL_KEY);
  if (savedApiUrl) apiBaseUrl = savedApiUrl;
  const refreshToken = await SecureStore.getItemAsync(REFRESH_KEY);
  if (!refreshToken) return null;
  const data = await rawRequest('/auth/mobile/refresh', {
    method: 'POST', body: { refresh_token: refreshToken },
  });
  await saveSession(data);
  return data.user;
}

export async function clearSession() {
  const refreshToken = await SecureStore.getItemAsync(REFRESH_KEY);
  try {
    if (refreshToken) await rawRequest('/auth/mobile/logout', {
      method: 'POST', body: { refresh_token: refreshToken },
    }, accessToken);
  } finally {
    accessToken = null;
    await SecureStore.deleteItemAsync(REFRESH_KEY);
  }
}

export function setAccessToken(token) {
  accessToken = token || null;
}

export const authApi = {
  login: body => rawRequest('/auth/mobile/login', { method: 'POST', body }),
  verifyMfa: body => rawRequest('/auth/mobile/mfa/verify', { method: 'POST', body }),
};

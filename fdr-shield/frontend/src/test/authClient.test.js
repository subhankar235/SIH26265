import { beforeEach, describe, expect, it, vi } from 'vitest';

const { axiosInstances } = vi.hoisted(() => ({ axiosInstances: [] }));

vi.mock('axios', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    default: {
      ...actual.default,
      create: (config) => {
        const instance = actual.default.create(config);
        axiosInstances.push(instance);
        return instance;
      },
    },
  };
});

function response(config, data, status = 200) {
  return { config, data, status, statusText: 'OK', headers: {} };
}

function reject(config, status, data = {}) {
  const error = new Error(`HTTP ${status}`);
  error.config = config;
  error.response = { config, status, data };
  return Promise.reject(error);
}

describe('cookie session API client', () => {
  let api;
  let refresh;
  let authStore;

  beforeEach(async () => {
    vi.resetModules();
    axiosInstances.length = 0;
    document.cookie = 'csrf_token=; Max-Age=0; path=/';
    const module = await import('../api/client');
    api = module.client;
    [api, refresh] = axiosInstances;
    authStore = await import('../store/authStore');
    authStore.useAuthStore.getState().clearSession();
    history.replaceState({}, '', '/');
  });

  it('coordinates concurrent 401s into one refresh and retries each request once', async () => {
    let refreshCalls = 0;
    const user = { id: 1, role: 'aicte_official' };
    api.defaults.adapter = (config) => config.url === '/one' || config.url === '/two'
      ? (config._authRetried ? Promise.resolve(response(config, { ok: true })) : reject(config, 401))
      : reject(config, 404);
    refresh.defaults.adapter = (config) => {
      if (config.url === '/auth/me') return reject(config, 401);
      if (config.url === '/auth/csrf') return Promise.resolve(response(config, { csrf_token: 'fresh-csrf' }));
      if (config.url === '/auth/refresh') {
        refreshCalls += 1;
        return Promise.resolve(response(config, { user, csrf_token: 'rotated-csrf' }));
      }
      return reject(config, 404);
    };

    const [one, two] = await Promise.all([api.get('/one'), api.get('/two')]);
    expect(one.data.ok).toBe(true);
    expect(two.data.ok).toBe(true);
    expect(refreshCalls).toBe(1);
    expect(authStore.useAuthStore.getState().user).toEqual(user);
  });

  it('does not refresh on ordinary 403 authorization errors', async () => {
    let refreshCalls = 0;
    api.defaults.adapter = (config) => reject(config, 403, { error: { code: 'FORBIDDEN' } });
    refresh.defaults.adapter = (config) => {
      if (config.url === '/auth/refresh') refreshCalls += 1;
      return reject(config, 404);
    };
    await expect(api.get('/protected')).rejects.toMatchObject({ response: { status: 403 } });
    expect(refreshCalls).toBe(0);
  });

  it('excludes login, logout, and refresh endpoints from recursive refresh attempts', async () => {
    let refreshCalls = 0;
    let loginCsrf='';
    api.defaults.adapter = (config) => {
      if(config.url==='/auth/login')loginCsrf=config.headers.get('X-CSRF-Token');
      return reject(config, 401);
    };
    refresh.defaults.adapter = (config) => {
      if (config.url === '/auth/csrf') return Promise.resolve(response(config, { csrf_token: 'login-csrf' }));
      if (config.url === '/auth/refresh') refreshCalls += 1;
      return reject(config, 401);
    };
    await expect(api.post('/auth/login', {})).rejects.toMatchObject({ response: { status: 401 } });
    await expect(api.post('/auth/logout', {})).rejects.toMatchObject({ response: { status: 401 } });
    await expect(api.post('/auth/refresh', {})).rejects.toMatchObject({ response: { status: 401 } });
    expect(refreshCalls).toBe(0);
    expect(loginCsrf).toBe('login-csrf');
  });

  it('retries an original 401 at most once after refresh', async () => {
    let protectedCalls = 0;
    api.defaults.adapter = (config) => {
      protectedCalls += 1;
      return reject(config, 401);
    };
    refresh.defaults.adapter = (config) => config.url === '/auth/me'
      ? reject(config, 401)
      : config.url === '/auth/csrf'
        ? Promise.resolve(response(config, { csrf_token: 'csrf' }))
        : Promise.resolve(response(config, { user: { id: 3, role: 'admin' }, csrf_token: 'rotated' }));
    await expect(api.get('/protected')).rejects.toMatchObject({ response: { status: 401 } });
    expect(protectedCalls).toBe(2);
  });

  it('repairs a missing CSRF cookie and retries only the affected mutation', async () => {
    let attempts = 0;
    let csrfFetches = 0;
    api.defaults.adapter = (config) => {
      attempts += 1;
      return attempts === 1
        ? reject(config, 403, { error: 'CSRF_VALIDATION_FAILED' })
        : Promise.resolve(response(config, { saved: true }));
    };
    refresh.defaults.adapter = (config) => {
      if (config.url === '/auth/csrf') {
        csrfFetches += 1;
        return Promise.resolve(response(config, { csrf_token: 'new-csrf' }));
      }
      return reject(config, 404);
    };
    document.cookie='csrf_token=stale-token; path=/';
    const result = await api.post('/protected', { value: 1 });
    expect(result.data.saved).toBe(true);
    expect(attempts).toBe(2);
    expect(csrfFetches).toBe(1);
  });

  it('does not clear a valid frontend session on transient refresh failure', async () => {
    authStore.useAuthStore.getState().setUser({ id: 8, role: 'admin' });
    api.defaults.adapter = (config) => reject(config, 401);
    refresh.defaults.adapter = (config) => config.url === '/auth/me'
      ? reject(config, 401)
      : config.url === '/auth/csrf'
        ? Promise.resolve(response(config, { csrf_token: 'csrf' }))
        : reject(config, 503);
    await expect(api.get('/protected')).rejects.toMatchObject({ response: { status: 503 } });
    expect(authStore.useAuthStore.getState().status).toBe('authenticated');
  });

  it('clears session only when refresh is definitively rejected', async () => {
    authStore.useAuthStore.getState().setUser({ id: 9, role: 'institution' });
    api.defaults.adapter = (config) => reject(config, 401);
    refresh.defaults.adapter = (config) => config.url === '/auth/me'
      ? reject(config, 401)
      : config.url === '/auth/csrf'
        ? Promise.resolve(response(config, { csrf_token: 'csrf' }))
        : reject(config, 401);
    await expect(api.get('/protected')).rejects.toMatchObject({ response: { status: 401 } });
    expect(authStore.useAuthStore.getState().status).toBe('anonymous');
  });

  it('maps expired-session redirects to the current portal, including legacy bureau routes', async () => {
    const { __authClientInternals } = await import('../api/client');
    expect(__authClientInternals.portalForPath('/admin/audit')).toBe('admin');
    expect(__authClientInternals.portalForPath('/official/queue')).toBe('official');
    expect(__authClientInternals.portalForPath('/bureau/scrutiny/4')).toBe('official');
    expect(__authClientInternals.portalForPath('/institution/fdrs')).toBe('institution');
  });
});

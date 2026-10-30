import AppRoutes from "./routes/AppRoutes";
import Layout from "./components/layout/Layout";
import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { getCsrf, getMe } from './api/auth.api';
import { useAuthStore } from './store/authStore';

function AuthBootstrap({ children }) {
  const setUser = useAuthStore((state) => state.setUser);
  const setRestoreUnavailable = useAuthStore((state) => state.setRestoreUnavailable);
  const location = useLocation();
  useEffect(() => {
    const publicPath = new Set(['/','/login','/mfa','/institution/register','/official/register',
      '/super-admin/setup','/verify-email','/accept-invite','/forgot-password','/reset-password','/unauthorized']);
    if (publicPath.has(location.pathname)) return;
    let active = true;
    getCsrf().then(() => getMe()).then((user) => { if (active) setUser(user); })
      .catch(() => {
        if (active && useAuthStore.getState().status === 'loading') setRestoreUnavailable();
      });
    return () => { active = false; };
  }, [location.pathname, setUser, setRestoreUnavailable]);
  return children;
}

export default function App() {
  return (
    <Layout>
      <AuthBootstrap><AppRoutes /></AuthBootstrap>
    </Layout>
  );
}

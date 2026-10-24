import AppRoutes from "./routes/AppRoutes";
import Layout from "./components/layout/Layout";
import { useEffect } from 'react';
import { getMe } from './api/auth.api';
import { useAuthStore } from './store/authStore';

function AuthBootstrap({ children }) {
  const setUser = useAuthStore((state) => state.setUser);
  const clearSession = useAuthStore((state) => state.clearSession);
  useEffect(() => {
    const hasSessionHint = document.cookie.split('; ').some((item) => item.startsWith('csrf_token='));
    if (!hasSessionHint) { clearSession(); return; }
    let active = true;
    getMe().then((user) => { if (active) setUser(user); }).catch(() => { if (active) clearSession(); });
    return () => { active = false; };
  }, [setUser, clearSession]);
  return children;
}

export default function App() {
  return (
    <Layout>
      <AuthBootstrap><AppRoutes /></AuthBootstrap>
    </Layout>
  );
}

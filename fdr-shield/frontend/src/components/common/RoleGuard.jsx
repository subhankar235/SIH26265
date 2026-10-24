import{Navigate,useLocation}from'react-router-dom';import{useAuthStore}from'../../store/authStore';
/**
 * RoleGuard
 * Props: roles, children
 */
export default function RoleGuard({ roles, children }) {
  // If token missing -> Navigate /login; if role not allowed -> 403 page
  const{user,status}=useAuthStore();const location=useLocation();if(status==='loading')return <div className="p-8" role="status">Checking your session…</div>;if(status!=='authenticated')return <Navigate to={location.pathname.startsWith('/institution')?'/institution/login':location.pathname.startsWith('/official')?'/official/login':location.pathname.startsWith('/admin')?'/admin/login':'/login'} state={{from:location}} replace/>;if(user?.must_change_password&&!location.pathname.startsWith('/account/change-password'))return <Navigate to="/account/change-password" replace/>;return roles.includes(user?.role)?children:<Navigate to="/unauthorized" replace/>;
}

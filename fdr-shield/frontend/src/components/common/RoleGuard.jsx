import{Navigate,useLocation}from'react-router-dom';import{useAuthStore}from'../../store/authStore';
/**
 * RoleGuard
 * Props: roles, children
 */
export default function RoleGuard({ roles, children }) {
  // If token missing -> Navigate /login; if role not allowed -> 403 page
  const{user,token}=useAuthStore();const location=useLocation();if(!token)return <Navigate to="/login" state={{from:location}} replace/>;return roles.includes(user?.role)?children:<Navigate to={user?.role==='institution'?'/institution':'/bureau'} replace/>;
}

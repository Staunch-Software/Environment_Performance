import { Outlet, Navigate, useLocation } from 'react-router-dom';
import Sidebar from '../../components/Layout/Sidebar';
import Header from '../../components/Layout/Header';
import { useAuth } from '../../context/AuthContext';

const TITLES = {
  '/admin/users': 'User Management',
  '/admin/vessels': 'Vessel Configuration',
};

export default function AdminLayout() {
  const { user } = useAuth();
  const { pathname } = useLocation();
  if (user?.role !== 'admin') return <Navigate to="/dashboard" replace />;

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content">
        <Header title={TITLES[pathname.replace(/\/$/, '')] || 'Admin Panel'} />
        <div className="page-body">
          <Outlet />
        </div>
      </div>
    </div>
  );
}

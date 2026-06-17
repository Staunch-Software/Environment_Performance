import { NavLink, Outlet, Navigate } from 'react-router-dom';
import Sidebar from '../../components/Layout/Sidebar';
import Header from '../../components/Layout/Header';
import { useAuth } from '../../context/AuthContext';

export default function AdminLayout() {
  const { user } = useAuth();
  if (user?.role !== 'admin') return <Navigate to="/dashboard" replace />;

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content">
        <Header title="Admin Panel" />
        <div style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface)', padding: '0 2rem' }}>
          <nav style={{ display: 'flex', gap: '0.25rem' }}>
            {[
              { to: '/admin/users', label: 'User Management' },
              { to: '/admin/vessels', label: 'Vessel Configuration' },
            ].map(link => (
              <NavLink
                key={link.to}
                to={link.to}
                style={({ isActive }) => ({
                  padding: '0.75rem 1rem',
                  fontSize: '0.875rem',
                  fontWeight: 500,
                  color: isActive ? 'var(--primary)' : 'var(--text-secondary)',
                  borderBottom: isActive ? '2px solid var(--primary)' : '2px solid transparent',
                  textDecoration: 'none',
                })}
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="page-body">
          <Outlet />
        </div>
      </div>
    </div>
  );
}

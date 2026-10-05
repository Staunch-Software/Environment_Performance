import { useState, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useSidebar } from '../../context/SidebarContext';
import {
  LayoutDashboard, Ship, Upload, FileText, Bell,
  BookOpen, Users, Settings,
} from 'lucide-react';
import api from '../../api/axios';

const MAIN_LINKS = [
  { to: '/dashboard',  label: 'Dashboard',   Icon: LayoutDashboard },
  { to: '/vessels',    label: 'Vessels',      Icon: Ship },
  { to: '/uploads',    label: 'ORB Uploads',  Icon: Upload },
  { to: '/entries',    label: 'ORB Entries',  Icon: FileText },
  { to: '/alerts',     label: 'Alerts',       Icon: Bell },
  { to: '/daily-log',  label: 'Daily Log',    Icon: BookOpen },
];

const ADMIN_LINKS = [
  { to: '/admin/users',   label: 'User Management', Icon: Users },
  { to: '/admin/vessels', label: 'Vessel Config',   Icon: Settings },
];

export default function Sidebar() {
  const { isAdmin } = useAuth();
  const { isOpen, close } = useSidebar();
  const [alertCount, setAlertCount] = useState(0);

  useEffect(() => {
    const fetch = () => api.get('/api/alerts/summary').then(r => setAlertCount(r.data.data?.total || 0)).catch(() => {});
    fetch();
    const id = setInterval(fetch, 30000);
    return () => clearInterval(id);
  }, []);

  return (
    <>
      {/* Backdrop — only visible on mobile when sidebar is open */}
      {isOpen && <div className="sidebar-backdrop" onClick={close} />}

      <aside className={`sidebar${isOpen ? ' open' : ''}`}>
        <div className="sidebar-logo">
          <div className="sidebar-logo__mark" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 64 64" fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="32" cy="16" r="5" />
              <line x1="32" y1="21" x2="32" y2="46" />
              <line x1="20" y1="28" x2="44" y2="28" />
              <path d="M16 38 a16 16 0 0 0 32 0" />
              <line x1="16" y1="38" x2="16" y2="33" />
              <line x1="48" y1="38" x2="48" y2="33" />
            </svg>
          </div>
          <div className="sidebar-logo__text">
            <span className="sidebar-logo__name">ORB Platform</span>
            <span className="sidebar-logo__tag">MARPOL Compliance</span>
          </div>
        </div>
        <nav className="sidebar-nav">
          <div className="sidebar-section">Main</div>
          {MAIN_LINKS.map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => `sidebar-link${isActive ? ' active' : ''}`}
              onClick={close}
            >
              <Icon size={18} className="sidebar-icon" />
              {label}
              {label === 'Alerts' && alertCount > 0 && (
                <span className="sidebar-badge">
                  {alertCount > 99 ? '99+' : alertCount}
                </span>
              )}
            </NavLink>
          ))}

          {isAdmin && (
            <>
              <div className="sidebar-section sidebar-section--admin">Admin</div>
              {ADMIN_LINKS.map(({ to, label, Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  className={({ isActive }) => `sidebar-link${isActive ? ' active' : ''}`}
                  onClick={close}
                >
                  <Icon size={18} className="sidebar-icon" />
                  {label}
                </NavLink>
              ))}
            </>
          )}
        </nav>
      </aside>
    </>
  );
}

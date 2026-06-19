import { NavLink } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useSidebar } from '../../context/SidebarContext';
import {
  LayoutDashboard, Ship, Upload, FileText, Bell,
  BookOpen, Users, Settings,
} from 'lucide-react';

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

  return (
    <>
      {/* Backdrop — only visible on mobile when sidebar is open */}
      {isOpen && <div className="sidebar-backdrop" onClick={close} />}

      <aside className={`sidebar${isOpen ? ' open' : ''}`}>
        <div className="sidebar-logo">
          ORB Platform
          <span>MARPOL Compliance</span>
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

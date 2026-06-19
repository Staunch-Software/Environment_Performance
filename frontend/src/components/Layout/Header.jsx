import { LogOut, Menu } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useSidebar } from '../../context/SidebarContext';

export default function Header({ title }) {
  const { user, logout } = useAuth();
  const { toggle } = useSidebar();

  return (
    <header className="header">
      <div className="header-left">
        {/* Hamburger — only visible on mobile via CSS */}
        <button className="btn-hamburger" onClick={toggle} aria-label="Toggle menu">
          <Menu size={22} />
        </button>
        <span className="header-title">{title}</span>
      </div>
      <div className="header-user">
        <div className="user-chip">
          <span className="user-chip__name">{user?.name}</span>
          <span className="user-chip__role">({user?.role})</span>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={logout}>
          <LogOut size={14} />
          <span className="btn-label">Sign Out</span>
        </button>
      </div>
    </header>
  );
}

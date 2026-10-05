import { useState, useEffect, useRef } from 'react';
import { LogOut, Menu, ArrowLeft, ChevronDown } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useSidebar } from '../../context/SidebarContext';
import { useNavigate } from 'react-router-dom';

export default function Header({ title, backTo }) {
  const { user, logout } = useAuth();
  const { toggle } = useSidebar();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);
  const initials = (user?.name || '?').trim().split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase();

  useEffect(() => {
    if (!open) return;
    const onDown = (e) => { if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <header className="header">
      <div className="header-left">
        {/* Hamburger — only visible on mobile via CSS */}
        <button className="btn-hamburger" onClick={toggle} aria-label="Toggle menu">
          <Menu size={22} />
        </button>
        {backTo && (
          <button
            onClick={() => navigate(backTo)}
            className="header-back"
            title="Go back"
            aria-label="Go back"
          >
            <ArrowLeft size={18} />
          </button>
        )}
        <span className="header-title">{title}</span>
      </div>
      <div className="header-user" ref={menuRef}>
        <button
          type="button"
          className={`user-chip user-chip--btn${open ? ' user-chip--open' : ''}`}
          onClick={() => setOpen(o => !o)}
          aria-haspopup="menu"
          aria-expanded={open}
        >
          <span className="user-chip__avatar" aria-hidden="true">{initials}</span>
          <span className="user-chip__name">{user?.name}</span>
          <ChevronDown size={14} className="user-chip__chevron" aria-hidden="true" />
        </button>
        {open && (
          <div className="user-menu" role="menu">
            <div className="user-menu__info">
              <span className="user-menu__avatar" aria-hidden="true">{initials}</span>
              <div className="user-menu__text">
                <span className="user-menu__name">{user?.name}</span>
                {user?.email && <span className="user-menu__email">{user.email}</span>}
                {user?.role && <span className="user-menu__role">{user.role}</span>}
              </div>
            </div>
            <button type="button" role="menuitem" className="user-menu__item" onClick={logout}>
              <LogOut size={15} />
              <span>Sign Out</span>
            </button>
          </div>
        )}
      </div>
    </header>
  );
}

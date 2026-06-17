import { LogOut } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

export default function Header({ title }) {
  const { user, logout } = useAuth();

  return (
    <header className="header">
      <span className="header-title">{title}</span>
      <div className="header-user">
        <div className="user-chip">
          <span>{user?.name}</span>
          <span className="user-chip__role">({user?.role})</span>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={logout}>
          <LogOut size={14} />
          Sign Out
        </button>
      </div>
    </header>
  );
}

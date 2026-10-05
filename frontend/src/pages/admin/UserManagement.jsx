import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import {
  Search, X, UserPlus, MoreVertical, Pencil, KeyRound, UserX, UserCheck,
  Users, ShieldCheck, UserRoundCheck, UserRoundX,
} from 'lucide-react';
import Modal from '../../components/shared/Modal';
import Badge from '../../components/shared/Badge';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import Dropdown from '../../components/shared/Dropdown';
import api from '../../api/axios';
import './UserManagement.css';

const ROLE_FILTER_OPTIONS = [
  { value: 'all', label: 'All Roles' },
  { value: 'admin', label: 'Admin' },
  { value: 'viewer', label: 'Viewer' },
];
const STATUS_FILTER_OPTIONS = [
  { value: 'all', label: 'All Statuses' },
  { value: 'active', label: 'Active' },
  { value: 'inactive', label: 'Inactive' },
];

const initialsOf = (name) =>
  (name || '?').trim().split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase();

// Row actions menu. Rendered with position:fixed so the table's horizontal
// scroll container can't clip it.
function ActionsMenu({ user, onEdit, onToggle, onReset }) {
  const [pos, setPos] = useState(null);
  const btnRef = useRef(null);
  const menuRef = useRef(null);
  const open = pos !== null;

  const close = useCallback(() => setPos(null), []);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (menuRef.current?.contains(e.target) || btnRef.current?.contains(e.target)) return;
      close();
    };
    const onKey = (e) => { if (e.key === 'Escape') { close(); btnRef.current?.focus(); } };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', close);
    window.addEventListener('scroll', close, true);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', close);
      window.removeEventListener('scroll', close, true);
    };
  }, [open, close]);

  const toggle = () => {
    if (open) { close(); return; }
    const r = btnRef.current.getBoundingClientRect();
    const menuH = 150;
    const top = r.bottom + menuH > window.innerHeight ? Math.max(8, r.top - menuH - 4) : r.bottom + 4;
    setPos({ top, right: Math.max(8, window.innerWidth - r.right) });
  };

  const run = (fn) => () => { close(); fn(user); };

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        className={`um-kebab${open ? ' um-kebab--open' : ''}`}
        onClick={toggle}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Actions for ${user.name}`}
      >
        <MoreVertical size={18} />
      </button>
      {open && (
        <div ref={menuRef} className="um-menu" role="menu" style={{ top: pos.top, right: pos.right }}>
          <button type="button" role="menuitem" className="um-menu__item" onClick={run(onEdit)}>
            <Pencil size={15} /> Edit
          </button>
          <button type="button" role="menuitem" className="um-menu__item" onClick={run(onReset)}>
            <KeyRound size={15} /> Reset Password
          </button>
          <div className="um-menu__sep" />
          <button
            type="button"
            role="menuitem"
            className={`um-menu__item ${user.is_active ? 'um-menu__item--danger' : 'um-menu__item--success'}`}
            onClick={run(onToggle)}
          >
            {user.is_active ? <UserX size={15} /> : <UserCheck size={15} />}
            {user.is_active ? 'Deactivate' : 'Activate'}
          </button>
        </div>
      )}
    </>
  );
}

export default function UserManagement() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editUser, setEditUser] = useState(null);
  const [tempPassword, setTempPassword] = useState(null);
  const [form, setForm] = useState({ name: '', email: '', password: '', role: 'viewer' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');

  const load = () => {
    setLoading(true);
    api.get('/api/users').then(r => setUsers(r.data.data || [])).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleAdd = async () => {
    setSaving(true); setError('');
    try {
      await api.post('/api/users', form);
      setShowAdd(false);
      setForm({ name: '', email: '', password: '', role: 'viewer' });
      load();
    } catch (e) { setError(e.response?.data?.detail || 'Failed'); }
    finally { setSaving(false); }
  };

  const handleEdit = async () => {
    setSaving(true); setError('');
    try {
      await api.put(`/api/users/${editUser.id}`, { name: editUser.name, email: editUser.email, role: editUser.role });
      setEditUser(null);
      load();
    } catch (e) { setError(e.response?.data?.detail || 'Failed'); }
    finally { setSaving(false); }
  };

  const handleToggle = async (u) => {
    if (u.is_active) {
      await api.patch(`/api/users/${u.id}/deactivate`);
    } else {
      await api.put(`/api/users/${u.id}`, { is_active: true });
    }
    load();
  };

  const handleReset = async (u) => {
    const r = await api.post(`/api/users/${u.id}/reset-password`);
    setTempPassword(r.data.data.temp_password);
  };

  const stats = useMemo(() => ({
    total: users.length,
    active: users.filter(u => u.is_active).length,
    inactive: users.filter(u => !u.is_active).length,
    admins: users.filter(u => u.role === 'admin').length,
  }), [users]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return users.filter(u =>
      (!q || (u.name || '').toLowerCase().includes(q) || (u.email || '').toLowerCase().includes(q)) &&
      (roleFilter === 'all' || u.role === roleFilter) &&
      (statusFilter === 'all' || (statusFilter === 'active') === !!u.is_active)
    );
  }, [users, search, roleFilter, statusFilter]);

  const filtersActive = search.trim() !== '' || roleFilter !== 'all' || statusFilter !== 'all';
  const clearFilters = () => { setSearch(''); setRoleFilter('all'); setStatusFilter('all'); };

  return (
    <div className="um">
      <div className="um-header">
        <div className="um-header__text">
          <span className="um-eyebrow">Administration</span>
          <h2 className="um-title">User Management</h2>
          <p className="um-subtitle">Manage platform access, roles and account status.</p>
        </div>
        <button className="um-btn um-btn--primary" onClick={() => setShowAdd(true)}>
          <UserPlus size={16} /> Add User
        </button>
      </div>

      <div className="um-stats">
        <div className="um-stat">
          <span className="um-stat__icon"><Users size={18} /></span>
          <div><div className="um-stat__value">{stats.total}</div><div className="um-stat__label">Total Users</div></div>
        </div>
        <div className="um-stat um-stat--green">
          <span className="um-stat__icon"><UserRoundCheck size={18} /></span>
          <div><div className="um-stat__value">{stats.active}</div><div className="um-stat__label">Active</div></div>
        </div>
        <div className="um-stat um-stat--grey">
          <span className="um-stat__icon"><UserRoundX size={18} /></span>
          <div><div className="um-stat__value">{stats.inactive}</div><div className="um-stat__label">Inactive</div></div>
        </div>
        <div className="um-stat um-stat--navy">
          <span className="um-stat__icon"><ShieldCheck size={18} /></span>
          <div><div className="um-stat__value">{stats.admins}</div><div className="um-stat__label">Admins</div></div>
        </div>
      </div>

      <div className="um-panel">
        <div className="um-toolbar">
          <div className="um-search">
            <Search size={16} className="um-search__icon" />
            <input
              type="text"
              className="um-search__input"
              placeholder="Search by name or email…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              aria-label="Search users"
            />
            {search && (
              <button type="button" className="um-search__clear" onClick={() => setSearch('')} aria-label="Clear search">
                <X size={14} />
              </button>
            )}
          </div>
          <div className="um-filters">
            <Dropdown value={roleFilter} onChange={setRoleFilter} options={ROLE_FILTER_OPTIONS} placeholder="All Roles" />
            <Dropdown value={statusFilter} onChange={setStatusFilter} options={STATUS_FILTER_OPTIONS} placeholder="All Statuses" />
            {filtersActive && (
              <button type="button" className="um-btn um-btn--link" onClick={clearFilters}>Clear</button>
            )}
          </div>
          <div className="um-count">
            Showing <strong>{filtered.length}</strong> of {users.length}
          </div>
        </div>

        {loading ? <LoadingSpinner /> : filtered.length === 0 ? (
          <div className="um-empty">
            <span className="um-empty__icon"><Users size={26} /></span>
            <div className="um-empty__title">{users.length === 0 ? 'No users yet' : 'No users match your filters'}</div>
            <div className="um-empty__text">
              {users.length === 0
                ? 'Add the first user to give them access to the platform.'
                : 'Try a different search term or clear the filters.'}
            </div>
            {filtersActive && (
              <button type="button" className="um-btn um-btn--secondary" onClick={clearFilters}>Clear filters</button>
            )}
          </div>
        ) : (
          <div className="um-table-wrap">
            <table className="um-table">
              <thead>
                <tr>
                  <th>User</th><th>Role</th><th>Last Login</th><th>Status</th><th className="um-th-actions">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(u => (
                  <tr key={u.id} className={u.is_active ? '' : 'um-row--inactive'}>
                    <td data-label="User">
                      <div className="um-user">
                        <span className="um-avatar" aria-hidden="true">{initialsOf(u.name)}</span>
                        <div className="um-user__text">
                          <div className="um-user__name">{u.name}</div>
                          <div className="um-user__email">{u.email}</div>
                        </div>
                      </div>
                    </td>
                    <td data-label="Role"><Badge value={u.role} /></td>
                    <td data-label="Last Login" className="um-muted">
                      {u.last_login ? new Date(u.last_login).toLocaleDateString() : 'Never'}
                    </td>
                    <td data-label="Status"><Badge value={u.is_active ? 'active' : 'inactive'} /></td>
                    <td className="um-td-actions">
                      <ActionsMenu user={u} onEdit={setEditUser} onToggle={handleToggle} onReset={handleReset} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showAdd && (
        <Modal title="Add User" onClose={() => setShowAdd(false)} footer={
          <>
            <button className="um-btn um-btn--secondary" onClick={() => setShowAdd(false)}>Cancel</button>
            <button className="um-btn um-btn--primary" onClick={handleAdd} disabled={saving}>{saving ? 'Saving…' : 'Add User'}</button>
          </>
        }>
          <div className="um-form">
            {error && <div className="alert-banner error">{error}</div>}
            <div className="form-group"><label>Full Name *</label><input className="form-control" value={form.name} onChange={e => setForm({...form, name: e.target.value})} /></div>
            <div className="form-group"><label>Email *</label><input type="email" className="form-control" value={form.email} onChange={e => setForm({...form, email: e.target.value})} /></div>
            <div className="form-group"><label>Password *</label><input type="password" className="form-control" value={form.password} onChange={e => setForm({...form, password: e.target.value})} /></div>
            <div className="form-group"><label>Role</label>
              <Dropdown
                value={form.role}
                onChange={v => setForm({ ...form, role: v })}
                options={[{ value: 'viewer', label: 'Viewer' }, { value: 'admin', label: 'Admin' }]}
              />
            </div>
          </div>
        </Modal>
      )}

      {editUser && (
        <Modal title="Edit User" onClose={() => setEditUser(null)} footer={
          <>
            <button className="um-btn um-btn--secondary" onClick={() => setEditUser(null)}>Cancel</button>
            <button className="um-btn um-btn--primary" onClick={handleEdit} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
          </>
        }>
          <div className="um-form">
            {error && <div className="alert-banner error">{error}</div>}
            <div className="form-group"><label>Full Name</label><input className="form-control" value={editUser.name} onChange={e => setEditUser({...editUser, name: e.target.value})} /></div>
            <div className="form-group"><label>Email</label><input type="email" className="form-control" value={editUser.email} onChange={e => setEditUser({...editUser, email: e.target.value})} /></div>
            <div className="form-group"><label>Role</label>
              <Dropdown
                value={editUser.role}
                onChange={v => setEditUser({ ...editUser, role: v })}
                options={[{ value: 'viewer', label: 'Viewer' }, { value: 'admin', label: 'Admin' }]}
              />
            </div>
          </div>
        </Modal>
      )}

      {tempPassword && (
        <Modal title="Temporary Password" onClose={() => setTempPassword(null)} footer={
          <button className="um-btn um-btn--primary" onClick={() => setTempPassword(null)}>Done</button>
        }>
          <p style={{ marginBottom: '1rem' }}>Share this temporary password with the user:</p>
          <code style={{ display: 'block', background: '#FBF6F1', border: '1px dashed #F58A3C', padding: '1rem', borderRadius: 8, fontSize: '1.2rem', fontFamily: 'monospace', letterSpacing: '0.1em', wordBreak: 'break-all' }}>
            {tempPassword}
          </code>
          <p style={{ marginTop: '0.75rem', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            The user should change this password after first login.
          </p>
        </Modal>
      )}
    </div>
  );
}

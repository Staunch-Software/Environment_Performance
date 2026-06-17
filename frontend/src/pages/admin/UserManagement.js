import { useState, useEffect } from 'react';
import Modal from '../../components/shared/Modal';
import Badge from '../../components/shared/Badge';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import api from '../../api/axios';

export default function UserManagement() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editUser, setEditUser] = useState(null);
  const [tempPassword, setTempPassword] = useState(null);
  const [form, setForm] = useState({ name: '', email: '', password: '', role: 'viewer' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

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

  return (
    <div>
      <div className="page-header">
        <h2>User Management</h2>
        <button className="btn btn-primary" onClick={() => setShowAdd(true)}>+ Add User</button>
      </div>

      {loading ? <LoadingSpinner /> : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Name</th><th>Email</th><th>Role</th><th>Last Login</th><th>Status</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id}>
                  <td>{u.name}</td>
                  <td>{u.email}</td>
                  <td><Badge value={u.role} /></td>
                  <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    {u.last_login ? new Date(u.last_login).toLocaleDateString() : 'Never'}
                  </td>
                  <td><Badge value={u.is_active ? 'active' : 'inactive'} /></td>
                  <td>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <button className="btn btn-ghost btn-sm" onClick={() => setEditUser(u)}>Edit</button>
                      <button className="btn btn-secondary btn-sm" onClick={() => handleToggle(u)}>
                        {u.is_active ? 'Deactivate' : 'Activate'}
                      </button>
                      <button className="btn btn-ghost btn-sm" onClick={() => handleReset(u)}>Reset Pwd</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showAdd && (
        <Modal title="Add User" onClose={() => setShowAdd(false)} footer={
          <>
            <button className="btn btn-secondary" onClick={() => setShowAdd(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleAdd} disabled={saving}>{saving ? 'Saving…' : 'Add User'}</button>
          </>
        }>
          {error && <div className="alert-banner error">{error}</div>}
          <div className="form-group"><label>Full Name *</label><input className="form-control" value={form.name} onChange={e => setForm({...form, name: e.target.value})} /></div>
          <div className="form-group"><label>Email *</label><input type="email" className="form-control" value={form.email} onChange={e => setForm({...form, email: e.target.value})} /></div>
          <div className="form-group"><label>Password *</label><input type="password" className="form-control" value={form.password} onChange={e => setForm({...form, password: e.target.value})} /></div>
          <div className="form-group"><label>Role</label>
            <select className="form-control" value={form.role} onChange={e => setForm({...form, role: e.target.value})}>
              <option value="viewer">Viewer</option><option value="admin">Admin</option>
            </select>
          </div>
        </Modal>
      )}

      {editUser && (
        <Modal title="Edit User" onClose={() => setEditUser(null)} footer={
          <>
            <button className="btn btn-secondary" onClick={() => setEditUser(null)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleEdit} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
          </>
        }>
          {error && <div className="alert-banner error">{error}</div>}
          <div className="form-group"><label>Full Name</label><input className="form-control" value={editUser.name} onChange={e => setEditUser({...editUser, name: e.target.value})} /></div>
          <div className="form-group"><label>Email</label><input type="email" className="form-control" value={editUser.email} onChange={e => setEditUser({...editUser, email: e.target.value})} /></div>
          <div className="form-group"><label>Role</label>
            <select className="form-control" value={editUser.role} onChange={e => setEditUser({...editUser, role: e.target.value})}>
              <option value="viewer">Viewer</option><option value="admin">Admin</option>
            </select>
          </div>
        </Modal>
      )}

      {tempPassword && (
        <Modal title="Temporary Password" onClose={() => setTempPassword(null)} footer={
          <button className="btn btn-primary" onClick={() => setTempPassword(null)}>Done</button>
        }>
          <p style={{ marginBottom: '1rem' }}>Share this temporary password with the user:</p>
          <code style={{ display: 'block', background: '#f0f4f8', padding: '1rem', borderRadius: 4, fontSize: '1.2rem', fontFamily: 'monospace', letterSpacing: '0.1em' }}>
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

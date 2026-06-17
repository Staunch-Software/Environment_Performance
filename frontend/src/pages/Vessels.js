import { useState, useEffect } from 'react';
import Sidebar from '../components/Layout/Sidebar';
import Header from '../components/Layout/Header';
import Table from '../components/shared/Table';
import Modal from '../components/shared/Modal';
import Badge from '../components/shared/Badge';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import { useAuth } from '../context/AuthContext';
import api from '../api/axios';

export default function Vessels() {
  const { isAdmin } = useAuth();
  const [vessels, setVessels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState({ name: '', imo_number: '', call_sign: '' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const load = () => {
    setLoading(true);
    api.get('/api/vessels').then(r => setVessels(r.data.data || [])).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      await api.post('/api/vessels', form);
      setShowModal(false);
      setForm({ name: '', imo_number: '', call_sign: '' });
      load();
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to create vessel');
    } finally {
      setSaving(false);
    }
  };

  const columns = [
    { key: 'name', label: 'Vessel Name' },
    { key: 'imo_number', label: 'IMO Number' },
    { key: 'call_sign', label: 'Call Sign', render: (r) => r.call_sign || '—' },
    { key: 'is_active', label: 'Status', render: (r) => <Badge value={r.is_active ? 'active' : 'inactive'} /> },
    { key: 'created_at', label: 'Added', render: (r) => new Date(r.created_at).toLocaleDateString() },
  ];

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content">
        <Header title="Vessels" />
        <div className="page-body">
          <div className="page-header">
            <h1>Vessels</h1>
            {isAdmin && (
              <button className="btn btn-primary" onClick={() => setShowModal(true)}>
                + Add Vessel
              </button>
            )}
          </div>
          {loading ? <LoadingSpinner /> : <Table columns={columns} data={vessels} />}

          {showModal && (
            <Modal
              title="Add Vessel"
              onClose={() => setShowModal(false)}
              footer={
                <>
                  <button className="btn btn-secondary" onClick={() => setShowModal(false)}>Cancel</button>
                  <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                    {saving ? 'Saving…' : 'Add Vessel'}
                  </button>
                </>
              }
            >
              {error && <div className="alert-banner error">{error}</div>}
              <div className="form-group">
                <label>Vessel Name *</label>
                <input className="form-control" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="form-group">
                <label>IMO Number *</label>
                <input className="form-control" value={form.imo_number} onChange={e => setForm({ ...form, imo_number: e.target.value })} />
              </div>
              <div className="form-group">
                <label>Call Sign</label>
                <input className="form-control" value={form.call_sign} onChange={e => setForm({ ...form, call_sign: e.target.value })} />
              </div>
            </Modal>
          )}
        </div>
      </div>
    </div>
  );
}

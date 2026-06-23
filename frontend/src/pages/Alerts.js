import { useState, useEffect } from 'react';
import Sidebar from '../components/Layout/Sidebar';
import Header from '../components/Layout/Header';
import Badge from '../components/shared/Badge';
import Modal from '../components/shared/Modal';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import api from '../api/axios';

const SEVERITIES = ['critical', 'major', 'minor', 'observation'];
const ALERT_TYPES = [
  'wrong_item_code', 'mass_balance_error', 'overdue_sounding',
  'tank_capacity_threshold', 'combined_capacity_threshold',
  'sludge_generation_rate', 'overdue_discharge', 'missing_bdn', 'low_confidence_extraction',
];

export default function Alerts() {
  const [alerts, setAlerts] = useState([]);
  const [vessels, setVessels] = useState([]);
  const [summary, setSummary] = useState({});
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ vessel_id: '', severity: '', is_resolved: '', alert_type: '' });
  const [resolving, setResolving] = useState(null);
  const [recalculating, setRecalculating] = useState(false);

  useEffect(() => { api.get('/api/vessels').then(r => setVessels(r.data.data || [])); }, []);

  const load = () => {
    setLoading(true);
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => { if (v !== '') params.append(k, v); });
    Promise.all([
      api.get(`/api/alerts?${params}`),
      api.get('/api/alerts/summary'),
    ]).then(([a, s]) => {
      setAlerts(a.data.data || []);
      setSummary(s.data.data || {});
    }).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const setFilter = (k, v) => setFilters(f => ({ ...f, [k]: v }));

  const handleResolve = async () => {
    await api.patch(`/api/alerts/${resolving}/resolve`, { notes: '' });
    setResolving(null);
    load();
  };

  const handleRecalculate = async () => {
    if (!filters.vessel_id) return;
    setRecalculating(true);
    try {
      await api.post(`/api/alerts/recalculate?vessel_id=${filters.vessel_id}`);
      load();
    } finally {
      setRecalculating(false);
    }
  };

  const CHIP_COLORS = {
    critical: { bg: '#FFE0E0', color: '#9b2335' },
    major: { bg: '#FFF0E0', color: '#7d4a00' },
    minor: { bg: '#FFFDE0', color: '#6d6200' },
    observation: { bg: '#f0f0f0', color: '#555' },
  };

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content">
        <Header title="Alerts" />
        <div className="page-body">
          <div className="page-header"><h1>Compliance Alerts</h1></div>

          <div className="severity-bar">
            {SEVERITIES.map(s => (
              <div key={s} className="severity-chip" style={{ background: CHIP_COLORS[s].bg, color: CHIP_COLORS[s].color }}>
                <span className="count">{summary[s] || 0}</span>
                <span style={{ textTransform: 'capitalize' }}>{s}</span>
              </div>
            ))}
          </div>

          <div className="card" style={{ marginBottom: '1rem' }}>
            <div className="filters-bar">
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Vessel</label>
                <select className="form-control" value={filters.vessel_id} onChange={e => setFilter('vessel_id', e.target.value)}>
                  <option value="">All</option>
                  {vessels.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
                </select>
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Severity</label>
                <select className="form-control" value={filters.severity} onChange={e => setFilter('severity', e.target.value)}>
                  <option value="">All</option>
                  {SEVERITIES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Status</label>
                <select className="form-control" value={filters.is_resolved} onChange={e => setFilter('is_resolved', e.target.value)}>
                  <option value="">All</option>
                  <option value="false">Open</option>
                  <option value="true">Resolved</option>
                </select>
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Type</label>
                <select className="form-control" value={filters.alert_type} onChange={e => setFilter('alert_type', e.target.value)}>
                  <option value="">All</option>
                  {ALERT_TYPES.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
                </select>
              </div>
              <button className="btn btn-primary" onClick={load} style={{ alignSelf: 'flex-end' }}>Apply</button>
              <button
                className="btn btn-secondary"
                onClick={handleRecalculate}
                disabled={!filters.vessel_id || recalculating}
                title={!filters.vessel_id ? 'Select a vessel first' : 'Clear stale alerts and rerun all compliance checks'}
                style={{ alignSelf: 'flex-end' }}
              >
                {recalculating ? 'Recalculating…' : 'Recalculate Alerts'}
              </button>
            </div>
          </div>

          {loading ? <LoadingSpinner /> : (
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Severity</th><th>Vessel</th><th>Type</th><th>Message</th>
                    <th>Created</th><th>Status</th><th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {alerts.length === 0 ? (
                    <tr><td colSpan={7} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>No alerts found.</td></tr>
                  ) : alerts.map(a => (
                    <tr key={a.id}>
                      <td><Badge value={a.severity} /></td>
                      <td style={{ fontSize: '0.85rem' }}>{vessels.find(v => v.id === a.vessel_id)?.name || '—'}</td>
                      <td style={{ fontSize: '0.8rem' }}>{a.alert_type.replace(/_/g, ' ')}</td>
                      <td style={{ maxWidth: 320, fontSize: '0.85rem' }}>{a.message}</td>
                      <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        {new Date(a.created_at).toLocaleDateString()}
                        {!a.is_resolved && (() => {
                          const days = Math.floor((Date.now() - new Date(a.created_at)) / 86400000);
                          const color = days < 7 ? '#22c55e' : days < 30 ? '#f59e0b' : '#ef4444';
                          return (
                            <span style={{
                              marginLeft: '0.4rem', fontSize: '0.72rem', fontWeight: 700,
                              color, background: color + '18', borderRadius: 4,
                              padding: '1px 5px',
                            }}>
                              {days === 0 ? 'Today' : `${days}d`}
                            </span>
                          );
                        })()}
                      </td>
                      <td><Badge value={a.is_resolved ? 'Resolved' : 'Open'} type={a.is_resolved ? 'completed' : 'pending'} /></td>
                      <td>
                        {!a.is_resolved && (
                          <button className="btn btn-ghost btn-sm" onClick={() => setResolving(a.id)}>Resolve</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {resolving && (
            <Modal
              title="Resolve Alert"
              onClose={() => setResolving(null)}
              footer={
                <>
                  <button className="btn btn-secondary" onClick={() => setResolving(null)}>Cancel</button>
                  <button className="btn btn-primary" onClick={handleResolve}>Confirm Resolve</button>
                </>
              }
            >
              <p>Mark this alert as resolved? This action will record your name and timestamp.</p>
            </Modal>
          )}
        </div>
      </div>
    </div>
  );
}

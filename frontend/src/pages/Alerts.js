import { Fragment, useState, useEffect, useRef } from 'react';
import Sidebar from '../components/Layout/Sidebar';
import Header from '../components/Layout/Header';
import Badge from '../components/shared/Badge';
import Modal from '../components/shared/Modal';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import Dropdown from '../components/shared/Dropdown';
import MultiSelectDropdown from '../components/shared/MultiSelectDropdown';
import api from '../api/axios';

const SEVERITIES = ['critical', 'major', 'minor', 'observation'];

// 12 alert types per the new compliance spec
const ALERT_TYPES = [
  'wrong_item_code',                 // 1  Major
  'mass_balance_error',              // 2  Major
  'tank_capacity_exceeded',          // 3  Critical
  'combined_capacity_threshold',     // 4  Major
  'sludge_generation_rate',          // 5  Observation/Minor
  'bilge_increasing_rate',           // 6  Major
  'sludge_vs_fuel_consumption',      // 7  Observation/Major/Critical
  'bilge_transfer_vs_soundings',     // 8  Minor
  // 'bilge_pump_capacity' (9) omitted — check paused, no UI to set pump capacity yet
  'bunker_mismatch',                 // 10 Minor
  'missing_master_signature',        // 11 Minor
  'non_chronological_entry',         // 12 Minor
  'erasure_detected',                // 12 Observation
];

export default function Alerts() {
  const [alerts, setAlerts] = useState([]);
  const [vessels, setVessels] = useState([]);
  const [summary, setSummary] = useState({});
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ vessel_id: [], severity: '', is_resolved: '', alert_type: '' });
  const [resolving, setResolving] = useState(null);
  const [recalculating, setRecalculating] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const [entryCache, setEntryCache] = useState({}); // entry_id -> EntryResponse
  const [entryLoading, setEntryLoading] = useState(null); // entry_id currently fetching
  const expandedRowRef = useRef(null);

  // Auto-scroll the expanded "Source ORB Entry" panel into view — it can render
  // below the fold (especially for the 3rd+ row), and once the entry data loads
  // the panel grows taller, so re-run after loading finishes too.
  useEffect(() => {
    if (expandedId && expandedRowRef.current) {
      expandedRowRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [expandedId, entryLoading]);

  useEffect(() => { api.get('/api/vessels').then(r => setVessels(r.data.data || [])); }, []);

  const load = (overrides = {}) => {
    setLoading(true);
    const activeFilters = { ...filters, ...overrides };
    const params = new URLSearchParams();
    Object.entries(activeFilters).forEach(([k, v]) => {
      if (Array.isArray(v)) v.forEach(item => params.append(k, item));
      else if (v !== '') params.append(k, v);
    });
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

  const handleSeverityClick = (s) => {
    const newSeverity = filters.severity === s ? '' : s;
    setFilters(f => ({ ...f, severity: newSeverity }));
    load({ severity: newSeverity });
  };

  const toggleExpand = async (alert) => {
    if (expandedId === alert.id) { setExpandedId(null); return; }
    setExpandedId(alert.id);
    if (alert.entry_id && !entryCache[alert.entry_id]) {
      setEntryLoading(alert.entry_id);
      try {
        const r = await api.get(`/api/entries/${alert.entry_id}`);
        setEntryCache(c => ({ ...c, [alert.entry_id]: r.data.data }));
      } finally {
        setEntryLoading(null);
      }
    }
  };

  const handleResolve = async () => {
    await api.patch(`/api/alerts/${resolving}/resolve`, { notes: '' });
    setResolving(null);
    load();
  };

  const handleRecalculate = async () => {
    if (filters.vessel_id.length !== 1) return;
    setRecalculating(true);
    try {
      await api.post(`/api/alerts/recalculate?vessel_id=${filters.vessel_id[0]}`);
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
              <div
                key={s}
                className="severity-chip"
                onClick={() => handleSeverityClick(s)}
                style={{
                  background: CHIP_COLORS[s].bg,
                  color: CHIP_COLORS[s].color,
                  cursor: 'pointer',
                  outline: filters.severity === s ? `2px solid ${CHIP_COLORS[s].color}` : 'none',
                  outlineOffset: '2px',
                }}
              >
                <span className="count">{summary[s] || 0}</span>
                <span style={{ textTransform: 'capitalize' }}>{s}</span>
              </div>
            ))}
          </div>

          <div className="card" style={{ marginBottom: '1rem' }}>
            <div className="filters-bar">
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Vessel</label>
                <MultiSelectDropdown
                  value={filters.vessel_id}
                  onChange={v => setFilter('vessel_id', v)}
                  placeholder="Select the vessel"
                  options={vessels.map(v => ({ value: v.id, label: v.name }))}
                />
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Severity</label>
                <Dropdown
                  value={filters.severity}
                  onChange={v => setFilter('severity', v)}
                  options={[{ value: '', label: 'All' }, ...SEVERITIES.map(s => ({ value: s, label: s }))]}
                />
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Status</label>
                <Dropdown
                  value={filters.is_resolved}
                  onChange={v => setFilter('is_resolved', v)}
                  options={[{ value: '', label: 'All' }, { value: 'false', label: 'Open' }, { value: 'true', label: 'Resolved' }]}
                />
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Type</label>
                <Dropdown
                  value={filters.alert_type}
                  onChange={v => setFilter('alert_type', v)}
                  options={[{ value: '', label: 'All' }, ...ALERT_TYPES.map(t => ({ value: t, label: t.replace(/_/g, ' ') }))]}
                />
              </div>
              <div style={{ display: 'flex', gap: '0.75rem', alignSelf: 'flex-end', flexShrink: 0 }}>
                <button className="btn btn-primary" onClick={load}>Apply</button>
                <button
                  className="btn btn-secondary"
                  onClick={handleRecalculate}
                  disabled={filters.vessel_id.length !== 1 || recalculating}
                  title={filters.vessel_id.length !== 1 ? 'Select exactly one vessel first' : 'Clear stale alerts and rerun all compliance checks'}
                >
                  {recalculating ? 'Recalculating…' : 'Recalculate Alerts'}
                </button>
              </div>
            </div>
          </div>

          {loading ? <LoadingSpinner /> : (
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Severity</th><th>Vessel</th><th>Type</th><th>Message</th><th>Page</th>
                    <th>Created</th><th>Status</th><th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {alerts.length === 0 ? (
                    <tr><td colSpan={8} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>No alerts found.</td></tr>
                  ) : alerts.map(a => {
                    const expanded = expandedId === a.id;
                    const entry = a.entry_id ? entryCache[a.entry_id] : null;
                    return (
                      <Fragment key={a.id}>
                        <tr onClick={() => toggleExpand(a)} style={{ cursor: 'pointer' }}>
                          <td><Badge value={a.severity} /></td>
                          <td style={{ fontSize: '0.85rem' }}>{vessels.find(v => v.id === a.vessel_id)?.name || '—'}</td>
                          <td style={{ fontSize: '0.8rem' }}>{a.alert_type.replace(/_/g, ' ')}</td>
                          <td style={{ maxWidth: 320, fontSize: '0.85rem' }}>{a.message}</td>
                          <td style={{ fontSize: '0.8rem', textAlign: 'center' }}>{a.page_number ?? '—'}</td>
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
                              <button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); setResolving(a.id); }}>Resolve</button>
                            )}
                          </td>
                        </tr>
                        {expanded && (
                          <tr key={`${a.id}-exp`} ref={expandedRowRef} style={{ background: '#f8fafc' }}>
                            <td colSpan={8} style={{ padding: '1rem 2rem' }}>
                              {!a.entry_id ? (
                                <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                                  No specific entry — this is a vessel-level aggregate alert.
                                </span>
                              ) : entryLoading === a.entry_id ? (
                                <LoadingSpinner />
                              ) : !entry ? (
                                <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Source entry not found.</span>
                              ) : (
                                <>
                                  <strong>Source ORB Entry</strong>
                                  <div style={{ fontSize: '0.85rem', marginTop: '0.5rem', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.5rem' }}>
                                    <div><span style={{ color: 'var(--text-muted)' }}>Date:</span> {entry.entry_date}</div>
                                    <div><span style={{ color: 'var(--text-muted)' }}>Code:</span> <strong>{entry.orb_code}</strong></div>
                                    <div><span style={{ color: 'var(--text-muted)' }}>Item:</span> {entry.item_number || '—'}</div>
                                    <div><span style={{ color: 'var(--text-muted)' }}>Tank/Location:</span> {entry.tank_location || '—'}</div>
                                    <div style={{ gridColumn: '1 / -1' }}><span style={{ color: 'var(--text-muted)' }}>Operation:</span> {entry.operation_description}</div>
                                    <div><span style={{ color: 'var(--text-muted)' }}>Officer 1:</span> {entry.officer_1_name || '—'} {entry.officer_1_rank ? `(${entry.officer_1_rank})` : ''}</div>
                                    <div><span style={{ color: 'var(--text-muted)' }}>Officer 2:</span> {entry.officer_2_name || '—'} {entry.officer_2_rank ? `(${entry.officer_2_rank})` : ''}</div>
                                    <div><span style={{ color: 'var(--text-muted)' }}>Confidence:</span> {entry.confidence_score != null ? `${(entry.confidence_score * 100).toFixed(0)}%` : '—'}</div>
                                  </div>
                                  <div style={{ marginTop: '0.75rem' }}>
                                    <strong>Quantities:</strong>
                                    {entry.quantities?.length ? (
                                      <table style={{ marginTop: '0.5rem', fontSize: '0.85rem' }}>
                                        <thead><tr><th style={{ paddingRight: 16 }}>Type</th><th style={{ paddingRight: 16 }}>Value</th><th style={{ paddingRight: 16 }}>Unit</th><th style={{ paddingRight: 16 }}>From</th><th>To</th></tr></thead>
                                        <tbody>
                                          {entry.quantities.map(q => (
                                            <tr key={q.id}>
                                              <td style={{ paddingRight: 16 }}>{q.qty_type}</td>
                                              <td style={{ paddingRight: 16 }}>{q.qty_value}</td>
                                              <td style={{ paddingRight: 16 }}>{q.qty_unit}</td>
                                              <td style={{ paddingRight: 16 }}>{q.from_tank || '—'}</td>
                                              <td>{q.to_tank || '—'}</td>
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    ) : <span style={{ marginLeft: '0.5rem', color: 'var(--text-muted)' }}>None</span>}
                                  </div>
                                </>
                              )}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
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
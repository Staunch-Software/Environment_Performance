import { Fragment, useState, useEffect, useRef } from 'react';
import {
  ShieldAlert, AlertTriangle, AlertCircle, Eye, RefreshCw, Check, FileText, BellOff, Filter,
} from 'lucide-react';
import Sidebar from '../components/Layout/Sidebar';
import Header from '../components/Layout/Header';
import Badge from '../components/shared/Badge';
import Modal from '../components/shared/Modal';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import Dropdown from '../components/shared/Dropdown';
import MultiSelectDropdown from '../components/shared/MultiSelectDropdown';
import api from '../api/axios';
import './Alerts.css';

const SEVERITIES = ['critical', 'major', 'minor', 'observation'];

const SEVERITY_ICONS = {
  critical: ShieldAlert,
  major: AlertTriangle,
  minor: AlertCircle,
  observation: Eye,
};

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

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content">
        <Header title="Alerts" />
        <div className="page-body">
          <div className="al">
            <div className="al-header">
              <div className="al-header__text">
                <span className="al-eyebrow">Compliance</span>
                <h1 className="al-title">Compliance Alerts</h1>
                <p className="al-subtitle">Review, investigate and resolve MARPOL compliance findings across your fleet.</p>
              </div>
            </div>

            <div className="al-severity">
              {SEVERITIES.map(s => {
                const Icon = SEVERITY_ICONS[s];
                const active = filters.severity === s;
                return (
                  <button
                    key={s}
                    type="button"
                    className={`al-sev al-sev--${s}${active ? ' al-sev--active' : ''}`}
                    onClick={() => handleSeverityClick(s)}
                    aria-pressed={active}
                  >
                    <span className="al-sev__icon"><Icon size={20} /></span>
                    <span className="al-sev__body">
                      <span className="al-sev__count">{summary[s] || 0}</span>
                      <span className="al-sev__label">{s}</span>
                    </span>
                    {active && <span className="al-sev__tag">Filtered</span>}
                  </button>
                );
              })}
            </div>

            <div className="al-filters">
              <div className="al-filters__title"><Filter size={14} /> Filters</div>
              <div className="al-filters__grid">
                <div className="form-group">
                  <label>Vessel</label>
                  <MultiSelectDropdown
                    value={filters.vessel_id}
                    onChange={v => setFilter('vessel_id', v)}
                    placeholder="Select the vessel"
                    options={vessels.map(v => ({ value: v.id, label: v.name }))}
                  />
                </div>
                <div className="form-group">
                  <label>Severity</label>
                  <Dropdown
                    value={filters.severity}
                    onChange={v => setFilter('severity', v)}
                    options={[{ value: '', label: 'All' }, ...SEVERITIES.map(s => ({ value: s, label: s }))]}
                  />
                </div>
                <div className="form-group">
                  <label>Status</label>
                  <Dropdown
                    value={filters.is_resolved}
                    onChange={v => setFilter('is_resolved', v)}
                    options={[{ value: '', label: 'All' }, { value: 'false', label: 'Open' }, { value: 'true', label: 'Resolved' }]}
                  />
                </div>
                <div className="form-group">
                  <label>Type</label>
                  <Dropdown
                    value={filters.alert_type}
                    onChange={v => setFilter('alert_type', v)}
                    options={[{ value: '', label: 'All' }, ...ALERT_TYPES.map(t => ({ value: t, label: t.replace(/_/g, ' ') }))]}
                  />
                </div>
                <div className="al-filters__actions">
                  <button className="al-btn al-btn--primary" onClick={load}>Apply</button>
                  <button
                    className="al-btn al-btn--secondary"
                    onClick={handleRecalculate}
                    disabled={filters.vessel_id.length !== 1 || recalculating}
                    title={filters.vessel_id.length !== 1 ? 'Select exactly one vessel first' : 'Clear stale alerts and rerun all compliance checks'}
                  >
                    <RefreshCw size={15} className={recalculating ? 'al-spin' : ''} />
                    {recalculating ? 'Recalculating…' : 'Recalculate Alerts'}
                  </button>
                </div>
              </div>
            </div>

            {loading ? <LoadingSpinner /> : (
              <div className="al-panel">
                <div className="al-table-wrap">
                  <table className="al-table">
                    <thead>
                      <tr>
                        <th>Severity</th><th>Vessel</th><th>Type</th><th>Message</th><th className="al-center">Page</th>
                        <th>Created</th><th>Status</th><th className="al-th-actions">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {alerts.length === 0 ? (
                        <tr className="al-emptyrow">
                          <td colSpan={8}>
                            <div className="al-empty">
                              <span className="al-empty__icon"><BellOff size={24} /></span>
                              <div className="al-empty__title">No alerts found.</div>
                              <div className="al-empty__text">Nothing matches the current filters.</div>
                            </div>
                          </td>
                        </tr>
                      ) : alerts.map(a => {
                        const expanded = expandedId === a.id;
                        const entry = a.entry_id ? entryCache[a.entry_id] : null;
                        return (
                          <Fragment key={a.id}>
                            <tr
                              onClick={() => toggleExpand(a)}
                              className={`al-row al-row--${a.severity}${expanded ? ' al-row--open' : ''}${a.is_resolved ? ' al-row--resolved' : ''}`}
                            >
                              <td data-label="Severity" className="al-td-sev"><Badge value={a.severity} /></td>
                              <td data-label="Vessel" className="al-vessel">{vessels.find(v => v.id === a.vessel_id)?.name || '—'}</td>
                              <td data-label="Type"><span className="al-type">{a.alert_type.replace(/_/g, ' ')}</span></td>
                              <td data-label="Message" className="al-msg"><span className="al-msg__text">{a.message}</span></td>
                              <td data-label="Page" className="al-center al-muted">{a.page_number ?? '—'}</td>
                              <td data-label="Created" className="al-muted">
                                {new Date(a.created_at).toLocaleDateString()}
                                {!a.is_resolved && (() => {
                                  const days = Math.floor((Date.now() - new Date(a.created_at)) / 86400000);
                                  const color = days < 7 ? '#22c55e' : days < 30 ? '#f59e0b' : '#ef4444';
                                  return (
                                    <span
                                      className="al-age"
                                      style={{ color, background: color + '18' }}
                                    >
                                      {days === 0 ? 'Today' : `${days}d`}
                                    </span>
                                  );
                                })()}
                              </td>
                              <td data-label="Status"><Badge value={a.is_resolved ? 'Resolved' : 'Open'} type={a.is_resolved ? 'completed' : 'pending'} /></td>
                              <td className="al-td-actions">
                                {!a.is_resolved && (
                                  <button className="al-btn al-btn--ghost al-btn--sm" onClick={(e) => { e.stopPropagation(); setResolving(a.id); }}>
                                    <Check size={14} /> Resolve
                                  </button>
                                )}
                              </td>
                            </tr>
                            {expanded && (
                              <tr key={`${a.id}-exp`} ref={expandedRowRef} className="al-exprow">
                                <td colSpan={8}>
                                  <div className="al-detail">
                                    {!a.entry_id ? (
                                      <span className="al-muted">
                                        No specific entry — this is a vessel-level aggregate alert.
                                      </span>
                                    ) : entryLoading === a.entry_id ? (
                                      <LoadingSpinner />
                                    ) : !entry ? (
                                      <span className="al-muted">Source entry not found.</span>
                                    ) : (
                                      <>
                                        <div className="al-detail__title"><FileText size={15} /> Source ORB Entry</div>
                                        <div className="al-detail__grid">
                                          <div><span className="al-k">Date:</span> {entry.entry_date}</div>
                                          <div><span className="al-k">Code:</span> <strong>{entry.orb_code}</strong></div>
                                          <div><span className="al-k">Item:</span> {entry.item_number || '—'}</div>
                                          <div><span className="al-k">Tank/Location:</span> {entry.tank_location || '—'}</div>
                                          <div className="al-detail__wide"><span className="al-k">Operation:</span> {entry.operation_description}</div>
                                          <div><span className="al-k">Officer 1:</span> {entry.officer_1_name || '—'} {entry.officer_1_rank ? `(${entry.officer_1_rank})` : ''}</div>
                                          <div><span className="al-k">Officer 2:</span> {entry.officer_2_name || '—'} {entry.officer_2_rank ? `(${entry.officer_2_rank})` : ''}</div>
                                          <div><span className="al-k">Confidence:</span> {entry.confidence_score != null ? `${(entry.confidence_score * 100).toFixed(0)}%` : '—'}</div>
                                        </div>
                                        <div className="al-detail__qty">
                                          <div className="al-detail__title">Quantities</div>
                                          {entry.quantities?.length ? (
                                            <div className="al-qty-wrap">
                                              <table className="al-qty">
                                                <thead><tr><th>Type</th><th>Value</th><th>Unit</th><th>From</th><th>To</th></tr></thead>
                                                <tbody>
                                                  {entry.quantities.map(q => (
                                                    <tr key={q.id}>
                                                      <td>{q.qty_type}</td>
                                                      <td>{q.qty_value}</td>
                                                      <td>{q.qty_unit}</td>
                                                      <td>{q.from_tank || '—'}</td>
                                                      <td>{q.to_tank || '—'}</td>
                                                    </tr>
                                                  ))}
                                                </tbody>
                                              </table>
                                            </div>
                                          ) : <span className="al-muted"> None</span>}
                                        </div>
                                      </>
                                    )}
                                  </div>
                                </td>
                              </tr>
                            )}
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {resolving && (
              <Modal
                title="Resolve Alert"
                onClose={() => setResolving(null)}
                footer={
                  <>
                    <button className="al-btn al-btn--secondary" onClick={() => setResolving(null)}>Cancel</button>
                    <button className="al-btn al-btn--primary" onClick={handleResolve}>Confirm Resolve</button>
                  </>
                }
              >
                <p>Mark this alert as resolved? This action will record your name and timestamp.</p>
              </Modal>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

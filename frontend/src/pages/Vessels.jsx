import { useState, useEffect, useMemo } from 'react';
import { Ship, Search, X, BellRing, ShieldCheck, Activity } from 'lucide-react';
import Sidebar from '../components/Layout/Sidebar';
import Header from '../components/Layout/Header';
import Badge from '../components/shared/Badge';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import api from '../api/axios';
import './Vessels.css';

const initialsOf = (name) => {
  const words = (name || '?').trim().split(/\s+/);
  return (words.length === 1 ? words[0].slice(0, 2) : words[0][0] + words[1][0]).toUpperCase();
};

// Same thresholds as before: 0 = clear, 1-2 = attention, 3+ = critical.
const healthOf = (count) => {
  if (count === 0) return { tone: 'ok', label: 'No alerts' };
  if (count <= 2) return { tone: 'warn', label: `${count} open` };
  return { tone: 'bad', label: `${count} open` };
};

export default function Vessels() {
  const [vessels, setVessels] = useState([]);
  const [alertsByVessel, setAlertsByVessel] = useState({});
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  const load = () => {
    setLoading(true);
    Promise.all([
      api.get('/api/vessels'),
      api.get('/api/alerts?is_resolved=false'),
    ]).then(([v, a]) => {
      setVessels(v.data.data || []);
      const map = {};
      (a.data.data || []).forEach(alert => {
        map[alert.vessel_id] = (map[alert.vessel_id] || 0) + 1;
      });
      setAlertsByVessel(map);
    }).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const stats = useMemo(() => ({
    total: vessels.length,
    active: vessels.filter(v => v.is_active).length,
    flagged: vessels.filter(v => (alertsByVessel[v.id] || 0) > 0).length,
    openAlerts: vessels.reduce((s, v) => s + (alertsByVessel[v.id] || 0), 0),
  }), [vessels, alertsByVessel]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return vessels;
    return vessels.filter(v =>
      (v.name || '').toLowerCase().includes(q) ||
      String(v.imo_number || '').toLowerCase().includes(q) ||
      (v.call_sign || '').toLowerCase().includes(q)
    );
  }, [vessels, search]);

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content">
        <Header title="Vessels" />
        <div className="page-body">
          <div className="vs">
            <div className="vs-header">
              <div className="vs-header__text">
                <span className="vs-eyebrow">Fleet</span>
                <h1 className="vs-title">Vessels</h1>
                <p className="vs-subtitle">Fleet overview with live compliance status for every registered vessel.</p>
              </div>
            </div>

            {loading ? <LoadingSpinner /> : (
              <>
                <div className="vs-stats">
                  <div className="vs-stat">
                    <span className="vs-stat__icon"><Ship size={18} /></span>
                    <div><div className="vs-stat__value">{stats.total}</div><div className="vs-stat__label">Total Vessels</div></div>
                  </div>
                  <div className="vs-stat vs-stat--green">
                    <span className="vs-stat__icon"><Activity size={18} /></span>
                    <div><div className="vs-stat__value">{stats.active}</div><div className="vs-stat__label">Active</div></div>
                  </div>
                  <div className="vs-stat vs-stat--amber">
                    <span className="vs-stat__icon"><BellRing size={18} /></span>
                    <div><div className="vs-stat__value">{stats.flagged}</div><div className="vs-stat__label">With Open Alerts</div></div>
                  </div>
                  <div className="vs-stat vs-stat--navy">
                    <span className="vs-stat__icon"><ShieldCheck size={18} /></span>
                    <div><div className="vs-stat__value">{stats.openAlerts}</div><div className="vs-stat__label">Total Open Alerts</div></div>
                  </div>
                </div>

                {vessels.length > 0 && (
                  <div className="vs-toolbar">
                    <div className="vs-search">
                      <Search size={16} className="vs-search__icon" />
                      <input
                        type="text"
                        className="vs-search__input"
                        placeholder="Search by vessel name, IMO or call sign…"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        aria-label="Search vessels"
                      />
                      {search && (
                        <button type="button" className="vs-search__clear" onClick={() => setSearch('')} aria-label="Clear search">
                          <X size={14} />
                        </button>
                      )}
                    </div>
                    <div className="vs-count">Showing <strong>{filtered.length}</strong> of {vessels.length}</div>
                  </div>
                )}

                {vessels.length === 0 ? (
                  <div className="vs-empty">
                    <span className="vs-empty__icon"><Ship size={26} /></span>
                    <div className="vs-empty__title">No records found.</div>
                  </div>
                ) : filtered.length === 0 ? (
                  <div className="vs-empty">
                    <span className="vs-empty__icon"><Search size={26} /></span>
                    <div className="vs-empty__title">No vessels match your search</div>
                    <button type="button" className="vs-btn vs-btn--secondary" onClick={() => setSearch('')}>Clear search</button>
                  </div>
                ) : (
                  <div className="vs-panel">
                    <div className="vs-table-wrap">
                      <table className="vs-table">
                        <thead>
                          <tr>
                            <th>Vessel Name</th>
                            <th>IMO Number</th>
                            <th>Call Sign</th>
                            <th>Status</th>
                            <th>Open Alerts</th>
                            <th>Created At</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filtered.map(v => {
                            const health = healthOf(alertsByVessel[v.id] || 0);
                            return (
                              <tr key={v.id} className={v.is_active ? '' : 'vs-row--inactive'}>
                                <td>
                                  <div className="vs-vessel">
                                    <span className="vs-vessel__avatar" aria-hidden="true">{initialsOf(v.name)}</span>
                                    <span className="vs-vessel__name">{v.name}</span>
                                  </div>
                                </td>
                                <td className="vs-mono">{v.imo_number}</td>
                                <td className="vs-mono">{v.call_sign || '—'}</td>
                                <td><Badge value={v.is_active ? 'active' : 'inactive'} /></td>
                                <td>
                                  <span className={`vs-health vs-health--${health.tone}`}>
                                    <span className="vs-health__dot" />
                                    {health.label}
                                  </span>
                                </td>
                                <td className="vs-muted">{new Date(v.created_at).toLocaleDateString()}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

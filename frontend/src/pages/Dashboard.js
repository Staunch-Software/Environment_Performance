import { useState, useEffect } from 'react';
import { Ship, Upload, AlertTriangle, Anchor, Droplets, X } from 'lucide-react';
import Sidebar from '../components/Layout/Sidebar';
import Header from '../components/Layout/Header';
import Badge from '../components/shared/Badge';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import api from '../api/axios';

function SummaryCard({ label, value, sub, variant, icon: Icon, iconColor, bar, onClick, active }) {
  return (
    <div
      className={`summary-card${variant ? ` ${variant}` : ''}`}
      onClick={onClick}
      style={{
        position: 'relative', overflow: 'hidden',
        cursor: onClick ? 'pointer' : undefined,
        border: active ? '2px solid var(--primary)' : undefined,
      }}
    >
      {Icon && (
        <Icon
          size={80}
          style={{
            position: 'absolute',
            right: '1rem',
            bottom: '50%',
            transform: 'translateY(50%)',
            opacity: 0.12,
            color: iconColor || 'var(--primary)',
            pointerEvents: 'none',
          }}
        />
      )}
      <span className="sc-label">{label}</span>
      <span className="sc-value">{value}</span>
      {sub && <span className="sc-sub">{sub}</span>}
      {bar && bar.total > 0 && (
        <div style={{ marginTop: '0.6rem' }}>
          <div style={{ display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden', gap: 2 }}>
            {bar.critical > 0 && <div style={{ flex: bar.critical, background: '#ef4444', borderRadius: 3, transition: 'flex 0.4s ease' }} title={`${bar.critical} critical`} />}
            {bar.major > 0 && <div style={{ flex: bar.major, background: '#f97316', borderRadius: 3, transition: 'flex 0.4s ease' }} title={`${bar.major} major`} />}
            {bar.minor > 0 && <div style={{ flex: bar.minor, background: '#f59e0b', borderRadius: 3, transition: 'flex 0.4s ease' }} title={`${bar.minor} minor`} />}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const [vessels, setVessels] = useState([]);
  const [uploads, setUploads] = useState([]);
  const [alertSummary, setAlertSummary] = useState(null);
  const [recentAlerts, setRecentAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showPlainVesselList, setShowPlainVesselList] = useState(false);
  const [showConfiguredList, setShowConfiguredList] = useState(false);
  const [tankPanelVessel, setTankPanelVessel] = useState(null); // vessel object or null
  const [tankCache, setTankCache] = useState({}); // vessel_id -> grouped tank data
  const [tankLoading, setTankLoading] = useState(false);
  const [vesselTankCounts, setVesselTankCounts] = useState({}); // vessel_id -> tank count

  const openPlainVesselList = () => {
    setShowPlainVesselList(v => !v);
    setShowConfiguredList(false);
    setTankPanelVessel(null);
  };

  const openConfiguredList = () => {
    setShowConfiguredList(v => !v);
    setShowPlainVesselList(false);
    setTankPanelVessel(null);
  };

  const openTankPanel = async (vessel) => {
    setTankPanelVessel(vessel);
    if (!tankCache[vessel.id]) {
      setTankLoading(true);
      try {
        const r = await api.get(`/api/vessels/${vessel.id}/tanks?grouped=true`);
        setTankCache(c => ({ ...c, [vessel.id]: r.data.data || [] }));
      } finally {
        setTankLoading(false);
      }
    }
  };

  useEffect(() => {
    Promise.all([
      api.get('/api/vessels'),
      api.get('/api/uploads'),
      api.get('/api/alerts/summary'),
      api.get('/api/alerts?is_resolved=false'),
    ]).then(([v, u, as, ra]) => {
      const vesselList = v.data.data || [];
      setVessels(vesselList);
      setUploads(u.data.data || []);
      setAlertSummary(as.data.data || {});
      setRecentAlerts((ra.data.data || []).slice(0, 5));

      Promise.all(vesselList.map(vessel => api.get(`/api/vessels/${vessel.id}/tanks`)))
        .then(results => {
          const counts = {};
          vesselList.forEach((vessel, idx) => {
            counts[vessel.id] = (results[idx].data.data || []).length;
          });
          setVesselTankCounts(counts);
        })
        .catch(console.error);
    }).catch(console.error).finally(() => setLoading(false));
  }, []);

  const configuredVesselCount = vessels.filter(v => (vesselTankCounts[v.id] || 0) > 0).length;

  const now = new Date();
  const uploadsThisMonth = uploads.filter((u) => {
    const d = new Date(u.created_at);
    return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
  });

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content">
        <Header title="Dashboard" />
        <div className="page-body">
          {loading ? <LoadingSpinner /> : (
            <>
              <div className="summary-cards">
                <SummaryCard
                  label="Total Vessels"
                  value={vessels.length}
                  sub="Active vessels"
                  icon={Ship}
                  iconColor="#1F4E79"
                  onClick={openPlainVesselList}
                  active={showPlainVesselList}
                />
                <SummaryCard
                  label="Configured Vessels"
                  value={configuredVesselCount}
                  sub={`of ${vessels.length} have tanks set up`}
                  icon={Droplets}
                  iconColor="#0ea58c"
                  onClick={openConfiguredList}
                  active={showConfiguredList}
                />
                <SummaryCard label="Uploads This Month" value={uploadsThisMonth.length} icon={Upload} iconColor="#0ea5e9" />
                <SummaryCard
                  label="Open Alerts"
                  value={alertSummary?.total || 0}
                  sub={`${alertSummary?.critical || 0} critical · ${alertSummary?.major || 0} major · ${alertSummary?.minor || 0} minor`}
                  variant={alertSummary?.critical > 0 ? 'danger' : alertSummary?.major > 0 ? 'warning' : ''}
                  icon={AlertTriangle}
                  iconColor="#f97316"
                  bar={{ total: alertSummary?.total || 0, critical: alertSummary?.critical || 0, major: alertSummary?.major || 0, minor: alertSummary?.minor || 0 }}
                />
              </div>

              {showPlainVesselList ? (
                <div className="card">
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
                    <h3 style={{ margin: 0 }}>Total Vessels</h3>
                    <button className="btn btn-ghost btn-sm" onClick={() => setShowPlainVesselList(false)}>
                      ← Back to overview
                    </button>
                  </div>

                  {vessels.length === 0 ? (
                    <div className="empty-state">No vessels configured.</div>
                  ) : (
                    <div style={{ maxHeight: 320, overflowY: 'auto' }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                          <tr>
                            <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: '#fff', position: 'sticky', top: 0, background: '#1F4E79' }}>S.No</th>
                            <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: '#fff', position: 'sticky', top: 0, background: '#1F4E79' }}>Vessel Name</th>
                            <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: '#fff', position: 'sticky', top: 0, background: '#1F4E79' }}>IMO Number</th>
                            <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: '#fff', position: 'sticky', top: 0, background: '#1F4E79' }}>Call Sign</th>
                          </tr>
                        </thead>
                        <tbody>
                          {vessels.map((v, idx) => (
                            <tr key={v.id}>
                              <td style={{ padding: '0.5rem', fontSize: '0.85rem' }}>{idx + 1}</td>
                              <td style={{ padding: '0.5rem', fontSize: '0.85rem' }}>{v.name}</td>
                              <td style={{ padding: '0.5rem', fontSize: '0.85rem' }}>{v.imo_number}</td>
                              <td style={{ padding: '0.5rem', fontSize: '0.85rem' }}>{v.call_sign || '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ) : showConfiguredList ? (
                <div className="card">
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
                    <h3 style={{ margin: 0 }}>Configured Vessels</h3>
                    <button className="btn btn-ghost btn-sm" onClick={() => { setShowConfiguredList(false); setTankPanelVessel(null); }}>
                      ← Back to overview
                    </button>
                  </div>

                  {vessels.length === 0 ? (
                    <div className="empty-state">No vessels configured.</div>
                  ) : (
                    <div style={{ maxHeight: 320, overflowY: 'auto' }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                          <tr>
                            <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: '#fff', position: 'sticky', top: 0, background: '#1F4E79' }}>S.No</th>
                            <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: '#fff', position: 'sticky', top: 0, background: '#1F4E79' }}>Vessel Name</th>
                            <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: '#fff', position: 'sticky', top: 0, background: '#1F4E79' }}>IMO Number</th>
                            <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: '#fff', position: 'sticky', top: 0, background: '#1F4E79' }}>Call Sign</th>
                            <th style={{ textAlign: 'right', padding: '0.5rem', fontSize: '0.75rem', color: '#fff', position: 'sticky', top: 0, background: '#1F4E79' }}>Tanks</th>
                          </tr>
                        </thead>
                        <tbody>
                          {vessels.map((v, idx) => (
                            <tr key={v.id}>
                              <td style={{ padding: '0.5rem', fontSize: '0.85rem' }}>{idx + 1}</td>
                              <td style={{ padding: '0.5rem', fontSize: '0.85rem' }}>{v.name}</td>
                              <td style={{ padding: '0.5rem', fontSize: '0.85rem' }}>{v.imo_number}</td>
                              <td style={{ padding: '0.5rem', fontSize: '0.85rem' }}>{v.call_sign || '—'}</td>
                              <td style={{ padding: '0.5rem', textAlign: 'right' }}>
                                <button className="btn btn-ghost btn-sm" onClick={() => openTankPanel(v)}>
                                  <Droplets size={13} style={{ marginRight: '0.3rem' }} />
                                  View Tanks
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ) : (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                <div className="card">
                  <h3 style={{ marginBottom: '1rem' }}>Recent Uploads</h3>
                  {uploads.slice(0, 5).length === 0 ? (
                    <div className="empty-state">No uploads yet.</div>
                  ) : (
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead>
                        <tr>
                          <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>File</th>
                          <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Status</th>
                          <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Date</th>
                        </tr>
                      </thead>
                      <tbody>
                        {uploads.slice(0, 5).map((u) => (
                          <tr key={u.id}>
                            <td style={{ padding: '0.5rem', fontSize: '0.85rem' }}>{u.original_filename}</td>
                            <td style={{ padding: '0.5rem' }}><Badge value={u.status} /></td>
                            <td style={{ padding: '0.5rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                              {new Date(u.created_at).toLocaleDateString()}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>

                <div className="card">
                  <h3 style={{ marginBottom: '1rem' }}>Recent Alerts</h3>
                  {recentAlerts.length === 0 ? (
                    <div className="empty-state">No open alerts.</div>
                  ) : (
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead>
                        <tr>
                          <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Severity</th>
                          <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Type</th>
                          <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Date</th>
                        </tr>
                      </thead>
                      <tbody>
                        {recentAlerts.map((a) => (
                          <tr key={a.id}>
                            <td style={{ padding: '0.5rem' }}><Badge value={a.severity} /></td>
                            <td style={{ padding: '0.5rem', fontSize: '0.8rem' }}>{a.alert_type.replace(/_/g, ' ')}</td>
                            <td style={{ padding: '0.5rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                              {new Date(a.created_at).toLocaleDateString()}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
              )}
            </>
          )}
        </div>
      </div>

      {tankPanelVessel && (
        <>
          <div className="tank-panel-backdrop" onClick={() => setTankPanelVessel(null)} />
          <div className="tank-panel">
            <div className="tank-panel__header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                <Ship size={20} />
                <div>
                  <h3 style={{ margin: 0 }}>{tankPanelVessel.name}</h3>
                  <span style={{ fontSize: '0.78rem', opacity: 0.85 }}>
                    IMO {tankPanelVessel.imo_number} · Call Sign {tankPanelVessel.call_sign || '—'}
                  </span>
                </div>
              </div>
              <button className="btn-icon tank-panel__close" onClick={() => setTankPanelVessel(null)} aria-label="Close">
                <X size={18} />
              </button>
            </div>
            {!tankLoading && (tankCache[tankPanelVessel.id] || []).length > 0 && (
              <div className="tank-panel__summary">
                <span><strong>{tankCache[tankPanelVessel.id].reduce((s, g) => s + g.tanks.length, 0)}</strong> tanks</span>
                <span><strong>{tankCache[tankPanelVessel.id].reduce((s, g) => s + g.total_capacity_m3, 0).toFixed(1)}</strong> m³ total capacity</span>
              </div>
            )}
            <div className="tank-panel__body">
              {tankLoading ? <LoadingSpinner /> : (
                (tankCache[tankPanelVessel.id] || []).length === 0 ? (
                  <div className="empty-state">No tanks configured for this vessel.</div>
                ) : (
                  tankCache[tankPanelVessel.id].map(group => (
                    <div key={group.group} className="tank-panel__group">
                      <div className="tank-panel__group-header">
                        <Anchor size={13} />
                        <span>{group.group}</span>
                        <span className="tank-panel__group-total">{group.total_capacity_m3.toFixed(1)} m³</span>
                      </div>
                      {group.tanks.map(t => (
                        <div key={t.id} className="tank-panel__row">
                          <span className="tank-panel__name">{t.tank_name}</span>
                          <span className="tank-panel__capacity">{t.capacity_m3} m³</span>
                        </div>
                      ))}
                    </div>
                  ))
                )
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

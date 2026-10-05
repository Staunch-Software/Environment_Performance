import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Ship, Upload, AlertTriangle, Anchor, Droplets, X, FileText, ShieldCheck, ShieldAlert,
  ArrowRight, ChevronRight, CheckCircle2, Activity, Inbox, BellOff,
} from 'lucide-react';
import Sidebar from '../components/Layout/Sidebar';
import Header from '../components/Layout/Header';
import Badge from '../components/shared/Badge';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import api from '../api/axios';
import './Dashboard.css';

const SEVERITIES = ['critical', 'major', 'minor', 'observation'];

function KpiCard({ label, value, sub, icon: Icon, tone, onClick, active, children }) {
  const clickable = !!onClick;
  const Tag = clickable ? 'button' : 'div';
  return (
    <Tag
      type={clickable ? 'button' : undefined}
      className={`db-kpi${tone ? ` db-kpi--${tone}` : ''}${clickable ? ' db-kpi--click' : ''}${active ? ' db-kpi--active' : ''}`}
      onClick={onClick}
    >
      <span className="db-kpi__icon"><Icon size={19} /></span>
      <span className="db-kpi__body">
        <span className="db-kpi__label">{label}</span>
        <span className="db-kpi__value">{value}</span>
        {sub && <span className="db-kpi__sub">{sub}</span>}
        {children}
      </span>
      {clickable && <ChevronRight size={16} className="db-kpi__go" />}
    </Tag>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [vessels, setVessels] = useState([]);
  const [uploads, setUploads] = useState([]);
  const [alertSummary, setAlertSummary] = useState(null);
  const [openAlerts, setOpenAlerts] = useState([]);
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
      setOpenAlerts(ra.data.data || []);

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

  const recentAlerts = openAlerts.slice(0, 5);
  const configuredVesselCount = vessels.filter(v => (vesselTankCounts[v.id] || 0) > 0).length;

  const now = new Date();
  const uploadsThisMonth = uploads.filter((u) => {
    const d = new Date(u.created_at);
    return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
  });

  const derived = useMemo(() => {
    const alertsByVessel = {};
    openAlerts.forEach(a => {
      const b = alertsByVessel[a.vessel_id] || (alertsByVessel[a.vessel_id] = { total: 0, critical: 0, major: 0 });
      b.total += 1;
      if (a.severity === 'critical') b.critical += 1;
      if (a.severity === 'major') b.major += 1;
    });
    return {
      alertsByVessel,
      totalEntries: uploads.reduce((s, u) => s + (u.extracted_entries_count || 0), 0),
      inProgress: uploads.filter(u => u.status === 'pending' || u.status === 'processing').length,
      failed: uploads.filter(u => u.status === 'failed').length,
    };
  }, [openAlerts, uploads]);

  const vesselName = (id) => vessels.find(v => v.id === id)?.name || '—';

  const critical = alertSummary?.critical || 0;
  const major = alertSummary?.major || 0;
  const minor = alertSummary?.minor || 0;
  const observation = alertSummary?.observation || 0;
  const totalAlerts = alertSummary?.total || 0;
  const alertTone = critical > 0 ? 'bad' : major > 0 ? 'warn' : totalAlerts > 0 ? 'info' : 'ok';

  const vesselRows = vessels
    .map(v => {
      const a = derived.alertsByVessel[v.id] || { total: 0, critical: 0, major: 0 };
      const status = a.critical > 0 ? 'bad' : a.major > 0 ? 'warn' : a.total > 0 ? 'info' : 'ok';
      return { v, a, status, tanks: vesselTankCounts[v.id] };
    })
    .sort((x, y) => (y.a.critical - x.a.critical) || (y.a.total - x.a.total));

  const topTypes = Object.entries(alertSummary?.by_type || {}).sort((a, b) => b[1] - a[1]).slice(0, 5);
  const sevMax = Math.max(1, critical, major, minor, observation);
  const sevCounts = { critical, major, minor, observation };

  const attentionText = [
    critical > 0 && `${critical} critical alert${critical === 1 ? '' : 's'}`,
    major > 0 && `${major} major alert${major === 1 ? '' : 's'}`,
    derived.failed > 0 && `${derived.failed} failed upload${derived.failed === 1 ? '' : 's'}`,
  ].filter(Boolean).join(' · ');
  const needsAttention = critical > 0 || major > 0 || derived.failed > 0;

  const today = now.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content">
        <Header title="Dashboard" />
        <div className="page-body">
          <div className="db">
            <div className="db-header">
              <div className="db-header__text">
                <span className="db-eyebrow">Control Center · {today}</span>
                <div className="db-title-row">
                  <h1 className="db-title">Fleet Compliance Overview</h1>
                  {!loading && needsAttention && (
                    <span
                      className={`db-alert-chip db-alert-chip--${critical > 0 ? 'bad' : 'warn'}`}
                      role="status"
                      title={`Attention required: ${attentionText}`}
                    >
                      <ShieldAlert size={14} />
                      <span>{attentionText}</span>
                    </span>
                  )}
                </div>
                <p className="db-subtitle">Live status of vessels, ORB uploads and MARPOL compliance alerts.</p>
              </div>
            </div>

            {loading ? <LoadingSpinner /> : (
              <>
                {/* Attention banner (all-clear state only; issues show as the chip by the heading) */}
                {!needsAttention && (
                  <div className="db-banner db-banner--ok">
                    <span className="db-banner__icon"><ShieldCheck size={20} /></span>
                    <div className="db-banner__text">
                      <strong>{totalAlerts === 0 ? 'All clear' : 'No critical or major alerts'}</strong>
                      <span>{totalAlerts === 0 ? 'There are no open compliance alerts.' : `${totalAlerts} minor or observation alert${totalAlerts === 1 ? '' : 's'} open.`}</span>
                    </div>
                  </div>
                )}

                {/* KPI cards */}
                <div className="db-kpis">
                  <KpiCard
                    label="Total Vessels"
                    value={vessels.length}
                    sub="Active vessels"
                    icon={Ship}
                    onClick={openPlainVesselList}
                    active={showPlainVesselList}
                  />
                  <KpiCard
                    label="Configured Vessels"
                    value={configuredVesselCount}
                    sub={`of ${vessels.length} have tanks set up`}
                    icon={Droplets}
                    onClick={openConfiguredList}
                    active={showConfiguredList}
                  >
                  </KpiCard>
                  <KpiCard
                    label="ORB Entries Extracted"
                    value={derived.totalEntries}
                    sub={`across ${uploads.length} upload${uploads.length === 1 ? '' : 's'}`}
                    icon={FileText}
                  />
                  <KpiCard
                    label="Uploads This Month"
                    value={uploadsThisMonth.length}
                    sub={
                      derived.inProgress > 0 || derived.failed > 0
                        ? `${derived.inProgress} in progress · ${derived.failed} failed`
                        : 'No uploads pending'
                    }
                    icon={Upload}
                  />
                  <KpiCard
                    label="Open Alerts"
                    value={totalAlerts}
                    sub={`${critical} critical · ${major} major · ${minor} minor`}
                    tone={alertTone}
                    icon={AlertTriangle}
                  >
                  </KpiCard>
                </div>

                {showPlainVesselList ? (
                  <section className="db-card">
                    <div className="db-card__head">
                      <h3 className="db-card__title"><Ship size={16} /> Total Vessels</h3>
                      <button className="db-btn db-btn--ghost db-btn--sm" onClick={() => setShowPlainVesselList(false)}>
                        ← Back to overview
                      </button>
                    </div>
                    {vessels.length === 0 ? (
                      <div className="db-empty"><span className="db-empty__icon"><Ship size={22} /></span>No vessels configured.</div>
                    ) : (
                      <div className="db-tablewrap">
                        <table className="db-table">
                          <thead>
                            <tr><th>S.No</th><th>Vessel Name</th><th>IMO Number</th><th>Call Sign</th></tr>
                          </thead>
                          <tbody>
                            {vessels.map((v, idx) => (
                              <tr key={v.id}>
                                <td className="db-muted">{idx + 1}</td>
                                <td className="db-strong">{v.name}</td>
                                <td className="db-mono">{v.imo_number}</td>
                                <td className="db-mono">{v.call_sign || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>
                ) : showConfiguredList ? (
                  <section className="db-card">
                    <div className="db-card__head">
                      <h3 className="db-card__title"><Droplets size={16} /> Configured Vessels</h3>
                      <button className="db-btn db-btn--ghost db-btn--sm" onClick={() => { setShowConfiguredList(false); setTankPanelVessel(null); }}>
                        ← Back to overview
                      </button>
                    </div>
                    {vessels.length === 0 ? (
                      <div className="db-empty"><span className="db-empty__icon"><Ship size={22} /></span>No vessels configured.</div>
                    ) : (
                      <div className="db-tablewrap">
                        <table className="db-table">
                          <thead>
                            <tr><th>S.No</th><th>Vessel Name</th><th>IMO Number</th><th>Call Sign</th><th className="db-right">Tanks</th></tr>
                          </thead>
                          <tbody>
                            {vessels.map((v, idx) => (
                              <tr key={v.id}>
                                <td className="db-muted">{idx + 1}</td>
                                <td className="db-strong">{v.name}</td>
                                <td className="db-mono">{v.imo_number}</td>
                                <td className="db-mono">{v.call_sign || '—'}</td>
                                <td className="db-right">
                                  <button className="db-btn db-btn--ghost db-btn--sm" onClick={() => openTankPanel(v)}>
                                    <Droplets size={13} />
                                    View Tanks
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>
                ) : (
                  <>
                    <div className="db-grid db-grid--main">
                      {/* Vessel compliance overview */}
                      <section className="db-card">
                        <div className="db-card__head">
                          <h3 className="db-card__title"><Activity size={16} /> Vessel Compliance Overview</h3>
                          <span className="db-card__meta">{vessels.length} {vessels.length === 1 ? 'vessel' : 'vessels'}</span>
                        </div>
                        {vesselRows.length === 0 ? (
                          <div className="db-empty"><span className="db-empty__icon"><Ship size={22} /></span>No vessels configured.</div>
                        ) : (
                          <div className="db-tablewrap">
                            <table className="db-table db-table--stack">
                              <thead>
                                <tr><th>Vessel</th><th>IMO</th><th className="db-center">Tanks</th><th className="db-center">Open Alerts</th><th>Status</th></tr>
                              </thead>
                              <tbody>
                                {vesselRows.map(({ v, a, status, tanks }) => (
                                  <tr key={v.id}>
                                    <td data-label="Vessel">
                                      <div className="db-vessel">
                                        <span className="db-vessel__mark"><Ship size={15} /></span>
                                        <span className="db-strong">{v.name}</span>
                                      </div>
                                    </td>
                                    <td data-label="IMO" className="db-mono">{v.imo_number}</td>
                                    <td data-label="Tanks" className="db-center">
                                      {tanks === undefined ? <span className="db-muted">…</span> : tanks > 0 ? tanks : <span className="db-pill db-pill--neutral">Not set up</span>}
                                    </td>
                                    <td data-label="Open Alerts" className="db-center">
                                      <strong className={a.total > 0 ? 'db-num' : 'db-muted'}>{a.total}</strong>
                                      {a.critical > 0 && <span className="db-sub db-sub--bad">{a.critical} critical</span>}
                                    </td>
                                    <td data-label="Status">
                                      <span className={`db-pill db-pill--${status}`}>
                                        <i className="db-dot" />
                                        {status === 'bad' ? 'Critical' : status === 'warn' ? 'Attention' : status === 'info' ? 'Minor items' : 'Compliant'}
                                      </span>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </section>

                      {/* Alert breakdown */}
                      <section className="db-card">
                        <div className="db-card__head">
                          <h3 className="db-card__title"><AlertTriangle size={16} /> Alerts by Severity</h3>
                          <button className="db-link" onClick={() => navigate('/alerts')}>All alerts <ArrowRight size={13} /></button>
                        </div>
                        <div className="db-card__body">
                          {totalAlerts === 0 ? (
                            <div className="db-empty db-empty--flat"><span className="db-empty__icon db-empty__icon--ok"><CheckCircle2 size={22} /></span>No open alerts.</div>
                          ) : (
                            <>
                              <ul className="db-sev">
                                {SEVERITIES.map(s => (
                                  <li key={s} className={`db-sev__row db-sev__row--${s}`}>
                                    <span className="db-sev__label">{s}</span>
                                    <span className="db-sev__track"><span className="db-sev__fill" style={{ width: `${(sevCounts[s] / sevMax) * 100}%` }} /></span>
                                    <span className="db-sev__count">{sevCounts[s]}</span>
                                  </li>
                                ))}
                              </ul>
                              {topTypes.length > 0 && (
                                <div className="db-types">
                                  <div className="db-types__title">Most frequent findings</div>
                                  {topTypes.map(([type, count]) => (
                                    <div key={type} className="db-types__row">
                                      <span className="db-types__name">{type.replace(/_/g, ' ')}</span>
                                      <span className="db-types__count">{count}</span>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      </section>
                    </div>

                    <div className="db-grid db-grid--pair">
                      <section className="db-card">
                        <div className="db-card__head">
                          <h3 className="db-card__title"><BellOff size={16} /> Recent Alerts</h3>
                          <button className="db-link" onClick={() => navigate('/alerts')}>View all <ArrowRight size={13} /></button>
                        </div>
                        {recentAlerts.length === 0 ? (
                          <div className="db-empty"><span className="db-empty__icon db-empty__icon--ok"><CheckCircle2 size={22} /></span>No open alerts.</div>
                        ) : (
                          <ul className="db-list">
                            {recentAlerts.map((a) => (
                              <li key={a.id} className="db-list__item" onClick={() => navigate('/alerts')}>
                                <Badge value={a.severity} />
                                <div className="db-list__main">
                                  <span className="db-list__title">{a.alert_type.replace(/_/g, ' ')}</span>
                                  <span className="db-list__sub">{vesselName(a.vessel_id)}</span>
                                </div>
                                <span className="db-list__date">{new Date(a.created_at).toLocaleDateString()}</span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </section>

                      <section className="db-card">
                        <div className="db-card__head">
                          <h3 className="db-card__title"><Inbox size={16} /> Recent Uploads</h3>
                          <button className="db-link" onClick={() => navigate('/uploads')}>View all <ArrowRight size={13} /></button>
                        </div>
                        {uploads.slice(0, 5).length === 0 ? (
                          <div className="db-empty">
                            <span className="db-empty__icon"><Upload size={22} /></span>
                            No uploads yet.
                          </div>
                        ) : (
                          <ul className="db-list">
                            {uploads.slice(0, 5).map((u) => (
                              <li key={u.id} className="db-list__item" onClick={() => navigate(`/uploads/${u.id}`)}>
                                <span className="db-list__file"><FileText size={16} /></span>
                                <div className="db-list__main">
                                  <span className="db-list__title" title={u.original_filename}>{u.original_filename}</span>
                                  <span className="db-list__sub">{vesselName(u.vessel_id)}</span>
                                </div>
                                <Badge value={u.status} />
                                <span className="db-list__date">{new Date(u.created_at).toLocaleDateString()}</span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </section>
                    </div>
                  </>
                )}
              </>
            )}

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
        </div>
      </div>
    </div>
  );
}

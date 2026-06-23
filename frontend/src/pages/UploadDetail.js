import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Sidebar from '../components/Layout/Sidebar';
import Header from '../components/Layout/Header';
import Badge from '../components/shared/Badge';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import api from '../api/axios';

const TABS = ['Entries', 'Alerts', 'Daily Log'];

const COL_LABELS = [
  { key: 'date',                  label: 'Date' },
  { key: 'iopp_retention',        label: 'IOPP Tanks Retention (m³)' },
  { key: 'non_iopp_retention',    label: 'Non-IOPP Tanks Retention (m³)' },
  { key: 'total_sludge_retention',label: 'Total Sludge Retention (m³)' },
  { key: 'sludge_incineration',   label: 'Sludge Incineration (m³)' },
  { key: 'evaporation',           label: 'Total Evaporation (m³)' },
  { key: 'sludge_ashore',         label: 'Sludge Pumped Ashore (m³)' },
  { key: 'bilge_retention',       label: 'Bilge Retention (m³)' },
  { key: 'bilge_15ppm',           label: 'Bilge Pumped thru 15 PPM (m³)' },
  { key: 'bilge_ashore',          label: 'Bilge Pumped Ashore (m³)' },
  { key: 'equipment_failure',     label: '15 PPM Failures' },
  { key: 'bunker_qty',            label: 'Bunker Taken (MT)' },
  { key: 'bunker_grade',          label: 'Grade' },
];

const SUMMARY_LABELS = [
  { key: 'total_sludge_retention',      label: 'Total Sludge Accumulation (m³)' },
  { key: 'sludge_accumulation_ratio',   label: 'Sludge Accum. / Fuel Consumed (%)' },
  { key: 'sludge_incineration',         label: 'Total Sludge Incineration (m³)' },
  { key: 'evaporation',                 label: 'Total Evaporation (m³)' },
  { key: 'sludge_ashore',              label: 'Total Sludge Pumped Ashore (m³)' },
  { key: 'bilge_retention',             label: 'Total Bilge Accumulation (m³)' },
  { key: 'bilge_15ppm',                 label: 'Total Bilge via 15 PPM (m³)' },
  { key: 'bilge_ashore',               label: 'Total Bilge Pumped Ashore (m³)' },
  { key: 'equipment_failure',           label: 'No. of 15 PPM Failures' },
  { key: 'bunker_qty',                  label: 'Total Bunker Taken (MT)' },
];

export default function UploadDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [upload, setUpload] = useState(null);
  const [entries, setEntries] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [dailyLog, setDailyLog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [logLoading, setLogLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('Entries');

  const load = async () => {
    setLoading(true);
    try {
      const [u, e, a] = await Promise.all([
        api.get(`/api/uploads/${id}`),
        api.get(`/api/uploads/${id}/entries`),
        api.get(`/api/alerts?is_resolved=false`),
      ]);
      setUpload(u.data.data);
      setEntries(e.data.data || []);
      setAlerts((a.data.data || []).filter(al => al.vessel_id === u.data.data?.vessel_id));
    } finally {
      setLoading(false);
    }
  };

  const loadDailyLog = async () => {
    if (dailyLog) return; // already loaded
    setLogLoading(true);
    try {
      const res = await api.get(`/api/uploads/${id}/daily-log`);
      setDailyLog(res.data.data);
    } catch (e) {
      console.error('Daily log load failed', e);
    } finally {
      setLogLoading(false);
    }
  };

  useEffect(() => { load(); }, [id]);

  useEffect(() => {
    if (activeTab === 'Daily Log') loadDailyLog();
  }, [activeTab]);

  const resolveAlert = async (alertId) => {
    await api.patch(`/api/alerts/${alertId}/resolve`, { notes: '' });
    load();
  };

  const downloadFile = async (type) => {
    const res = await api.get(`/api/uploads/${id}/export/${type}`, { responseType: 'blob' });
    const url = window.URL.createObjectURL(res.data);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ORB_Report.${type === 'excel' ? 'xlsx' : 'pdf'}`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  if (loading) return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content"><Header title="Upload Detail" backTo="/uploads" /><LoadingSpinner /></div>
    </div>
  );

  const tabStyle = (tab) => ({
    padding: '0.6rem 1.2rem',
    cursor: 'pointer',
    borderBottom: activeTab === tab ? '3px solid var(--primary)' : '3px solid transparent',
    fontWeight: activeTab === tab ? 700 : 400,
    color: activeTab === tab ? 'var(--primary)' : 'var(--text-secondary)',
    background: 'none',
    border: 'none',
    fontSize: '0.95rem',
  });

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content">
        <Header title="Upload Detail" backTo="/uploads" />
        <div className="page-body">

          {/* ── Breadcrumb ── */}
          <nav style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '1.25rem', fontSize: '0.85rem' }}>
            <span
              onClick={() => navigate('/uploads')}
              style={{ color: 'var(--primary)', fontWeight: 500, cursor: 'pointer' }}
            >
              ORB Uploads
            </span>
            <span style={{ color: 'var(--text-muted)' }}>/</span>
            <span style={{ color: 'var(--text-secondary)', fontWeight: 600, maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {upload?.original_filename || 'Detail'}
            </span>
          </nav>

          {/* ── Upload info card ── */}
          {upload && (
            <div className="card" style={{ marginBottom: '1.5rem' }}>

              {/* Stage stepper */}
              {(() => {
                const STEPS = ['Uploaded', 'Processing', 'Extracted', 'Completed'];
                const stepIndex = upload.status === 'pending' ? 0
                  : upload.status === 'processing' ? 1
                  : upload.status === 'error' ? 1
                  : upload.extracted_entries_count > 0 ? 2 : 1;
                const activeIndex = upload.status === 'completed' ? 3 : stepIndex;
                const isError = upload.status === 'error';
                return (
                  <div style={{ display: 'flex', alignItems: 'center', marginBottom: '1.5rem', gap: 0 }}>
                    {STEPS.map((step, i) => {
                      const done = i < activeIndex;
                      const active = i === activeIndex;
                      const failed = isError && i === 1;
                      const color = failed ? '#ef4444' : done || active ? '#1F4E79' : '#cbd5e1';
                      const textColor = failed ? '#ef4444' : done || active ? '#1F4E79' : '#94a3b8';
                      return (
                        <div key={step} style={{ display: 'flex', alignItems: 'center', flex: i < STEPS.length - 1 ? 1 : 'none' }}>
                          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.3rem' }}>
                            <div style={{
                              width: 28, height: 28, borderRadius: '50%',
                              background: done ? '#1F4E79' : active ? (failed ? '#ef4444' : '#1F4E79') : '#e2e8f0',
                              display: 'flex', alignItems: 'center', justifyContent: 'center',
                              fontSize: '0.75rem', fontWeight: 700,
                              color: done || active ? '#fff' : '#94a3b8',
                              boxShadow: active ? `0 0 0 3px ${failed ? '#fecaca' : '#bfdbfe'}` : 'none',
                              transition: 'all 0.3s ease',
                              position: 'relative',
                            }}>
                              {active && !done && (upload.status === 'processing' || upload.status === 'pending') ? (
                                <span style={{
                                  width: 10, height: 10, borderRadius: '50%',
                                  background: '#fff',
                                  animation: 'pulse-dot 1.2s ease-in-out infinite',
                                }} />
                              ) : done ? '✓' : failed ? '✕' : i + 1}
                            </div>
                            <span style={{ fontSize: '0.72rem', fontWeight: active ? 700 : 500, color: textColor, whiteSpace: 'nowrap' }}>
                              {step}
                            </span>
                          </div>
                          {i < STEPS.length - 1 && (
                            <div style={{
                              flex: 1, height: 2, margin: '0 0.25rem', marginBottom: '1rem',
                              background: i < activeIndex ? '#1F4E79' : '#e2e8f0',
                              transition: 'background 0.3s ease',
                            }} />
                          )}
                        </div>
                      );
                    })}
                  </div>
                );
              })()}

              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem' }}>
                <div>
                  <h2>{upload.original_filename}</h2>
                  <p style={{ color: 'var(--text-secondary)', marginTop: '0.25rem', fontSize: '0.9rem' }}>
                    Vessel: <strong>{upload.vessel_name}</strong> ·
                    Uploaded by: {upload.uploader_name} ·
                    {new Date(upload.created_at).toLocaleString()}
                  </p>
                  <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                    <Badge value={upload.status} />
                    <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                      {upload.extracted_entries_count} entries extracted
                    </span>
                    {upload.duplicate_entries_skipped > 0 && (
                      <span className="badge badge-major">
                        {upload.duplicate_entries_skipped} duplicate {upload.duplicate_entries_skipped === 1 ? 'entry' : 'entries'} skipped
                      </span>
                    )}
                  </div>
                  {upload.duplicate_entries_skipped > 0 && (
                    <div className="alert-banner" style={{ marginTop: '0.75rem', background: '#FFF8E1', borderLeft: '4px solid #FFC107', color: '#7d5800' }}>
                      <strong>{upload.duplicate_entries_skipped} duplicate {upload.duplicate_entries_skipped === 1 ? 'entry was' : 'entries were'} detected and skipped</strong> during extraction.
                      These entries already existed for this vessel (from a previous upload covering the same date range) and were not saved again to prevent double-counting.
                    </div>
                  )}
                  {upload.error_message && (
                    <div className="alert-banner error" style={{ marginTop: '0.75rem' }}>
                      {upload.error_message}
                    </div>
                  )}
                </div>
                {upload.status === 'completed' && (
                  <div style={{ display: 'flex', gap: '0.75rem' }}>
                    <button className="btn btn-secondary" onClick={() => downloadFile('excel')}>Download Excel</button>
                    <button className="btn btn-secondary" onClick={() => downloadFile('pdf')}>Download PDF</button>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── Tabs ── */}
          <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--border)', marginBottom: '1.5rem' }}>
            {TABS.map(tab => (
              <button key={tab} style={tabStyle(tab)} onClick={() => setActiveTab(tab)}>
                {tab}
                {tab === 'Alerts' && alerts.length > 0 && (
                  <span style={{
                    marginLeft: '0.4rem', background: 'var(--danger)', color: '#fff',
                    borderRadius: '999px', padding: '0 6px', fontSize: '0.75rem',
                  }}>{alerts.length}</span>
                )}
              </button>
            ))}
          </div>

          {/* ── Tab: Entries ── */}
          {activeTab === 'Entries' && (
            <div className="card">
              <h3 style={{ marginBottom: '1rem' }}>Extracted Entries ({entries.length})</h3>
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th><th>Code</th><th>Item</th><th>Operation</th>
                      <th>Quantities</th><th>Tank / Location</th><th>Officer 1</th><th>Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map(e => (
                      <tr key={e.id} className={e.confidence_score < 0.75 ? 'row-low-confidence' : ''}>
                        <td>{e.entry_date}</td>
                        <td><strong>{e.orb_code}</strong></td>
                        <td>{e.item_number || '—'}</td>
                        <td style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis' }}>{e.operation_description}</td>
                        <td style={{ fontSize: '0.8rem' }}>
                          {e.quantities?.map(q => `${q.qty_value} ${q.qty_unit} (${q.qty_type})`).join(', ') || '—'}
                        </td>
                        <td>{e.tank_location || '—'}</td>
                        <td style={{ fontSize: '0.8rem' }}>{e.officer_1_name ? `${e.officer_1_name} (${e.officer_1_rank || ''})` : '—'}</td>
                        <td>
                          <span style={{
                            color: e.confidence_score < 0.75 ? 'var(--danger)' : 'var(--success)',
                            fontWeight: 600, fontSize: '0.85rem',
                          }}>
                            {e.confidence_score != null ? (e.confidence_score * 100).toFixed(0) + '%' : '—'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── Tab: Alerts ── */}
          {activeTab === 'Alerts' && (
            <div className="card">
              <h3 style={{ marginBottom: '1rem' }}>Alerts ({alerts.length})</h3>
              {alerts.length === 0 ? (
                <div style={{ color: 'var(--text-muted)', padding: '1rem' }}>No open alerts for this vessel.</div>
              ) : alerts.map(a => (
                <div key={a.id} style={{
                  display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
                  padding: '0.75rem', borderRadius: 'var(--radius-sm)', marginBottom: '0.5rem',
                  background: a.severity === 'critical' ? '#FFE0E0' : a.severity === 'major' ? '#FFF0E0' : '#FFFDE0',
                }}>
                  <div>
                    <Badge value={a.severity} />
                    <span style={{ marginLeft: '0.5rem', fontSize: '0.85rem' }}>{a.alert_type.replace(/_/g, ' ')}</span>
                    <p style={{ fontSize: '0.85rem', marginTop: '0.25rem', color: 'var(--text-secondary)' }}>{a.message}</p>
                  </div>
                  <button className="btn btn-ghost btn-sm" onClick={() => resolveAlert(a.id)}>Resolve</button>
                </div>
              ))}
            </div>
          )}

          {/* ── Tab: Daily Log ── */}
          {activeTab === 'Daily Log' && (
            logLoading ? <LoadingSpinner /> : !dailyLog ? (
              <div style={{ color: 'var(--text-muted)', padding: '1rem' }}>No daily log data available.</div>
            ) : (
              <>
                {/* Table 1: Daily rows */}
                <div className="card" style={{ marginBottom: '1.5rem' }}>
                  <h3 style={{ marginBottom: '1rem' }}>Daily Log</h3>
                  <div className="table-wrapper" style={{ overflowX: 'auto' }}>
                    <table style={{ minWidth: 1200 }}>
                      <thead>
                        <tr>
                          {COL_LABELS.map(c => (
                            <th key={c.key} style={{ fontSize: '0.75rem', whiteSpace: 'nowrap', padding: '0.5rem 0.75rem' }}>
                              {c.label}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {dailyLog.daily_rows.map((row, idx) => (
                          <tr key={row.date} style={{ background: idx % 2 === 0 ? '#f8fafc' : '#fff' }}>
                            {COL_LABELS.map(c => (
                              <td key={c.key} style={{ fontSize: '0.82rem', padding: '0.4rem 0.75rem', textAlign: c.key === 'date' || c.key === 'bunker_grade' ? 'left' : 'center' }}>
                                {row[c.key] || '—'}
                              </td>
                            ))}
                          </tr>
                        ))}
                        {/* Total row */}
                        <tr style={{ background: '#D6E4F0', fontWeight: 700 }}>
                          {COL_LABELS.map(c => (
                            <td key={c.key} style={{ fontSize: '0.82rem', padding: '0.5rem 0.75rem', textAlign: c.key === 'date' || c.key === 'bunker_grade' ? 'left' : 'center' }}>
                              {c.key === 'date' ? 'TOTAL' : c.key === 'bunker_grade' ? '—' : (dailyLog.monthly_summary[c.key] || '—')}
                            </td>
                          ))}
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Table 2: Monthly summary */}
                <div className="card" style={{ marginBottom: '1.5rem' }}>
                  <h3 style={{ marginBottom: '1rem' }}>Monthly / Custom Date Selection Summary</h3>
                  <div className="table-wrapper" style={{ overflowX: 'auto' }}>
                    <table style={{ minWidth: 900 }}>
                      <thead>
                        <tr>
                          {SUMMARY_LABELS.map(c => (
                            <th key={c.key} style={{ fontSize: '0.75rem', whiteSpace: 'nowrap', padding: '0.5rem 0.75rem' }}>
                              {c.label}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        <tr style={{ background: '#E2EFDA', fontWeight: 700 }}>
                          {SUMMARY_LABELS.map(c => (
                            <td key={c.key} style={{ fontSize: '0.85rem', padding: '0.6rem 0.75rem', textAlign: 'center' }}>
                              {dailyLog.monthly_summary[c.key] ?? '—'}
                            </td>
                          ))}
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Tank Reference */}
                <div className="card">
                  <h3 style={{ marginBottom: '1rem' }}>Tank Reference — From Capacity Plan & IOPP Certificate</h3>
                  <div className="table-wrapper">
                    <table>
                      <thead>
                        <tr>
                          <th>Tank Code</th>
                          <th>Tank Name</th>
                          <th>Group</th>
                          <th>Capacity (m³)</th>
                          <th>IOPP / NON-IOPP</th>
                          <th>Evaporation Allowed</th>
                        </tr>
                      </thead>
                      <tbody>
                        {dailyLog.tank_reference.map((t, idx) => (
                          <tr key={t.tank_code} style={{ background: idx % 2 === 0 ? '#f8fafc' : '#fff' }}>
                            <td style={{ fontSize: '0.85rem' }}>{t.tank_code}</td>
                            <td style={{ fontSize: '0.85rem' }}>{t.tank_name}</td>
                            <td style={{ fontSize: '0.85rem' }}>{t.tank_group || '—'}</td>
                            <td style={{ fontSize: '0.85rem', textAlign: 'center' }}>{t.capacity_m3}</td>
                            <td style={{ fontSize: '0.85rem', textAlign: 'center' }}>
                              <span style={{
                                padding: '2px 8px', borderRadius: 4,
                                background: t.is_iopp ? '#E2EFDA' : '#FFF0E0',
                                color: t.is_iopp ? '#2d6a2d' : '#7d4a00',
                                fontWeight: 600,
                              }}>
                                {t.is_iopp ? 'IOPP' : 'NON-IOPP'}
                              </span>
                            </td>
                            <td style={{ fontSize: '0.85rem', textAlign: 'center' }}>
                              {t.is_evaporation_allowed ? '✓ Yes' : '—'}
                            </td>
                          </tr>
                        ))}
                        <tr style={{ background: '#D6E4F0', fontWeight: 700 }}>
                          <td colSpan={3}>SUBTOTAL</td>
                          <td style={{ textAlign: 'center' }}>
                            {dailyLog.tank_reference.reduce((s, t) => s + t.capacity_m3, 0).toFixed(2)}
                          </td>
                          <td colSpan={2}></td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )
          )}

        </div>
      </div>
    </div>
  );
}
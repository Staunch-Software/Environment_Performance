import { useState, useEffect } from 'react';
import Sidebar from '../components/Layout/Sidebar';
import Header from '../components/Layout/Header';
import Badge from '../components/shared/Badge';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import api from '../api/axios';

function SummaryCard({ label, value, sub, variant }) {
  return (
    <div className={`summary-card${variant ? ` ${variant}` : ''}`}>
      <span className="sc-label">{label}</span>
      <span className="sc-value">{value}</span>
      {sub && <span className="sc-sub">{sub}</span>}
    </div>
  );
}

export default function Dashboard() {
  const [vessels, setVessels] = useState([]);
  const [uploads, setUploads] = useState([]);
  const [alertSummary, setAlertSummary] = useState(null);
  const [recentAlerts, setRecentAlerts] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get('/api/vessels'),
      api.get('/api/uploads'),
      api.get('/api/alerts/summary'),
      api.get('/api/alerts?is_resolved=false'),
    ]).then(([v, u, as, ra]) => {
      setVessels(v.data.data || []);
      setUploads(u.data.data || []);
      setAlertSummary(as.data.data || {});
      setRecentAlerts((ra.data.data || []).slice(0, 5));
    }).catch(console.error).finally(() => setLoading(false));
  }, []);

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
                <SummaryCard label="Total Vessels" value={vessels.length} sub="Active vessels" />
                <SummaryCard label="Uploads This Month" value={uploadsThisMonth.length} />
                <SummaryCard
                  label="Open Alerts"
                  value={alertSummary?.total || 0}
                  sub={`${alertSummary?.critical || 0} critical · ${alertSummary?.major || 0} major · ${alertSummary?.minor || 0} minor`}
                  variant={alertSummary?.critical > 0 ? 'danger' : alertSummary?.major > 0 ? 'warning' : ''}
                />
                <SummaryCard
                  label="Pending Uploads"
                  value={uploads.filter(u => u.status === 'pending' || u.status === 'processing').length}
                  sub="In queue"
                />
              </div>

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
            </>
          )}
        </div>
      </div>
    </div>
  );
}

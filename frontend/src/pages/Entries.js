import { useState, useEffect } from 'react';
import Sidebar from '../components/Layout/Sidebar';
import Header from '../components/Layout/Header';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import api from '../api/axios';

const ORB_CODES = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I'];

export default function Entries() {
  const [entries, setEntries] = useState([]);
  const [vessels, setVessels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [filters, setFilters] = useState({
    vessel_id: '', orb_code: '', date_from: '', date_to: '', confidence_below: '',
  });

  useEffect(() => { api.get('/api/vessels').then(r => setVessels(r.data.data || [])); }, []);

  const load = () => {
    setLoading(true);
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => { if (v) params.append(k, v); });
    api.get(`/api/entries?${params}`).then(r => setEntries(r.data.data || [])).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const setFilter = (k, v) => setFilters(f => ({ ...f, [k]: v }));

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content">
        <Header title="ORB Entries" />
        <div className="page-body">
          <div className="page-header"><h1>ORB Entries</h1></div>

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
                <label>ORB Code</label>
                <select className="form-control" value={filters.orb_code} onChange={e => setFilter('orb_code', e.target.value)}>
                  <option value="">All</option>
                  {ORB_CODES.map(c => <option key={c} value={c}>Code {c}</option>)}
                </select>
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Date From</label>
                <input type="date" className="form-control" value={filters.date_from} onChange={e => setFilter('date_from', e.target.value)} />
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Date To</label>
                <input type="date" className="form-control" value={filters.date_to} onChange={e => setFilter('date_to', e.target.value)} />
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Confidence Below</label>
                <input type="number" step="0.05" min="0" max="1" className="form-control" style={{ width: 100 }}
                  value={filters.confidence_below} onChange={e => setFilter('confidence_below', e.target.value)}
                  placeholder="e.g. 0.75" />
              </div>
              <button className="btn btn-primary" onClick={load} style={{ alignSelf: 'flex-end' }}>Apply</button>
            </div>
          </div>

          {loading ? <LoadingSpinner /> : (
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Date</th><th>Code</th><th>Item</th><th>Operation</th>
                    <th>Tank/Location</th><th>Officers</th><th>Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.length === 0 ? (
                    <tr><td colSpan={7} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>No entries found.</td></tr>
                  ) : entries.map(e => (
                    <>
                      <tr
                        key={e.id}
                        className={e.confidence_score < 0.75 ? 'row-low-confidence' : ''}
                        style={{ cursor: 'pointer' }}
                        onClick={() => setExpanded(expanded === e.id ? null : e.id)}
                      >
                        <td>{e.entry_date}</td>
                        <td><strong>{e.orb_code}</strong></td>
                        <td>{e.item_number || '—'}</td>
                        <td style={{ maxWidth: 280 }}>{e.operation_description}</td>
                        <td>{e.tank_location || '—'}</td>
                        <td style={{ fontSize: '0.8rem' }}>{e.officer_1_name || '—'}</td>
                        <td style={{ color: e.confidence_score < 0.75 ? 'var(--danger)' : 'var(--success)', fontWeight: 600 }}>
                          {e.confidence_score != null ? (e.confidence_score * 100).toFixed(0) + '%' : '—'}
                        </td>
                      </tr>
                      {expanded === e.id && (
                        <tr key={`${e.id}-exp`} style={{ background: '#f8fafc' }}>
                          <td colSpan={7} style={{ padding: '1rem 2rem' }}>
                            <strong>Quantities:</strong>
                            {e.quantities?.length ? (
                              <table style={{ marginTop: '0.5rem', fontSize: '0.85rem' }}>
                                <thead><tr><th style={{ paddingRight: 16 }}>Type</th><th style={{ paddingRight: 16 }}>Value</th><th style={{ paddingRight: 16 }}>Unit</th><th style={{ paddingRight: 16 }}>From</th><th>To</th></tr></thead>
                                <tbody>
                                  {e.quantities.map(q => (
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
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

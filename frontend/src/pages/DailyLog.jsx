import { useState, useEffect } from 'react';
import { Search, ChevronLeft, ChevronRight } from 'lucide-react';
import Sidebar from '../components/Layout/Sidebar';
import Header from '../components/Layout/Header';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import Dropdown from '../components/shared/Dropdown';
import api from '../api/axios';

const DAILY_COLS = [
  { key: 'date',                   label: 'Date',                          isArray: false },
  { key: 'iopp_retention',         label: 'IOPP Tanks Retention (m³)',     isArray: true  },
  { key: 'non_iopp_retention',     label: 'Non-IOPP Tanks Retention (m³)', isArray: true  },
  { key: 'total_sludge_retention', label: 'Total Sludge Retention (m³)',   isArray: false },
  { key: 'sludge_incineration',    label: 'Sludge Incineration (m³)',      isArray: true  },
  { key: 'evaporation',            label: 'Total Evaporation (m³)',        isArray: true  },
  { key: 'sludge_ashore',          label: 'Sludge Pumped Ashore (m³)',     isArray: true  },
  { key: 'bilge_retention',        label: 'Bilge Retention (m³)',          isArray: true  },
  { key: 'bilge_15ppm',            label: 'Bilge Pumped thru 15 PPM (m³)',isArray: true  },
  { key: 'bilge_ashore',           label: 'Bilge Pumped Ashore (m³)',      isArray: true  },
  { key: 'equipment_failure',      label: 'Failure with 15 PPM Equipment', isArray: false },
  { key: 'bunker_qty',             label: 'Bunker Taken (MT)',             isArray: true  },
  { key: 'bunker_grade',           label: 'Grade',                         isArray: false },
];

const SUMMARY_COLS = [
  { key: 'fuel_consumed',             label: 'Fuel Consumption / daily noon to noon' },
  { key: 'total_sludge_retention',    label: 'Total Sludge Accumulation / month' },
  { key: 'sludge_accumulation_ratio', label: 'Total sludge accumulation / fuel consumed (%)' },
  { key: 'sludge_incineration',       label: 'Total Sludge incineration' },
  { key: 'evaporation',               label: 'Total evaporation' },
  { key: 'sludge_ashore',             label: 'Total Sludge pumped Ashore' },
  { key: 'bilge_retention',           label: 'Total Bilge Accumulation' },
  { key: 'bilge_15ppm',               label: 'Total bilge water pumped out thru 15 ppm' },
  { key: 'bilge_ashore',              label: 'Total bilge water pumped Ashore' },
  { key: 'equipment_failure',         label: 'No. of failure of 15 PPM equipment' },
  { key: 'pending_defect',            label: 'Pending defect, if any' },
];

function pctBand(pct) {
  if (pct >= 85) return 'high';
  if (pct >= 60) return 'mid';
  return 'low';
}

function TankCell({ items, capacities = {} }) {
  if (!items || items.length === 0) return <span className="text-muted">—</span>;
  return (
    <div className="tank-cell">
      {items.map((item, i) => {
        const cap = capacities[item.tank_name];
        const pct = cap ? Math.round((item.value / cap) * 100) : null;
        return (
          <div key={i} className="tank-cell__row">
            <span className="tank-cell__name">{item.tank_name}</span>
            <span className="tank-cell__value">{item.value} m³</span>
            {pct !== null && <span className={`tank-cell__pct tank-cell__pct--${pctBand(pct)}`}>{pct}%</span>}
          </div>
        );
      })}
    </div>
  );
}

function renderDailyCell(col, row, capacities) {
  if (col.key === 'total_sludge_retention') {
    const items = row[col.key];
    if (!items || items.length === 0) return <span className="text-muted">—</span>;
    const total = items.reduce((s, i) => s + i.value, 0);
    return <span className="tank-cell__value">{Math.round(total * 1000) / 1000} m³</span>;
  }
  if (!col.isArray) {
    const val = row[col.key];
    if (val === null || val === undefined || val === '' || val === 0) return <span className="text-muted">—</span>;
    return val;
  }
  return <TankCell items={row[col.key]} capacities={capacities} />;
}

const MONTH_LABEL = (date) =>
  date.toLocaleString('en-US', { month: 'short', year: 'numeric' }).toUpperCase();

function ModeToggle({ mode, onChange }) {
  return (
    <div className="month-filter-toggle">
      <button
        type="button"
        className={`month-filter-toggle__btn${mode === 'month' ? ' month-filter-toggle__btn--active' : ''}`}
        onClick={() => onChange('month')}
      >
        Month
      </button>
      <button
        type="button"
        className={`month-filter-toggle__btn${mode === 'custom' ? ' month-filter-toggle__btn--active' : ''}`}
        onClick={() => onChange('custom')}
      >
        Custom Range
      </button>
    </div>
  );
}

function MonthStepper({ date, onChange, disabled }) {
  const shift = (delta) => onChange(new Date(date.getFullYear(), date.getMonth() + delta, 1));
  return (
    <div className="month-stepper" style={{ opacity: disabled ? 0.5 : 1 }}>
      <button type="button" className="month-stepper__arrow" disabled={disabled} onClick={() => shift(-1)} aria-label="Previous month">
        <ChevronLeft size={16} />
      </button>
      <span className="month-stepper__label">{MONTH_LABEL(date)}</span>
      <button type="button" className="month-stepper__arrow" disabled={disabled} onClick={() => shift(1)} aria-label="Next month">
        <ChevronRight size={16} />
      </button>
    </div>
  );
}

export default function DailyLog() {
  const [vessels, setVessels] = useState([]);

  const toDateStr = (d) => d.toISOString().slice(0, 10);
  const monthRange = (date) => [
    toDateStr(new Date(date.getFullYear(), date.getMonth(), 1)),
    toDateStr(new Date(date.getFullYear(), date.getMonth() + 1, 0)),
  ];

  // Daily log filter state (own vessel + date range)
  const [dailyVessel, setDailyVessel] = useState('');
  const [dailyFrom,   setDailyFrom]   = useState('');
  const [dailyTo,     setDailyTo]     = useState('');
  const [logData,     setLogData]     = useState(null);
  const [loading,     setLoading]     = useState(false);
  const [error,       setError]       = useState('');

  // Monthly summary filter state (own vessel + date range)
  const [summaryVessel,  setSummaryVessel]  = useState('');
  const [summaryMode,    setSummaryMode]    = useState('month'); // 'month' | 'custom'
  const [summaryMonth,   setSummaryMonth]   = useState(new Date());
  const [summaryFrom,    setSummaryFrom]    = useState('');
  const [summaryTo,      setSummaryTo]      = useState('');
  const [summaryData,    setSummaryData]    = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError,   setSummaryError]   = useState('');

  const handleSummaryMonthChange = (date) => {
    setSummaryMonth(date);
    const [from, to] = monthRange(date);
    setSummaryFrom(from);
    setSummaryTo(to);
    setSummaryData(null);
  };

  useEffect(() => {
    api.get('/api/vessels').then(r => {
      const list = r.data.data || [];
      setVessels(list);

      const today = new Date();
      const todayStr = toDateStr(today);
      const from7 = toDateStr(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 7));
      const [monthFrom, monthTo] = monthRange(today);

      // Default vessel = AM UMANG (case-insensitive), else first vessel
      const defaultVessel = list.find(v => v.name.toUpperCase().includes('AM UMANG')) || list[0];
      const vid = defaultVessel?.id || '';

      setDailyVessel(vid);
      setSummaryVessel(vid);
      setDailyFrom(from7);
      setDailyTo(todayStr);
      setSummaryMonth(today);
      setSummaryFrom(monthFrom);
      setSummaryTo(monthTo);

      // Auto-load immediately with the resolved values (state isn't flushed yet)
      if (vid) {
        loadDailyLog(vid, from7, todayStr);
        loadSummary(vid, monthFrom, monthTo);
      }
    });
  }, []);

  async function loadDailyLog(vessel = dailyVessel, from = dailyFrom, to = dailyTo) {
    if (!vessel) return;
    setLoading(true);
    setError('');
    setLogData(null);
    try {
      const params = new URLSearchParams();
      if (from) params.append('date_from', from);
      if (to)   params.append('date_to',   to);
      const res = await api.get(`/api/vessels/${vessel}/daily-log?${params}`);
      setLogData(res.data.data);
    } catch {
      setError('Failed to load daily log.');
    } finally {
      setLoading(false);
    }
  }

  async function loadSummary(vessel = summaryVessel, from = summaryFrom, to = summaryTo) {
    if (!vessel) return;
    setSummaryLoading(true);
    setSummaryError('');
    setSummaryData(null);
    try {
      const params = new URLSearchParams();
      if (from) params.append('date_from', from);
      if (to)   params.append('date_to',   to);
      const res = await api.get(`/api/vessels/${vessel}/daily-log?${params}`);
      setSummaryData(res.data.data.monthly_summary);
    } catch {
      setSummaryError('Failed to load summary.');
    } finally {
      setSummaryLoading(false);
    }
  }

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content">
        <Header title="Daily Log" />

        <div className="daily-log-shell">
          <div className="daily-log-body">
            {/* ── Table 1: Daily Log ── */}
            <div className="card">
              <div className="page-header">
                <h3>Daily Log</h3>
              </div>

              {/* Daily filters */}
              <div className="filters-bar">
                <div className="form-group">
                  <label>Vessel</label>
                  <Dropdown
                    value={dailyVessel}
                    onChange={v => { setDailyVessel(v); setLogData(null); }}
                    placeholder="— Select Vessel —"
                    options={vessels.map(v => ({ value: v.id, label: v.name }))}
                  />
                </div>
                <div className="form-group">
                  <label>Date From</label>
                  <input
                    type="date"
                    className="form-control"
                    value={dailyFrom}
                    onChange={e => setDailyFrom(e.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label>Date To</label>
                  <input
                    type="date"
                    className="form-control"
                    value={dailyTo}
                    onChange={e => setDailyTo(e.target.value)}
                  />
                </div>
                <button
                  className="btn btn-primary"
                  onClick={() => loadDailyLog()}
                  disabled={!dailyVessel || loading}
                  style={{ width: 160, justifyContent: 'center' }}
                >
                  <Search size={14} />
                  {loading ? 'Loading…' : 'Load Log'}
                </button>
              </div>

              {error && <div className="alert-banner error">{error}</div>}
              {loading && <LoadingSpinner />}

              {!loading && logData && logData.daily_rows.length === 0 && (
                <div className="daily-log-empty">No entries found for the selected date range.</div>
              )}

              {!loading && logData && logData.daily_rows.length > 0 && (
                <div className="daily-log-table-wrap">
                  <table className="daily-log-table">
                    <thead>
                      <tr>
                        {DAILY_COLS.map(c => (
                          <th key={c.key} className={c.key === 'date' ? 'col-date' : ''}>
                            {c.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {logData.daily_rows.map(row => (
                        <tr key={row.date}>
                          {DAILY_COLS.map(c => (
                            <td
                              key={c.key}
                              className={c.key === 'date' ? 'col-date' : c.key === 'bunker_grade' ? 'col-grade' : ''}
                            >
                              {renderDailyCell(c, row, logData.tank_capacities || {})}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {!loading && !logData && (
                <div className="daily-log-empty">Select a vessel and date range, then click Load Log.</div>
              )}

            </div>

            {/* ── Table 2: Monthly / Custom Date Summary ── */}
            <div className="card">
              <div className="page-header">
                <h3>Monthly or Custom Date Selection Log</h3>
              </div>

              {/* Summary filters (independent) */}
              <div className="filters-bar">
                <div className="form-group">
                  <label>Vessel</label>
                  <Dropdown
                    value={summaryVessel}
                    onChange={v => { setSummaryVessel(v); setSummaryData(null); }}
                    placeholder="— Select Vessel —"
                    options={vessels.map(v => ({ value: v.id, label: v.name }))}
                  />
                </div>
                <div className="form-group" style={{ flex: '0 0 auto' }}>
                  <label>Filter Mode</label>
                  <ModeToggle mode={summaryMode} onChange={setSummaryMode} />
                </div>
                <div className="form-group" style={{ flex: '0 0 auto' }}>
                  <label>Month</label>
                  <MonthStepper date={summaryMonth} onChange={handleSummaryMonthChange} disabled={summaryMode !== 'month'} />
                </div>
                <div className="form-group">
                  <label>Date From</label>
                  <input
                    type="date"
                    className="form-control"
                    value={summaryFrom}
                    onChange={e => setSummaryFrom(e.target.value)}
                    disabled={summaryMode !== 'custom'}
                  />
                </div>
                <div className="form-group">
                  <label>Date To</label>
                  <input
                    type="date"
                    className="form-control"
                    value={summaryTo}
                    onChange={e => setSummaryTo(e.target.value)}
                    disabled={summaryMode !== 'custom'}
                  />
                </div>
                <button
                  className="btn btn-primary"
                  onClick={() => loadSummary()}
                  disabled={!summaryVessel || summaryLoading}
                  style={{ width: 160, justifyContent: 'center' }}
                >
                  <Search size={14} />
                  {summaryLoading ? 'Loading…' : 'Load Summary'}
                </button>
              </div>

              {summaryError && <div className="alert-banner error">{summaryError}</div>}
              {summaryLoading && <LoadingSpinner />}

              {!summaryLoading && summaryData && (
                <div className="monthly-table-wrap">
                  <table className="monthly-table">
                    <thead>
                      <tr>
                        {SUMMARY_COLS.map(c => <th key={c.key}>{c.label}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        {SUMMARY_COLS.map(c => {
                          const val = summaryData[c.key];
                          return (
                            <td key={c.key}>
                              {val === null || val === undefined || val === 0 ? '—' : val}
                            </td>
                          );
                        })}
                      </tr>
                    </tbody>
                  </table>
                </div>
              )}

              {!summaryLoading && !summaryData && (

                <div className="daily-log-empty">Select a date range and click Load Summary.</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

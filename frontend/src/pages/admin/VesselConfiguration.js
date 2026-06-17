import { useState, useEffect } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import Modal from '../../components/shared/Modal';
import Badge from '../../components/shared/Badge';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import api from '../../api/axios';

export default function VesselConfiguration() {
  const [vessels, setVessels] = useState([]);
  const [tanks, setTanks] = useState({});
  const [expanded, setExpanded] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showAddVessel, setShowAddVessel] = useState(false);
  const [addTankFor, setAddTankFor] = useState(null);
  const [vesselForm, setVesselForm] = useState({ name: '', imo_number: '', call_sign: '' });
  const [tankForm, setTankForm] = useState({ tank_name: '', tank_code: '', tank_group: '', capacity_m3: '', is_iopp: true, is_evaporation_allowed: false });
  const [editTank, setEditTank] = useState(null); // { vesselId, tank }
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const loadVessels = () => {
    setLoading(true);
    api.get('/api/vessels').then(r => setVessels(r.data.data || [])).finally(() => setLoading(false));
  };

  useEffect(() => { loadVessels(); }, []);

  const loadTanks = async (vesselId) => {
    const r = await api.get(`/api/vessels/${vesselId}/tanks`);
    setTanks(t => ({ ...t, [vesselId]: r.data.data || [] }));
  };

  // Helper: group flat tank array by tank_group
  const groupTanks = (tankList) => {
    const groups = {};
    for (const t of tankList) {
      const key = t.tank_group || 'Ungrouped';
      if (!groups[key]) groups[key] = { group: key, tanks: [], total: 0 };
      groups[key].tanks.push(t);
      groups[key].total += t.capacity_m3;
    }
    return Object.values(groups);
  };

  const toggleVessel = async (vesselId) => {
    if (expanded === vesselId) { setExpanded(null); return; }
    setExpanded(vesselId);
    if (!tanks[vesselId]) await loadTanks(vesselId);
  };

  const handleAddVessel = async () => {
    setSaving(true); setError('');
    try {
      await api.post('/api/vessels', vesselForm);
      setShowAddVessel(false);
      setVesselForm({ name: '', imo_number: '', call_sign: '' });
      loadVessels();
    } catch (e) { setError(e.response?.data?.detail || 'Failed'); }
    finally { setSaving(false); }
  };

  const handleAddTank = async () => {
    setSaving(true); setError('');
    try {
      await api.post(`/api/vessels/${addTankFor}/tanks`, {
        ...tankForm, capacity_m3: parseFloat(tankForm.capacity_m3),
      });
      setAddTankFor(null);
      setTankForm({ tank_name: '', tank_code: '', tank_group: '', capacity_m3: '' });
      await loadTanks(addTankFor);
    } catch (e) { setError(e.response?.data?.detail || 'Failed'); }
    finally { setSaving(false); }
  };

  const handleEditTank = async () => {
    setSaving(true); setError('');
    try {
      await api.put(`/api/vessels/${editTank.vesselId}/tanks/${editTank.tank.id}`, {
        tank_name: tankForm.tank_name,
        tank_code: tankForm.tank_code,
        tank_group: tankForm.tank_group,
        capacity_m3: parseFloat(tankForm.capacity_m3),
        is_iopp: tankForm.is_iopp,
        is_evaporation_allowed: tankForm.is_evaporation_allowed,
      });
      await loadTanks(editTank.vesselId);
      setEditTank(null);
      setTankForm({ tank_name: '', tank_code: '', tank_group: '', capacity_m3: '', is_iopp: true, is_evaporation_allowed: false });
    } catch (e) { setError(e.response?.data?.detail || 'Failed'); }
    finally { setSaving(false); }
  };

  const deactivateTank = async (vesselId, tankId) => {
    await api.patch(`/api/vessels/${vesselId}/tanks/${tankId}/deactivate`);
    await loadTanks(vesselId);
  };

  return (
    <div>
      <div className="page-header">
        <h2>Vessel Configuration</h2>
        <button className="btn btn-primary" onClick={() => setShowAddVessel(true)}>+ Add Vessel</button>
      </div>

      {loading ? <LoadingSpinner /> : (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          {vessels.length === 0 ? (
            <div className="empty-state">No vessels configured.</div>
          ) : vessels.map(v => (
            <div key={v.id} style={{ borderBottom: '1px solid var(--border)' }}>
              <div
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '1rem 1.5rem', cursor: 'pointer' }}
                onClick={() => toggleVessel(v.id)}
              >
                <div>
                  <strong>{v.name}</strong>
                  <span style={{ marginLeft: '1rem', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                    IMO: {v.imo_number} · Call Sign: {v.call_sign || '—'}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    {tanks[v.id] ? `${tanks[v.id].filter(t => t.is_active).length} tanks` : '—'}
                  </span>
                  {expanded === v.id
                    ? <ChevronUp size={18} color="var(--text-muted)" />
                    : <ChevronDown size={18} color="var(--text-muted)" />
                  }
                </div>
              </div>

              {expanded === v.id && (
                <div style={{ padding: '0 1.5rem 1rem', background: '#f8fafc' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <h4>Tanks</h4>
                    <button className="btn btn-ghost btn-sm" onClick={() => { setAddTankFor(v.id); setError(''); }}>+ Add Tank</button>
                  </div>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ background: 'var(--border)' }}>
                        <th style={{ padding: '0.5rem', textAlign: 'left', fontSize: '0.8rem' }}>Tank Name</th>
                        <th style={{ padding: '0.5rem', textAlign: 'left', fontSize: '0.8rem' }}>Code</th>
                        <th style={{ padding: '0.5rem', textAlign: 'left', fontSize: '0.8rem' }}>Group</th>
                        <th style={{ padding: '0.5rem', textAlign: 'left', fontSize: '0.8rem' }}>Capacity (m³)</th>
                        <th style={{ padding: '0.5rem', textAlign: 'left', fontSize: '0.8rem' }}>IOPP</th>
                        <th style={{ padding: '0.5rem', textAlign: 'left', fontSize: '0.8rem' }}>Evap. Allowed</th>
                        <th style={{ padding: '0.5rem', textAlign: 'left', fontSize: '0.8rem' }}>Status</th>
                        <th style={{ padding: '0.5rem', fontSize: '0.8rem' }}>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {groupTanks(tanks[v.id] || []).map(g => (
                        <>
                          {/* Group header row */}
                          <tr key={`group-${g.group}`} style={{ background: '#1F4E79' }}>
                            <td colSpan={3} style={{ padding: '0.4rem 0.5rem', color: '#fff', fontWeight: 700, fontSize: '0.8rem', letterSpacing: '0.05em' }}>
                              {g.group}
                            </td>
                            <td style={{ padding: '0.4rem 0.5rem', color: '#fff', fontSize: '0.8rem', fontWeight: 600 }}>
                              {g.total.toFixed(1)} m³
                            </td>
                            <td colSpan={4} />
                          </tr>
                          {/* Tank rows */}
                          {g.tanks.map(t => (
                            <tr key={t.id} style={{ borderBottom: '1px solid var(--border)', background: '#fff' }}>
                              <td style={{ padding: '0.5rem', paddingLeft: '1.25rem' }}>{t.tank_name}</td>
                              <td style={{ padding: '0.5rem', fontFamily: 'monospace', fontSize: '0.85rem' }}>{t.tank_code}</td>
                              <td style={{ padding: '0.5rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>{t.tank_group || '—'}</td>
                              <td style={{ padding: '0.5rem' }}>{t.capacity_m3}</td>
                              <td style={{ padding: '0.5rem', textAlign: 'center' }}>
                                <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: '0.78rem', fontWeight: 600, background: t.is_iopp ? '#E2EFDA' : '#FFF0E0', color: t.is_iopp ? '#2d6a2d' : '#7d4a00' }}>
                                  {t.is_iopp ? 'IOPP' : 'NON-IOPP'}
                                </span>
                              </td>
                              <td style={{ padding: '0.5rem', textAlign: 'center', fontSize: '0.85rem' }}>
                                {t.is_evaporation_allowed ? '✓ Yes' : '—'}
                              </td>
                              <td style={{ padding: '0.5rem' }}><Badge value={t.is_active ? 'active' : 'inactive'} /></td>
                              <td style={{ padding: '0.5rem' }}>
                                <div style={{ display: 'flex', gap: '0.4rem' }}>
                                  <button className="btn btn-ghost btn-sm" onClick={() => {
                                    setEditTank({ vesselId: v.id, tank: t });
                                    setTankForm({
                                      tank_name: t.tank_name,
                                      tank_code: t.tank_code,
                                      tank_group: t.tank_group || '',
                                      capacity_m3: t.capacity_m3,
                                      is_iopp: t.is_iopp ?? true,
                                      is_evaporation_allowed: t.is_evaporation_allowed ?? false,
                                    });
                                    setError('');
                                  }}>Edit</button>
                                  {t.is_active && (
                                    <button className="btn btn-danger btn-sm" onClick={() => deactivateTank(v.id, t.id)}>Deactivate</button>
                                  )}
                                </div>
                              </td>
                            </tr>
                          ))}
                        </>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {showAddVessel && (
        <Modal title="Add Vessel" onClose={() => setShowAddVessel(false)} footer={
          <>
            <button className="btn btn-secondary" onClick={() => setShowAddVessel(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleAddVessel} disabled={saving}>{saving ? 'Saving…' : 'Add'}</button>
          </>
        }>
          {error && <div className="alert-banner error">{error}</div>}
          <div className="form-group"><label>Vessel Name *</label><input className="form-control" value={vesselForm.name} onChange={e => setVesselForm({ ...vesselForm, name: e.target.value })} /></div>
          <div className="form-group"><label>IMO Number *</label><input className="form-control" value={vesselForm.imo_number} onChange={e => setVesselForm({ ...vesselForm, imo_number: e.target.value })} /></div>
          <div className="form-group"><label>Call Sign</label><input className="form-control" value={vesselForm.call_sign} onChange={e => setVesselForm({ ...vesselForm, call_sign: e.target.value })} /></div>
        </Modal>
      )}

      {addTankFor && (
        <Modal title="Add Tank" onClose={() => setAddTankFor(null)} footer={
          <>
            <button className="btn btn-secondary" onClick={() => setAddTankFor(null)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleAddTank} disabled={saving}>{saving ? 'Saving…' : 'Add Tank'}</button>
          </>
        }>
          {error && <div className="alert-banner error">{error}</div>}
          <div className="form-group"><label>Tank Name *</label><input className="form-control" value={tankForm.tank_name} onChange={e => setTankForm({ ...tankForm, tank_name: e.target.value })} /></div>
          <div className="form-group"><label>Tank Code *</label><input className="form-control" value={tankForm.tank_code} onChange={e => setTankForm({ ...tankForm, tank_code: e.target.value })} placeholder="e.g. FO1P" /></div>
          <div className="form-group">
            <label>Group</label>
            <select className="form-control" value={tankForm.tank_group} onChange={e => setTankForm({ ...tankForm, tank_group: e.target.value })}>
              <option value="">— Select Group —</option>
              <option value="FUEL OIL TANK">FUEL OIL TANK</option>
              <option value="DIESEL OIL TANK">DIESEL OIL TANK</option>
              <option value="L.O. & Cyl. Oil">L.O. &amp; Cyl. Oil</option>
              <option value="SLUDGE OIL">SLUDGE OIL</option>
              <option value="BILGE WATER">BILGE WATER</option>
              <option value="GRAY WATER">GRAY WATER</option>
            </select>
          </div>
          <div className="form-group"><label>Capacity (m³) *</label><input type="number" step="0.01" className="form-control" value={tankForm.capacity_m3} onChange={e => setTankForm({ ...tankForm, capacity_m3: e.target.value })} /></div>
          <div className="checkbox-row">
            <input type="checkbox" id="is_iopp" checked={tankForm.is_iopp} onChange={e => setTankForm({ ...tankForm, is_iopp: e.target.checked })} />
            <label htmlFor="is_iopp">IOPP Tank</label>
          </div>
          <div className="checkbox-row">
            <input type="checkbox" id="is_evap" checked={tankForm.is_evaporation_allowed} onChange={e => setTankForm({ ...tankForm, is_evaporation_allowed: e.target.checked })} />
            <label htmlFor="is_evap">Evaporation Allowed (as per IOPP Certificate)</label>
          </div>
        </Modal>
      )}
    {editTank && (
        <Modal title={`Edit Tank — ${editTank.tank.tank_name}`} onClose={() => setEditTank(null)} footer={
          <>
            <button className="btn btn-secondary" onClick={() => setEditTank(null)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleEditTank} disabled={saving}>{saving ? 'Saving…' : 'Save Changes'}</button>
          </>
        }>
          {error && <div className="alert-banner error">{error}</div>}
          <div className="form-group"><label>Tank Name *</label><input className="form-control" value={tankForm.tank_name} onChange={e => setTankForm({ ...tankForm, tank_name: e.target.value })} /></div>
          <div className="form-group"><label>Tank Code *</label><input className="form-control" value={tankForm.tank_code} onChange={e => setTankForm({ ...tankForm, tank_code: e.target.value })} /></div>
          <div className="form-group">
            <label>Group</label>
            <select className="form-control" value={tankForm.tank_group} onChange={e => setTankForm({ ...tankForm, tank_group: e.target.value })}>
              <option value="">— Select Group —</option>
              <option value="FUEL OIL TANK">FUEL OIL TANK</option>
              <option value="DIESEL OIL TANK">DIESEL OIL TANK</option>
              <option value="L.O. & Cyl. Oil">L.O. &amp; Cyl. Oil</option>
              <option value="SLUDGE OIL">SLUDGE OIL</option>
              <option value="BILGE WATER">BILGE WATER</option>
              <option value="GRAY WATER">GRAY WATER</option>
            </select>
          </div>
          <div className="form-group"><label>Capacity (m³) *</label><input type="number" step="0.01" className="form-control" value={tankForm.capacity_m3} onChange={e => setTankForm({ ...tankForm, capacity_m3: e.target.value })} /></div>
          <div className="checkbox-row">
            <input type="checkbox" id="edit_is_iopp" checked={tankForm.is_iopp} onChange={e => setTankForm({ ...tankForm, is_iopp: e.target.checked })} />
            <label htmlFor="edit_is_iopp">IOPP Tank</label>
          </div>
          <div className="checkbox-row">
            <input type="checkbox" id="edit_is_evap" checked={tankForm.is_evaporation_allowed} onChange={e => setTankForm({ ...tankForm, is_evaporation_allowed: e.target.checked })} />
            <label htmlFor="edit_is_evap">Evaporation Allowed (as per IOPP Certificate)</label>
          </div>
        </Modal>
      )}
    </div>
  );
}

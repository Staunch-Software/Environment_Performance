import { Fragment, useState, useEffect, useMemo } from 'react';
import {
  ChevronDown, Ship, Plus, Pencil, Ban, Search, X, Droplets, FileCheck2, Gauge, Anchor,
} from 'lucide-react';
import Modal from '../../components/shared/Modal';
import Badge from '../../components/shared/Badge';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import Dropdown from '../../components/shared/Dropdown';
import api from '../../api/axios';
import './VesselConfiguration.css';

const TANK_GROUPS = ['FUEL OIL TANK', 'DIESEL OIL TANK', 'L.O. & Cyl. Oil', 'SLUDGE OIL', 'BILGE WATER', 'GRAY WATER'];

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
  const [tankFiles, setTankFiles] = useState({ doc1: null, doc2: null });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [docModal, setDocModal] = useState(null); // { vesselId, tank }
  const [docUrls, setDocUrls] = useState({}); // { 1: objectUrl, 2: objectUrl }
  const [docLoading, setDocLoading] = useState(false);
  const [activeDocTab, setActiveDocTab] = useState(1);
  const [search, setSearch] = useState('');

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

  const buildTankFormData = () => {
    const fd = new FormData();
    fd.append('tank_name', tankForm.tank_name);
    fd.append('tank_code', tankForm.tank_code);
    fd.append('tank_group', tankForm.tank_group || '');
    fd.append('capacity_m3', parseFloat(tankForm.capacity_m3));
    fd.append('is_iopp', tankForm.is_iopp);
    fd.append('is_evaporation_allowed', tankForm.is_evaporation_allowed);
    if (tankFiles.doc1) fd.append('iopp_doc1', tankFiles.doc1);
    if (tankFiles.doc2) fd.append('iopp_doc2', tankFiles.doc2);
    return fd;
  };

  const handleAddTank = async () => {
    if (tankForm.is_iopp && !tankFiles.doc1 && !tankFiles.doc2) {
      setError('At least one IOPP document is required for an IOPP tank');
      return;
    }
    setSaving(true); setError('');
    try {
      await api.post(`/api/vessels/${addTankFor}/tanks`, buildTankFormData(), {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setAddTankFor(null);
      setTankForm({ tank_name: '', tank_code: '', tank_group: '', capacity_m3: '', is_iopp: true, is_evaporation_allowed: false });
      setTankFiles({ doc1: null, doc2: null });
      await loadTanks(addTankFor);
    } catch (e) { setError(e.response?.data?.detail || 'Failed'); }
    finally { setSaving(false); }
  };

  const handleEditTank = async () => {
    const hasExistingDocs = editTank.tank.iopp_doc1_url || editTank.tank.iopp_doc2_url;
    if (tankForm.is_iopp && !hasExistingDocs && !tankFiles.doc1 && !tankFiles.doc2) {
      setError('At least one IOPP document is required for an IOPP tank');
      return;
    }
    setSaving(true); setError('');
    try {
      await api.put(`/api/vessels/${editTank.vesselId}/tanks/${editTank.tank.id}`, buildTankFormData(), {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      await loadTanks(editTank.vesselId);
      setEditTank(null);
      setTankForm({ tank_name: '', tank_code: '', tank_group: '', capacity_m3: '', is_iopp: true, is_evaporation_allowed: false });
      setTankFiles({ doc1: null, doc2: null });
    } catch (e) { setError(e.response?.data?.detail || 'Failed'); }
    finally { setSaving(false); }
  };

  const deactivateTank = async (vesselId, tankId) => {
    await api.patch(`/api/vessels/${vesselId}/tanks/${tankId}/deactivate`);
    await loadTanks(vesselId);
  };

  const openDocModal = async (vesselId, tank) => {
    setDocModal({ vesselId, tank });
    setActiveDocTab(1);
    setDocUrls({});
    setDocLoading(true);
    try {
      const docNums = [tank.iopp_doc1_url ? 1 : null, tank.iopp_doc2_url ? 2 : null].filter(Boolean);
      const results = await Promise.all(
        docNums.map(n => api.get(`/api/vessels/${vesselId}/tanks/${tank.id}/iopp-doc/${n}`, { responseType: 'blob' }))
      );
      const urls = {};
      docNums.forEach((n, i) => { urls[n] = URL.createObjectURL(results[i].data); });
      setDocUrls(urls);
      setActiveDocTab(docNums[0] || 1);
    } catch (e) {
      setError('Failed to load IOPP documents');
    } finally {
      setDocLoading(false);
    }
  };

  const closeDocModal = () => {
    Object.values(docUrls).forEach(url => URL.revokeObjectURL(url));
    setDocModal(null);
    setDocUrls({});
  };

  const filteredVessels = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return vessels;
    return vessels.filter(v =>
      (v.name || '').toLowerCase().includes(q) ||
      String(v.imo_number || '').toLowerCase().includes(q) ||
      (v.call_sign || '').toLowerCase().includes(q)
    );
  }, [vessels, search]);

  const openAddTank = (vesselId) => {
    setAddTankFor(vesselId);
    setTankFiles({ doc1: null, doc2: null });
    setError('');
  };

  const openEditTank = (vesselId, t) => {
    setEditTank({ vesselId, tank: t });
    setTankForm({
      tank_name: t.tank_name,
      tank_code: t.tank_code,
      tank_group: t.tank_group || '',
      capacity_m3: t.capacity_m3,
      is_iopp: t.is_iopp ?? true,
      is_evaporation_allowed: t.is_evaporation_allowed ?? false,
    });
    setTankFiles({ doc1: null, doc2: null });
    setError('');
  };

  return (
    <div className="vc">
      <div className="vc-header">
        <div className="vc-header__text">
          <span className="vc-eyebrow">Administration</span>
          <h2 className="vc-title">Vessel Configuration</h2>
          <p className="vc-subtitle">Manage each vessel's tanks, capacities and IOPP certification.</p>
        </div>
        {!loading && (
          <div className="vc-header__meta">
            <span className="vc-meta-chip"><Ship size={15} /> <strong>{vessels.length}</strong> {vessels.length === 1 ? 'Vessel' : 'Vessels'}</span>
            <button className="vc-btn vc-btn--primary" onClick={() => { setError(''); setShowAddVessel(true); }}>
              <Plus size={16} /> Add Vessel
            </button>
          </div>
        )}
      </div>

      {loading ? <LoadingSpinner /> : (
        <>
          {vessels.length > 0 && (
            <div className="vc-toolbar">
              <div className="vc-search">
                <Search size={16} className="vc-search__icon" />
                <input
                  type="text"
                  className="vc-search__input"
                  placeholder="Search by vessel name, IMO or call sign…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  aria-label="Search vessels"
                />
                {search && (
                  <button type="button" className="vc-search__clear" onClick={() => setSearch('')} aria-label="Clear search">
                    <X size={14} />
                  </button>
                )}
              </div>
              <div className="vc-count">Showing <strong>{filteredVessels.length}</strong> of {vessels.length}</div>
            </div>
          )}

          {vessels.length === 0 ? (
            <div className="vc-empty">
              <span className="vc-empty__icon"><Ship size={26} /></span>
              <div className="vc-empty__title">No vessels configured.</div>
            </div>
          ) : filteredVessels.length === 0 ? (
            <div className="vc-empty">
              <span className="vc-empty__icon"><Search size={26} /></span>
              <div className="vc-empty__title">No vessels match your search</div>
              <button type="button" className="vc-btn vc-btn--secondary" onClick={() => setSearch('')}>Clear search</button>
            </div>
          ) : (
            <div className="vc-list">
              {filteredVessels.map(v => {
                const isOpen = expanded === v.id;
                const vesselTanks = tanks[v.id];
                const activeCount = vesselTanks ? vesselTanks.filter(t => t.is_active).length : null;
                const totalCapacity = vesselTanks ? vesselTanks.filter(t => t.is_active).reduce((s, t) => s + (t.capacity_m3 || 0), 0) : 0;
                const ioppCount = vesselTanks ? vesselTanks.filter(t => t.is_active && t.is_iopp).length : 0;

                return (
                  <section key={v.id} className={`vc-vessel${isOpen ? ' vc-vessel--open' : ''}`}>
                    <div
                      className="vc-vessel__head"
                      role="button"
                      tabIndex={0}
                      aria-expanded={isOpen}
                      onClick={() => toggleVessel(v.id)}
                      onKeyDown={(e) => {
                        if (e.target !== e.currentTarget) return;
                        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleVessel(v.id); }
                      }}
                    >
                      <span className="vc-vessel__icon" aria-hidden="true"><Ship size={22} /></span>
                      <div className="vc-vessel__id">
                        <div className="vc-vessel__name">{v.name}</div>
                        <div className="vc-vessel__chips">
                          <span className="vc-chip"><span className="vc-chip__k">IMO</span> {v.imo_number}</span>
                          <span className="vc-chip"><span className="vc-chip__k">Call Sign</span> {v.call_sign || '—'}</span>
                        </div>
                      </div>
                      <div className="vc-vessel__actions">
                        <span className="vc-tankcount">
                          {vesselTanks ? `${activeCount} tanks` : '—'}
                        </span>
                        <button
                          className="vc-btn vc-btn--primary vc-btn--sm"
                          onClick={(e) => { e.stopPropagation(); openAddTank(v.id); }}
                        >
                          <Plus size={15} /> Add Tank
                        </button>
                        <ChevronDown size={20} className={`vc-chevron${isOpen ? ' vc-chevron--open' : ''}`} />
                      </div>
                    </div>

                    {isOpen && (
                      <div className="vc-vessel__body">
                        {vesselTanks && (
                          <div className="vc-summary">
                            <div className="vc-summary__item">
                              <Droplets size={16} />
                              <span className="vc-summary__val">{activeCount}</span>
                              <span className="vc-summary__lbl">Active tanks</span>
                            </div>
                            <div className="vc-summary__item">
                              <Gauge size={16} />
                              <span className="vc-summary__val">{totalCapacity.toFixed(1)} m³</span>
                              <span className="vc-summary__lbl">Total capacity</span>
                            </div>
                            <div className="vc-summary__item">
                              <FileCheck2 size={16} />
                              <span className="vc-summary__val">{ioppCount}</span>
                              <span className="vc-summary__lbl">IOPP tanks</span>
                            </div>
                          </div>
                        )}

                        <div className="vc-sectionhead">
                          <h4 className="vc-sectionhead__title"><Anchor size={16} /> Tanks</h4>
                        </div>

                        {!vesselTanks ? <LoadingSpinner /> : vesselTanks.length === 0 ? (
                          <div className="vc-notanks">No tanks configured for this vessel yet.</div>
                        ) : (
                          <div className="vc-table-wrap">
                            <table className="vc-table">
                              <thead>
                                <tr>
                                  <th>Tank Name</th>
                                  <th>Code</th>
                                  <th>Group</th>
                                  <th className="vc-num">Capacity (m³)</th>
                                  <th className="vc-center">IOPP</th>
                                  <th className="vc-center">Evap. Allowed</th>
                                  <th>Status</th>
                                  <th className="vc-th-actions">Action</th>
                                </tr>
                              </thead>
                              <tbody>
                                {groupTanks(vesselTanks).map(g => (
                                  <Fragment key={`group-${g.group}`}>
                                    {/* Group header row */}
                                    <tr className="vc-group">
                                      <td colSpan={3}>
                                        <span className="vc-group__name">{g.group}</span>
                                        <span className="vc-group__count">{g.tanks.length} {g.tanks.length === 1 ? 'tank' : 'tanks'}</span>
                                      </td>
                                      <td className="vc-num vc-group__total">{g.total.toFixed(1)} m³</td>
                                      <td colSpan={4} />
                                    </tr>
                                    {/* Tank rows */}
                                    {g.tanks.map(t => {
                                      const hasDocs = t.is_iopp && (t.iopp_doc1_url || t.iopp_doc2_url);
                                      return (
                                        <tr key={t.id} className={`vc-row${t.is_active ? '' : ' vc-row--inactive'}`}>
                                          <td data-label="Tank Name" className="vc-tankname">{t.tank_name}</td>
                                          <td data-label="Code"><span className="vc-code">{t.tank_code}</span></td>
                                          <td data-label="Group" className="vc-muted">{t.tank_group || '—'}</td>
                                          <td data-label="Capacity (m³)" className="vc-num">{t.capacity_m3}</td>
                                          <td data-label="IOPP" className="vc-center">
                                            {hasDocs ? (
                                              <button
                                                type="button"
                                                className="vc-pill vc-pill--iopp vc-pill--link"
                                                onClick={() => openDocModal(v.id, t)}
                                                title="View IOPP documents"
                                              >
                                                <FileCheck2 size={13} /> IOPP
                                              </button>
                                            ) : (
                                              <span className={`vc-pill ${t.is_iopp ? 'vc-pill--iopp' : 'vc-pill--non'}`}>
                                                {t.is_iopp ? 'IOPP' : 'NON-IOPP'}
                                              </span>
                                            )}
                                          </td>
                                          <td data-label="Evap. Allowed" className="vc-center">
                                            {t.is_evaporation_allowed ? <span className="vc-yes">✓ Yes</span> : <span className="vc-muted">—</span>}
                                          </td>
                                          <td data-label="Status"><Badge value={t.is_active ? 'active' : 'inactive'} /></td>
                                          <td className="vc-td-actions">
                                            <div className="vc-rowbtns">
                                              <button className="vc-btn vc-btn--secondary vc-btn--sm" onClick={() => openEditTank(v.id, t)}>
                                                <Pencil size={14} /> Edit
                                              </button>
                                              {t.is_active && (
                                                <button className="vc-btn vc-btn--danger vc-btn--sm" onClick={() => deactivateTank(v.id, t.id)}>
                                                  <Ban size={14} /> Deactivate
                                                </button>
                                              )}
                                            </div>
                                          </td>
                                        </tr>
                                      );
                                    })}
                                  </Fragment>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>
                    )}
                  </section>
                );
              })}
            </div>
          )}
        </>
      )}

      {showAddVessel && (
        <Modal title="Add Vessel" onClose={() => setShowAddVessel(false)} footer={
          <>
            <button className="vc-btn vc-btn--secondary" onClick={() => setShowAddVessel(false)}>Cancel</button>
            <button className="vc-btn vc-btn--primary" onClick={handleAddVessel} disabled={saving}>{saving ? 'Saving…' : 'Add'}</button>
          </>
        }>
          <div className="vc-form">
            {error && <div className="alert-banner error">{error}</div>}
            <div className="form-group"><label>Vessel Name *</label><input className="form-control" value={vesselForm.name} onChange={e => setVesselForm({ ...vesselForm, name: e.target.value })} /></div>
            <div className="form-group"><label>IMO Number *</label><input className="form-control" value={vesselForm.imo_number} onChange={e => setVesselForm({ ...vesselForm, imo_number: e.target.value })} /></div>
            <div className="form-group"><label>Call Sign</label><input className="form-control" value={vesselForm.call_sign} onChange={e => setVesselForm({ ...vesselForm, call_sign: e.target.value })} /></div>
          </div>
        </Modal>
      )}

      {addTankFor && (
        <Modal title="Add Tank" onClose={() => { setAddTankFor(null); setTankFiles({ doc1: null, doc2: null }); }} footer={
          <>
            <button className="vc-btn vc-btn--secondary" onClick={() => setAddTankFor(null)}>Cancel</button>
            <button className="vc-btn vc-btn--primary" onClick={handleAddTank} disabled={saving}>{saving ? 'Saving…' : 'Add Tank'}</button>
          </>
        }>
          <div className="vc-form">
            {error && <div className="alert-banner error">{error}</div>}
            <div className="form-group"><label>Tank Name *</label><input className="form-control" value={tankForm.tank_name} onChange={e => setTankForm({ ...tankForm, tank_name: e.target.value })} /></div>
            <div className="form-group"><label>Tank Code *</label><input className="form-control" value={tankForm.tank_code} onChange={e => setTankForm({ ...tankForm, tank_code: e.target.value })} placeholder="e.g. FO1P" /></div>
            <div className="form-group">
              <label>Group</label>
              <Dropdown
                value={tankForm.tank_group}
                onChange={v => setTankForm({ ...tankForm, tank_group: v })}
                placeholder="— Select Group —"
                options={TANK_GROUPS.map(g => ({ value: g, label: g }))}
              />
            </div>
            <div className="form-group"><label>Capacity (m³) *</label><input type="number" step="0.01" className="form-control" value={tankForm.capacity_m3} onChange={e => setTankForm({ ...tankForm, capacity_m3: e.target.value })} /></div>
            <div className="checkbox-row">
              <input type="checkbox" id="is_iopp" checked={tankForm.is_iopp} onChange={e => setTankForm({ ...tankForm, is_iopp: e.target.checked })} />
              <label htmlFor="is_iopp">IOPP Tank</label>
            </div>
            {tankForm.is_iopp && (
              <>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '-0.25rem', marginBottom: '0.5rem' }}>
                  At least one IOPP document is required — both slots are optional individually.
                </p>
                <div className="form-group">
                  <label>IOPP Document 1</label>
                  <input type="file" className="form-control" onChange={e => setTankFiles(f => ({ ...f, doc1: e.target.files[0] || null }))} />
                </div>
                <div className="form-group">
                  <label>IOPP Document 2</label>
                  <input type="file" className="form-control" onChange={e => setTankFiles(f => ({ ...f, doc2: e.target.files[0] || null }))} />
                </div>
              </>
            )}
            <div className="checkbox-row">
              <input type="checkbox" id="is_evap" checked={tankForm.is_evaporation_allowed} onChange={e => setTankForm({ ...tankForm, is_evaporation_allowed: e.target.checked })} />
              <label htmlFor="is_evap">Evaporation Allowed (as per IOPP Certificate)</label>
            </div>
          </div>
        </Modal>
      )}

      {editTank && (
        <Modal title={`Edit Tank — ${editTank.tank.tank_name}`} onClose={() => { setEditTank(null); setTankFiles({ doc1: null, doc2: null }); }} footer={
          <>
            <button className="vc-btn vc-btn--secondary" onClick={() => setEditTank(null)}>Cancel</button>
            <button className="vc-btn vc-btn--primary" onClick={handleEditTank} disabled={saving}>{saving ? 'Saving…' : 'Save Changes'}</button>
          </>
        }>
          <div className="vc-form">
            {error && <div className="alert-banner error">{error}</div>}
            <div className="form-group"><label>Tank Name *</label><input className="form-control" value={tankForm.tank_name} onChange={e => setTankForm({ ...tankForm, tank_name: e.target.value })} /></div>
            <div className="form-group"><label>Tank Code *</label><input className="form-control" value={tankForm.tank_code} onChange={e => setTankForm({ ...tankForm, tank_code: e.target.value })} /></div>
            <div className="form-group">
              <label>Group</label>
              <Dropdown
                value={tankForm.tank_group}
                onChange={v => setTankForm({ ...tankForm, tank_group: v })}
                placeholder="— Select Group —"
                options={TANK_GROUPS.map(g => ({ value: g, label: g }))}
              />
            </div>
            <div className="form-group"><label>Capacity (m³) *</label><input type="number" step="0.01" className="form-control" value={tankForm.capacity_m3} onChange={e => setTankForm({ ...tankForm, capacity_m3: e.target.value })} /></div>
            <div className="checkbox-row">
              <input type="checkbox" id="edit_is_iopp" checked={tankForm.is_iopp} onChange={e => setTankForm({ ...tankForm, is_iopp: e.target.checked })} />
              <label htmlFor="edit_is_iopp">IOPP Tank</label>
            </div>
            {tankForm.is_iopp && (
              <>
                {!(editTank.tank.iopp_doc1_url || editTank.tank.iopp_doc2_url) && (
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '-0.25rem', marginBottom: '0.5rem' }}>
                    At least one IOPP document is required — both slots are optional individually.
                  </p>
                )}
                <div className="form-group">
                  <label>IOPP Document 1 {editTank.tank.iopp_doc1_url ? '(uploaded — choose a file to replace)' : ''}</label>
                  <input type="file" className="form-control" onChange={e => setTankFiles(f => ({ ...f, doc1: e.target.files[0] || null }))} />
                </div>
                <div className="form-group">
                  <label>IOPP Document 2 {editTank.tank.iopp_doc2_url ? '(uploaded — choose a file to replace)' : ''}</label>
                  <input type="file" className="form-control" onChange={e => setTankFiles(f => ({ ...f, doc2: e.target.files[0] || null }))} />
                </div>
              </>
            )}
            <div className="checkbox-row">
              <input type="checkbox" id="edit_is_evap" checked={tankForm.is_evaporation_allowed} onChange={e => setTankForm({ ...tankForm, is_evaporation_allowed: e.target.checked })} />
              <label htmlFor="edit_is_evap">Evaporation Allowed (as per IOPP Certificate)</label>
            </div>
          </div>
        </Modal>
      )}

      {docModal && (
        <Modal
          title={`IOPP Documents — ${docModal.tank.tank_name}`}
          onClose={closeDocModal}
          wide
          footer={<button className="vc-btn vc-btn--secondary" onClick={closeDocModal}>Close</button>}
        >
          {docLoading ? <LoadingSpinner /> : (
            <>
              <div className="vc-doctabs">
                {docModal.tank.iopp_doc1_url && (
                  <button
                    className={`vc-btn vc-btn--sm ${activeDocTab === 1 ? 'vc-btn--primary' : 'vc-btn--secondary'}`}
                    onClick={() => setActiveDocTab(1)}
                  >Document 1</button>
                )}
                {docModal.tank.iopp_doc2_url && (
                  <button
                    className={`vc-btn vc-btn--sm ${activeDocTab === 2 ? 'vc-btn--primary' : 'vc-btn--secondary'}`}
                    onClick={() => setActiveDocTab(2)}
                  >Document 2</button>
                )}
              </div>
              {docUrls[activeDocTab] ? (
                <iframe
                  src={docUrls[activeDocTab]}
                  title={`IOPP Document ${activeDocTab}`}
                  className="vc-docframe"
                />
              ) : (
                <div className="empty-state">Document not available.</div>
              )}
            </>
          )}
        </Modal>
      )}
    </div>
  );
}

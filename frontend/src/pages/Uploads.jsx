import { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Upload, CheckCircle, FileText, FileUp, FileSearch, Cpu, ClipboardCheck, Ship, X,
  Files, Loader2, AlertTriangle, ChevronRight, FileSpreadsheet, FileDown, CloudUpload,
} from 'lucide-react';
import Sidebar from '../components/Layout/Sidebar';
import Header from '../components/Layout/Header';
import Modal from '../components/shared/Modal';
import Badge from '../components/shared/Badge';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import Dropdown from '../components/shared/Dropdown';
import MultiSelectDropdown from '../components/shared/MultiSelectDropdown';
import api from '../api/axios';
import { useToast } from '../context/ToastContext';
import './Uploads.css';

// phase: 'form' | 'uploading' | 'queued'
const INITIAL_FORM = { vessel_id: '', file: null };

const STEPS = [
  { Icon: FileUp, title: 'Upload', text: 'Select the vessel and its scanned ORB PDF.' },
  { Icon: Cpu, title: 'AI extraction', text: 'Handwritten entries are read page by page.' },
  { Icon: ClipboardCheck, title: 'Compliance checks', text: 'Entries are validated and alerts raised.' },
];

export default function Uploads() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [uploads, setUploads] = useState([]);
  const prevStatusRef = useRef({});
  const [vessels, setVessels] = useState([]);
  const [vesselFilter, setVesselFilter] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState(INITIAL_FORM);
  const [phase, setPhase] = useState('form'); // 'form' | 'uploading' | 'queued'
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState('');
  const fileRef = useRef();
  const [preview, setPreview] = useState(null); // { filename, url, loading }

  const load = (silent = false) => {
    const params = new URLSearchParams();
    vesselFilter.forEach(id => params.append('vessel_id', id));
    if (!silent) setLoading(true);
    return api.get(`/api/uploads?${params}`)
      .then(r => {
        const fresh = r.data.data || [];
        fresh.forEach(u => {
          const prev = prevStatusRef.current[u.id];
          if (prev && (prev === 'pending' || prev === 'processing') && u.status === 'completed') {
            toast({ message: `Extraction complete — ${u.extracted_entries_count} entries found from ${u.original_filename}`, type: 'success' });
          }
          if (prev && (prev === 'pending' || prev === 'processing') && u.status === 'failed') {
            toast({ message: `Extraction failed for ${u.original_filename}`, type: 'error' });
          }
          prevStatusRef.current[u.id] = u.status;
        });
        setUploads(fresh);
      })
      .finally(() => { if (!silent) setLoading(false); });
  };

  useEffect(() => {
    api.get('/api/vessels').then(r => setVessels(r.data.data || []));
  }, []);

  useEffect(() => { load(); }, [vesselFilter]);

  // Poll every 4 s while any upload is pending/processing
  useEffect(() => {
    const hasPending = uploads.some(u => u.status === 'pending' || u.status === 'processing');
    if (!hasPending) return;
    const id = setInterval(() => load(true), 4000);
    return () => clearInterval(id);
  }, [uploads, vesselFilter]);

  const openModal = () => {
    setForm(INITIAL_FORM);
    setPhase('form');
    setProgress(0);
    setError('');
    setShowModal(true);
  };

  const closeModal = () => {
    if (phase === 'uploading') return; // block close during transfer
    setShowModal(false);
    if (phase === 'queued') load(true);
  };

  const handleUpload = async () => {
    if (!form.vessel_id || !form.file) { setError('Select a vessel and a PDF file.'); return; }
    setError('');
    setPhase('uploading');
    setProgress(0);

    const fd = new FormData();
    fd.append('vessel_id', form.vessel_id);
    fd.append('file', form.file);

    try {
      await api.post('/api/uploads', fd, {
        onUploadProgress: (e) => {
          if (e.total) setProgress(Math.round((e.loaded / e.total) * 100));
        },
      });
      setProgress(100);
      setPhase('queued');
    } catch (e) {
      setPhase('form');
      setError(e.response?.data?.detail || 'Upload failed. Please try again.');
    }
  };

  const openPreview = async (uploadId, filename) => {
    setPreview({ filename, url: null, loading: true });
    try {
      const res = await api.get(`/api/uploads/${uploadId}/pdf`, { responseType: 'blob' });
      const url = window.URL.createObjectURL(res.data);
      setPreview({ filename, url, loading: false });
    } catch (e) {
      toast({ message: 'Could not load PDF preview.', type: 'error' });
      setPreview(null);
    }
  };

  const closePreview = () => {
    if (preview?.url) window.URL.revokeObjectURL(preview.url);
    setPreview(null);
  };

  const downloadFile = async (uploadId, type, filename) => {
    const res = await api.get(`/api/uploads/${uploadId}/export/${type}`, { responseType: 'blob' });
    const url = window.URL.createObjectURL(res.data);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  const vesselName = (r) => vessels.find(v => v.id === r.vessel_id)?.name || r.vessel_id.slice(0, 8);

  const stats = useMemo(() => ({
    total: uploads.length,
    completed: uploads.filter(u => u.status === 'completed').length,
    active: uploads.filter(u => u.status === 'pending' || u.status === 'processing').length,
    failed: uploads.filter(u => u.status === 'failed').length,
  }), [uploads]);

  const selectedVessels = vessels.filter(v => vesselFilter.includes(v.id));
  const removeVesselFilter = (id) => setVesselFilter(vesselFilter.filter(x => x !== id));

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content">
        <Header title="ORB Uploads" />
        <div className="page-body">
          <div className="up">
            <div className="up-header">
              <div className="up-header__text">
                <span className="up-eyebrow">Oil Record Book</span>
                <h1 className="up-title">ORB Uploads</h1>
                <p className="up-subtitle">Upload scanned Oil Record Books and track AI extraction for each vessel.</p>
              </div>
            </div>

            {/* Upload section */}
            <section className="up-hero">
              <div className="up-hero__main">
                <span className="up-hero__icon"><CloudUpload size={28} /></span>
                <div className="up-hero__text">
                  <h2 className="up-hero__title">Digitise a new Oil Record Book</h2>
                  <p className="up-hero__desc">PDF only · up to 50 MB. Extraction runs in the background — you can keep working while it processes.</p>
                </div>
                <button className="up-btn up-btn--light" onClick={openModal}>
                  <FileUp size={16} /> Upload ORB PDF
                </button>
              </div>
              <ol className="up-steps">
                {STEPS.map(({ Icon, title, text }, i) => (
                  <li key={title} className="up-step">
                    <span className="up-step__num">{i + 1}</span>
                    <Icon size={16} className="up-step__icon" />
                    <div>
                      <div className="up-step__title">{title}</div>
                      <div className="up-step__text">{text}</div>
                    </div>
                  </li>
                ))}
              </ol>
            </section>

            {/* Filter */}
            <div className="up-filter">
              <div className="up-filter__field">
                <label className="up-filter__label"><Ship size={14} /> Filter by Vessel</label>
                <MultiSelectDropdown
                  value={vesselFilter}
                  onChange={v => setVesselFilter(v)}
                  placeholder="Select the vessel"
                  options={vessels.map(v => ({ value: v.id, label: v.name }))}
                />
              </div>
              {selectedVessels.length > 0 && (
                <div className="up-filter__chips">
                  {selectedVessels.map(v => (
                    <span key={v.id} className="up-fchip">
                      {v.name}
                      <button type="button" onClick={() => removeVesselFilter(v.id)} aria-label={`Remove ${v.name}`}><X size={12} /></button>
                    </span>
                  ))}
                  <button type="button" className="up-btn up-btn--link" onClick={() => setVesselFilter([])}>Clear all</button>
                </div>
              )}
            </div>

            {loading ? <LoadingSpinner /> : (
              <>
                {uploads.length > 0 && (
                  <div className="up-stats">
                    <div className="up-stat">
                      <span className="up-stat__icon"><Files size={17} /></span>
                      <div><div className="up-stat__value">{stats.total}</div><div className="up-stat__label">Uploads</div></div>
                    </div>
                    <div className="up-stat up-stat--green">
                      <span className="up-stat__icon"><CheckCircle size={17} /></span>
                      <div><div className="up-stat__value">{stats.completed}</div><div className="up-stat__label">Completed</div></div>
                    </div>
                    <div className="up-stat up-stat--amber">
                      <span className="up-stat__icon"><Loader2 size={17} /></span>
                      <div><div className="up-stat__value">{stats.active}</div><div className="up-stat__label">In progress</div></div>
                    </div>
                    <div className="up-stat up-stat--red">
                      <span className="up-stat__icon"><AlertTriangle size={17} /></span>
                      <div><div className="up-stat__value">{stats.failed}</div><div className="up-stat__label">Failed</div></div>
                    </div>
                  </div>
                )}

                {uploads.length === 0 ? (
                  <div className="up-empty">
                    <span className="up-empty__icon"><FileSearch size={28} /></span>
                    <div className="up-empty__title">
                      {vesselFilter.length > 0 ? 'No uploads for the selected vessels' : 'No ORB uploads yet'}
                    </div>
                    <div className="up-empty__text">
                      {vesselFilter.length > 0
                        ? 'Try a different vessel, or clear the filter to see every upload.'
                        : 'Upload a scanned Oil Record Book PDF to extract entries and run compliance checks automatically.'}
                    </div>
                    <div className="up-empty__actions">
                      {vesselFilter.length > 0 && (
                        <button className="up-btn up-btn--secondary" onClick={() => setVesselFilter([])}>Clear filter</button>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="up-panel">
                    <div className="up-table-wrap">
                      <table className="up-table">
                        <thead>
                          <tr>
                            <th>File</th>
                            <th>Vessel</th>
                            <th>Status</th>
                            <th>Entries</th>
                            <th>Uploaded</th>
                            <th className="up-th-actions">Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {uploads.map(r => (
                            <tr key={r.id} className="up-row" onClick={() => navigate(`/uploads/${r.id}`)}>
                              <td data-label="File">
                                <div className="up-file">
                                  <span className="up-file__icon"><FileText size={17} /></span>
                                  <span className="up-file__name" title={r.original_filename}>{r.original_filename}</span>
                                </div>
                              </td>
                              <td data-label="Vessel">
                                <span className="up-vessel"><Ship size={14} /> {vesselName(r)}</span>
                              </td>
                              <td data-label="Status">
                                <span className="up-status">
                                  <Badge value={r.status} />
                                  {(r.status === 'pending' || r.status === 'processing') && (
                                    <span title="Extracting…" className="up-extracting">
                                      <span className="up-extracting__dot" />
                                      Extracting{r.total_pages ? ` (${r.pages_processed || 0}/${r.total_pages} pages)` : ''}
                                    </span>
                                  )}
                                </span>
                              </td>
                              <td data-label="Entries">
                                <span className="up-entries">
                                  <strong>{r.extracted_entries_count || 0}</strong>
                                  {r.duplicate_entries_skipped > 0 && (
                                    <span
                                      className="up-skipped"
                                      title={`${r.duplicate_entries_skipped} duplicate entries detected and skipped`}
                                    >
                                      · {r.duplicate_entries_skipped} skipped
                                    </span>
                                  )}
                                </span>
                              </td>
                              <td data-label="Uploaded" className="up-muted">{new Date(r.created_at).toLocaleDateString()}</td>
                              <td className="up-td-actions">
                                <div className="up-rowbtns">
                                  <button
                                    className="up-iconbtn"
                                    title="Preview original PDF"
                                    aria-label="Preview original PDF"
                                    onClick={(e) => { e.stopPropagation(); openPreview(r.id, r.original_filename); }}
                                  >
                                    <FileText size={16} />
                                  </button>
                                  <button className="up-btn up-btn--secondary up-btn--sm" onClick={(e) => { e.stopPropagation(); navigate(`/uploads/${r.id}`); }}>
                                    View <ChevronRight size={14} />
                                  </button>
                                  {r.status === 'completed' && (
                                    <>
                                      <button className="up-btn up-btn--ghost up-btn--sm" onClick={(e) => { e.stopPropagation(); downloadFile(r.id, 'excel', `ORB_${r.original_filename}.xlsx`); }}>
                                        <FileSpreadsheet size={14} /> Excel
                                      </button>
                                      <button className="up-btn up-btn--ghost up-btn--sm" onClick={(e) => { e.stopPropagation(); downloadFile(r.id, 'pdf', `ORB_${r.original_filename}.pdf`); }}>
                                        <FileDown size={14} /> PDF
                                      </button>
                                    </>
                                  )}
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}

            {showModal && (
              <Modal
                title={phase === 'queued' ? 'Upload Queued' : 'Upload ORB PDF'}
                onClose={closeModal}
                footer={
                  phase === 'form' ? (
                    <>
                      <button className="up-btn up-btn--secondary" onClick={closeModal}>Cancel</button>
                      <button className="up-btn up-btn--primary" onClick={handleUpload}>
                        <Upload size={15} />
                        Upload
                      </button>
                    </>
                  ) : phase === 'queued' ? (
                    <button className="up-btn up-btn--primary" onClick={closeModal}>Done</button>
                  ) : null
                }
              >
                {phase === 'form' && (
                  <div className="up-form">
                    {error && <div className="alert-banner error">{error}</div>}
                    <div className="form-group">
                      <label>Vessel *</label>
                      <Dropdown
                        value={form.vessel_id}
                        onChange={v => setForm({ ...form, vessel_id: v })}
                        placeholder="Select vessel…"
                        options={vessels.map(v => ({ value: v.id, label: `${v.name} (${v.imo_number})` }))}
                      />
                    </div>
                    <div className="form-group">
                      <label>PDF File *</label>
                      <label className={`up-drop${form.file ? ' up-drop--has' : ''}`}>
                        <input
                          type="file"
                          accept=".pdf"
                          className="up-drop__input"
                          ref={fileRef}
                          onChange={e => setForm({ ...form, file: e.target.files[0] })}
                        />
                        <span className="up-drop__icon">{form.file ? <FileText size={22} /> : <CloudUpload size={22} />}</span>
                        <span className="up-drop__main">{form.file ? form.file.name : 'Click to choose a PDF file'}</span>
                        <span className="up-drop__sub">
                          {form.file ? `${(form.file.size / (1024 * 1024)).toFixed(2)} MB · click to replace` : 'PDF only · max 50 MB'}
                        </span>
                      </label>
                    </div>
                    <p className="up-note">
                      Max file size: 50 MB. PDF only.
                    </p>
                  </div>
                )}

                {phase === 'uploading' && (
                  <div className="upload-progress-wrap">
                    <p className="upload-progress-filename">{form.file?.name}</p>
                    <div className="upload-progress-bar-track">
                      <div className="upload-progress-bar-fill" style={{ width: `${progress}%` }} />
                    </div>
                    <p className="upload-progress-pct">{progress < 100 ? `Transferring… ${progress}%` : 'Processing on server…'}</p>
                    <p className="upload-progress-note">Please wait, do not close this window.</p>
                  </div>
                )}

                {phase === 'queued' && (
                  <div className="upload-queued-wrap">
                    <CheckCircle size={48} color="var(--success)" strokeWidth={1.5} />
                    <h3 className="upload-queued-title">File received successfully</h3>
                    <p className="upload-queued-desc">
                      AI extraction is running in the background. The upload list will update automatically — you can close this and continue working.
                    </p>
                  </div>
                )}
              </Modal>
            )}

            {preview && (
              <Modal title={preview.filename} onClose={closePreview} xwide>
                {preview.loading ? (
                  <LoadingSpinner />
                ) : (
                  <iframe
                    src={preview.url}
                    title={preview.filename}
                    style={{ width: '100%', height: '100%', minHeight: '75vh', border: 'none', display: 'block' }}
                  />
                )}
              </Modal>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

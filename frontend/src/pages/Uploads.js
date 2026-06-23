import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Upload, CheckCircle } from 'lucide-react';
import Sidebar from '../components/Layout/Sidebar';
import Header from '../components/Layout/Header';
import Table from '../components/shared/Table';
import Modal from '../components/shared/Modal';
import Badge from '../components/shared/Badge';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import api from '../api/axios';
import { useToast } from '../context/ToastContext';

// phase: 'form' | 'uploading' | 'queued'
const INITIAL_FORM = { vessel_id: '', file: null };

export default function Uploads() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [uploads, setUploads] = useState([]);
  const prevStatusRef = useRef({});
  const [vessels, setVessels] = useState([]);
  const [vesselFilter, setVesselFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState(INITIAL_FORM);
  const [phase, setPhase] = useState('form'); // 'form' | 'uploading' | 'queued'
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState('');
  const fileRef = useRef();

  const load = (silent = false) => {
    const params = vesselFilter ? `?vessel_id=${vesselFilter}` : '';
    if (!silent) setLoading(true);
    return api.get(`/api/uploads${params}`)
      .then(r => {
        const fresh = r.data.data || [];
        fresh.forEach(u => {
          const prev = prevStatusRef.current[u.id];
          if (prev && (prev === 'pending' || prev === 'processing') && u.status === 'completed') {
            toast({ message: `Extraction complete — ${u.extracted_entries_count} entries found from ${u.original_filename}`, type: 'success' });
          }
          if (prev && (prev === 'pending' || prev === 'processing') && u.status === 'error') {
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

  const downloadFile = async (uploadId, type, filename) => {
    const res = await api.get(`/api/uploads/${uploadId}/export/${type}`, { responseType: 'blob' });
    const url = window.URL.createObjectURL(res.data);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  const columns = [
    { key: 'original_filename', label: 'File' },
    {
      key: 'vessel_id', label: 'Vessel',
      render: (r) => vessels.find(v => v.id === r.vessel_id)?.name || r.vessel_id.slice(0, 8),
    },
    {
      key: 'status', label: 'Status',
      render: (r) => (
        <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Badge value={r.status} />
          {(r.status === 'pending' || r.status === 'processing') && (
            <span title="Extracting…" style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.75rem', color: '#f59e0b' }}>
              <span style={{
                width: 8, height: 8, borderRadius: '50%',
                background: '#f59e0b',
                display: 'inline-block',
                animation: 'pulse-dot 1.2s ease-in-out infinite',
              }} />
              Extracting
            </span>
          )}
        </span>
      ),
    },
    {
      key: 'extracted_entries_count', label: 'Entries',
      render: (r) => (
        <span>
          {r.extracted_entries_count || 0}
          {r.duplicate_entries_skipped > 0 && (
            <span
              className="badge badge-minor"
              style={{ marginLeft: '0.4rem' }}
              title={`${r.duplicate_entries_skipped} duplicate entries detected and skipped`}
            >
              {r.duplicate_entries_skipped} skipped
            </span>
          )}
        </span>
      ),
    },
    { key: 'created_at', label: 'Uploaded', render: (r) => new Date(r.created_at).toLocaleDateString() },
    {
      key: 'actions', label: 'Actions',
      render: (r) => (
        <div className="row-actions">
          <button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); navigate(`/uploads/${r.id}`); }}>
            View
          </button>
          {r.status === 'completed' && (
            <>
              <button className="btn btn-secondary btn-sm" onClick={(e) => { e.stopPropagation(); downloadFile(r.id, 'excel', `ORB_${r.original_filename}.xlsx`); }}>
                Excel
              </button>
              <button className="btn btn-secondary btn-sm" onClick={(e) => { e.stopPropagation(); downloadFile(r.id, 'pdf', `ORB_${r.original_filename}.pdf`); }}>
                PDF
              </button>
            </>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content">
        <Header title="ORB Uploads" />
        <div className="page-body">
          <div className="page-header">
            <h1>ORB Uploads</h1>
            <button className="btn btn-primary" onClick={openModal}>
              <Upload size={16} style={{ marginRight: '0.4rem' }} />
              Upload ORB PDF
            </button>
          </div>

          <div className="filters-bar">
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label>Filter by Vessel</label>
              <select className="form-control" value={vesselFilter} onChange={e => setVesselFilter(e.target.value)}>
                <option value="">All Vessels</option>
                {vessels.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
              </select>
            </div>
          </div>

          {loading ? <LoadingSpinner /> : (
            <Table columns={columns} data={uploads} onRowClick={(r) => navigate(`/uploads/${r.id}`)} />
          )}
        </div>
      </div>

      {showModal && (
        <Modal
          title={phase === 'queued' ? 'Upload Queued' : 'Upload ORB PDF'}
          onClose={closeModal}
          footer={
            phase === 'form' ? (
              <>
                <button className="btn btn-secondary" onClick={closeModal}>Cancel</button>
                <button className="btn btn-primary" onClick={handleUpload}>
                  <Upload size={15} style={{ marginRight: '0.35rem' }} />
                  Upload
                </button>
              </>
            ) : phase === 'queued' ? (
              <button className="btn btn-primary" onClick={closeModal}>Done</button>
            ) : null
          }
        >
          {phase === 'form' && (
            <>
              {error && <div className="alert-banner error">{error}</div>}
              <div className="form-group">
                <label>Vessel *</label>
                <select
                  className="form-control"
                  value={form.vessel_id}
                  onChange={e => setForm({ ...form, vessel_id: e.target.value })}
                >
                  <option value="">Select vessel…</option>
                  {vessels.map(v => <option key={v.id} value={v.id}>{v.name} ({v.imo_number})</option>)}
                </select>
              </div>
              <div className="form-group">
                <label>PDF File *</label>
                <input
                  type="file"
                  accept=".pdf"
                  className="form-control"
                  ref={fileRef}
                  onChange={e => setForm({ ...form, file: e.target.files[0] })}
                />
              </div>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Max file size: 50 MB. PDF only.
              </p>
            </>
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
    </div>
  );
}

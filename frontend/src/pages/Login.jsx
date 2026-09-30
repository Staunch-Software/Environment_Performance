import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Anchor,
  ClipboardCheck,
  Droplet,
  Eye,
  EyeOff,
  Lock,
  Mail,
  Ship,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import './Login.css';

const FEATURES = [
  {
    icon: ClipboardCheck,
    title: 'MARPOL-ready records',
    text: 'Oil Record Book entries kept audit-ready.',
  },
  {
    icon: Droplet,
    title: 'Tank & oil tracking',
    text: 'Daily tank levels and oil movements in one log.',
  },
  {
    icon: Ship,
    title: 'Fleet-wide visibility',
    text: 'Vessels, alerts and reports side by side.',
  },
];

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      navigate('/dashboard');
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid email or password');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="lg-page">
      {/* ── Brand panel ─────────────────────────────────────────── */}
      <aside className="lg-brand">
        {/* Plimsoll (load line) mark — decorative watermark */}
        <svg
          className="lg-plimsoll"
          viewBox="0 0 240 160"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          aria-hidden="true"
        >
          <circle cx="90" cy="80" r="54" />
          <line x1="22" y1="80" x2="158" y2="80" />
          <line x1="168" y1="40" x2="224" y2="40" />
          <line x1="168" y1="60" x2="224" y2="60" />
          <line x1="168" y1="80" x2="224" y2="80" />
          <line x1="168" y1="100" x2="224" y2="100" />
          <line x1="168" y1="120" x2="224" y2="120" />
          <line x1="168" y1="34" x2="168" y2="126" />
        </svg>

        <div className="lg-brand-inner">
          <div className="lg-brand-top">
            <span className="lg-logo">
              <Anchor size={22} />
            </span>
            <span className="lg-brand-name">ORB Platform</span>
          </div>

          <div className="lg-brand-copy">
            <h1>
              Oil Record Book,
              <br />
              kept shipshape.
            </h1>
            <p>MARPOL Oil Record Book Digitization</p>
          </div>

          <ul className="lg-features">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title}>
                <span className="lg-feature-icon">
                  <Icon size={18} />
                </span>
                <span className="lg-feature-text">
                  <strong>{title}</strong>
                  <span>{text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>

        <svg
          className="lg-waves"
          viewBox="0 0 800 160"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <path d="M0,70 C160,130 320,10 480,60 C600,98 700,90 800,50 L800,160 L0,160 Z" fill="rgba(255,255,255,0.07)" />
          <path d="M0,105 C140,70 300,150 470,105 C610,68 700,120 800,95 L800,160 L0,160 Z" fill="rgba(20,33,43,0.22)" />
          <path d="M0,135 C180,112 320,160 500,134 C640,114 720,145 800,130 L800,160 L0,160 Z" fill="rgba(20,33,43,0.38)" />
        </svg>
      </aside>

      {/* ── Form panel ──────────────────────────────────────────── */}
      <main className="lg-form-panel">
        <div className="lg-card">
          <header className="lg-card-header">
            <h2>Welcome back</h2>
            <p>Sign in to continue to your dashboard</p>
          </header>

          {error && (
            <div className="lg-error" role="alert">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="lg-field">
              <label htmlFor="email">Email</label>
              <div className="lg-input-wrap">
                <Mail size={18} className="lg-input-icon" />
                <input
                  id="email"
                  type="email"
                  className="lg-input"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="admin@orbplatform.com"
                  autoComplete="email"
                  required
                />
              </div>
            </div>

            <div className="lg-field">
              <label htmlFor="password">Password</label>
              <div className="lg-input-wrap">
                <Lock size={18} className="lg-input-icon" />
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  className="lg-input lg-input--password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  className="lg-eye-btn"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <button type="submit" className="lg-submit" disabled={loading}>
              {loading && <span className="lg-spinner" />}
              {loading ? 'Signing in…' : 'Sign In'}
            </button>
          </form>

          <p className="lg-footnote">Protected access — authorized personnel only</p>
        </div>
      </main>
    </div>
  );
}
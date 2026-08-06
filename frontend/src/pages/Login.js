import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Anchor, Droplet, Eye, EyeOff, Lock, Mail, ShieldCheck, Waves } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

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
    <div className="login-page">
      <div className="login-brand-panel">
        <div className="login-brand-content">
          <div className="login-brand-logo">
            <Anchor size={28} />
          </div>
          <h1>ORB Platform</h1>
          <p>MARPOL Oil Record Book Digitization</p>

          <ul className="login-brand-features">
            <li><ShieldCheck size={18} /> Regulatory-compliant record keeping</li>
            <li><Droplet size={18} /> Automated tank &amp; oil tracking</li>
            <li><Waves size={18} /> Fleet-wide environmental reporting</li>
          </ul>
        </div>

        <svg className="login-brand-waves" viewBox="0 0 500 150" preserveAspectRatio="none">
          <path d="M0,80 C150,150 350,0 500,80 L500,150 L0,150 Z" fill="rgba(255,255,255,0.08)" />
          <path d="M0,110 C150,60 350,160 500,100 L500,150 L0,150 Z" fill="rgba(255,255,255,0.14)" />
        </svg>
      </div>

      <div className="login-form-panel">
        <div className="login-card">
          <div className="login-card-header">
            <h2>Welcome back</h2>
            <p>Sign in to continue to your dashboard</p>
          </div>

          {error && <div className="alert-banner error">{error}</div>}

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="email">Email</label>
              <div className="input-with-icon">
                <Mail size={17} className="input-icon" />
                <input
                  id="email"
                  type="email"
                  className="form-control"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="admin@orbplatform.com"
                  autoComplete="email"
                  required
                />
              </div>
            </div>
            <div className="form-group">
              <label htmlFor="password">Password</label>
              <div className="input-with-icon">
                <Lock size={17} className="input-icon" />
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  className="form-control"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  className="input-icon-btn"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </div>
            </div>
            <button
              type="submit"
              className="btn btn-primary login-submit-btn"
              disabled={loading}
            >
              {loading ? <span className="spinner-inline" /> : null}
              {loading ? 'Signing in…' : 'Sign In'}
            </button>
          </form>

          <p className="login-footnote">Protected access — authorized personnel only</p>
        </div>
      </div>
    </div>
  );
}
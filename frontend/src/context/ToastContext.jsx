import { createContext, useContext, useState, useCallback } from 'react';

const ToastContext = createContext(null);

const ICONS = { success: '✓', error: '✕', info: 'ℹ', warning: '⚠' };
const COLORS = {
  success: { bg: '#f0fdf4', border: '#22c55e', icon: '#22c55e', text: '#14532d' },
  error:   { bg: '#fef2f2', border: '#ef4444', icon: '#ef4444', text: '#7f1d1d' },
  warning: { bg: '#fffbeb', border: '#f59e0b', icon: '#f59e0b', text: '#78350f' },
  info:    { bg: '#eff6ff', border: '#3b82f6', icon: '#3b82f6', text: '#1e3a8a' },
};

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const toast = useCallback(({ message, type = 'success', duration = 4500 }) => {
    const id = Date.now() + Math.random();
    setToasts(t => [...t, { id, message, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), duration);
  }, []);

  const dismiss = (id) => setToasts(t => t.filter(x => x.id !== id));

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div style={{
        position: 'fixed', bottom: '1.5rem', right: '1.5rem',
        zIndex: 9999, display: 'flex', flexDirection: 'column', gap: '0.5rem',
        pointerEvents: 'none',
      }}>
        {toasts.map(t => {
          const c = COLORS[t.type] || COLORS.info;
          return (
            <div key={t.id} style={{
              display: 'flex', alignItems: 'flex-start', gap: '0.6rem',
              background: c.bg, border: `1px solid ${c.border}`,
              borderLeft: `4px solid ${c.border}`,
              borderRadius: 8, padding: '0.75rem 1rem',
              minWidth: 260, maxWidth: 380,
              boxShadow: '0 4px 12px rgba(0,0,0,0.12)',
              animation: 'slideInRight 0.25s ease',
              pointerEvents: 'all',
            }}>
              <span style={{ color: c.icon, fontWeight: 700, fontSize: '1rem', lineHeight: 1.4 }}>
                {ICONS[t.type]}
              </span>
              <span style={{ flex: 1, fontSize: '0.875rem', color: c.text, lineHeight: 1.5 }}>
                {t.message}
              </span>
              <button
                onClick={() => dismiss(t.id)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: c.text, opacity: 0.5, fontSize: '1rem', lineHeight: 1, padding: 0 }}
              >×</button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

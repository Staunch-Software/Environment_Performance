import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Check } from 'lucide-react';

// Custom select replacement so every filter dropdown in the app gets a
// consistently styled, scrollable popup (native <select> popups are
// rendered by the browser/OS and can't be restyled with CSS).
export default function Dropdown({ value, onChange, options, placeholder = 'All', style }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    const onDocClick = (e) => { if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, []);

  const selected = options.find(o => String(o.value) === String(value));

  return (
    <div className="dropdown" ref={rootRef} style={style}>
      <button
        type="button"
        className="form-control dropdown__trigger"
        onClick={() => setOpen(o => !o)}
      >
        <span className={selected ? '' : 'dropdown__placeholder'}>{selected ? selected.label : placeholder}</span>
        <ChevronDown size={16} className={`dropdown__chevron${open ? ' dropdown__chevron--open' : ''}`} />
      </button>
      {open && (
        <ul className="dropdown__menu" role="listbox">
          {options.map(o => {
            const isSelected = String(o.value) === String(value);
            return (
              <li
                key={o.value}
                role="option"
                aria-selected={isSelected}
                className={`dropdown__option${isSelected ? ' dropdown__option--selected' : ''}`}
                onClick={() => { onChange(o.value); setOpen(false); }}
              >
                <span>{o.label}</span>
                {isSelected && <Check size={15} className="dropdown__check" />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

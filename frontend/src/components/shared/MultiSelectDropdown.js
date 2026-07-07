import { useState, useRef, useEffect } from 'react';
import { ChevronDown } from 'lucide-react';

// Multi-select variant of Dropdown — checkboxes + "Select All", for filters
// where picking several values at once (e.g. multiple vessels) makes sense.
// `value` is an array of selected option values; [] means nothing selected ("All").
export default function MultiSelectDropdown({ value = [], onChange, options, placeholder = 'Select…', style }) {
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

  const allSelected = options.length > 0 && value.length === options.length;

  const toggleAll = () => onChange(allSelected ? [] : options.map(o => o.value));

  const toggleOne = (optValue) => {
    if (value.includes(optValue)) onChange(value.filter(v => v !== optValue));
    else onChange([...value, optValue]);
  };

  const label = value.length === 0
    ? placeholder
    : value.length === options.length
      ? 'All vessels selected'
      : options.filter(o => value.includes(o.value)).map(o => o.label).join(', ');

  return (
    <div className="dropdown" ref={rootRef} style={style}>
      <button
        type="button"
        className="form-control dropdown__trigger"
        onClick={() => setOpen(o => !o)}
      >
        <span className={value.length === 0 ? 'dropdown__placeholder' : 'dropdown__trigger-text'}>{label}</span>
        <ChevronDown size={16} className={`dropdown__chevron${open ? ' dropdown__chevron--open' : ''}`} />
      </button>
      {open && (
        <div className="dropdown__menu dropdown__menu--multi">
          <label className="dropdown__option dropdown__option--all">
            <input type="checkbox" checked={allSelected} onChange={toggleAll} />
            Select All
          </label>
          <div className="dropdown__divider" />
          {options.map(o => (
            <label key={o.value} className="dropdown__option">
              <input type="checkbox" checked={value.includes(o.value)} onChange={() => toggleOne(o.value)} />
              {o.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

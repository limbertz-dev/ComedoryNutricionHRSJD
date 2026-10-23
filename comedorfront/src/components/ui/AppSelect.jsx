import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import './AppSelect.css';

export default function AppSelect({
  id,
  name,
  value,
  defaultValue = '',
  onChange,
  disabled = false,
  placeholder = 'Seleccionar',
  options = [],
  className = '',
  ariaLabel = undefined,
}) {
  const listboxId = useId();
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [internalValue, setInternalValue] = useState(defaultValue);
  const [abrirArriba, setAbrirArriba] = useState(false);

  const isControlled = value !== undefined;
  const currentValue = isControlled ? value : internalValue;
  const selectedOption = options.find((opcion) => String(opcion.value) === String(currentValue));
  const displayLabel = selectedOption?.label ?? placeholder;

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const espacioAbajo = window.innerHeight - rect.bottom;
    setAbrirArriba(espacioAbajo < 210 && rect.top > 210);
  }, [open]);

  useEffect(() => {
    if (!open) return;

    const closeMenu = (event) => {
      if (!rootRef.current?.contains(event.target)) {
        setOpen(false);
      }
    };
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setOpen(false);
    };

    document.addEventListener('pointerdown', closeMenu);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeMenu);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  const handleSelect = (nextValue) => {
    if (!isControlled) setInternalValue(nextValue);
    onChange?.(nextValue);
    setOpen(false);
  };

  return (
    <div className={`app-select ${open ? 'open' : ''} ${className}`} ref={rootRef}>
      <button
        ref={triggerRef}
        id={id}
        name={name}
        type="button"
        className="app-select-trigger"
        disabled={disabled}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        onClick={() => {
          if (disabled) return;
          setOpen((actual) => !actual);
        }}
      >
        <span className="app-select-value">{displayLabel}</span>
        <span className="app-select-chevron" aria-hidden="true">⌄</span>
      </button>

      {open && (
        <ul
          className={`app-select-menu ${abrirArriba ? 'app-select-menu--arriba' : ''}`}
          id={listboxId}
          role="listbox"
        >
          {options.map((opcion) => {
            const isSelected = String(opcion.value) === String(currentValue);
            return (
              <li key={opcion.value} role="none">
                <button
                  type="button"
                  role="option"
                  data-value={opcion.value}
                  className={isSelected ? 'selected' : undefined}
                  aria-selected={isSelected}
                  disabled={opcion.disabled}
                  onClick={() => handleSelect(opcion.value)}
                >
                  <span>{opcion.label}</span>
                  {isSelected && <span className="app-select-check" aria-hidden="true">✓</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

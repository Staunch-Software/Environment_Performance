const PALETTE = [
  '#1F4E79', '#0ea5e9', '#7c3aed', '#0d9488', '#b45309',
  '#be123c', '#15803d', '#9333ea', '#c2410c', '#1d4ed8',
];

function colorFromName(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return PALETTE[Math.abs(hash) % PALETTE.length];
}

function initials(name) {
  const words = name.trim().split(/\s+/);
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

export default function VesselAvatar({ name, size = 32 }) {
  if (!name) return null;
  const bg = colorFromName(name);
  const fontSize = size * 0.38;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: size, height: size, borderRadius: '50%',
      background: bg, color: '#fff',
      fontSize, fontWeight: 700, flexShrink: 0,
      userSelect: 'none', letterSpacing: '0.03em',
    }}>
      {initials(name)}
    </span>
  );
}

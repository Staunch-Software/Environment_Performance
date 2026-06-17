export default function Badge({ value, type }) {
  const cls = type ? `badge badge-${type}` : `badge badge-${(value || '').toLowerCase().replace(/\s+/g, '-')}`;
  return <span className={cls}>{value}</span>;
}

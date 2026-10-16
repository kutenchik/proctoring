/** Convert a chosen wall time in an explicit IANA zone. Reject DST gaps and folds.
 * Requiring an unambiguous time avoids silently choosing the browser's own zone.
 */
export function zonedDateTimeToUtc(local: string, timeZone: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(local);
  if (!match) throw new Error('invalid_datetime');
  const [, y, m, d, h, min] = match.map(Number);
  const wall = Date.UTC(y, m - 1, d, h, min);
  const check = new Date(wall);
  if (check.getUTCFullYear() !== y || check.getUTCMonth() !== m - 1 || check.getUTCDate() !== d || h > 23 || min > 59) throw new Error('invalid_datetime');
  let format: Intl.DateTimeFormat;
  try { format = new Intl.DateTimeFormat('en-CA', {timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}); }
  catch { throw new Error('invalid_timezone'); }
  const parts = (stamp: number) => Object.fromEntries(format.formatToParts(stamp).filter(p => p.type !== 'literal').map(p => [p.type, Number(p.value)]));
  const offsets = new Set<number>();
  for (const delta of [-36, -12, 0, 12, 36]) {
    const stamp = wall + delta * 3600_000;
    const p = parts(stamp);
    offsets.add(Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) - stamp);
  }
  const matches = [...offsets].map(offset => wall - offset).filter(stamp => {
    const p = parts(stamp); return p.year === y && p.month === m && p.day === d && p.hour === h && p.minute === min;
  });
  if (matches.length === 0) throw new Error('nonexistent_time');
  if (matches.length > 1) throw new Error('ambiguous_time');
  return new Date(matches[0]).toISOString();
}

export function displayTime(value: string | null | undefined, locale: string, timeZone?: string): string {
  if (!value) return '—';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '—';
  return new Intl.DateTimeFormat(locale, {dateStyle: 'medium', timeStyle: 'short', ...(timeZone ? {timeZone} : {})}).format(date);
}

export type Route = {page: 'security' | 'configurations' | 'configuration' | 'exams' | 'library' | 'create' | 'detail' | 'live' | 'attempt' | 'login' | 'invite' | 'reset'; id?: string; source?: string; token?: string};
export function routeFromHash(hash: string): Route {
  const [path, query = ''] = hash.replace(/^#\/?/, '').split('?');
  if (path === 'invite' || path === 'reset') return {page: path, token: new URLSearchParams(query).get('token') ?? ''};
  if (path.startsWith('configuration/')) return {page:'configuration',id:decodeURIComponent(path.slice(14)),source:new URLSearchParams(query).get('from')||undefined};
  if (path==='security') return {page:'security'};
  if (path==='configurations') return {page:'configurations'};
  if (path.startsWith('live/')) return {page: 'live', id: decodeURIComponent(path.slice(5))};
  if (path.startsWith('exam/')) return {page: 'detail', id: decodeURIComponent(path.slice(5))};
  if (path.startsWith('attempt/')) return {page: 'attempt', id: decodeURIComponent(path.slice(8))};
  if (path === 'library' || path === 'create' || path === 'login') return {page: path};
  return {page: 'exams'};
}

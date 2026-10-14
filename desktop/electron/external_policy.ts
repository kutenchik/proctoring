import { domainToASCII } from 'node:url';
import { isIP } from 'node:net';
import type { Bounds } from '../shared/contracts';

function hostname(input: string): string {
  if (!input || /[\s\x00-\x1f\x7f%/\\@?#*]/.test(input)) throw new Error('Invalid hostname');
  const unbracketed = input.startsWith('[') && input.endsWith(']') ? input.slice(1, -1) : input;
  if (isIP(unbracketed) === 6) return new URL(`http://[${unbracketed}]/`).hostname.slice(1, -1).toLowerCase();
  if (isIP(unbracketed) === 4) return unbracketed;
  if (/[:\[\]]/.test(input)) throw new Error('Invalid hostname');
  const host = domainToASCII(input.replace(/\.$/, '')).toLowerCase();
  if (host.length > 253 || !host.split('.').every(part => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(part)) || /^[0-9.]+$/.test(host)) throw new Error('Invalid hostname');
  return host;
}
function parseURL(input: string): { url: URL; host: string } {
  if (!input || /[\s\x00-\x1f\x7f\\]/.test(input)) throw new Error('Invalid navigation URL');
  const authority = /^https?:\/\/([^/?#]+)/i.exec(input)?.[1];
  if (!authority || authority.includes('@') || authority.includes('%') || authority.endsWith(':')) throw new Error('Invalid authority');
  const rawHost = authority.startsWith('[') ? authority.slice(0, authority.indexOf(']') + 1) : authority.split(':')[0];
  const original = hostname(rawHost);
  const url = new URL(input);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('Invalid scheme');
  const host = hostname(url.hostname);
  if (host !== original) throw new Error('Ambiguous hostname');
  return { url, host };
}
/** Exact document-host parity with Python NavigationPolicy, not a subresource firewall. */
export class ExamNavigationPolicy {
  readonly url: string;
  readonly hosts: ReadonlySet<string>;
  constructor(url: string, domains: string[]) {
    const parsed = parseURL(url);
    this.url = parsed.url.href;
    this.hosts = new Set((domains.length ? domains : [parsed.host]).map(hostname));
    if (!this.hosts.has(parsed.host)) throw new Error('Configured URL hostname is not allowed');
  }
  allows(input: string): boolean {
    try { return this.hosts.has(parseURL(input).host); } catch { return false; }
  }
}

/** Reserve trusted header and monitoring space even if a faulty renderer asks for fullscreen. */
export function safeExternalBounds(request: Bounds, content: { width: number; height: number }, zoom = 1): Bounds | null {
  if (![...Object.values(request), content.width, content.height, zoom].every(Number.isFinite) || zoom <= 0) return null;
  const margin = 12;
  const wide = content.width >= 1000;
  const right = content.width - (wide ? 304 : margin);
  const bottom = content.height - (wide ? margin : 220);
  const x = Math.max(margin, Math.ceil(request.x * zoom));
  const y = Math.max(108, Math.ceil(request.y * zoom));
  const width = Math.floor(Math.min(request.width * zoom, right - x));
  const height = Math.floor(Math.min(request.height * zoom, bottom - y));
  return width >= 120 && height >= 80 ? { x, y, width, height } : null;
}

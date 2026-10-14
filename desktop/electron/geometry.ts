import { randomUUID } from 'node:crypto';
import { screen, type BrowserWindow } from 'electron';
import type { DisplayGeometry } from '../shared/contracts';

export class GeometryOwner {
  private previous?: DisplayGeometry;
  constructor(private window: BrowserWindow) {}
  snapshot(): DisplayGeometry {
    const content = this.window.getContentBounds();
    const display = screen.getDisplayMatching(content);
    const zoom = this.window.webContents.getZoomFactor();
    const center = { x: (display.bounds.x + display.bounds.width / 2 - content.x) / zoom,
      y: (display.bounds.y + display.bounds.height / 2 - content.y) / zoom };
    const data = { content_bounds: content, display_bounds: display.bounds, scale_factor: display.scaleFactor,
      zoom_factor: zoom, center_client: center,
      center_visible: center.x >= 24 && center.y >= 24 && center.x < content.width / zoom - 24 && center.y < content.height / zoom - 24 };
    const { geometry_id: _old, ...prior } = this.previous ?? {};
    if (!this.previous || JSON.stringify(prior) !== JSON.stringify(data)) this.previous = { geometry_id: randomUUID(), ...data };
    return this.previous;
  }
}

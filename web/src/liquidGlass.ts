const SVG_NS = 'http://www.w3.org/2000/svg';

const SURFACE_SELECTOR = [
  '.panel',
  '.kpi-card',
  '.chat-bubble',
  '.chat-current',
  '.context-box',
  '.knowledge-save-box',
  '.source-item',
  '.finding-suggestion-card',
  '.mcp-tool-card',
  '.skill-detail dl',
  '.skill-version-box',
  '.skill-test-summary',
  '.marketplace-card',
  '.marketplace-install-card',
  '.rag-gold-card',
  '.benchmark-case-card',
  '.benchmark-result-item',
  '.trace-item',
  '.prompt-card',
  '.ab-result-card',
  '.resume-card',
  '.memory-panel',
  '.memory-candidate',
  '.memory-confirmed',
  '.mode-tabs button',
  '.mode-hint',
  '.guide-box',
  '.guide-box button',
  '.toggle-row',
  '.run-form input:not([type="checkbox"])',
  '.run-form select',
  '.run-form textarea',
  '.config-form input:not([type="checkbox"])',
  '.config-form select',
  '.config-form textarea',
  '.timeline-row',
  '.state-summary',
  '.review-box',
  '.resume-panel',
  '.review-actions button',
  '.review-extra-actions button',
  '.palette button',
  '.flow-node',
  '.workflow-validation',
  '.workflow-skill-approval',
  '.report-tabs button',
  '.markdown-view',
  '.mermaid-visual',
].join(',');

type FilterRecord = {
  filter: SVGFilterElement;
  references: number;
};

type SurfaceRecord = {
  filterKey: string;
  resizeObserver: ResizeObserver;
};

function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(maximum, value));
}

function smoothStep(edge0: number, edge1: number, value: number) {
  const amount = clamp((value - edge0) / (edge1 - edge0), 0, 1);
  return amount * amount * (3 - 2 * amount);
}

function roundedRectDistance(
  x: number,
  y: number,
  halfWidth: number,
  halfHeight: number,
  radius: number,
) {
  const qx = Math.abs(x) - halfWidth + radius;
  const qy = Math.abs(y) - halfHeight + radius;
  return Math.min(Math.max(qx, qy), 0) + Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) - radius;
}

function createDisplacementMap(width: number, height: number, radius: number) {
  const resolutionScale = Math.min(1, 320 / width, 220 / height);
  const mapWidth = Math.max(48, Math.round(width * resolutionScale));
  const mapHeight = Math.max(36, Math.round(height * resolutionScale));
  const canvas = document.createElement('canvas');
  canvas.width = mapWidth;
  canvas.height = mapHeight;

  const context = canvas.getContext('2d');
  if (!context) {
    return { dataUrl: '', scale: 0 };
  }

  const image = context.createImageData(mapWidth, mapHeight);
  const data = image.data;
  const centerX = (mapWidth - 1) / 2;
  const centerY = (mapHeight - 1) / 2;
  const scaledRadius = clamp(radius * resolutionScale, 4, Math.min(mapWidth, mapHeight) / 2);
  const edgeBand = clamp(Math.min(mapWidth, mapHeight) * 0.29, 16, 54);
  const lensStrength = clamp(Math.min(width, height) * 0.17, 14, 38) * resolutionScale;
  let maximumOffset = 1;
  const offsets = new Float32Array(mapWidth * mapHeight * 2);

  for (let y = 0; y < mapHeight; y += 1) {
    for (let x = 0; x < mapWidth; x += 1) {
      const pixelIndex = y * mapWidth + x;
      const signedDistance = roundedRectDistance(
        x - centerX,
        y - centerY,
        centerX,
        centerY,
        scaledRadius,
      );
      const innerDistance = Math.max(0, -signedDistance);
      const edgeWeight = 1 - smoothStep(0, edgeBand, innerDistance);
      const normalizedX = centerX ? (x - centerX) / centerX : 0;
      const normalizedY = centerY ? (y - centerY) / centerY : 0;
      const cornerWeight = Math.pow(Math.min(1, Math.hypot(normalizedX, normalizedY) / 1.18), 1.45);
      const refraction = Math.pow(edgeWeight, 0.78) * (0.88 + cornerWeight * 0.64);
      const ripple = Math.sin((normalizedY + 1) * Math.PI * 1.35) * edgeWeight * 1.25;
      const dx = -normalizedX * lensStrength * refraction + ripple;
      const dy = -normalizedY * lensStrength * refraction + Math.cos((normalizedX + 1) * Math.PI * 1.2) * edgeWeight * 1.05;

      offsets[pixelIndex * 2] = dx;
      offsets[pixelIndex * 2 + 1] = dy;
      maximumOffset = Math.max(maximumOffset, Math.abs(dx), Math.abs(dy));
    }
  }

  const filterScale = maximumOffset * 2;
  for (let index = 0; index < mapWidth * mapHeight; index += 1) {
    const dataIndex = index * 4;
    data[dataIndex] = clamp(128 + (offsets[index * 2] / filterScale) * 255, 0, 255);
    data[dataIndex + 1] = clamp(128 + (offsets[index * 2 + 1] / filterScale) * 255, 0, 255);
    data[dataIndex + 2] = 128;
    data[dataIndex + 3] = 255;
  }

  context.putImageData(image, 0, 0);
  return {
    dataUrl: canvas.toDataURL('image/png'),
    scale: filterScale / resolutionScale,
  };
}

function numericRadius(element: HTMLElement) {
  const value = Number.parseFloat(window.getComputedStyle(element).borderTopLeftRadius);
  return Number.isFinite(value) ? value : 12;
}

export function attachLiquidGlassSurfaces() {
  if (typeof window === 'undefined' || typeof ResizeObserver === 'undefined') {
    return () => undefined;
  }

  const svg = document.createElementNS(SVG_NS, 'svg');
  const defs = document.createElementNS(SVG_NS, 'defs');
  svg.classList.add('liquid-glass-runtime-defs');
  svg.setAttribute('aria-hidden', 'true');
  svg.appendChild(defs);
  document.body.appendChild(svg);

  const filters = new Map<string, FilterRecord>();
  const surfaces = new Map<HTMLElement, SurfaceRecord>();
  let filterSequence = 0;
  const rippleTimers = new WeakMap<HTMLButtonElement, number>();

  const handleButtonPress = (event: PointerEvent) => {
    const source = event.target;
    if (!(source instanceof Element)) return;
    const button = source.closest<HTMLButtonElement>('button:not(.connector)');
    if (!button || button.disabled) return;
    if (button.closest('.skill-list, .task-list, .saved-list, .mcp-server-list')) return;

    const rect = button.getBoundingClientRect();
    button.style.setProperty('--liquid-press-x', `${event.clientX - rect.left}px`);
    button.style.setProperty('--liquid-press-y', `${event.clientY - rect.top}px`);
    button.classList.remove('liquid-pressing');
    void button.offsetWidth;
    button.classList.add('liquid-pressing');

    const currentTimer = rippleTimers.get(button);
    if (currentTimer) window.clearTimeout(currentTimer);
    rippleTimers.set(button, window.setTimeout(() => button.classList.remove('liquid-pressing'), 620));
  };

  document.addEventListener('pointerdown', handleButtonPress, true);

  const releaseFilter = (key: string) => {
    const record = filters.get(key);
    if (!record) return;
    record.references -= 1;
    if (record.references <= 0) {
      record.filter.remove();
      filters.delete(key);
    }
  };

  const acquireFilter = (width: number, height: number, radius: number) => {
    const roundedWidth = Math.max(24, Math.round(width / 8) * 8);
    const roundedHeight = Math.max(24, Math.round(height / 8) * 8);
    const roundedRadius = Math.max(4, Math.round(radius / 2) * 2);
    const key = `${roundedWidth}:${roundedHeight}:${roundedRadius}`;
    const existing = filters.get(key);
    if (existing) {
      existing.references += 1;
      return { id: existing.filter.id, key };
    }

    const id = `liquid-glass-surface-${filterSequence++}`;
    const filter = document.createElementNS(SVG_NS, 'filter');
    const image = document.createElementNS(SVG_NS, 'feImage');
    const displacement = document.createElementNS(SVG_NS, 'feDisplacementMap');
    const map = createDisplacementMap(roundedWidth, roundedHeight, roundedRadius);

    filter.id = id;
    filter.setAttribute('filterUnits', 'objectBoundingBox');
    filter.setAttribute('primitiveUnits', 'userSpaceOnUse');
    filter.setAttribute('x', '-8%');
    filter.setAttribute('y', '-8%');
    filter.setAttribute('width', '116%');
    filter.setAttribute('height', '116%');
    filter.setAttribute('color-interpolation-filters', 'sRGB');

    image.setAttribute('href', map.dataUrl);
    image.setAttribute('x', '0');
    image.setAttribute('y', '0');
    image.setAttribute('width', String(roundedWidth));
    image.setAttribute('height', String(roundedHeight));
    image.setAttribute('preserveAspectRatio', 'none');
    image.setAttribute('result', 'liquidMap');

    displacement.setAttribute('in', 'SourceGraphic');
    displacement.setAttribute('in2', 'liquidMap');
    displacement.setAttribute('scale', map.scale.toFixed(2));
    displacement.setAttribute('xChannelSelector', 'R');
    displacement.setAttribute('yChannelSelector', 'G');

    filter.append(image, displacement);
    defs.appendChild(filter);
    filters.set(key, { filter, references: 1 });
    return { id, key };
  };

  const updateSurface = (element: HTMLElement) => {
    if (!element.isConnected) return;
    const rect = element.getBoundingClientRect();
    if (rect.width < 24 || rect.height < 24) return;

    const next = acquireFilter(rect.width, rect.height, numericRadius(element));
    const current = surfaces.get(element);
    if (current?.filterKey === next.key) {
      releaseFilter(next.key);
      return;
    }
    if (current) releaseFilter(current.filterKey);
    element.style.setProperty('--liquid-glass-filter', `url("#${next.id}")`);
    element.dataset.liquidGlass = 'ready';
    if (current) current.filterKey = next.key;
  };

  const attachSurface = (element: HTMLElement) => {
    if (surfaces.has(element)) return;
    const resizeObserver = new ResizeObserver(() => updateSurface(element));
    surfaces.set(element, { filterKey: '', resizeObserver });
    resizeObserver.observe(element);
    updateSurface(element);
  };

  const scan = (root: ParentNode) => {
    if (root instanceof HTMLElement && root.matches(SURFACE_SELECTOR)) attachSurface(root);
    root.querySelectorAll<HTMLElement>(SURFACE_SELECTOR).forEach(attachSurface);
  };

  scan(document);
  const mutationObserver = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      mutation.addedNodes.forEach((node) => {
        if (node instanceof HTMLElement) scan(node);
      });
      mutation.removedNodes.forEach((node) => {
        if (!(node instanceof HTMLElement)) return;
        const removed = [node, ...node.querySelectorAll<HTMLElement>(SURFACE_SELECTOR)];
        removed.forEach((element) => {
          const record = surfaces.get(element);
          if (!record) return;
          record.resizeObserver.disconnect();
          releaseFilter(record.filterKey);
          surfaces.delete(element);
        });
      });
    });
  });
  mutationObserver.observe(document.body, { childList: true, subtree: true });

  return () => {
    document.removeEventListener('pointerdown', handleButtonPress, true);
    mutationObserver.disconnect();
    surfaces.forEach((record, element) => {
      record.resizeObserver.disconnect();
      element.style.removeProperty('--liquid-glass-filter');
      delete element.dataset.liquidGlass;
    });
    surfaces.clear();
    filters.clear();
    svg.remove();
  };
}

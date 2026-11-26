export const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
export const extOf = p => String(p).toLowerCase().split('.').pop();
export const GEO_EXT = ['geojson', 'json', 'shp', 'gpkg', 'gml', 'kml'];
export const IMG_EXT = ['png', 'jpg', 'jpeg', 'webp'];
export const humanSize = n => { if (!n) return ''; const units = ['B', 'KB', 'MB', 'GB']; let i = 0; while (n >= 1024 && i < 3) { n /= 1024; i++; } return n.toFixed(i ? 1 : 0) + units[i]; };
  export function prose(md) {
    const inline = s => esc(s)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s.,;:)!?]|$)/g, '$1<em>$2</em>')
      .replace(/(^|[\s(])_([^_\n]+)_(?=[\s.,;:)!?]|$)/g, '$1<em>$2</em>');
    const lines = String(md || '').replace(/\r/g, '').split('\n');
    const out = [];
    let para = [], list = null, fence = null;
    const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; } };
    const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
    const block = () => { flushPara(); closeList(); };
    const cellsOf = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => inline(c.trim()));

    for (let i = 0; i < lines.length; i++) {
      const raw = lines[i].replace(/\s+$/, '');
      const line = raw.trim();

      if (fence !== null) {                       // inside a code fence
        if (/^```/.test(line)) { out.push(`<pre class="prose-pre"><code>${esc(fence.join('\n'))}</code></pre>`); fence = null; }
        else fence.push(raw);
        continue;
      }
      if (/^```/.test(line)) { block(); fence = []; continue; }
      if (!line) { block(); continue; }           // blank line ends a paragraph
      if (/^([-*_]\s*){3,}$/.test(line)) { block(); out.push('<hr/>'); continue; }

      const h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) { block(); out.push(`<h${Math.min(h[1].length + 2, 6)}>${inline(h[2])}</h${Math.min(h[1].length + 2, 6)}>`); continue; }

      if (/^>\s?/.test(line)) { block(); out.push(`<blockquote>${inline(line.replace(/^>\s?/, ''))}</blockquote>`); continue; }

      // a table needs its dashed separator on the next line to count as one
      if (line.includes('|') && /^\|?[\s:|-]*-{2,}[\s:|-]*$/.test((lines[i + 1] || '').trim())) {
        block();
        const head = cellsOf(line);
        const rows = [];
        i += 2;
        while (i < lines.length && lines[i].trim() && lines[i].includes('|')) { rows.push(cellsOf(lines[i])); i++; }
        i--;
        out.push('<table class="prose-table"><thead><tr>' + head.map(c => `<th>${c}</th>`).join('')
          + '</tr></thead><tbody>' + rows.map(r => '<tr>' + r.map(c => `<td>${c}</td>`).join('') + '</tr>').join('')
          + '</tbody></table>');
        continue;
      }

      const ol = line.match(/^(\d+)[.)]\s+(.*)$/);
      const ul = line.match(/^[-*•]\s+(.*)$/);
      if (ol || ul) {
        const want = ol ? 'ol' : 'ul';
        flushPara();
        if (list !== want) { closeList(); out.push(`<${want}>`); list = want; }
        out.push(`<li${/^\s{2,}/.test(raw) ? ' class="sub"' : ''}>${inline(ol ? ol[2] : ul[1])}</li>`);
        continue;
      }
      closeList();
      para.push(line);                            // wrapped lines join one paragraph
    }
    if (fence && fence.length) out.push(`<pre class="prose-pre"><code>${esc(fence.join('\n'))}</code></pre>`);
    block();
    return out.join('\n');
  }

  // The finish tool wraps the agent's words in "Task complete / Summary: /
  // Output files". Only the middle was written for a person. Mirrors the same
  // strip on the server, for replayed runs that never went through it.
  export const cleanFinish = obs => String(obs || '')
    .replace(/^\s*(?:\u{1F4CB}\s*)?Task complete\s*\n?/u, '')
    .replace(/^\s*Summary:\s*/, '')
    .split(/\n(?:Output files \(\d+\):|\u26A0\uFE0F? ?No output files)/)[0]
    .trim();

/* ==========================================================================
   Graficos em SVG puro - sem bibliotecas externas.
   Regras aplicadas: marcas finas, grade recessiva, legenda sempre presente
   para 2+ series, rotulos diretos ate 4 series, camada de hover por padrao,
   e redesenho no resize.
   ========================================================================== */
'use strict';

const G = (() => {

  const NS = 'http://www.w3.org/2000/svg';
  const CORES = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6', '--s7', '--s8'];

  const brl = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
  const brl0 = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL',
                                                maximumFractionDigits: 0 });

  const moeda = v => brl.format(v || 0);
  const moeda0 = v => brl0.format(v || 0);

  /** Eixo de valores: R$ 1,2 mi / R$ 340 mil / R$ 850 */
  function moedaCurta(v) {
    const a = Math.abs(v);
    if (a >= 1e6) return 'R$ ' + (v / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' mi';
    if (a >= 1e3) return 'R$ ' + (v / 1e3).toLocaleString('pt-BR', { maximumFractionDigits: 0 }) + ' mil';
    return 'R$ ' + v.toLocaleString('pt-BR', { maximumFractionDigits: 0 });
  }

  /**
   * Formatador de eixo que respeita o passo entre as marcas.
   * Sem isso, uma escala de 10 mil a 13 mil imprime "R$ 13 mil" tres vezes.
   */
  function formatadorEixo(ticks) {
    const passo = Math.abs(ticks.length > 1 ? ticks[1] - ticks[0] : ticks[0] || 1);
    const div = passo >= 1e6 ? 1e6 : passo >= 1e3 ? 1e3 : 1;
    const suf = div === 1e6 ? ' mi' : div === 1e3 ? ' mil' : '';
    const casas = Math.max(0, Math.min(2, Math.ceil(-Math.log10(passo / div))));
    return v => 'R$ ' + (v / div).toLocaleString('pt-BR', {
      minimumFractionDigits: casas, maximumFractionDigits: casas }) + suf;
  }

  /** Afasta rotulos que ficariam por cima uns dos outros. */
  function afastar(itens, minimo = 13) {
    const ord = [...itens].sort((a, b) => a.y - b.y);
    for (let i = 1; i < ord.length; i++) {
      if (ord[i].y - ord[i - 1].y < minimo) ord[i].y = ord[i - 1].y + minimo;
    }
    return itens;
  }

  const pct = v => (v || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2,
                                                     maximumFractionDigits: 2 }) + '%';

  function cor(i) {
    const nome = CORES[i % CORES.length];
    return getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
  }
  function token(nome) {
    return getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
  }

  function dataCurta(iso, comAno = true) {
    const [a, m, d] = iso.split('-');
    const meses = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun',
                   'jul', 'ago', 'set', 'out', 'nov', 'dez'];
    return comAno ? `${meses[+m - 1]}/${a.slice(2)}` : `${d}/${m}/${a}`;
  }
  const dataLonga = iso => { const [a, m, d] = iso.split('-'); return `${d}/${m}/${a}`; };

  // ---------------------------------------------------------------- SVG ---
  function tag(nome, atrs = {}, filhos = []) {
    const e = document.createElementNS(NS, nome);
    for (const [k, v] of Object.entries(atrs)) {
      if (v !== null && v !== undefined) e.setAttribute(k, v);
    }
    for (const f of [].concat(filhos)) if (f) e.appendChild(f);
    return e;
  }
  function texto(x, y, txt, classe = 'eixo-texto', extra = {}) {
    const t = tag('text', { x, y, class: classe, ...extra });
    t.textContent = txt;
    return t;
  }

  /** Marcas "redondas" para o eixo de valores. */
  function marcas(min, max, alvo = 5) {
    if (max === min) { max = min + 1; }
    const bruto = (max - min) / alvo;
    const mag = Math.pow(10, Math.floor(Math.log10(bruto)));
    const norm = bruto / mag;
    const passo = (norm >= 7.5 ? 10 : norm >= 3.5 ? 5 : norm >= 1.5 ? 2 : 1) * mag;
    const ini = Math.floor(min / passo) * passo;
    const out = [];
    for (let v = ini; v <= max + passo * 0.5; v += passo) if (v >= min - 1e-9) out.push(v);
    return out;
  }

  // ------------------------------------------------------------ tooltip ---
  function criarDica(host) {
    let d = host.querySelector('.dica-grafico');
    if (!d) {
      d = document.createElement('div');
      d.className = 'dica-grafico';
      host.appendChild(d);
    }
    return d;
  }
  function posicionarDica(dica, host, x, y) {
    const lh = host.clientWidth, lv = host.clientHeight;
    const dw = dica.offsetWidth, dh = dica.offsetHeight;
    let px = x + 14, py = y - dh - 10;
    if (px + dw > lh - 4) px = x - dw - 14;
    if (px < 4) px = 4;
    if (py < 4) py = Math.min(y + 16, lv - dh - 4);
    dica.style.left = px + 'px';
    dica.style.top = py + 'px';
  }
  const linhaDica = (c, rot, val) => `
    <div class="dica-grafico__linha">
      <span class="legenda__esq">
        ${c ? `<span class="legenda__marca" style="background:${c}"></span>` : ''}
        <span>${rot}</span>
      </span>
      <span class="dica-grafico__valor">${val}</span>
    </div>`;

  /** Prepara o host: limpa, mede e devolve o <svg> ou null se nao ha dados. */
  function preparar(host, dados, alt) {
    host.querySelectorAll('svg').forEach(s => s.remove());
    const dica = host.querySelector('.dica-grafico');
    if (dica) dica.remove();
    if (!dados || !dados.length) { host.dataset.estado = 'vazio'; return null; }
    delete host.dataset.estado;
    const L = host.clientWidth || 640;
    const A = alt || host.clientHeight || 300;
    const svg = tag('svg', { viewBox: `0 0 ${L} ${A}`, preserveAspectRatio: 'none',
                             role: 'img' });
    host.appendChild(svg);
    return { svg, L, A };
  }

  /** Redesenha ao mudar o tamanho do container. */
  function observar(host, redesenhar) {
    if (host._obs) host._obs.disconnect();
    let largura = host.clientWidth;
    host._obs = new ResizeObserver(() => {
      if (Math.abs(host.clientWidth - largura) < 8) return;
      largura = host.clientWidth;
      redesenhar();
    });
    host._obs.observe(host);
    host._redesenhar = redesenhar;   // permite forcar o redesenho (ex.: troca de tema)
  }

  /** Redesenha um grafico ja montado neste host (usado na troca de tema). */
  function redesenhar(host) {
    if (host && host._redesenhar) host._redesenhar();
  }

  // =================================================== AREA EMPILHADA ====
  /**
   * Evolucao do patrimonio: base = total aportado, faixa de cima = juros.
   * @param {object} cfg {serie:[{data,principal,liquido}], hoje:'AAAA-MM-DD', legenda:Element}
   */
  function areaEmpilhada(host, cfg) {
    const desenhar = () => {
      const s = cfg.serie || [];
      const base = preparar(host, s);
      if (!base) { if (cfg.legenda) cfg.legenda.innerHTML = ''; return; }
      const { svg, L, A } = base;
      const m = { t: 14, d: 16, b: 30, e: 62 };
      const lw = L - m.e - m.d, lh = A - m.t - m.b;

      const topo = Math.max(...s.map(p => Math.max(p.liquido, p.base)));
      const ticks = marcas(0, topo, 5);
      const yMax = Math.max(ticks[ticks.length - 1], topo);
      const x = i => m.e + (s.length === 1 ? lw / 2 : (i / (s.length - 1)) * lw);
      const y = v => m.t + lh - (v / yMax) * lh;

      // grade + eixo de valores
      const g = tag('g');
      const fmt = formatadorEixo(ticks);
      ticks.forEach(t => {
        g.appendChild(tag('line', { x1: m.e, x2: m.e + lw, y1: y(t), y2: y(t),
                                    class: 'grade-linha' }));
        g.appendChild(texto(m.e - 8, y(t) + 3.5, fmt(t), 'eixo-texto',
                            { 'text-anchor': 'end' }));
      });
      svg.appendChild(g);

      // areas: aportado (base) e juros (por cima)
      const c1 = cor(0), c2 = cor(2);
      const linhaP = s.map((p, i) => `${x(i)},${y(p.base)}`).join(' ');
      const linhaL = s.map((p, i) => `${x(i)},${y(p.liquido)}`).join(' ');

      svg.appendChild(tag('polygon', {
        points: `${x(0)},${y(0)} ${linhaP} ${x(s.length - 1)},${y(0)}`,
        fill: c1, 'fill-opacity': .22,
      }));
      // faixa de juros entre as duas curvas
      svg.appendChild(tag('polygon', {
        points: `${linhaP} ${s.map((p, i) => `${x(s.length - 1 - i)},${y(s[s.length - 1 - i].liquido)}`).join(' ')}`,
        fill: c2, 'fill-opacity': .30,
      }));
      // separacao de 2px entre as faixas (regra do gap de superficie)
      svg.appendChild(tag('polyline', {
        points: linhaP, fill: 'none', stroke: token('--superficie'), 'stroke-width': 2,
      }));
      svg.appendChild(tag('polyline', {
        points: linhaP, fill: 'none', stroke: c1, 'stroke-width': 2,
        'stroke-linejoin': 'round',
      }));
      svg.appendChild(tag('polyline', {
        points: linhaL, fill: 'none', stroke: c2, 'stroke-width': 2,
        'stroke-linejoin': 'round',
      }));

      // eixo de datas
      svg.appendChild(tag('line', { x1: m.e, x2: m.e + lw, y1: m.t + lh, y2: m.t + lh,
                                    class: 'eixo-linha' }));
      const n = Math.max(2, Math.min(6, Math.floor(lw / 90)));
      for (let k = 0; k < n; k++) {
        const i = Math.round(k * (s.length - 1) / (n - 1));
        svg.appendChild(texto(x(i), A - 10, dataCurta(s[i].data), 'eixo-texto', {
          'text-anchor': k === 0 ? 'start' : k === n - 1 ? 'end' : 'middle',
        }));
      }

      // divisor "hoje" separando historico de projecao
      if (cfg.hoje) {
        let iH = s.findIndex(p => p.data >= cfg.hoje);
        if (iH > 0 && iH < s.length - 1) {
          svg.appendChild(tag('line', { x1: x(iH), x2: x(iH), y1: m.t, y2: m.t + lh,
                                        class: 'marca-hoje' }));
          svg.appendChild(texto(x(iH) + 5, m.t + 11, 'hoje', 'marca-hoje-texto'));
        }
      }

      // camada de hover
      const dica = criarDica(host);
      const cruz = tag('line', { class: 'marca-hoje', y1: m.t, y2: m.t + lh, opacity: 0 });
      const pt1 = tag('circle', { r: 4.5, fill: c1, stroke: token('--superficie'),
                                  'stroke-width': 2, opacity: 0 });
      const pt2 = tag('circle', { r: 4.5, fill: c2, stroke: token('--superficie'),
                                  'stroke-width': 2, opacity: 0 });
      svg.append(cruz, pt1, pt2);

      const captura = tag('rect', { x: m.e, y: m.t, width: lw, height: lh,
                                    fill: 'transparent', style: 'cursor:crosshair' });
      svg.appendChild(captura);

      captura.addEventListener('pointermove', ev => {
        const cx = ev.clientX - host.getBoundingClientRect().left;
        const razao = Math.max(0, Math.min(1, (cx - m.e) / lw));
        const i = Math.round(razao * (s.length - 1));
        const p = s[i];
        cruz.setAttribute('x1', x(i)); cruz.setAttribute('x2', x(i));
        cruz.setAttribute('opacity', 1);
        pt1.setAttribute('cx', x(i)); pt1.setAttribute('cy', y(p.base));
        pt2.setAttribute('cx', x(i)); pt2.setAttribute('cy', y(p.liquido));
        pt1.setAttribute('opacity', 1); pt2.setAttribute('opacity', 1);

        const juros = p.liquido - p.base;
        dica.innerHTML =
          `<div class="dica-grafico__titulo">${dataLonga(p.data)}` +
          (cfg.hoje && p.data > cfg.hoje ? ' &middot; projetado' : '') + '</div>' +
          linhaDica(c2, 'Patrimonio liquido', moeda(p.liquido)) +
          linhaDica(c1, 'Total aportado', moeda(p.base)) +
          linhaDica('', 'Juros acumulados', moeda(juros));
        dica.dataset.visivel = '1';
        posicionarDica(dica, host, x(i), y(p.liquido));
      });
      captura.addEventListener('pointerleave', () => {
        dica.dataset.visivel = '0';
        [cruz, pt1, pt2].forEach(e => e.setAttribute('opacity', 0));
      });

      if (cfg.legenda) {
        const ult = s[s.length - 1];
        cfg.legenda.innerHTML =
          item(c1, 'Total aportado', moeda0(ult.base)) +
          item(c2, 'Juros acumulados', moeda0(ult.liquido - ult.base));
      }
    };
    desenhar();
    observar(host, desenhar);
  }

  const item = (c, rot, val) => `
    <span class="legenda__item">
      <span class="legenda__marca" style="background:${c}"></span>
      <span>${rot}</span>${val ? `<strong class="legenda__valor">${val}</strong>` : ''}
    </span>`;

  // ============================================================ ROSCA ====
  function rosca(host, fatias, legendaEl) {
    const desenhar = () => {
      const base = preparar(host, fatias);
      if (!base) { if (legendaEl) legendaEl.innerHTML = ''; return; }
      const { svg, L, A } = base;
      const cx = L / 2, cy = A / 2;
      const raio = Math.min(L, A) / 2 - 8;
      const esp = raio * 0.34;
      const total = fatias.reduce((s, f) => s + f.valor, 0) || 1;
      const dica = criarDica(host);

      let ang = -Math.PI / 2;
      fatias.forEach((f, i) => {
        const frac = f.valor / total;
        const delta = frac * Math.PI * 2;
        const c = cor(f.slot ?? i);   // slot fixo: a cor acompanha a entidade
        const arco = setor(cx, cy, raio, raio - esp, ang, ang + delta);
        const p = tag('path', {
          d: arco, fill: c,
          stroke: token('--superficie'), 'stroke-width': 2,   // gap de 2px
          style: 'cursor:pointer; transition:opacity .12s',
        });
        p.addEventListener('pointerenter', () => {
          p.style.opacity = .78;
          dica.innerHTML = `<div class="dica-grafico__titulo">${f.rotulo}</div>` +
                           linhaDica(c, 'Valor liquido', moeda(f.valor)) +
                           linhaDica('', 'Peso na carteira', pct(f.peso));
          dica.dataset.visivel = '1';
        });
        p.addEventListener('pointermove', ev => {
          const r = host.getBoundingClientRect();
          posicionarDica(dica, host, ev.clientX - r.left, ev.clientY - r.top);
        });
        p.addEventListener('pointerleave', () => {
          p.style.opacity = 1; dica.dataset.visivel = '0';
        });
        svg.appendChild(p);
        ang += delta;
      });

      // total no centro
      svg.appendChild(texto(cx, cy - 4, 'Total liquido', 'eixo-texto',
                            { 'text-anchor': 'middle' }));
      svg.appendChild(texto(cx, cy + 15, moeda0(total), 'rotulo-direto',
                            { 'text-anchor': 'middle', style: 'font-size:15px' }));

      // A cor sozinha nunca carrega a identidade: legenda com valor sempre visivel.
      if (legendaEl) {
        legendaEl.innerHTML = fatias.map((f, i) => `
          <span class="legenda__item">
            <span class="legenda__esq">
              <span class="legenda__marca" style="background:${cor(f.slot ?? i)}"></span>
              <span class="legenda__nome">${f.rotulo}</span>
            </span>
            <span class="legenda__valor">${moeda0(f.valor)} &middot; ${pct(f.peso)}</span>
          </span>`).join('');
      }
    };
    desenhar();
    observar(host, desenhar);
  }

  function setor(cx, cy, re, ri, a0, a1) {
    if (a1 - a0 >= Math.PI * 2 - 1e-6) a1 = a0 + Math.PI * 2 - 1e-4;
    const P = (r, a) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
    const [x1, y1] = P(re, a0), [x2, y2] = P(re, a1);
    const [x3, y3] = P(ri, a1), [x4, y4] = P(ri, a0);
    const gr = a1 - a0 > Math.PI ? 1 : 0;
    return `M${x1},${y1} A${re},${re} 0 ${gr} 1 ${x2},${y2} L${x3},${y3} ` +
           `A${ri},${ri} 0 ${gr} 0 ${x4},${y4} Z`;
  }

  // ============================================= BARRAS 100% PROPORCAO ====
  /** Composicao proporcional (ex.: por indexador). fatias:[{rotulo,valor,peso,slot}] */
  function barrasProporcao(host, fatias, legendaEl) {
    const desenhar = () => {
      const base = preparar(host, fatias, 46);
      if (!base) { if (legendaEl) legendaEl.innerHTML = ''; return; }
      const { svg, L, A } = base;
      const total = fatias.reduce((s, f) => s + f.valor, 0) || 1;
      const dica = criarDica(host);
      const alt = Math.min(30, A - 10);
      const y0 = (A - alt) / 2;
      let x = 4;
      const lw = L - 8;

      fatias.forEach((f, i) => {
        const w = Math.max(0, (f.valor / total) * lw);
        const c = cor(f.slot ?? i);
        const r = tag('rect', { x, y: y0, width: Math.max(0, w - 2), height: alt,
                                fill: c, rx: 5, style: 'cursor:pointer' });
        r.addEventListener('pointerenter', () => {
          dica.innerHTML = `<div class="dica-grafico__titulo">${f.rotulo}</div>` +
                           linhaDica(c, 'Valor liquido', moeda(f.valor)) +
                           linhaDica('', 'Peso na carteira', pct(f.peso));
          dica.dataset.visivel = '1';
        });
        r.addEventListener('pointermove', ev => {
          const rc = host.getBoundingClientRect();
          posicionarDica(dica, host, ev.clientX - rc.left, ev.clientY - rc.top);
        });
        r.addEventListener('pointerleave', () => { dica.dataset.visivel = '0'; });
        svg.appendChild(r);
        x += w;
      });

      if (legendaEl) {
        legendaEl.innerHTML = fatias.map((f, i) => `
          <span class="legenda__item">
            <span class="legenda__esq">
              <span class="legenda__marca" style="background:${cor(f.slot ?? i)}"></span>
              <span class="legenda__nome">${f.rotulo}</span>
            </span>
            <span class="legenda__valor">${pct(f.peso)}</span>
          </span>`).join('');
      }
    };
    desenhar();
    observar(host, desenhar);
  }

  // ============================================== BARRAS EMPILHADAS ====
  /** Projecao ano a ano: aportado + juros. */
  function barrasEmpilhadas(host, marcosDados, legendaEl) {
    const desenhar = () => {
      const base = preparar(host, marcosDados);
      if (!base) { if (legendaEl) legendaEl.innerHTML = ''; return; }
      const { svg, L, A } = base;
      const m = { t: 22, d: 16, b: 34, e: 62 };
      const lw = L - m.e - m.d, lh = A - m.t - m.b;
      const n = marcosDados.length;

      const topo = Math.max(...marcosDados.map(d => d.liquido));
      const ticks = marcas(0, topo, 5);
      const yMax = Math.max(ticks[ticks.length - 1], topo);
      const y = v => m.t + lh - (v / yMax) * lh;

      const passo = lw / n;
      const larg = Math.min(52, passo * 0.62);
      const c1 = cor(0), c2 = cor(2);
      const dica = criarDica(host);

      const fmt = formatadorEixo(ticks);
      ticks.forEach(t => {
        svg.appendChild(tag('line', { x1: m.e, x2: m.e + lw, y1: y(t), y2: y(t),
                                      class: 'grade-linha' }));
        svg.appendChild(texto(m.e - 8, y(t) + 3.5, fmt(t), 'eixo-texto',
                              { 'text-anchor': 'end' }));
      });

      marcosDados.forEach((d, i) => {
        const cx = m.e + passo * i + passo / 2;
        const x0 = cx - larg / 2;
        const juros = Math.max(0, d.liquido - d.principal);

        // base ancorada na linha zero, topo arredondado em 4px
        const hp = Math.max(1, y(0) - y(d.principal));
        svg.appendChild(tag('rect', { x: x0, y: y(d.principal), width: larg, height: hp,
                                      fill: c1, rx: 0 }));
        const hj = Math.max(0, y(d.principal) - y(d.liquido) - 2); // gap de 2px
        if (hj > 0) {
          svg.appendChild(tag('rect', { x: x0, y: y(d.liquido), width: larg, height: hj,
                                        fill: c2, rx: 4 }));
        }

        svg.appendChild(texto(cx, y(d.liquido) - 8, moedaCurta(d.liquido), 'rotulo-direto',
                              { 'text-anchor': 'middle' }));
        svg.appendChild(texto(cx, A - 12, `${d.ano}a`, 'eixo-texto',
                              { 'text-anchor': 'middle' }));

        const alvo = tag('rect', { x: x0 - 4, y: m.t, width: larg + 8, height: lh,
                                   fill: 'transparent', style: 'cursor:pointer' });
        alvo.addEventListener('pointerenter', () => {
          dica.innerHTML =
            `<div class="dica-grafico__titulo">Em ${d.ano} ano${d.ano > 1 ? 's' : ''} &middot; ${dataLonga(d.data)}</div>` +
            linhaDica(c2, 'Patrimonio liquido', moeda(d.liquido)) +
            linhaDica(c1, 'Total aportado', moeda(d.principal)) +
            linhaDica('', 'Juros acumulados', moeda(juros));
          dica.dataset.visivel = '1';
        });
        alvo.addEventListener('pointermove', ev => {
          const r = host.getBoundingClientRect();
          posicionarDica(dica, host, ev.clientX - r.left, ev.clientY - r.top);
        });
        alvo.addEventListener('pointerleave', () => { dica.dataset.visivel = '0'; });
        svg.appendChild(alvo);
      });

      svg.appendChild(tag('line', { x1: m.e, x2: m.e + lw, y1: y(0), y2: y(0),
                                    class: 'eixo-linha' }));

      if (legendaEl) {
        legendaEl.innerHTML = item(c1, 'Total aportado') + item(c2, 'Juros acumulados');
      }
    };
    desenhar();
    observar(host, desenhar);
  }

  // ============================================================ LINHAS ====
  /** Comparativo do simulador. series = [{rotulo, pontos:[{data,liquido}]}] */
  function linhas(host, series, legendaEl) {
    const desenhar = () => {
      const base = preparar(host, series);
      if (!base) { if (legendaEl) legendaEl.innerHTML = ''; return; }
      const { svg, L, A } = base;
      const rotulaDireto = series.length <= 4;
      const m = { t: 14, d: rotulaDireto ? 104 : 18, b: 30, e: 68 };
      const lw = L - m.e - m.d, lh = A - m.t - m.b;

      const nMax = Math.max(...series.map(s => s.pontos.length));
      const topo = Math.max(...series.flatMap(s => s.pontos.map(p => p.liquido)));
      const piso = Math.min(...series.flatMap(s => s.pontos.map(p => p.liquido)));
      const ticks = marcas(piso * 0.985, topo, 5);
      const yMin = ticks[0], yMax = Math.max(ticks[ticks.length - 1], topo);
      const x = i => m.e + (nMax === 1 ? lw / 2 : (i / (nMax - 1)) * lw);
      const y = v => m.t + lh - ((v - yMin) / (yMax - yMin || 1)) * lh;

      const fmt = formatadorEixo(ticks);
      ticks.forEach(t => {
        svg.appendChild(tag('line', { x1: m.e, x2: m.e + lw, y1: y(t), y2: y(t),
                                      class: 'grade-linha' }));
        svg.appendChild(texto(m.e - 8, y(t) + 3.5, fmt(t), 'eixo-texto',
                              { 'text-anchor': 'end' }));
      });

      const refs = series.map((s, i) => {
        const c = cor(i);
        const pts = s.pontos.map((p, k) => `${x(k)},${y(p.liquido)}`).join(' ');
        svg.appendChild(tag('polyline', {
          points: pts, fill: 'none', stroke: c, 'stroke-width': 2,
          'stroke-linejoin': 'round', 'stroke-linecap': 'round',
        }));
        return { c, s };
      });

      // Rotulos diretos no fim de cada linha, afastados para nao colidirem.
      if (rotulaDireto) {
        const marcadores = afastar(refs.map(({ c, s }) => {
          const ult = s.pontos[s.pontos.length - 1];
          return { c, y: y(ult.liquido), valor: ult.liquido, n: s.pontos.length - 1 };
        }));
        marcadores.forEach(r => {
          svg.appendChild(texto(x(r.n) + 9, r.y + 4, moeda0(r.valor), 'rotulo-direto',
                                { fill: r.c, 'text-anchor': 'start' }));
        });
      }

      svg.appendChild(tag('line', { x1: m.e, x2: m.e + lw, y1: m.t + lh, y2: m.t + lh,
                                    class: 'eixo-linha' }));
      const nt = Math.max(2, Math.min(5, Math.floor(lw / 100)));
      const eixoRef = series[0].pontos;
      for (let k = 0; k < nt; k++) {
        const i = Math.round(k * (eixoRef.length - 1) / (nt - 1));
        svg.appendChild(texto(x(i), A - 10, dataCurta(eixoRef[i].data), 'eixo-texto', {
          'text-anchor': k === 0 ? 'start' : k === nt - 1 ? 'end' : 'middle',
        }));
      }

      const dica = criarDica(host);
      const cruz = tag('line', { class: 'marca-hoje', y1: m.t, y2: m.t + lh, opacity: 0 });
      svg.appendChild(cruz);
      const pontos = refs.map(({ c }) => {
        const p = tag('circle', { r: 4.5, fill: c, stroke: token('--superficie'),
                                  'stroke-width': 2, opacity: 0 });
        svg.appendChild(p);
        return p;
      });

      const captura = tag('rect', { x: m.e, y: m.t, width: lw, height: lh,
                                    fill: 'transparent', style: 'cursor:crosshair' });
      svg.appendChild(captura);
      captura.addEventListener('pointermove', ev => {
        const cx = ev.clientX - host.getBoundingClientRect().left;
        const razao = Math.max(0, Math.min(1, (cx - m.e) / lw));
        const i = Math.round(razao * (nMax - 1));
        cruz.setAttribute('x1', x(i)); cruz.setAttribute('x2', x(i));
        cruz.setAttribute('opacity', 1);

        const ordenados = refs
          .map(({ c, s }, k) => ({ c, s, p: s.pontos[Math.min(i, s.pontos.length - 1)], k }))
          .sort((a, b) => b.p.liquido - a.p.liquido);

        ordenados.forEach(o => {
          pontos[o.k].setAttribute('cx', x(i));
          pontos[o.k].setAttribute('cy', y(o.p.liquido));
          pontos[o.k].setAttribute('opacity', 1);
        });
        dica.innerHTML =
          `<div class="dica-grafico__titulo">${dataLonga(ordenados[0].p.data)}</div>` +
          ordenados.map(o => linhaDica(o.c, o.s.rotulo, moeda(o.p.liquido))).join('');
        dica.dataset.visivel = '1';
        posicionarDica(dica, host, x(i), y(ordenados[0].p.liquido));
      });
      captura.addEventListener('pointerleave', () => {
        dica.dataset.visivel = '0';
        cruz.setAttribute('opacity', 0);
        pontos.forEach(p => p.setAttribute('opacity', 0));
      });

      if (legendaEl) legendaEl.innerHTML = refs.map(({ c, s }) => item(c, s.rotulo)).join('');
    };
    desenhar();
    observar(host, desenhar);
  }

  /** Mini-grafico de linha sem eixos/dica, para o valor de destaque de um KPI. */
  function spark(host, valores) {
    const w = 110, h = 34, pad = 2;
    const vs = valores.length ? valores : [0, 0];
    const min = Math.min(...vs), max = Math.max(...vs);
    const x = i => vs.length === 1 ? w / 2 : (i / (vs.length - 1)) * w;
    const y = v => h - pad - ((v - min) / (max - min || 1)) * (h - pad * 2);
    const pontos = vs.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    host.innerHTML = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <polyline points="${pontos}" fill="none" stroke="var(--s1)" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round"></polyline></svg>`;
  }

  // ========================================================= TIMELINE ====
  /**
   * Faixa horizontal com os vencimentos no tempo - responde "quando o
   * dinheiro volta" de forma mais direta que uma tabela.
   * itens: [{nome, data_aplicacao, data, valor, dias}]
   */
  function timeline(host, itens, hojeISO) {
    const desenhar = () => {
      host.querySelectorAll('svg').forEach(s => s.remove());
      const dica0 = host.querySelector('.dica-grafico');
      if (dica0) dica0.remove();
      if (!itens || !itens.length) { host.dataset.estado = 'vazio'; return; }
      delete host.dataset.estado;

      const L = host.clientWidth || 640;
      const linhaAlt = 34, m = { t: 10, e: 14, d: 90, b: 26 };
      const A = m.t + itens.length * linhaAlt + m.b;
      const svg = tag('svg', { viewBox: `0 0 ${L} ${A}`, preserveAspectRatio: 'none',
                               role: 'img' });
      host.appendChild(svg);

      const hoje = new Date(hojeISO);
      const datas = itens.flatMap(it => [new Date(it.data_aplicacao), new Date(it.data)]);
      const min = new Date(Math.min(hoje, ...datas));
      const max = new Date(Math.max(hoje, ...datas));
      const span = Math.max(1, max - min);
      const lw = L - m.e - m.d;
      const x = d => m.e + ((new Date(d) - min) / span) * lw;

      const dica = criarDica(host);
      itens.forEach((it, i) => {
        const y = m.t + i * linhaAlt + linhaAlt / 2;
        const x0 = x(it.data_aplicacao), x1 = x(it.data);
        const vencido = it.dias < 0;
        const c = vencido ? token('--tinta-3') : it.dias <= 30 ? cor(3) : cor(0);

        svg.appendChild(tag('line', { x1: x0, x2: x1, y1: y, y2: y,
                                      stroke: token('--grade'), 'stroke-width': 6,
                                      'stroke-linecap': 'round' }));
        svg.appendChild(tag('line', { x1: x0, x2: Math.min(x(hojeISO), x1), y1: y, y2: y,
                                      stroke: c, 'stroke-width': 6, 'stroke-linecap': 'round',
                                      opacity: .55 }));
        const ponto = tag('circle', { cx: x1, cy: y, r: 6, fill: c, style: 'cursor:pointer' });
        svg.appendChild(ponto);
        svg.appendChild(texto(m.e, y - 11, it.nome, 'eixo-texto'));
        svg.appendChild(texto(L - m.d + 10, y + 4,
                              vencido ? 'vencido' : `${it.dias}d`, 'rotulo-direto',
                              { fill: c }));

        const alvo = tag('rect', { x: x0 - 4, y: y - linhaAlt / 2, width: x1 - x0 + 8,
                                   height: linhaAlt, fill: 'transparent', style: 'cursor:pointer' });
        const mostrar = ev => {
          dica.innerHTML = `<div class="dica-grafico__titulo">${it.nome}</div>` +
            linhaDica(c, 'Vencimento', dataLonga(it.data)) +
            linhaDica('', 'Valor liquido hoje', moeda(it.valor)) +
            linhaDica('', vencido ? 'Venceu ha' : 'Faltam',
                      `${Math.abs(it.dias)} dia${Math.abs(it.dias) === 1 ? '' : 's'}`);
          dica.dataset.visivel = '1';
          const r = host.getBoundingClientRect();
          posicionarDica(dica, host, ev.clientX - r.left, ev.clientY - r.top);
        };
        alvo.addEventListener('pointerenter', mostrar);
        alvo.addEventListener('pointermove', mostrar);
        alvo.addEventListener('pointerleave', () => { dica.dataset.visivel = '0'; });
        svg.appendChild(alvo);
      });

      // marca de "hoje"
      const xh = x(hojeISO);
      svg.appendChild(tag('line', { x1: xh, x2: xh, y1: m.t - 2, y2: A - m.b + 2,
                                    class: 'marca-hoje' }));
      svg.appendChild(texto(xh + 5, m.t + 8, 'hoje', 'marca-hoje-texto'));
    };
    desenhar();
    observar(host, desenhar);
  }

  return { areaEmpilhada, rosca, barrasEmpilhadas, barrasProporcao, linhas, spark, timeline,
           redesenhar, moeda, moeda0, moedaCurta, pct, cor, dataLonga, dataCurta };
})();

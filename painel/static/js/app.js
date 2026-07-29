/* ==========================================================================
   Painel de Investimentos - logica da interface
   ========================================================================== */
'use strict';

const S = {              // estado da aplicacao
  catalogo: null,
  mercado: null,
  carteira: null,
  investimentos: [],
  editando: null,
  cores: {},             // tipo -> slot de cor (estavel, segue a entidade)
  ocultarValores: localStorage.getItem('ocultarValores') === '1',
  ultimaSerie: [],
  ordenacao: { coluna: null, direcao: 1 },
  abortoProjecao: null,  // AbortController da requisicao de projecao em curso
};

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

// ------------------------------------------------------------------ rede --
async function api(rota, opcoes = {}) {
  const r = await fetch(rota, {
    headers: { 'Content-Type': 'application/json' }, ...opcoes,
  });
  const corpo = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(corpo.erro || `Falha na requisicao (${r.status}).`);
  return corpo;
}

let timerAviso;
function avisar(msg, erro = false) {
  const el = $('#aviso');
  el.textContent = msg;
  el.hidden = false;
  el.style.background = erro ? 'var(--critico)' : 'var(--tinta)';
  el.style.color = erro ? '#fff' : 'var(--plano)';
  clearTimeout(timerAviso);
  timerAviso = setTimeout(() => { el.hidden = true; }, erro ? 6000 : 3000);
}

// -------------------------------------------------------------- formatos --
const moeda = G.moeda, moeda0 = G.moeda0, pct = G.pct;
const num = v => (v || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2,
                                                   maximumFractionDigits: 2 });

/** Mascara os digitos de um valor monetario quando o usuario pede privacidade. */
const m = txt => S.ocultarValores ? String(txt).replace(/[0-9]/g, '•') : txt;

const escapar = t => String(t ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Texto curto que descreve como o investimento rende. */
function descreveTaxa(inv) {
  const t = num(inv.taxa);
  switch (inv.indexador) {
    case 'POS_CDI':    return `${t}% do CDI`;
    case 'CDI_MAIS':   return `CDI + ${t}% a.a.`;
    case 'PRE':        return `${t}% a.a. prefixado`;
    case 'IPCA_MAIS':  return `IPCA + ${t}% a.a.`;
    case 'SELIC_MAIS': return `Selic + ${t}% a.a.`;
    case 'POUPANCA':   return 'Regra da poupanca';
    default:           return `${t}%`;
  }
}

// ============================================================== BANCOS ===
/** Selecao de instituicao: lista completa (icone + nome, ordem alfabetica),
    filtravel por digitacao, com "Outro banco" sempre como ultima opcao. Ao
    escolher um banco da lista, o campo grava o nome canonico; ao escolher
    "Outro banco", o campo esvazia para digitacao livre com o icone padrao. */
function iniciarComboBanco() {
  const raiz = $('#combo-banco');
  const input = $('#inp-instituicao');
  const lista = $('#lista-bancos');
  const icoWrap = $('#combo-banco-ico');
  if (!raiz || !input) return;

  let itens = [];
  let ativo = -1;

  function mostrarIcone(banco) {
    icoWrap.innerHTML = Bancos.icone(banco, 18);
    icoWrap.hidden = false;
    input.classList.add('tem-icone');
  }

  function esconderIcone() {
    icoWrap.hidden = true;
    icoWrap.innerHTML = '';
    input.classList.remove('tem-icone');
  }

  /** Icone conforme o texto atual: reconhecido -> selo do banco; digitando
      algo sem correspondencia -> nao presume, so mostra ao selecionar. */
  /** Enquanto ha texto, sempre mostra algum icone: o do banco reconhecido ou,
      na falta de um cadastrado para aquele nome, o icone generico - o mesmo
      criterio usado ao salvar (ver `Bancos.badge`), so que ao vivo. */
  function atualizarIcone() {
    const texto = input.value.trim();
    if (!texto) { esconderIcone(); return; }
    mostrarIcone(Bancos.resolver(texto) || Bancos.OUTRO);
  }

  function fechar() {
    lista.hidden = true;
    lista.innerHTML = '';
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    itens = [];
    ativo = -1;
  }

  function marcarAtivo(i) {
    ativo = i;
    [...lista.children].forEach((li, idx) =>
      li.classList.toggle('combo-banco__item--ativo', idx === ativo));
    if (ativo >= 0) input.setAttribute('aria-activedescendant', `banco-op-${ativo}`);
    else input.removeAttribute('aria-activedescendant');
  }

  function escolher(banco) {
    if (banco.id === 'outro') {
      // "Outro banco" nao e um valor a salvar - e um atalho pra limpar o
      // campo e deixar o usuario digitar o nome, com o icone padrao ja aceso.
      input.value = '';
      mostrarIcone(banco);
    } else {
      input.value = banco.nome;
      mostrarIcone(banco);
    }
    fechar();
    input.focus();
  }

  function abrir() {
    itens = Bancos.buscar(input.value);
    if (!itens.length) {
      lista.innerHTML = '<li class="combo-banco__vazio">Nenhum banco encontrado.</li>';
      lista.hidden = false;
      return;
    }
    lista.innerHTML = itens.map((b, i) => `
      <li class="combo-banco__item${b.id === 'outro' ? ' combo-banco__item--outro' : ''}"
          id="banco-op-${i}" role="option">
        ${Bancos.icone(b, 22)}<span>${escapar(b.nome)}</span>
      </li>`).join('');
    [...lista.children].forEach((li, i) => {
      li.onmousedown = ev => { ev.preventDefault(); escolher(itens[i]); };
    });
    lista.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    marcarAtivo(-1);
  }

  input.addEventListener('input', () => { atualizarIcone(); abrir(); });
  // 'focus' sozinho nao reabre a lista ao clicar de novo num campo que ja
  // estava focado (ex.: logo apos escolher um item) - 'click' cobre esse caso.
  input.addEventListener('focus', abrir);
  input.addEventListener('click', abrir);
  input.addEventListener('keydown', ev => {
    if (lista.hidden && ev.key !== 'Escape') return;
    if (ev.key === 'ArrowDown') { ev.preventDefault(); marcarAtivo(Math.min(ativo + 1, itens.length - 1)); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); marcarAtivo(Math.max(ativo - 1, 0)); }
    else if (ev.key === 'Enter') { if (ativo >= 0) { ev.preventDefault(); escolher(itens[ativo]); } }
    else if (ev.key === 'Escape') { fechar(); }
  });
  document.addEventListener('click', ev => { if (!raiz.contains(ev.target)) fechar(); });

  // exposto para o modal atualizar o selo quando abre em modo edicao/criacao
  raiz._sincronizar = () => { atualizarIcone(); fechar(); };
}

/** Slot de cor fixo por tipo: a cor segue a entidade, nao a posicao no ranking. */
function slotCor(chave) {
  if (!(chave in S.cores)) {
    const usados = new Set(Object.values(S.cores));
    let livre = 0;
    while (usados.has(livre) && livre < 8) livre++;
    S.cores[chave] = livre % 8;
    localStorage.setItem('cores', JSON.stringify(S.cores));
  }
  return S.cores[chave];
}

// ============================================================== MERCADO ===
async function carregarMercado(forcar = false) {
  S.mercado = await api('/api/mercado' + (forcar ? '?atualizar=1' : ''));
  const m = S.mercado;
  const chips = [
    ['Selic meta', pct(m.selic_meta) + ' a.a.'],
    ['CDI', pct(m.cdi_anual) + ' a.a.'],
    ['IPCA 12m', pct(m.ipca_12m)],
    ['Poupanca', pct(m.poupanca_mensal) + ' a.m.'],
    ['Juro real', pct(m.juro_real) + ' a.a.'],
  ];
  $('#taxas').innerHTML = chips.map(([r, v]) => `
    <div class="taxa"><span class="taxa__rotulo">${escapar(r)}</span><span class="taxa__valor">${escapar(v)}</span></div>
  `).join('') + (m.online ? '' : `
    <div class="taxa taxa--offline" title="Sem conexao com o BACEN - usando o ultimo valor conhecido">
      <span class="taxa__rotulo">Fonte</span><span class="taxa__valor">Cache</span></div>`);
}

// ============================================================= CARTEIRA ===
async function carregarCarteira() {
  const [carteira, lista, evo] = await Promise.all([
    api('/api/carteira'), api('/api/investimentos'), api('/api/carteira/evolucao?historico=1'),
  ]);
  S.carteira = carteira;
  S.investimentos = lista;
  S.ultimaSerie = evo.serie;

  renderKpis(carteira.resumo, carteira.metricas, evo.serie);
  renderAlertas(carteira.alertas);
  renderTabela(lista, carteira.resumo);
  renderTimeline(carteira.vencimentos, evo.hoje);

  const fatias = carteira.por_tipo.map(f => ({ ...f, slot: slotCor(f.rotulo) }));
  G.rosca($('#g-alocacao'), fatias, $('#legenda-alocacao'));

  const nomesIndexador = Object.fromEntries(
    Object.entries((S.catalogo || {}).indexadores || {}).map(([k, v]) => [k, v.nome]));
  const porIndexador = carteira.por_indexador.map(f => ({
    ...f, rotulo: nomesIndexador[f.rotulo] || f.rotulo, slot: slotCor('ix:' + f.rotulo),
  }));
  G.barrasProporcao($('#g-indexadores'), porIndexador, $('#legenda-indexadores'));

  G.areaEmpilhada($('#g-evolucao'), { serie: evo.serie, legenda: $('#legenda-evolucao') });
}

function renderKpis(r, metricas = {}, serie = []) {
  if (!r.quantidade) {
    $('#kpis').innerHTML = `
      <div class="kpi"><p class="kpi__rotulo">Comece por aqui</p>
        <div class="kpi__valor kpi__valor--menor">Sem investimentos</div>
        <p class="kpi__nota">Cadastre o primeiro para ver patrimonio, rendimento diario e projecoes.</p>
      </div>`;
    return;
  }
  const classeRend = r.rendimento_liquido >= 0 ? 'ganho' : 'perda';
  const pontosSpark = serie.slice(-24).map(p => p.liquido);
  const cdiTxt = metricas.pct_cdi != null
    ? `<span class="${metricas.pct_cdi >= 100 ? 'ganho' : ''}">${num(metricas.pct_cdi)}% do CDI</span>`
    : '&mdash;';
  const taxaTxt = metricas.taxa_anualizada != null ? pct(metricas.taxa_anualizada) + ' a.a.' : '&mdash;';
  $('#kpis').innerHTML = `
    <article class="kpi kpi--destaque">
      <p class="kpi__rotulo">Patrimonio liquido hoje</p>
      <div class="kpi__linha">
        <div class="kpi__valor kpi__valor--grande">${m(moeda(r.liquido))}</div>
        <div class="kpi__spark" id="kpi-spark"></div>
      </div>
      <p class="kpi__nota">Rende/dia <span class="ganho">${m(moeda(r.rendimento_dia))}</span></p>
    </article>
    <article class="kpi">
      <p class="kpi__rotulo">Total aportado</p>
      <div class="kpi__valor">${m(moeda0(r.aportado ?? r.principal))}</div>
      <p class="kpi__nota">${r.quantidade} investimento${r.quantidade > 1 ? 's' : ''}</p>
    </article>
    <article class="kpi">
      <p class="kpi__rotulo">Rendimento liquido</p>
      <div class="kpi__valor ${classeRend}">${m(moeda(r.rendimento_liquido))}</div>
      <p class="kpi__nota">Rentabilidade liquida <span class="${classeRend}">${pct(r.rentabilidade_liquida)}</span></p>
    </article>
    <article class="kpi" title="Taxa anualizada real da carteira (XIRR), comparada ao CDI do mesmo periodo">
      <p class="kpi__rotulo">Desempenho vs. CDI</p>
      <div class="kpi__valor kpi__valor--menor">${cdiTxt}</div>
      <p class="kpi__nota">Anualizada <strong>${taxaTxt}</strong></p>
    </article>`;
  if (pontosSpark.length >= 2) G.spark($('#kpi-spark'), pontosSpark);
}

function renderAlertas(alertas) {
  $('#alertas').innerHTML = (alertas || []).map(a => `
    <div class="alerta alerta--${a.nivel}">
      <span class="alerta__ico">${a.nivel === 'alerta' ? '&#9888;' : '&#9432;'}</span>
      <span>${escapar(a.texto)}</span>
    </div>`).join('');
}

function renderTimeline(vencimentos, hojeISO) {
  const host = $('#g-vencimentos');
  const secao = $('#secao-vencimentos');
  if (!vencimentos || !vencimentos.length) { secao.hidden = true; return; }
  secao.hidden = false;
  G.timeline(host, vencimentos.map(v => ({ ...v, nome: v.nome })), hojeISO);
}

const COLUNAS = {
  nome: (a, b) => a.nome.localeCompare(b.nome, 'pt-BR'),
  principal: (a, b) => a.posicao.principal - b.posicao.principal,
  bruto: (a, b) => a.posicao.bruto - b.posicao.bruto,
  impostos: (a, b) => (a.posicao.ir + a.posicao.iof) - (b.posicao.ir + b.posicao.iof),
  liquido: (a, b) => a.posicao.liquido - b.posicao.liquido,
  rendimento_dia: (a, b) => a.posicao.rendimento_dia - b.posicao.rendimento_dia,
  rentabilidade: (a, b) =>
    (a.detalhes.taxa_anualizada ?? -Infinity) - (b.detalhes.taxa_anualizada ?? -Infinity),
};

function ordenarLista(lista) {
  const { coluna, direcao } = S.ordenacao;
  if (!coluna || !COLUNAS[coluna]) return lista;
  return [...lista].sort((a, b) => COLUNAS[coluna](a, b) * direcao);
}

function renderTabela(listaBruta, resumo) {
  const lista = ordenarLista(listaBruta);
  const corpo = $('#tabela-investimentos tbody');
  const rodape = $('#tabela-investimentos tfoot');
  $('#vazio-tabela').hidden = lista.length > 0;
  $('#tabela-investimentos').style.display = lista.length ? '' : 'none';

  $$('#tabela-investimentos thead [data-ordenar]').forEach(th => {
    th.classList.toggle('th--asc', S.ordenacao.coluna === th.dataset.ordenar && S.ordenacao.direcao === 1);
    th.classList.toggle('th--desc', S.ordenacao.coluna === th.dataset.ordenar && S.ordenacao.direcao === -1);
  });

  corpo.innerHTML = lista.map(inv => {
    const p = inv.posicao, d = inv.detalhes;
    const cor = G.cor(slotCor(inv.tipo_nome));
    const encerrado = d.encerrado;
    const selos = [
      d.isento_ir ? '<span class="selo selo--isento">isento de IR</span>' : '',
      encerrado ? '<span class="selo selo--encerrado">encerrado</span>' : (
        inv.data_vencimento && d.dias_para_vencer >= 0 && d.dias_para_vencer <= 60
        ? `<span class="selo selo--venc">vence em ${d.dias_para_vencer}d</span>` : ''),
      inv.resgates && inv.resgates.length
        ? `<span class="selo selo--resgate">${inv.resgates.length} resgate${inv.resgates.length > 1 ? 's' : ''}</span>` : '',
    ].filter(Boolean).join(' ');
    const rentab = d.taxa_anualizada != null
      ? `${pct(d.taxa_anualizada)} a.a.${d.pct_cdi != null ? ` &middot; ${num(d.pct_cdi)}% do CDI` : ''}`
      : pct(p.rentabilidade_liquida);
    const infoInst = inv.instituicao
      ? ` &middot; ${Bancos.badge(inv.instituicao, 14)} ${escapar(inv.instituicao)}`
      : '';

    return `<tr data-label-linha="${escapar(inv.nome)}">
      <td data-rotulo="Investimento">
        <div class="celula-nome">
          <span class="ponto" style="background:${cor}"></span>
          <span class="celula-nome__txt">
            <strong>${escapar(inv.nome)}</strong>
            <small>${escapar(inv.tipo_nome)}${infoInst} ${selos}</small>
          </span>
        </div>
      </td>
      <td data-rotulo="Indexador"><small>${descreveTaxa(inv)}</small><br><small style="color:var(--tinta-3)">&asymp; ${pct(d.taxa_anual_equivalente)} a.a.</small></td>
      <td class="num" data-rotulo="Aplicado">${m(moeda0(p.principal))}</td>
      <td class="num" data-rotulo="Bruto hoje">${m(moeda0(p.bruto))}</td>
      <td class="num" data-rotulo="IR + IOF">${p.ir + p.iof > 0 ? m(moeda0(p.ir + p.iof)) : '&mdash;'}</td>
      <td class="num" data-rotulo="Liquido hoje"><strong>${m(moeda(p.liquido))}</strong></td>
      <td class="num ganho" data-rotulo="Rende/dia">${m(moeda(p.rendimento_dia))}</td>
      <td class="num ${(d.taxa_anualizada ?? p.rentabilidade_liquida) >= 0 ? 'ganho' : 'perda'}" data-rotulo="Rentab.">${rentab}</td>
      <td class="acoes">
        <button class="botao botao--mini botao--fantasma" data-editar="${inv.id}">Editar</button>
        <button class="botao botao--mini botao--fantasma botao--perigo" data-excluir="${inv.id}">Excluir</button>
      </td>
    </tr>`;
  }).join('');

  rodape.innerHTML = lista.length ? `
    <tr>
      <td colspan="2">Total</td>
      <td class="num">${m(moeda0(resumo.principal))}</td>
      <td class="num">${m(moeda0(resumo.bruto))}</td>
      <td class="num">${m(moeda0(resumo.ir + resumo.iof))}</td>
      <td class="num">${m(moeda(resumo.liquido))}</td>
      <td class="num ganho">${m(moeda(resumo.rendimento_dia))}</td>
      <td class="num ganho">${pct(resumo.rentabilidade_liquida)}</td>
      <td></td>
    </tr>` : '';

  corpo.querySelectorAll('[data-editar]').forEach(b =>
    b.onclick = () => abrirModal(S.investimentos.find(i => i.id == b.dataset.editar)));
  corpo.querySelectorAll('[data-excluir]').forEach(b =>
    b.onclick = () => excluir(+b.dataset.excluir));
}

// ============================================================= PROJECAO ===
async function carregarProjecao() {
  const anos = $('#sel-anos').value;
  const cenario = $('#sel-cenario') ? $('#sel-cenario').value : 'base';
  const host = $('#g-projecao');
  if (!S.investimentos.length) {
    G.areaEmpilhada(host, { serie: [] });
    $('#g-marcos').dataset.estado = 'vazio';
    return;
  }

  // Uma troca rapida de horizonte nao pode deixar a resposta antiga sobrescrever
  // a mais recente: cancela a requisicao anterior antes de disparar a nova.
  if (S.abortoProjecao) S.abortoProjecao.abort();
  const controlador = new AbortController();
  S.abortoProjecao = controlador;

  host.dataset.estado = 'carregando';
  $('#g-marcos').dataset.estado = 'carregando';
  try {
    const d = await api(`/api/carteira/evolucao?anos=${anos}&cenario=${cenario}`,
                        { signal: controlador.signal });
    if (controlador.signal.aborted) return;

    G.areaEmpilhada(host, { serie: d.serie, hoje: d.hoje, legenda: $('#legenda-projecao') });
    G.barrasEmpilhadas($('#g-marcos'), d.marcos, $('#legenda-marcos'));

    $('#tabela-marcos tbody').innerHTML = d.marcos.map(mc => {
      const juros = mc.liquido - mc.principal;
      const razao = mc.principal ? juros / mc.principal * 100 : 0;
      return `<tr>
        <td>${mc.ano} ano${mc.ano > 1 ? 's' : ''}</td>
        <td>${G.dataLonga(mc.data)}</td>
        <td class="num">${moeda0(mc.principal)}</td>
        <td class="num ganho">${moeda0(juros)}</td>
        <td class="num"><strong>${moeda0(mc.liquido)}</strong></td>
        <td class="num">${pct(razao)}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    if (e.name === 'AbortError') return;
    avisar(e.message, true);
  } finally {
    if (S.abortoProjecao === controlador) S.abortoProjecao = null;
  }
}

// ================================================================ MODAL ===
function preencherTipos() {
  const sel = $('#sel-tipo');
  const grupos = {};
  for (const [k, v] of Object.entries(S.catalogo.tipos)) {
    (grupos[v.grupo] ||= []).push([k, v]);
  }
  sel.innerHTML = Object.entries(grupos).map(([g, itens]) => `
    <optgroup label="${escapar(g)}">
      ${itens.map(([k, v]) => `<option value="${k}">${escapar(v.nome)}</option>`).join('')}
    </optgroup>`).join('');
}

function atualizarIndexadores(manter) {
  const tipo = $('#sel-tipo').value;
  const permitidos = S.catalogo.tipos[tipo].indexadores;
  const sel = $('#sel-indexador');
  sel.innerHTML = permitidos.map(k =>
    `<option value="${k}">${escapar(S.catalogo.indexadores[k].nome)}</option>`).join('');
  if (manter && permitidos.includes(manter)) sel.value = manter;
  atualizarDicaTaxa();
}

function atualizarDicaTaxa() {
  const ix = S.catalogo.indexadores[$('#sel-indexador').value];
  if (!ix) return;
  $('#sufixo-taxa').textContent = ix.unidade;
  $('#dica-taxa').textContent = ix.ajuda;
  const inp = $('#inp-taxa');
  const poupanca = $('#sel-indexador').value === 'POUPANCA';
  inp.disabled = poupanca;
  inp.required = !poupanca;
  inp.max = ix.maximo || '';
  if (poupanca) inp.value = 0;
  else if (!inp.value || +inp.value === 0) inp.value = ix.padrao;
}

function renderResgates(inv) {
  const bloco = $('#bloco-resgates');
  const lista = $('#lista-resgates');
  if (!inv || !inv.id) { bloco.hidden = true; return; }
  bloco.hidden = false;
  const resgates = inv.resgates || [];
  lista.innerHTML = resgates.length ? resgates.map(r => `
    <li class="resgate-item">
      <span>${G.dataLonga(r.data)} &middot; ${r.valor ? moeda(r.valor) : '<strong>total</strong>'}</span>
      <button type="button" class="botao botao--mini botao--fantasma botao--perigo" data-remover-resgate="${r.id}">Remover</button>
    </li>`).join('') : '<li class="resgate-item resgate-item--vazio">Nenhum resgate registrado.</li>';

  lista.querySelectorAll('[data-remover-resgate]').forEach(b => {
    b.onclick = async () => {
      try {
        const atualizado = await api(`/api/investimentos/${inv.id}/resgates/${b.dataset.removerResgate}`,
          { method: 'DELETE' });
        S.editando = atualizado;
        renderResgates(atualizado);
        avisar('Resgate removido.');
        await recarregarTudo();
      } catch (e) { avisar(e.message, true); }
    };
  });
}

async function registrarResgate(ev) {
  ev.preventDefault();
  if (!S.editando || !S.editando.id) return;
  const data = $('#resgate-data').value;
  const valorTxt = $('#resgate-valor').value;
  if (!data) return avisar('Informe a data do resgate.', true);
  try {
    const atualizado = await api(`/api/investimentos/${S.editando.id}/resgates`, {
      method: 'POST',
      body: JSON.stringify({ data, valor: valorTxt ? +valorTxt : null }),
    });
    S.editando = atualizado;
    renderResgates(atualizado);
    $('#resgate-valor').value = '';
    avisar('Resgate registrado.');
    await recarregarTudo();
  } catch (e) { avisar(e.message, true); }
}

function abrirModal(inv = null) {
  S.editando = inv;
  const f = $('#form-investimento');
  f.reset();
  $('#erro-form').hidden = true;
  $('#modal-titulo').textContent = inv ? 'Editar investimento' : 'Novo investimento';
  $('#btn-salvar').textContent = inv ? 'Salvar alteracoes' : 'Cadastrar';

  if (inv) {
    for (const campo of ['nome', 'tipo', 'valor_aplicado', 'aporte_mensal',
                         'data_aplicacao', 'data_vencimento', 'instituicao', 'observacoes']) {
      if (f.elements[campo]) f.elements[campo].value = inv[campo] ?? '';
    }
    atualizarIndexadores(inv.indexador);
    $('#inp-taxa').value = inv.taxa;
    $('#resgate-data').max = new Date().toISOString().slice(0, 10);
    $('#resgate-data').min = inv.data_aplicacao;
    $('#resgate-data').value = new Date().toISOString().slice(0, 10);
  } else {
    f.elements.data_aplicacao.value = new Date().toISOString().slice(0, 10);
    f.elements.aporte_mensal.value = 0;
    atualizarIndexadores();
  }
  const comboBanco = $('#combo-banco');
  if (comboBanco && comboBanco._sincronizar) comboBanco._sincronizar();
  renderResgates(inv);
  $('#modal-investimento').showModal();
  setTimeout(() => f.elements.nome.focus(), 40);
}

async function salvar(ev) {
  ev.preventDefault();
  const f = ev.target;
  const dados = Object.fromEntries(new FormData(f).entries());
  dados.taxa = $('#inp-taxa').disabled ? 0 : dados.taxa;
  const botao = $('#btn-salvar');
  botao.disabled = true;
  try {
    const rota = S.editando ? `/api/investimentos/${S.editando.id}` : '/api/investimentos';
    await api(rota, { method: S.editando ? 'PUT' : 'POST', body: JSON.stringify(dados) });
    $('#modal-investimento').close();
    avisar(S.editando ? 'Investimento atualizado.' : 'Investimento cadastrado.');
    await recarregarTudo();
  } catch (e) {
    const box = $('#erro-form');
    box.textContent = e.message;
    box.hidden = false;
    box.scrollIntoView({ block: 'nearest' });
  } finally {
    botao.disabled = false;
  }
}

async function excluir(id) {
  const inv = S.investimentos.find(i => i.id === id);
  if (!confirm(`Excluir "${inv?.nome}"? Essa acao nao pode ser desfeita.`)) return;
  try {
    await api(`/api/investimentos/${id}`, { method: 'DELETE' });
    avisar('Investimento excluido.');
    await recarregarTudo();
  } catch (e) { avisar(e.message, true); }
}

// ============================================================ SIMULADOR ===
function linhaCenario(pre = {}) {
  const div = document.createElement('div');
  div.className = 'cenario';
  const idx = $('#cenarios').children.length;
  div.innerHTML = `
    <span class="cenario__cor" style="background:${G.cor(idx)}"></span>
    <label class="campo"><span>Produto</span><select class="c-tipo"></select></label>
    <label class="campo"><span>Como rende</span><select class="c-indexador"></select></label>
    <label class="campo"><span>Taxa</span>
      <div class="campo__com-sufixo">
        <input type="number" class="c-taxa" step="0.01" min="0">
        <span class="sufixo c-sufixo"></span>
      </div>
    </label>
    <button type="button" class="botao botao--fantasma botao--icone c-remover" aria-label="Remover">&times;</button>`;

  const selT = div.querySelector('.c-tipo');
  const selI = div.querySelector('.c-indexador');
  const inpX = div.querySelector('.c-taxa');
  const suf  = div.querySelector('.c-sufixo');

  const grupos = {};
  for (const [k, v] of Object.entries(S.catalogo.tipos)) (grupos[v.grupo] ||= []).push([k, v]);
  selT.innerHTML = Object.entries(grupos).map(([g, itens]) => `
    <optgroup label="${escapar(g)}">${itens.map(([k, v]) =>
      `<option value="${k}">${escapar(v.nome)}</option>`).join('')}</optgroup>`).join('');

  const sincronizar = (ixDesejado) => {
    const permitidos = S.catalogo.tipos[selT.value].indexadores;
    selI.innerHTML = permitidos.map(k =>
      `<option value="${k}">${escapar(S.catalogo.indexadores[k].nome)}</option>`).join('');
    if (ixDesejado && permitidos.includes(ixDesejado)) selI.value = ixDesejado;
    const ix = S.catalogo.indexadores[selI.value];
    suf.textContent = ix.unidade;
    inpX.max = ix.maximo || '';
    inpX.disabled = selI.value === 'POUPANCA';
    inpX.value = inpX.disabled ? 0 : (pre.taxa ?? ix.padrao);
    pre.taxa = undefined;
  };

  selT.onchange = () => sincronizar();
  selI.onchange = () => sincronizar(selI.value);
  div.querySelector('.c-remover').onclick = () => { div.remove(); recolorirCenarios(); };

  if (pre.tipo) selT.value = pre.tipo;
  sincronizar(pre.indexador);
  $('#cenarios').appendChild(div);
}

function recolorirCenarios() {
  $$('#cenarios .cenario').forEach((d, i) => {
    d.querySelector('.cenario__cor').style.background = G.cor(i);
  });
}

async function simular(ev) {
  ev?.preventDefault();
  const cenarios = $$('#cenarios .cenario').map(d => {
    const c = {
      tipo: d.querySelector('.c-tipo').value,
      indexador: d.querySelector('.c-indexador').value,
      taxa: +d.querySelector('.c-taxa').value || 0,
    };
    c.nome = `${S.catalogo.tipos[c.tipo].nome} · ${descreveTaxa(c)}`;
    return c;
  });
  if (!cenarios.length) return avisar('Adicione ao menos um produto.', true);

  try {
    const r = await api('/api/simulador', {
      method: 'POST',
      body: JSON.stringify({
        valor_aplicado: +$('#sim-valor').value || 0,
        aporte_mensal: +$('#sim-aporte').value || 0,
        prazo_meses: +$('#sim-prazo').value || 12,
        cenarios,
      }),
    });

    G.linhas($('#g-simulador'),
      r.resultados.map(x => ({ rotulo: x.nome, pontos: x.serie })),
      $('#legenda-simulador'));

    $('#tabela-simulador tbody').innerHTML = r.resultados.map((x, i) => `
      <tr>
        <td><div class="celula-nome">
          <span class="ponto" style="background:${G.cor(i)}"></span>
          <span class="celula-nome__txt"><strong>${escapar(x.tipo_nome)}</strong>
          <small>${x.isento_ir ? 'isento de IR' : 'tributado'}</small></span>
        </div></td>
        <td><small>${descreveTaxa(x)}</small></td>
        <td class="num">${pct(x.taxa_anual_equivalente)} a.a.</td>
        <td class="num">${moeda0(x.final.principal)}</td>
        <td class="num">${moeda0(x.final.bruto)}</td>
        <td class="num">${moeda0(x.final.ir + x.final.iof)}</td>
        <td class="num"><strong>${moeda(x.final.liquido)}</strong></td>
        <td class="num ${i === 0 ? 'ganho' : 'perda'}">${
          i === 0 ? 'melhor' : moeda(x.diferenca_para_melhor)}</td>
      </tr>`).join('');
  } catch (e) { avisar(e.message, true); }
}

async function calcularEquivalencia(ev) {
  ev.preventDefault();
  try {
    const r = await api('/api/equivalencia', {
      method: 'POST',
      body: JSON.stringify({
        percentual_cdi: +$('#eq-cdi').value || 100,
        prazo_meses: +$('#eq-prazo').value || 12,
      }),
    });
    $('#resultado-eq').innerHTML = `
      Em ${r.prazo_meses} meses o IR e de <strong>${pct(r.aliquota_ir)}</strong>.<br>
      Um CDB de <strong>${num(r.percentual_cdi_tributado)}% do CDI</strong> entrega o mesmo liquido que uma
      LCI/LCA de <strong>${num(r.percentual_cdi_isento_equivalente)}% do CDI</strong>.<br>
      <small style="color:var(--tinta-3)">Acima disso, o isento ganha.</small>`;
  } catch (e) { avisar(e.message, true); }
}

// ================================================================= INIT ===
const ABAS = ['carteira', 'projecao', 'simulador', 'ajuda'];

function trocarAba(nome, comHash = true) {
  if (!ABAS.includes(nome)) nome = 'carteira';
  $$('.aba').forEach(b => {
    const ativa = b.dataset.aba === nome;
    b.classList.toggle('aba--ativa', ativa);
    b.setAttribute('aria-selected', ativa);
    b.tabIndex = ativa ? 0 : -1;
  });
  $$('.painel').forEach(p =>
    p.classList.toggle('painel--ativo', p.id === `painel-${nome}`));
  if (comHash) history.replaceState(null, '', '#' + nome);

  if (nome === 'projecao') carregarProjecao();
  // Na primeira visita ao simulador ja mostramos a comparacao pronta.
  if (nome === 'simulador' && !$('#tabela-simulador tbody').innerHTML) simular();
}

/** Navegacao das abas por teclado (setas), como recomenda o padrao ARIA de tabs. */
function iniciarNavegacaoAbas() {
  const abas = $$('.aba');
  abas.forEach((b, i) => {
    b.addEventListener('keydown', ev => {
      const teclas = { ArrowRight: 1, ArrowLeft: -1 };
      if (!(ev.key in teclas)) return;
      ev.preventDefault();
      const prox = abas[(i + teclas[ev.key] + abas.length) % abas.length];
      prox.focus();
      trocarAba(prox.dataset.aba);
    });
  });
}

function aplicarTema(t) {
  if (t) document.documentElement.setAttribute('data-tema', t);
  else document.documentElement.removeAttribute('data-tema');
  localStorage.setItem('tema', t || '');
}

/** Redesenha os graficos ja montados sem refazer nenhuma requisicao de rede. */
function redesenharGraficos() {
  ['#g-evolucao', '#g-alocacao', '#g-indexadores', '#g-vencimentos',
   '#g-projecao', '#g-marcos', '#g-simulador'].forEach(sel => G.redesenhar($(sel)));
}

async function recarregarTudo() {
  await carregarCarteira();
  if ($('#painel-projecao').classList.contains('painel--ativo')) await carregarProjecao();
}

async function iniciar() {
  S.cores = JSON.parse(localStorage.getItem('cores') || '{}');
  const tema = localStorage.getItem('tema');
  if (tema) aplicarTema(tema);
  if (S.ocultarValores) $('#btn-ocultar').textContent = 'Mostrar valores';

  // eventos
  $$('.aba').forEach(b => b.onclick = () => trocarAba(b.dataset.aba));
  iniciarNavegacaoAbas();
  $('#btn-novo').onclick = () => abrirModal();
  $('#btn-fechar').onclick = $('#btn-cancelar').onclick =
    () => $('#modal-investimento').close();
  $('#form-investimento').onsubmit = salvar;
  $('#btn-registrar-resgate').onclick = registrarResgate;
  $('#sel-tipo').onchange = () => atualizarIndexadores();
  $('#sel-indexador').onchange = atualizarDicaTaxa;
  $('#sel-anos').onchange = carregarProjecao;
  if ($('#sel-cenario')) $('#sel-cenario').onchange = carregarProjecao;
  $('#form-simulador').onsubmit = simular;
  $('#btn-add-cenario').onclick = () => { linhaCenario(); recolorirCenarios(); };
  $('#form-equivalencia').onsubmit = calcularEquivalencia;

  // O catalogo de bancos so precisa estar pronto antes do primeiro render
  // que usa selo (tabela de investimentos, mais abaixo) - por isso carrega
  // em paralelo com catalogo/mercado, nao em serie.
  const bancosProntos = Bancos.carregar();
  iniciarComboBanco();

  $$('#tabela-investimentos thead [data-ordenar]').forEach(th => {
    th.tabIndex = 0;
    th.setAttribute('role', 'button');
    const ativar = () => {
      const col = th.dataset.ordenar;
      S.ordenacao = S.ordenacao.coluna === col
        ? { coluna: col, direcao: -S.ordenacao.direcao }
        : { coluna: col, direcao: 1 };
      renderTabela(S.investimentos, S.carteira.resumo);
    };
    th.addEventListener('click', ativar);
    th.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); ativar(); } });
  });

  $('#btn-ocultar').onclick = () => {
    S.ocultarValores = !S.ocultarValores;
    localStorage.setItem('ocultarValores', S.ocultarValores ? '1' : '0');
    $('#btn-ocultar').textContent = S.ocultarValores ? 'Mostrar valores' : 'Ocultar valores';
    if (S.carteira) {
      renderKpis(S.carteira.resumo, S.carteira.metricas, S.ultimaSerie);
      renderTabela(S.investimentos, S.carteira.resumo);
    }
  };

  // A troca de tema so precisa redesenhar o que ja esta na tela - nao ha razao
  // para refazer chamadas de rede so porque as cores do grafico mudaram.
  $('#btn-tema').onclick = () => {
    const atual = document.documentElement.getAttribute('data-tema');
    const escuroAgora = atual === 'escuro' ||
      (!atual && matchMedia('(prefers-color-scheme: dark)').matches);
    aplicarTema(escuroAgora ? 'claro' : 'escuro');
    requestAnimationFrame(redesenharGraficos);
  };

  $('#btn-atualizar').onclick = async () => {
    const b = $('#btn-atualizar');
    b.disabled = true;
    try {
      await carregarMercado(true);
      await recarregarTudo();
      avisar('Taxas atualizadas com o Banco Central.');
    } catch (e) { avisar(e.message, true); }
    finally { b.disabled = false; }
  };

  window.addEventListener('keydown', ev => {
    if (ev.shiftKey && ev.key.toLowerCase() === 'h' &&
        !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
      $('#btn-ocultar').click();
    }
  });

  try {
    S.catalogo = await api('/api/catalogo');
    preencherTipos();
    if ($('#sel-cenario') && S.catalogo.cenarios) {
      $('#sel-cenario').innerHTML = S.catalogo.cenarios
        .map(c => `<option value="${c.chave}">${escapar(c.nome)}</option>`).join('');
    }
    await bancosProntos;   // a tabela abaixo ja desenha o selo de instituicao
    await carregarMercado();
    await carregarCarteira();

    // tres produtos tipicos ja prontos para comparar
    [{ tipo: 'CDB', indexador: 'POS_CDI', taxa: 110 },
     { tipo: 'LCI', indexador: 'POS_CDI', taxa: 95 },
     { tipo: 'TESOURO_SELIC', indexador: 'SELIC_MAIS', taxa: 0.05 }].forEach(p => linhaCenario(p));

    // abre a aba do endereco (#projecao, #simulador, ...)
    trocarAba(location.hash.replace('#', '') || 'carteira', false);
    addEventListener('hashchange', () =>
      trocarAba(location.hash.replace('#', ''), false));
  } catch (e) {
    avisar(e.message, true);
    console.error(e);
  }
}

document.addEventListener('DOMContentLoaded', iniciar);

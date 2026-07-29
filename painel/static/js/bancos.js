/* ==========================================================================
   Bancos - carrega o catalogo de instituicoes (icone local + aliases) e
   oferece busca/selecao para o campo "Instituicao" do formulario.

   Toda a logica aqui e generica: quem decide QUAIS bancos existem e como sao
   os icones e o arquivo `static/dados/bancos.json` (gerado por
   `ferramentas/gerar_icones_bancos.py`). Adicionar um banco novo e so
   acrescentar uma linha nesse gerador e rodar de novo - nada neste arquivo
   precisa mudar.
   ========================================================================== */
'use strict';

const BANCOS_URL = '/static/dados/bancos.json';

let _catalogo = null;   // { bancos: [...], outro: {...} }
let _prontoP = null;

/** minusculas, sem acento, so letras/numeros/espaco - pra comparar texto livre. */
function normalizarBanco(txt) {
  return String(txt || '')
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
}

/** Busca (uma vez) e ordena o catalogo alfabeticamente (locale pt-BR). */
async function carregarBancos() {
  if (_catalogo) return _catalogo;
  if (!_prontoP) {
    _prontoP = fetch(BANCOS_URL)
      .then(r => { if (!r.ok) throw new Error('falha ao carregar bancos.json'); return r.json(); })
      .then(dados => {
        const bancos = [...dados.bancos].sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR'));
        for (const b of bancos) b._chaves = [normalizarBanco(b.nome), ...(b.aliases || []).map(normalizarBanco)];
        _catalogo = { bancos, outro: dados.outro };
        return _catalogo;
      })
      .catch(err => {
        console.error('Bancos: nao foi possivel carregar o catalogo', err);
        // Sem catalogo o campo continua funcionando como texto livre - so
        // sem selo colorido - entao um catalogo vazio e uma degradacao segura.
        _catalogo = { bancos: [], outro: { id: 'outro', nome: 'Outro banco', icone: '' } };
        return _catalogo;
      });
  }
  return _prontoP;
}

function catalogoPronto() {
  return _catalogo || { bancos: [], outro: { id: 'outro', nome: 'Outro banco', icone: '' } };
}

/** Banco cujo nome/alias bate (exato ou por substring) com o texto digitado. */
function resolverBanco(nomeDigitado) {
  const alvo = normalizarBanco(nomeDigitado);
  if (!alvo) return null;
  const { bancos } = catalogoPronto();
  for (const b of bancos) if (b._chaves.includes(alvo)) return b;
  for (const b of bancos) if (b._chaves.some(c => alvo.includes(c) || c.includes(alvo))) return b;
  return null;
}

/** Lista filtrada (alfabetica) + "Outro banco" sempre por ultimo.
    Query vazia devolve o catalogo inteiro - a lista e pra ser navegavel. */
function buscarBancos(query) {
  const { bancos, outro } = catalogoPronto();
  const alvo = normalizarBanco(query);
  const filtrados = !alvo ? bancos : bancos.filter(b => b._chaves.some(c => c.includes(alvo)));
  return [...filtrados, outro];
}

function iconeHtml(banco, tamanho = 18) {
  if (!banco || !banco.icone) return '';
  const alt = String(banco.nome || '').replace(/"/g, '&quot;');
  return `<img class="banco-ico" src="/static/${banco.icone}" width="${tamanho}" height="${tamanho}" ` +
    `alt="" title="${alt}" loading="lazy">`;
}

/** Selo pronto para um texto de instituicao livre (o que fica salvo no BD):
    icone do banco reconhecido, ou o icone generico "Outro banco". */
function badgeInstituicaoHtml(nomeDigitado, tamanho = 18) {
  const achado = resolverBanco(nomeDigitado) || catalogoPronto().outro;
  return iconeHtml(achado, tamanho);
}

window.Bancos = {
  carregar: carregarBancos,
  get LISTA() { return catalogoPronto().bancos; },
  get OUTRO() { return catalogoPronto().outro; },
  resolver: resolverBanco,
  buscar: buscarBancos,
  icone: iconeHtml,
  badge: badgeInstituicaoHtml,
};

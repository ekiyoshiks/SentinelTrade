'use strict';
/* SentinelTrade — dashboard (sem dependências externas). Todo texto dinâmico passa por esc(). */

// ───────────────────────────── utilidades ─────────────────────────────
const $ = (s, r = document) => r.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const brl = v => v == null ? '—' : Number(v).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const num = v => v == null ? '—' : Number(v).toLocaleString('pt-BR');
const hora = iso => iso ? new Date(/Z|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z').toLocaleString('pt-BR') : '—';
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));
const ROTULO = { MERCADO: 'Mercado', LIMITADA: 'Limitada', COMPRA: 'Compra', VENDA: 'Venda' };
const ESTADOS = ['CRIADA', 'VALIDADA', 'ENVIADA', 'PARCIALMENTE_EXECUTADA', 'EXECUTADA', 'REJEITADA', 'CANCELADA', 'FALHA', 'INTERVENCAO_MANUAL'];
const ALTERAVEIS = ['VALIDADA', 'ENVIADA', 'PARCIALMENTE_EXECUTADA'];
const nomeEstado = e => String(e).replaceAll('_', ' ').toLowerCase().replace(/^./, c => c.toUpperCase()).replace('Intervencao', 'Intervenção').replace('Notificacao', 'Notificação');
const pill = e => `<span class="pill p-${esc(e)}">${esc(nomeEstado(e))}</span>`;

async function api(caminho, { method = 'GET', body, headers = {} } = {}) {
  const r = await fetch('/api' + caminho, {
    method, credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...headers }, body: body ? JSON.stringify(body) : undefined,
  });
  const texto = await r.text();
  let dados = null; try { dados = texto ? JSON.parse(texto) : null; } catch { /* resposta não-JSON */ }
  if (!r.ok) {
    const e = dados?.erro || { mensagem: 'Falha na requisição.' };
    const campos = e.detalhes?.campos ? ' (' + e.detalhes.campos.map(c => c.campo + ': ' + c.motivo).join('; ') + ')' : '';
    const err = new Error(e.mensagem + campos); err.codigo = e.codigo; err.status = r.status; err.detalhes = e.detalhes;
    if (r.status === 401 && e.codigo !== 'AUTENTICACAO' && e.codigo !== 'MFA_INVALIDO' && e.codigo !== 'MFA_EXPIRADO') sessaoExpirou();
    throw err;
  }
  return dados;
}
function toast(msg, tipo = '') {
  const el = document.createElement('div'); el.className = 'toast ' + tipo; el.textContent = msg;
  $('#toasts').appendChild(el); setTimeout(() => el.remove(), tipo === 'erro' ? 7000 : 4200);
}
const falha = e => toast(e.message || 'Erro inesperado.', 'erro');
function abrirModal(html) { const m = $('#modal'); m.innerHTML = `<div class="modal-box">${html}</div>`; m.hidden = false; }
function fecharModal() { $('#modal').hidden = true; $('#modal').innerHTML = ''; }
document.addEventListener('click', e => { if (e.target.closest('[data-fechar]') || e.target.id === 'modal') fecharModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') fecharModal(); });

// ───────────────────────────── estado global ─────────────────────────────
const S = { usuario: null, view: null, timer: null, hist: {}, saude: null };

function sessaoExpirou() { if (S.usuario) { S.usuario = null; toast('Sessão encerrada. Faça login novamente.', 'aviso'); renderLogin(); } }

// ───────────────────────────── login (CSU01) ─────────────────────────────
const LOGO = `<svg viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#0b1220" stroke="#23314f"/><path d="M16 5l9 4v7c0 5.5-3.8 9.3-9 11-5.2-1.7-9-5.5-9-11V9z" fill="none" stroke="#38bdf8" stroke-width="2.2"/><path d="M11 17l3.5 3.5L21 13" fill="none" stroke="#34d399" stroke-width="2.4"/></svg>`;

function renderLogin(etapa = 'senha', ctx = {}) {
  clearInterval(S.timer);
  const demo = ['ana', 'bruno', 'carla', 'operador', 'admin', 'auditor'];
  $('#app').innerHTML = `<div class="login-wrap"><div class="login-card">
    <div class="marca">${LOGO}<div><b>SentinelTrade</b><span>Orion Capital · ambiente simulado</span></div></div>
    ${etapa === 'senha' ? `
      <form id="f-login" autocomplete="off">
        <label>Usuário<input name="login" required maxlength="60" autofocus></label>
        <label>Senha<input name="senha" type="password" required maxlength="200"></label>
        <button class="btn">Continuar</button>
      </form>
      <div class="demo-users">Usuários de demonstração: ${demo.map(u => `<code data-demo="${u}">${u}</code>`).join(' ')}<br>Senha de demonstração: veja o README (<code>Orion@Demo2026</code>).</div>`
    : `
      <form id="f-mfa" autocomplete="off">
        <label>Código de verificação (6 dígitos)<input name="codigo" inputmode="numeric" pattern="\\d{6}" maxlength="6" required autofocus class="mono"></label>
        <button class="btn">Entrar</button>
        <div class="linha"><button type="button" class="btn sec mini" id="b-reenviar">Reenviar código</button>
        <button type="button" class="btn sec mini" id="b-voltar">Voltar</button></div>
      </form>
      <div class="simulador-mfa"><div class="suave">📱 Segundo fator simulado — este é o “celular” (válido por ${ctx.validade || 60} s):</div>
        <div class="cod mono" id="cod-sim">······</div>
        <div class="suave centro" id="cod-info"></div></div>`}
  </div></div>`;
  if (etapa === 'senha') {
    document.querySelectorAll('[data-demo]').forEach(el => el.onclick = () => { $('#f-login [name=login]').value = el.dataset.demo; $('#f-login [name=senha]').focus(); });
    $('#f-login').onsubmit = async ev => {
      ev.preventDefault(); const f = new FormData(ev.target);
      try {
        const d = await api('/auth/login', { method: 'POST', body: { login: f.get('login'), senha: f.get('senha') } });
        renderLogin('mfa', { login: f.get('login'), desafio: d.desafio_id, validade: d.validade_segundos });
      } catch (e) { falha(e); }
    };
  } else {
    const mostrarCodigo = async () => {
      try {
        const r = await api('/simulador/codigo-mfa/' + encodeURIComponent(ctx.login));
        $('#cod-sim').textContent = r.codigo || '······';
        $('#cod-info').textContent = r.codigo ? 'Digite este código ao lado.' : '';
      } catch { $('#cod-sim').textContent = '······'; $('#cod-info').textContent = 'Simulador desativado: use o código recebido.'; }
    };
    mostrarCodigo();
    $('#f-mfa').onsubmit = async ev => {
      ev.preventDefault();
      try {
        const d = await api('/auth/mfa', { method: 'POST', body: { desafio_id: ctx.desafio, codigo: new FormData(ev.target).get('codigo').trim() } });
        S.usuario = d.usuario; renderShell();
      } catch (e) { falha(e); if (e.codigo === 'MFA_EXPIRADO') mostrarCodigo(); if (e.codigo === 'RN11') renderLogin(); }
    };
    $('#b-reenviar').onclick = async () => {
      try { await api('/auth/mfa/reenviar', { method: 'POST', body: { desafio_id: ctx.desafio } }); toast('Novo código emitido.', 'ok'); mostrarCodigo(); } catch (e) { falha(e); }
    };
    $('#b-voltar').onclick = () => renderLogin();
  }
}

// ───────────────────────────── casca (menu por perfil) ─────────────────────────────
const MENUS = {
  INVESTIDOR: [['mercado', 'Mercado e ordens'], ['carteira', 'Carteira'], ['ordens', 'Minhas ordens'], ['notificacoes', 'Notificações']],
  OPERADOR_RISCO: [['painel', 'Painel'], ['problemas', 'Ordens com problema'], ['ordens', 'Todas as ordens'], ['limites', 'Limites de risco'], ['suspensao', 'Indisponibilidade segura'], ['simulacao', 'Simulação de falhas'], ['notificacoes', 'Notificações']],
  ADMINISTRADOR: [['painel', 'Painel'], ['investidores', 'Investidores e contas'], ['ativos', 'Ativos'], ['usuarios', 'Perfis de acesso'], ['ordens', 'Todas as ordens']],
  AUDITOR: [['painel', 'Painel'], ['auditoria', 'Registros de auditoria'], ['ordens', 'Todas as ordens']],
};

function renderShell() {
  const u = S.usuario, menu = MENUS[u.perfil] || [];
  $('#app').innerHTML = `<div class="shell">
    <aside class="lado"><div class="marca">${LOGO}<div><b>SentinelTrade</b><span>Orion Capital</span></div></div>
      ${menu.map(([id, nome]) => `<button class="nav" data-nav="${id}"><span class="t">${esc(nome)}</span></button>`).join('')}
      <div class="usuario"><b>${esc(u.login)}</b><div class="suave">${esc(u.nome_perfil)}</div>
        <button class="btn sec mini" id="b-sair" style="margin-top:8px">Sair</button></div></aside>
    <main class="principal"><div class="topo"><h2 id="titulo"></h2><div class="chips" id="chips"></div></div>
      <div id="faixa"></div><div id="conteudo"></div></main></div>`;
  document.querySelectorAll('[data-nav]').forEach(b => b.onclick = () => abrirView(b.dataset.nav));
  $('#b-sair').onclick = async () => { try { await api('/auth/logout', { method: 'POST' }); } catch { } S.usuario = null; renderLogin(); };
  abrirView(menu[0][0]);
  clearInterval(S.timer);
  S.timer = setInterval(ciclo, 2000); ciclo();
}

async function ciclo() {
  if (document.hidden || !S.usuario) return;
  try {
    S.saude = await api('/saude');
    $('#faixa').innerHTML = S.saude.novas_ordens_suspensas
      ? `<div class="faixa-alerta">⛔ <b>Indisponibilidade segura ativa:</b> novas ordens estão temporariamente suspensas. Consultas e cancelamentos continuam disponíveis.</div>` : '';
    await S.view?.update?.($('#conteudo'));
  } catch (e) { if (e.status !== 401) console.warn(e); }
}

function abrirView(id) {
  const v = VIEWS[id]; if (!v) return;
  S.view = v; S.viewId = id;
  document.querySelectorAll('[data-nav]').forEach(b => b.classList.toggle('ativo', b.dataset.nav === id));
  $('#titulo').textContent = v.titulo;
  const el = $('#conteudo'); el.innerHTML = ''; el.onclick = null; el.onsubmit = null;
  v.mount(el); v.update?.(el);
}

// ───────────────────────────── componentes ─────────────────────────────
function spark(valores) {
  if (!valores || valores.length < 2) return '';
  const min = Math.min(...valores), max = Math.max(...valores), w = 84, h = 22, d = max - min || 1;
  const pts = valores.map((v, i) => `${(i / (valores.length - 1) * w).toFixed(1)},${(h - 2 - (v - min) / d * (h - 4)).toFixed(1)}`).join(' ');
  const cor = valores.at(-1) >= valores[0] ? '#34d399' : '#f87171';
  return `<svg class="spark" viewBox="0 0 ${w} ${h}"><polyline points="${pts}" fill="none" stroke="${cor}" stroke-width="1.6"/></svg>`;
}
const kpi = (t, v, s = '') => `<div class="card kpi"><h3>${esc(t)}</h3><div class="v">${v}</div><div class="s">${s}</div></div>`;
function tabela(cols, linhas, vazio = 'Nada para mostrar.') {
  if (!linhas.length) return `<div class="vazio">${esc(vazio)}</div>`;
  return `<div class="tabela-wrap"><table><thead><tr>${cols.map(c => `<th class="${c.dir ? 'dir' : ''}">${esc(c.t)}</th>`).join('')}</tr></thead>
    <tbody>${linhas.join('')}</tbody></table></div>`;
}
const set = (sel, html) => { const el = $(sel); if (el && el.innerHTML !== html) el.innerHTML = html; };

function tabelaOrdens(ordens, { acoes = false, investidor = false, detalhe = false } = {}) {
  const cols = [{ t: 'Ordem' }, ...(investidor ? [{ t: 'Investidor' }] : []), { t: 'Ativo' }, { t: 'Lado' }, { t: 'Tipo' },
    { t: 'Qtd (exec./total)', dir: 1 }, { t: 'Preço', dir: 1 }, { t: 'Estado' }, { t: 'Atualizada' }, ...(acoes ? [{ t: '' }] : [])];
  const linhas = ordens.map(o => `<tr class="${detalhe ? 'clicavel' : ''}" data-ordem="${esc(o.id)}">
    <td class="mono">${esc(o.id)}</td>${investidor ? `<td>#${esc(o.investidor_id)}</td>` : ''}<td><b>${esc(o.ativo)}</b></td>
    <td class="lado-${o.lado === 'COMPRA' ? 'compra' : 'venda'}">${esc(ROTULO[o.lado])}</td><td>${esc(ROTULO[o.modalidade])}</td>
    <td class="dir">${num(o.quantidade_executada)} / ${num(o.quantidade)}</td>
    <td class="dir">${o.preco_limite ? brl(o.preco_limite) : (o.preco_medio_execucao ? '~' + brl(o.preco_medio_execucao) : 'a mercado')}</td>
    <td>${pill(o.estado)}${o.cancelamento_pendente ? ' <span class="pill p-PENDENTE">cancel. pendente</span>' : ''}</td>
    <td class="suave">${hora(o.atualizado_em)}</td>
    ${acoes ? `<td><div class="acoes">${ALTERAVEIS.includes(o.estado)
      ? `<button class="btn sec mini" data-act="alterar" data-id="${esc(o.id)}">Alterar</button><button class="btn verm mini" data-act="cancelar" data-id="${esc(o.id)}">Cancelar</button>` : ''}</div></td>` : ''}</tr>`);
  return tabela(cols, linhas, 'Nenhuma ordem encontrada.');
}

async function detalheOrdem(id) {
  try {
    const o = await api('/ordens/' + encodeURIComponent(id));
    abrirModal(`<header><h3>Ordem <span class="mono">${esc(o.id)}</span></h3>${pill(o.estado)}<button class="btn sec mini x" data-fechar>Fechar</button></header>
      <dl class="kv"><dt>Ativo</dt><dd>${esc(o.ativo)} · ${esc(ROTULO[o.lado])} · ${esc(ROTULO[o.modalidade])}</dd>
      <dt>Quantidade</dt><dd>${num(o.quantidade_executada)} executadas de ${num(o.quantidade)}</dd>
      <dt>Preço</dt><dd>${o.preco_limite ? brl(o.preco_limite) : 'a mercado'}${o.preco_medio_execucao ? ' · médio executado ' + brl(o.preco_medio_execucao) : ''}</dd>
      <dt>Valor estimado</dt><dd>${brl(o.valor_estimado)}</dd>
      <dt>Tentativas</dt><dd>${esc(o.tentativas)}</dd>
      <dt>Chave de idempotência</dt><dd class="mono">${esc(o.chave_idempotencia)}</dd>
      <dt>Correlação</dt><dd class="mono">${esc(o.correlacao_id)}</dd>
      ${o.motivo_rejeicao ? `<dt>Motivo</dt><dd class="neg">${esc(o.motivo_rejeicao)}</dd>` : ''}</dl>
      <h3 style="margin:16px 0 8px">Histórico de estados</h3>
      <div class="linha-tempo">${o.historico.map(h => `<div class="ev"><div>${h.de ? esc(nomeEstado(h.de)) + ' → ' : ''}<b>${esc(nomeEstado(h.para))}</b>
        ${h.evento !== 'ESTADO' ? `<span class="suave">(${esc(h.evento.toLowerCase())})</span>` : ''}</div><div class="suave">${hora(h.em)}${h.motivo ? ' · ' + esc(h.motivo) : ''}</div></div>`).join('')}</div>
      ${o.operacoes.length ? `<h3 style="margin:16px 0 8px">Execuções</h3>${tabela([{ t: 'Quantidade', dir: 1 }, { t: 'Preço', dir: 1 }, { t: 'Quando' }],
        o.operacoes.map(x => `<tr><td class="dir">${num(x.quantidade)}</td><td class="dir">${brl(x.preco)}</td><td>${hora(x.em)}</td></tr>`))}` : ''}`);
  } catch (e) { falha(e); }
}

async function modalAlterar(id) {
  try {
    const o = await api('/ordens/' + encodeURIComponent(id));
    abrirModal(`<header><h3>Alterar ordem <span class="mono">${esc(o.id)}</span></h3><button class="btn sec mini x" data-fechar>Fechar</button></header>
      <form id="f-alterar" class="grade"><label>Quantidade (executadas: ${num(o.quantidade_executada)})<input name="quantidade" type="number" min="1" step="1" value="${esc(o.quantidade)}"></label>
      ${o.modalidade === 'LIMITADA' ? `<label>Preço limite<input name="preco" type="number" min="0.01" step="0.01" value="${esc(o.preco_limite)}"></label>` : '<div class="suave">Ordem a mercado: só a quantidade pode mudar.</div>'}
      <button class="btn">Salvar alteração</button><div id="r-alterar"></div></form>`);
    $('#f-alterar').onsubmit = async ev => {
      ev.preventDefault(); const f = new FormData(ev.target); const corpo = { quantidade: Number(f.get('quantidade')) };
      if (f.get('preco')) corpo.preco = Number(f.get('preco'));
      try { await api('/ordens/' + encodeURIComponent(id), { method: 'PATCH', body: corpo }); toast('Ordem alterada.', 'ok'); fecharModal(); S.view?.update?.($('#conteudo')); }
      catch (e) { $('#r-alterar').innerHTML = `<div class="msg-form erro">${esc(e.message)}</div>`; }
    };
  } catch (e) { falha(e); }
}

async function modalCancelar(id) {
  try {
    const o = await api('/ordens/' + encodeURIComponent(id));
    abrirModal(`<header><h3>Cancelar ordem <span class="mono">${esc(o.id)}</span></h3><button class="btn sec mini x" data-fechar>Fechar</button></header>
      <p>${esc(o.ativo)} · ${esc(ROTULO[o.lado])} · ${num(o.quantidade)} unidades.</p>
      ${o.quantidade_executada ? `<p class="defasada">Parte já executada: <b>${num(o.quantidade_executada)}</b> unidades. Somente o restante será cancelado.</p>` : ''}
      <div class="linha"><button class="btn verm" id="b-conf">Confirmar cancelamento</button><button class="btn sec" data-fechar>Voltar</button></div>`);
    $('#b-conf').onclick = async () => {
      try {
        const r = await api('/ordens/' + encodeURIComponent(id) + '/cancelar', { method: 'POST' });
        toast(r.aviso || 'Ordem cancelada.', r.aviso ? 'aviso' : 'ok'); fecharModal(); S.view?.update?.($('#conteudo'));
      } catch (e) { falha(e); fecharModal(); }
    };
  } catch (e) { falha(e); }
}

// ações comuns da tabela de ordens
function ligarAcoesOrdens(el) {
  el.addEventListener('click', ev => {
    const b = ev.target.closest('[data-act]');
    if (b?.dataset.act === 'alterar') return modalAlterar(b.dataset.id);
    if (b?.dataset.act === 'cancelar') return modalCancelar(b.dataset.id);
    const tr = ev.target.closest('tr[data-ordem]');
    if (tr && tr.classList.contains('clicavel')) detalheOrdem(tr.dataset.ordem);
  });
}

// ───────────────────────────── visões ─────────────────────────────
const VIEWS = {};

// ---- Investidor: mercado e ordens (CSU02, CSU04) ----
VIEWS.mercado = {
  titulo: 'Mercado e ordens',
  mount(el) {
    el.innerHTML = `<div class="grade g2">
      <div class="card"><h3>Cotações <span class="suave" style="text-transform:none;letter-spacing:0">clique em um ativo para preencher a ordem</span></h3><div id="cot"></div></div>
      <div class="card"><h3>Nova ordem</h3>
        <form id="f-ordem" class="grade"><label>Ativo<select name="ativo"></select></label>
          <div class="linha"><label style="flex:1">Lado<select name="lado"><option value="COMPRA">Compra</option><option value="VENDA">Venda</option></select></label>
          <label style="flex:1">Tipo<select name="modalidade"><option value="MERCADO">A mercado</option><option value="LIMITADA">Limitada</option></select></label></div>
          <div class="linha"><label style="flex:1">Quantidade<input name="quantidade" type="number" min="1" step="1" required value="100"></label>
          <label style="flex:1">Preço limite<input name="preco" type="number" min="0.01" step="0.01" disabled placeholder="a mercado"></label></div>
          <div class="suave" id="resumo">—</div>
          <button class="btn" id="b-enviar">Enviar ordem</button><div id="r-ordem"></div></form></div></div>`;
    const f = $('#f-ordem'); f.dataset.key = uuid();
    const atualizarResumo = () => {
      const q = Number(f.quantidade.value) || 0, c = (S.cotacoes || []).find(x => x.codigo === f.ativo.value);
      const p = f.modalidade.value === 'LIMITADA' && f.preco.value ? Number(f.preco.value) : (c?.preco ? Number(c.preco) : null);
      $('#resumo').textContent = p ? `Valor total estimado: ${brl(p * q)}` : 'Sem cotação de referência.';
    };
    f.modalidade.onchange = () => { f.preco.disabled = f.modalidade.value !== 'LIMITADA'; f.preco.required = !f.preco.disabled; if (f.preco.disabled) f.preco.value = ''; atualizarResumo(); };
    ['input', 'change'].forEach(t => f.addEventListener(t, atualizarResumo));
    f.onsubmit = async ev => {
      ev.preventDefault();
      const corpo = { ativo: f.ativo.value, lado: f.lado.value, modalidade: f.modalidade.value, quantidade: Number(f.quantidade.value) };
      if (f.modalidade.value === 'LIMITADA') corpo.preco = Number(f.preco.value);
      $('#b-enviar').disabled = true;
      try {
        // a mesma chave acompanha reenvios do mesmo formulário (RN08): clique duplo não gera duas ordens
        const o = await api('/ordens', { method: 'POST', body: corpo, headers: { 'Idempotency-Key': f.dataset.key } });
        const rej = o.estado === 'REJEITADA';
        $('#r-ordem').innerHTML = `<div class="msg-form ${rej ? 'erro' : 'ok'}">${rej ? 'Ordem rejeitada: ' + esc(o.motivo_rejeicao) : (o.duplicada ? 'Repetição detectada — esta é a ordem original ' : 'Ordem aceita ')}<b class="mono">${esc(o.id)}</b> ${pill(o.estado)}</div>`;
        f.dataset.key = uuid();
      } catch (e) { $('#r-ordem').innerHTML = `<div class="msg-form erro">${esc(e.message)}</div>`; if (e.status && e.status < 500) f.dataset.key = uuid(); }
      finally { $('#b-enviar').disabled = false; }
    };
    $('#cot').onclick = ev => {
      const tr = ev.target.closest('tr[data-codigo]'); if (!tr) return;
      f.ativo.value = tr.dataset.codigo; if (f.modalidade.value === 'LIMITADA') f.preco.value = tr.dataset.preco; atualizarResumo();
    };
  },
  async update() {
    const cot = await api('/cotacoes'); S.cotacoes = cot;
    const sel = $('#f-ordem [name=ativo]');
    if (sel && sel.options.length !== cot.length) { const atual = sel.value; sel.innerHTML = cot.map(c => `<option value="${esc(c.codigo)}">${esc(c.codigo)} — ${esc(c.nome)}</option>`).join(''); if (atual) sel.value = atual; }
    cot.forEach(c => { if (c.preco) { const h = S.hist[c.codigo] ||= []; if (h.at(-1) !== Number(c.preco) || h.length < 2) h.push(Number(c.preco)); if (h.length > 40) h.shift(); } });
    set('#cot', tabela([{ t: 'Ativo' }, { t: 'Tipo' }, { t: 'Preço', dir: 1 }, { t: 'Variação', dir: 1 }, { t: 'Volume', dir: 1 }, { t: 'Lote', dir: 1 }, { t: '' }, { t: 'Atualizada' }],
      cot.map(c => `<tr class="clicavel" data-codigo="${esc(c.codigo)}" data-preco="${esc(c.preco ?? '')}"><td><b>${esc(c.codigo)}</b> <span class="suave">${esc(c.nome)}</span></td><td>${esc(c.tipo)}</td>
        <td class="dir">${brl(c.preco)}</td><td class="dir ${Number(c.variacao) >= 0 ? 'pos' : 'neg'}">${c.variacao == null ? '—' : (Number(c.variacao) >= 0 ? '+' : '') + c.variacao + '%'}</td>
        <td class="dir">${num(c.volume)}</td><td class="dir">${num(c.lote_padrao)}</td><td>${spark(S.hist[c.codigo])}</td>
        <td class="${c.defasada ? 'defasada' : 'suave'}">${c.defasada ? '⚠ defasada · ' : ''}${c.atualizada_em ? hora(c.atualizada_em).split(' ')[1] : 'sem dados'}${c.situacao === 'SUSPENSO' ? ' · <b class="neg">suspenso</b>' : ''}</td></tr>`)));
    const ch = cot.some(c => c.defasada);
    set('#chips', `<span class="chip"><span class="dot ${ch ? 'amar' : ''}"></span>Cotações ${ch ? 'defasadas' : 'em dia'}</span>`);
  },
};

// ---- Investidor: carteira (CSU03) ----
VIEWS.carteira = {
  titulo: 'Carteira',
  mount(el) { el.innerHTML = `<div class="grade g4" id="kpis"></div><div class="card" style="margin-top:14px"><h3>Posições</h3><div id="pos"></div></div>`; },
  async update() {
    const c = await api('/carteira');
    set('#kpis', kpi('Saldo em conta', brl(c.saldo)) + kpi('Reservado em ordens', brl(c.reservado), 'bloqueado até execução/cancelamento') +
      kpi('Disponível', brl(c.disponivel)) + kpi('Patrimônio', brl(c.patrimonio), `posições: ${brl(c.valor_posicoes)} · resultado <span class="${Number(c.resultado_total) >= 0 ? 'pos' : 'neg'}">${brl(c.resultado_total)}</span>`));
    set('#pos', tabela([{ t: 'Ativo' }, { t: 'Quantidade', dir: 1 }, { t: 'Reservada', dir: 1 }, { t: 'Disponível', dir: 1 }, { t: 'Preço médio', dir: 1 }, { t: 'Preço atual', dir: 1 }, { t: 'Valor', dir: 1 }, { t: 'Resultado', dir: 1 }],
      c.posicoes.map(p => `<tr><td><b>${esc(p.ativo)}</b></td><td class="dir">${num(p.quantidade)}</td><td class="dir">${num(p.reservada)}</td><td class="dir">${num(p.disponivel)}</td>
        <td class="dir">${brl(p.preco_medio)}</td><td class="dir">${brl(p.preco_atual)}</td><td class="dir">${brl(p.valor_atual)}</td><td class="dir ${Number(p.resultado) >= 0 ? 'pos' : 'neg'}">${brl(p.resultado)}</td></tr>`), 'Carteira vazia.'));
  },
};

// ---- ordens: investidor (CSU05/06/07/08) e perfis internos (somente leitura) ----
VIEWS.ordens = {
  get titulo() { return S.usuario.perfil === 'INVESTIDOR' ? 'Minhas ordens' : 'Todas as ordens'; },
  mount(el) {
    el.innerHTML = `<div class="card"><div class="linha" style="margin-bottom:12px">
      <label>Estado<select id="fo-estado"><option value="">Todos</option>${ESTADOS.map(e => `<option value="${e}">${esc(nomeEstado(e))}</option>`).join('')}</select></label>
      <label>Ativo<input id="fo-ativo" placeholder="ex.: PETR4" maxlength="12" style="width:120px"></label>
      <label>De<input id="fo-desde" type="date"></label><label>Até<input id="fo-ate" type="date"></label></div><div id="lista-ordens"></div></div>`;
    ligarAcoesOrdens(el);
    ['fo-estado', 'fo-ativo', 'fo-desde', 'fo-ate'].forEach(id => $('#' + id).addEventListener('change', () => this.update()));
  },
  async update() {
    const q = new URLSearchParams(); const g = id => $('#' + id)?.value;
    if (g('fo-estado')) q.set('estado', g('fo-estado')); if (g('fo-ativo')) q.set('ativo', g('fo-ativo').toUpperCase());
    if (g('fo-desde')) q.set('desde', g('fo-desde') + 'T00:00:00'); if (g('fo-ate')) q.set('ate', g('fo-ate') + 'T23:59:59');
    const o = await api('/ordens?' + q);
    const inv = S.usuario.perfil === 'INVESTIDOR';
    set('#lista-ordens', tabelaOrdens(o, { acoes: inv, investidor: !inv, detalhe: inv }));
  },
};

VIEWS.notificacoes = {
  titulo: 'Notificações',
  mount(el) { el.innerHTML = `<div class="card"><div id="not"></div></div>`; },
  async update() {
    const n = await api('/notificacoes');
    set('#not', tabela([{ t: 'Quando' }, { t: 'Tipo' }, { t: 'Mensagem' }, { t: 'Entrega' }],
      n.map(x => `<tr><td class="suave">${hora(x.criado_em)}</td><td><span class="pill p-${/REJEIT|FALHA|INTERV|INCONS|AUTOMATICA/.test(x.tipo) ? 'REJEITADA' : 'ENVIADA'}">${esc(nomeEstado(x.tipo))}</span></td>
        <td style="white-space:normal">${esc(x.mensagem)}</td><td>${x.entregue ? '<span class="pos">entregue</span>' : '<span class="defasada">na fila</span>'}</td></tr>`), 'Sem notificações.'));
  },
};

// ---- painel (operador, administrador, auditor) ----
VIEWS.painel = {
  titulo: 'Painel operacional',
  mount(el) {
    el.innerHTML = `<div class="grade g4" id="p-kpis"></div>
      <div class="grade g2" style="margin-top:14px"><div class="card"><h3>Ordens por estado</h3><div class="barras" id="p-barras"></div></div>
      <div class="card"><h3>Infraestrutura</h3><div id="p-infra" class="grade"></div></div></div>
      <div class="card" style="margin-top:14px"><h3>Suspensões ativas</h3><div id="p-susp"></div></div>`;
  },
  async update() {
    const p = await api('/painel');
    set('#p-kpis', kpi('Ordens registradas', num(p.total_ordens)) + kpi('Com problema', `<span class="${p.ordens_com_problema ? 'neg' : 'pos'}">${num(p.ordens_com_problema)}</span>`, 'em Falha ou Intervenção Manual') +
      kpi('Volume executado hoje', brl(p.volume_executado_hoje)) + kpi('Saldo / reservado', brl(p.saldo_total), 'reservado: ' + brl(p.reservado_total)));
    const max = Math.max(1, ...Object.values(p.ordens_por_estado));
    set('#p-barras', Object.entries(p.ordens_por_estado).map(([e, n]) => `<div class="barra"><span>${esc(nomeEstado(e))}</span><div class="trilho"><div class="preench" style="width:${n / max * 100}%;${/REJEIT|FALHA|INTERV/.test(e) ? 'background:var(--verm)' : e === 'EXECUTADA' ? 'background:var(--verde)' : ''}"></div></div><b>${n}</b></div>`).join(''));
    const i = p.integracoes, st = (ok, t) => `<span class="chip"><span class="dot ${ok ? '' : 'ruim'}"></span>${esc(t)}</span>`;
    set('#p-infra', `<div class="linha">${st(i.banco_ok, 'Banco de dados')}${st(i.bolsa_ok, 'Bolsa: ' + i.bolsa_modo)}${st(i.provedor_ok && !i.provedor_pausado, 'Provedor de cotações')}${st(!i.notificador_falhando, 'Notificações')}</div>
      <dl class="kv"><dt>Fila de mensagens</dt><dd>${Object.entries(p.fila).map(([k, v]) => `${esc(k.toLowerCase())}: <b>${v}</b>`).join(' · ') || 'vazia'}</dd>
      <dt>Notificações na fila</dt><dd>${p.notificacoes_pendentes}</dd><dt>Registros de auditoria</dt><dd>${num(p.registros_auditoria)}</dd>
      <dt>Novas ordens</dt><dd>${p.indisponibilidade_segura ? '<b class="neg">suspensas</b>' : '<span class="pos">liberadas</span>'}</dd></dl>`);
    set('#p-susp', tabela([{ t: 'Escopo' }, { t: 'Motivo' }, { t: 'Origem' }], p.suspensoes_ativas.map(s => `<tr><td><b>${esc(s.escopo)}</b></td><td>${esc(s.motivo)}</td><td>${s.automatica ? 'automática (sistema)' : 'operador'}</td></tr>`), 'Nenhuma suspensão ativa.'));
    set('#chips', `<span class="chip"><span class="dot ${p.indisponibilidade_segura ? 'ruim' : ''}"></span>${p.indisponibilidade_segura ? 'Ordens suspensas' : 'Operação normal'}</span>`);
  },
};

VIEWS.problemas = {
  titulo: 'Ordens com problema',
  mount(el) { el.innerHTML = `<div class="card"><div id="prob"></div></div>`; },
  async update() { set('#prob', tabelaOrdens(await api('/painel/ordens-com-problema'), { investidor: true })); },
};

// ---- Operador: limites (CSU12) ----
VIEWS.limites = {
  titulo: 'Limites de risco',
  mount(el) {
    el.innerHTML = `<div class="card"><div id="lim"></div></div>`; this.carregado = false;
    el.onclick = async ev => {
      const b = ev.target.closest('[data-act=salvar-limite]'); if (!b) return;
      const tr = b.closest('tr');
      try {
        await api('/risco/limites/' + b.dataset.id, { method: 'PUT', body: { max_por_ordem: Number(tr.querySelector('[name=o]').value), max_diario: Number(tr.querySelector('[name=d]').value) } });
        toast('Limites salvos.', 'ok'); this.carregado = false; this.update();
      } catch (e) { falha(e); }
    };
  },
  async update() {
    if (this.carregado && document.activeElement?.closest('#lim')) return;   // não atrapalha a digitação
    const l = await api('/risco/limites'); this.carregado = true;
    set('#lim', tabela([{ t: 'Investidor' }, { t: 'Limite por ordem (R$)' }, { t: 'Limite diário (R$)' }, { t: '' }],
      l.map(x => `<tr><td>${esc(x.nome)} <span class="suave">#${x.investidor_id}</span></td><td><input name="o" type="number" step="0.01" min="0.01" value="${esc(x.max_por_ordem ?? '')}"></td>
        <td><input name="d" type="number" step="0.01" min="0.01" value="${esc(x.max_diario ?? '')}"></td><td><button class="btn mini" data-act="salvar-limite" data-id="${x.investidor_id}">Salvar</button></td></tr>`)));
  },
};

// ---- Operador: indisponibilidade segura (CSU13) ----
VIEWS.suspensao = {
  titulo: 'Indisponibilidade segura',
  mount(el) {
    el.innerHTML = `<div class="grade g2"><div class="card"><h3>Suspender novas ordens</h3><p class="suave">Consultas e cancelamentos continuam disponíveis. Informe o motivo e o escopo.</p>
      <form id="f-susp" class="grade"><label>Escopo<select name="escopo"><option value="MERCADO">Todo o mercado</option></select></label>
      <label>Motivo<input name="motivo" required minlength="3" maxlength="300" placeholder="ex.: anomalia nas cotações"></label><button class="btn amar">Acionar suspensão</button></form></div>
      <div class="card"><h3>Suspensões</h3><div id="susp-lista"></div></div></div>`;
    $('#f-susp').onsubmit = async ev => {
      ev.preventDefault(); const f = new FormData(ev.target);
      try {
        const r = await api('/risco/suspensoes', { method: 'POST', body: { escopo: f.get('escopo'), motivo: f.get('motivo') } });
        toast(`Suspensão ativada. Ordens em andamento: ${r.ordens_em_andamento}.`, 'aviso'); ev.target.reset(); this.update();
      } catch (e) { falha(e); }
    };
    el.onclick = async ev => {
      const b = ev.target.closest('[data-act=encerrar]'); if (!b) return;
      try { await api('/risco/suspensoes/encerrar', { method: 'POST', body: { escopo: b.dataset.escopo } }); toast('Suspensão encerrada.', 'ok'); this.update(); } catch (e) { falha(e); }
    };
  },
  async update() {
    const [s, ativos] = await Promise.all([api('/risco/suspensoes'), api('/admin/ativos')]);
    const sel = $('#f-susp [name=escopo]'); if (sel && sel.options.length === 1) sel.insertAdjacentHTML('beforeend', ativos.map(a => `<option value="${esc(a.codigo)}">${esc(a.codigo)}</option>`).join(''));
    set('#susp-lista', tabela([{ t: 'Escopo' }, { t: 'Motivo' }, { t: 'Por' }, { t: 'Situação' }, { t: '' }],
      s.map(x => `<tr><td><b>${esc(x.escopo)}</b></td><td style="white-space:normal">${esc(x.motivo)}</td><td>${esc(x.acionada_por)}</td><td>${x.ativa ? '<span class="pill p-FALHA">ativa</span>' : `<span class="suave">encerrada ${hora(x.encerrada_em)}</span>`}</td>
        <td>${x.ativa ? `<button class="btn verde mini" data-act="encerrar" data-escopo="${esc(x.escopo)}">Encerrar</button>` : ''}</td></tr>`), 'Nenhuma suspensão registrada.'));
  },
};

// ---- Operador: simulação de falhas ----
VIEWS.simulacao = {
  titulo: 'Simulação de falhas',
  mount(el) {
    el.innerHTML = `<p class="suave" style="margin-top:0">Provoque os cenários de falha do documento de visão sistêmica e acompanhe a resposta do sistema no painel e nas ordens.</p>
      <div class="grade g3"><div class="card"><h3>Bolsa simulada</h3><div class="grade" id="sim-bolsa"></div></div>
      <div class="card"><h3>Provedor de cotações</h3><div class="grade" id="sim-prov"></div></div>
      <div class="card"><h3>Notificações e ciclo</h3><div class="grade" id="sim-not"></div></div></div>`;
    el.onclick = async ev => {
      const b = ev.target.closest('[data-sim]'); if (!b) return;
      try {
        if (b.dataset.sim === 'ciclo') { await api('/simulacao/ciclo', { method: 'POST' }); toast('Ciclo de processamento executado.', 'ok'); }
        else { const [rota, campo, valor] = b.dataset.sim.split('|'); await api('/simulacao/' + rota, { method: 'POST', body: { [campo]: valor === 'true' ? true : valor === 'false' ? false : isNaN(valor) ? valor : Number(valor) } }); }
        this.update();
      } catch (e) { falha(e); }
    };
  },
  async update() {
    const p = await api('/painel'), i = p.integracoes;
    const modo = (m, t) => `<button class="btn ${i.bolsa_modo === m ? '' : 'sec'} mini" data-sim="bolsa|modo|${m}">${t}</button>`;
    const tog = (rotulo, ativo, rota, campo, extra = '') => `<div class="toggle"><span>${rotulo}${extra}</span><button class="btn ${ativo ? 'verm' : 'sec'} mini" data-sim="${rota}|${campo}|${!ativo}">${ativo ? 'Desligar' : 'Ligar'}</button></div>`;
    set('#sim-bolsa', `<div><div class="suave" style="margin-bottom:6px">Modo de resposta</div><div class="linha">${modo('NORMAL', 'Normal')}${modo('SEM_RESPOSTA', 'Sem resposta')}${modo('RESPOSTA_PERDIDA', 'Resposta perdida')}</div></div>
      ${tog('Execução parcial', i.bolsa_execucao_parcial, 'bolsa', 'execucao_parcial')}
      <div class="toggle"><span>Rejeitar próximas 2 ordens</span><button class="btn sec mini" data-sim="bolsa|rejeitar_proximas|2">Armar</button></div>
      <div class="toggle"><span>Duplicar próximo retorno</span><button class="btn sec mini" data-sim="bolsa|duplicar_retorno|true">Armar</button></div>`);
    set('#sim-prov', tog('Provedor fora do ar', i.provedor_pausado, 'cotacoes', 'pausado') +
      `<div class="toggle"><span>Dados defasados (30 s)</span><span class="acoes"><button class="btn sec mini" data-sim="cotacoes|atraso_s|30">Ligar</button><button class="btn sec mini" data-sim="cotacoes|atraso_s|0">Desligar</button></span></div>`);
    set('#sim-not', tog('Falha na entrega de notificações', i.notificador_falhando, 'notificador', 'falhar') + `<button class="btn" data-sim="ciclo">Executar ciclo agora</button>`);
  },
};

// ---- Administrador: investidores e contas (CSU09) ----
VIEWS.investidores = {
  titulo: 'Investidores e contas',
  mount(el) {
    el.innerHTML = `<div class="grade g2"><div class="card"><h3>Investidores</h3><div id="inv-lista"></div></div>
      <div class="card"><h3>Novo investidor</h3><form id="f-inv" class="grade">
        <label>Nome<input name="nome" required minlength="2" maxlength="120"></label><label>Documento (fictício)<input name="documento" required maxlength="20"></label>
        <label>Login<input name="login" required minlength="3" maxlength="60" pattern="[A-Za-z0-9_.\\-]+"></label>
        <label>Senha (mín. 12 caracteres, letras e números)<input name="senha" type="password" required></label>
        <div class="linha"><label style="flex:1">Saldo inicial<input name="saldo_inicial" type="number" min="0" step="0.01" value="50000"></label></div>
        <div class="linha"><label style="flex:1">Limite/ordem<input name="max_por_ordem" type="number" min="1" step="0.01" value="50000"></label>
        <label style="flex:1">Limite/dia<input name="max_diario" type="number" min="1" step="0.01" value="200000"></label></div><button class="btn">Cadastrar</button></form></div></div>`;
    $('#f-inv').onsubmit = async ev => {
      ev.preventDefault(); const f = Object.fromEntries(new FormData(ev.target));
      ['saldo_inicial', 'max_por_ordem', 'max_diario'].forEach(k => f[k] = Number(f[k]));
      try { await api('/admin/investidores', { method: 'POST', body: f }); toast('Investidor cadastrado.', 'ok'); ev.target.reset(); this.update(); } catch (e) { falha(e); }
    };
    el.onclick = async ev => {
      const b = ev.target.closest('[data-act]'); if (!b) return; const id = b.dataset.id;
      try {
        if (b.dataset.act === 'situacao') { await api(`/admin/investidores/${id}/situacao`, { method: 'POST', body: { ativo: b.dataset.ativo === 'true' } }); toast('Situação atualizada.', 'ok'); }
        if (b.dataset.act === 'deposito') {
          abrirModal(`<header><h3>Depósito simulado</h3><button class="btn sec mini x" data-fechar>Fechar</button></header><form id="f-dep" class="grade"><label>Valor (R$)<input name="valor" type="number" min="0.01" step="0.01" required autofocus></label><button class="btn">Depositar</button></form>`);
          $('#f-dep').onsubmit = async e2 => { e2.preventDefault(); try { await api(`/admin/investidores/${id}/deposito`, { method: 'POST', body: { valor: Number(new FormData(e2.target).get('valor')) } }); toast('Depósito registrado.', 'ok'); fecharModal(); this.update(); } catch (e) { falha(e); } };
          return;
        }
        this.update();
      } catch (e) { falha(e); }
    };
  },
  async update() {
    const l = await api('/admin/investidores');
    set('#inv-lista', tabela([{ t: 'Nome' }, { t: 'Login' }, { t: 'Saldo', dir: 1 }, { t: 'Reservado', dir: 1 }, { t: 'Situação' }, { t: '' }],
      l.map(x => `<tr><td>${esc(x.nome)}<div class="suave">${esc(x.documento)}</div></td><td>${esc(x.login)}</td><td class="dir">${brl(x.saldo)}</td><td class="dir">${brl(x.reservado)}</td>
        <td>${x.ativo ? '<span class="pos">ativo</span>' : '<span class="neg">inativo</span>'}</td><td><div class="acoes"><button class="btn sec mini" data-act="deposito" data-id="${x.id}">Depositar</button>
        <button class="btn ${x.ativo ? 'verm' : 'verde'} mini" data-act="situacao" data-id="${x.id}" data-ativo="${!x.ativo}">${x.ativo ? 'Desativar' : 'Reativar'}</button></div></td></tr>`)));
  },
};

// ---- Administrador: ativos (CSU10) ----
VIEWS.ativos = {
  titulo: 'Ativos negociáveis',
  mount(el) {
    el.innerHTML = `<div class="grade g2"><div class="card"><h3>Catálogo</h3><div id="ativos-lista"></div></div>
      <div class="card"><h3>Novo ativo</h3><form id="f-ativo" class="grade"><label>Código<input name="codigo" required minlength="3" maxlength="12" style="text-transform:uppercase"></label>
      <label>Nome<input name="nome" required minlength="2" maxlength="120"></label><div class="linha"><label style="flex:1">Tipo<select name="tipo"><option>ACAO</option><option>ETF</option><option>FII</option></select></label>
      <label style="flex:1">Lote padrão<input name="lote_padrao" type="number" min="1" value="100" required></label></div><label>Preço inicial (R$)<input name="preco_inicial" type="number" min="0.01" step="0.01" required value="25"></label>
      <button class="btn">Cadastrar</button></form></div></div>`;
    $('#f-ativo').onsubmit = async ev => {
      ev.preventDefault(); const f = Object.fromEntries(new FormData(ev.target)); f.lote_padrao = Number(f.lote_padrao); f.preco_inicial = Number(f.preco_inicial);
      try { await api('/admin/ativos', { method: 'POST', body: f }); toast('Ativo cadastrado.', 'ok'); ev.target.reset(); this.update(); } catch (e) { falha(e); }
    };
    el.onclick = async ev => {
      const b = ev.target.closest('[data-act=sit-ativo]'); if (!b) return;
      try { await api('/admin/ativos/' + b.dataset.id, { method: 'PATCH', body: { situacao: b.dataset.sit } }); toast('Situação do ativo atualizada.', 'ok'); this.update(); } catch (e) { falha(e); }
    };
  },
  async update() {
    const l = await api('/admin/ativos');
    set('#ativos-lista', tabela([{ t: 'Código' }, { t: 'Nome' }, { t: 'Tipo' }, { t: 'Lote', dir: 1 }, { t: 'Situação' }, { t: '' }],
      l.map(a => `<tr><td><b>${esc(a.codigo)}</b></td><td>${esc(a.nome)}</td><td>${esc(a.tipo)}</td><td class="dir">${num(a.lote_padrao)}</td>
        <td>${a.situacao === 'NEGOCIAVEL' ? '<span class="pos">negociável</span>' : '<span class="neg">suspenso</span>'}</td>
        <td><button class="btn ${a.situacao === 'NEGOCIAVEL' ? 'amar' : 'verde'} mini" data-act="sit-ativo" data-id="${esc(a.codigo)}" data-sit="${a.situacao === 'NEGOCIAVEL' ? 'SUSPENSO' : 'NEGOCIAVEL'}">${a.situacao === 'NEGOCIAVEL' ? 'Suspender' : 'Reativar'}</button></td></tr>`)));
  },
};

// ---- Administrador: perfis de acesso (CSU11) ----
VIEWS.usuarios = {
  titulo: 'Perfis de acesso',
  mount(el) {
    el.innerHTML = `<div class="grade g2"><div class="card"><h3>Usuários</h3><div id="usr-lista"></div></div>
      <div class="card"><h3>Novo usuário interno</h3><form id="f-usr" class="grade"><label>Login<input name="login" required minlength="3" maxlength="60" pattern="[A-Za-z0-9_.\\-]+"></label>
      <label>Senha<input name="senha" type="password" required></label><label>Perfil<select name="perfil"><option value="OPERADOR_RISCO">Operador de Risco</option><option value="AUDITOR">Auditor</option></select></label>
      <button class="btn">Criar</button><p class="suave" style="margin:0">Administradores só são criados por linha de comando (alçada).</p></form></div></div>`;
    $('#f-usr').onsubmit = async ev => {
      ev.preventDefault();
      try { await api('/admin/usuarios', { method: 'POST', body: Object.fromEntries(new FormData(ev.target)) }); toast('Usuário criado.', 'ok'); ev.target.reset(); this.update(); } catch (e) { falha(e); }
    };
    el.onclick = async ev => {
      const b = ev.target.closest('[data-act]'); if (!b) return; const id = b.dataset.id;
      try {
        if (b.dataset.act === 'ativo') await api(`/admin/usuarios/${id}/situacao`, { method: 'POST', body: { ativo: b.dataset.valor === 'true' } });
        if (b.dataset.act === 'desbloquear') await api(`/admin/usuarios/${id}/situacao`, { method: 'POST', body: { desbloquear: true } });
        toast('Usuário atualizado.', 'ok'); this.update();
      } catch (e) { falha(e); }
    };
    el.onchange = async ev => {
      const s = ev.target.closest('[data-perfil]'); if (!s) return;
      try { await api(`/admin/usuarios/${s.dataset.perfil}/perfil`, { method: 'PUT', body: { perfil: s.value } }); toast('Perfil alterado.', 'ok'); } catch (e) { falha(e); }
      this.update();
    };
  },
  async update() {
    if (document.activeElement?.tagName === 'SELECT' && document.activeElement.closest('#usr-lista')) return;
    const l = await api('/admin/usuarios');
    const nome = { INVESTIDOR: 'Investidor', OPERADOR_RISCO: 'Operador de Risco', ADMINISTRADOR: 'Administrador', AUDITOR: 'Auditor' };
    set('#usr-lista', tabela([{ t: 'Login' }, { t: 'Perfil' }, { t: 'Situação' }, { t: '' }],
      l.map(u => `<tr><td><b>${esc(u.login)}</b></td><td>${['OPERADOR_RISCO', 'AUDITOR'].includes(u.perfil)
        ? `<select data-perfil="${u.id}"><option value="OPERADOR_RISCO" ${u.perfil === 'OPERADOR_RISCO' ? 'selected' : ''}>Operador de Risco</option><option value="AUDITOR" ${u.perfil === 'AUDITOR' ? 'selected' : ''}>Auditor</option></select>` : esc(nome[u.perfil])}</td>
        <td>${u.bloqueado ? '<span class="pill p-FALHA">bloqueado</span> ' : ''}${u.ativo ? '<span class="pos">ativo</span>' : '<span class="neg">inativo</span>'}</td>
        <td><div class="acoes"><button class="btn sec mini" data-act="ativo" data-id="${u.id}" data-valor="${!u.ativo}">${u.ativo ? 'Desativar' : 'Reativar'}</button>${u.bloqueado ? `<button class="btn amar mini" data-act="desbloquear" data-id="${u.id}">Desbloquear</button>` : ''}</div></td></tr>`)));
  },
};

// ---- Auditor (CSU14) ----
VIEWS.auditoria = {
  titulo: 'Registros de auditoria',
  mount(el) {
    el.innerHTML = `<div class="card"><form id="f-aud" class="linha" style="margin-bottom:12px">
      <label>Usuário<input name="usuario" maxlength="60" style="width:130px"></label><label>Ação<input name="acao" maxlength="40" placeholder="ex.: ORDEM_ACEITA" style="width:170px"></label>
      <label>Ordem<input name="ordem_id" maxlength="60" style="width:150px"></label><label>De<input name="desde" type="datetime-local"></label><label>Até<input name="ate" type="datetime-local"></label>
      <button class="btn">Consultar</button><button type="button" class="btn sec" id="b-int">Verificar integridade</button></form><div id="res-int"></div><div id="aud-lista"></div></div>`;
    this.registros = [];
    const consultar = async ev => {
      ev?.preventDefault(); const f = new FormData($('#f-aud')); const q = new URLSearchParams();
      for (const [k, v] of f) if (v) q.set(k, k === 'desde' || k === 'ate' ? v.length === 16 ? v + ':00' : v : v);
      try {
        this.registros = await api('/auditoria?' + q);
        set('#aud-lista', tabela([{ t: '#', dir: 1 }, { t: 'Quando' }, { t: 'Usuário' }, { t: 'Ação' }, { t: 'Entidade' }, { t: 'Resultado' }, { t: 'Hash' }],
          this.registros.map((r, i) => `<tr class="clicavel" data-i="${i}"><td class="dir suave">${r.id}</td><td>${hora(r.ocorrido_em)}</td><td>${esc(r.usuario)}</td><td><b>${esc(r.acao)}</b></td>
            <td class="mono">${esc(r.entidade_id ?? '')}</td><td><span class="pill p-${r.resultado === 'FALHA' ? 'FALHA_A' : esc(r.resultado)}">${esc(r.resultado)}</span></td><td class="mono suave">${esc(r.hash)}</td></tr>`), 'Nenhum registro para os filtros informados.'));
      } catch (e) { falha(e); }
    };
    $('#f-aud').onsubmit = consultar; this.consultar = consultar;
    $('#b-int').onclick = async () => {
      try {
        const r = await api('/auditoria/verificar', { method: 'POST' });
        $('#res-int').innerHTML = `<div class="msg-form ${r.integra ? 'ok' : 'erro'}" style="margin:0 0 12px">${r.integra ? `✔ Cadeia íntegra: ${num(r.total_verificado)} registros verificados.` : `✖ Inconsistência detectada nos registros: ${esc(r.registros_suspeitos.join(', '))}. O Operador de Risco foi notificado.`}</div>`;
      } catch (e) { falha(e); }
    };
    $('#aud-lista').onclick = ev => {
      const tr = ev.target.closest('tr[data-i]'); if (!tr) return; const r = this.registros[tr.dataset.i];
      abrirModal(`<header><h3>Registro #${r.id}</h3><button class="btn sec mini x" data-fechar>Fechar</button></header><dl class="kv"><dt>Quando</dt><dd>${hora(r.ocorrido_em)}</dd><dt>Usuário</dt><dd>${esc(r.usuario)} ${r.perfil ? '(' + esc(r.perfil) + ')' : ''}</dd>
        <dt>Ação</dt><dd>${esc(r.acao)}</dd><dt>Entidade</dt><dd>${esc(r.entidade ?? '—')} ${esc(r.entidade_id ?? '')}</dd><dt>Resultado</dt><dd>${esc(r.resultado)}</dd><dt>Origem</dt><dd>${esc(r.origem ?? '—')}</dd>
        <dt>Correlação</dt><dd class="mono">${esc(r.correlacao_id ?? '—')}</dd><dt>Hash</dt><dd class="mono">${esc(r.hash)}…</dd></dl><pre class="mono" style="white-space:pre-wrap;background:#0d1730;padding:10px;border-radius:8px;margin-top:12px">${esc(r.detalhes)}</pre>`);
    };
    consultar();
  },
};

// ───────────────────────────── início ─────────────────────────────
(async function iniciar() {
  try { S.usuario = await api('/auth/eu'); renderShell(); } catch { renderLogin(); }
})();

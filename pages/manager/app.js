const bridge = window.AstrBotPluginPage;

let projects = [];
let settings = {};

// ---- Init ----

async function init() {
  await bridge.ready();
  setupTabs();
  setupModal();
  await loadProjects();
  await loadSettings();
}

// ---- Tab Navigation ----

function setupTabs() {
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    });
  });
}

// ---- Projects ----

async function loadProjects() {
  try {
    const data = await bridge.apiGet('projects');
    projects = data.projects || [];
    renderProjects();
  } catch (e) {
    console.error('Failed to load projects', e);
  }
}

function renderProjects() {
  const container = document.getElementById('project-list');
  if (!projects.length) {
    container.innerHTML = '<p style="color:var(--text-secondary)">暂无项目，点击右上角「新建项目」开始。</p>';
    return;
  }
  container.innerHTML = projects.map(p => `
    <div class="project-card" data-id="${p.id}">
      <h3>${esc(p.name || '未命名项目')}</h3>
      <span class="badge ${p.enabled ? 'badge-on' : 'badge-off'}">
        ${p.enabled ? '已启用' : '已停用'}
      </span>
      <div class="meta">
        <div>QQ 群: ${p.qq_groups.length} 个</div>
        <div>管理员: ${p.admins.length} 人</div>
        <div>摘要: ${p.schedule.summary_cron} | 报告: ${p.schedule.report_cron}</div>
      </div>
    </div>
  `).join('');

  container.querySelectorAll('.project-card').forEach(card => {
    card.addEventListener('click', () => {
      const proj = projects.find(p => p.id === card.dataset.id);
      if (proj) openProjectModal(proj);
    });
  });
}

// ---- Settings ----

async function loadSettings() {
  try {
    const data = await bridge.apiGet('settings');
    settings = data.settings || {};

    const select = document.getElementById('llm-provider');
    select.innerHTML = '<option value="">自动选择</option>';
    (data.available_providers || []).forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = p.name;
      if (p.id === settings.llm_provider_id) opt.selected = true;
      select.appendChild(opt);
    });

    document.getElementById('lark-cli-path').value = settings.lark_cli_path || 'lark-cli';
    document.getElementById('retention-days').value = settings.message_retention_days || 7;

    const badge = document.getElementById('lark-status');
    if (data.lark_available) {
      badge.className = 'status-badge ok';
      badge.textContent = 'lark-cli: 可用';
    } else {
      badge.className = 'status-badge warn';
      badge.textContent = 'lark-cli: 不可用 — 请检查安装和登录状态';
    }
  } catch (e) {
    console.error('Failed to load settings', e);
  }
}

document.getElementById('settings-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await bridge.apiPost('settings', {
      llm_provider_id: document.getElementById('llm-provider').value,
      lark_cli_path: document.getElementById('lark-cli-path').value,
      message_retention_days: parseInt(document.getElementById('retention-days').value, 10),
    });
    await loadSettings();
    showToast('设置已保存');
  } catch (e) {
    showToast('保存失败: ' + e.message, true);
  }
});

// ---- Project Modal ----

function setupModal() {
  document.getElementById('btn-add-project').addEventListener('click', () => {
    openProjectModal(null);
  });
  document.getElementById('btn-close-modal').addEventListener('click', closeModal);
  document.getElementById('modal-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
  });

  document.getElementById('project-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    await saveProject();
  });

  document.getElementById('btn-delete-project').addEventListener('click', async () => {
    const id = document.getElementById('pf-id').value;
    if (!id) return;
    if (!confirm('确定要删除这个项目吗？')) return;
    try {
      await bridge.apiPost('projects/delete', { id });
      closeModal();
      await loadProjects();
      showToast('项目已删除');
    } catch (e) {
      showToast('删除失败: ' + e.message, true);
    }
  });
}

function openProjectModal(proj) {
  const isNew = !proj;
  document.getElementById('modal-title').textContent = isNew ? '新建项目' : '编辑项目';
  document.getElementById('btn-delete-project').classList.toggle('hidden', isNew);

  document.getElementById('pf-id').value = proj?.id || '';
  document.getElementById('pf-name').value = proj?.name || '';
  document.getElementById('pf-handbook').value = proj?.lark_handbook_url || '';
  document.getElementById('pf-bulletin').value = proj?.lark_bulletin_url || '';
  document.getElementById('pf-groups').value = (proj?.qq_groups || []).join('\n');
  document.getElementById('pf-admins').value = (proj?.admins || []).join('\n');
  document.getElementById('pf-filtered').value = (proj?.filtered_members || []).join('\n');

  const mapping = proj?.member_mapping || {};
  document.getElementById('pf-mapping').value = Object.entries(mapping)
    .map(([k, v]) => `${k}=${v}`)
    .join('\n');

  document.getElementById('pf-summary-cron').value = proj?.schedule?.summary_cron || '0 18 * * *';
  document.getElementById('pf-report-cron').value = proj?.schedule?.report_cron || '0 9 * * *';
  document.getElementById('pf-urge-days').value = proj?.schedule?.urge_threshold_days || 3;
  document.getElementById('pf-enabled').checked = proj?.enabled ?? true;

  document.getElementById('modal-overlay').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
}

async function saveProject() {
  const lines = s => s.split('\n').map(l => l.trim()).filter(Boolean);
  const mapping = {};
  lines(document.getElementById('pf-mapping').value).forEach(line => {
    const [k, v] = line.split('=');
    if (k && v) mapping[k.trim()] = v.trim();
  });

  const data = {
    id: document.getElementById('pf-id').value || undefined,
    name: document.getElementById('pf-name').value,
    lark_handbook_url: document.getElementById('pf-handbook').value,
    lark_bulletin_url: document.getElementById('pf-bulletin').value,
    qq_groups: lines(document.getElementById('pf-groups').value),
    admins: lines(document.getElementById('pf-admins').value),
    filtered_members: lines(document.getElementById('pf-filtered').value),
    member_mapping: mapping,
    schedule: {
      summary_cron: document.getElementById('pf-summary-cron').value,
      report_cron: document.getElementById('pf-report-cron').value,
      urge_threshold_days: parseInt(document.getElementById('pf-urge-days').value, 10),
    },
    enabled: document.getElementById('pf-enabled').checked,
  };

  try {
    await bridge.apiPost('projects', data);
    closeModal();
    await loadProjects();
    showToast('项目已保存');
  } catch (e) {
    showToast('保存失败: ' + e.message, true);
  }
}

// ---- Utilities ----

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function showToast(msg, isError = false) {
  const el = document.createElement('div');
  el.textContent = msg;
  Object.assign(el.style, {
    position: 'fixed', bottom: '20px', left: '50%', transform: 'translateX(-50%)',
    padding: '10px 24px', borderRadius: '8px', fontSize: '14px', zIndex: '9999',
    background: isError ? '#d63031' : '#00b894', color: '#fff',
    boxShadow: '0 4px 12px rgba(0,0,0,0.2)', transition: 'opacity 0.3s',
  });
  document.body.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; }, 2000);
  setTimeout(() => el.remove(), 2500);
}

init();

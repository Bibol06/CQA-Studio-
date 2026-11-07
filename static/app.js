"use strict";
const $ = (s) => document.querySelector(s);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const paths = {
  messages:
    "M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-6 4V6a2 2 0 0 1 2-2ZM7 8h10M7 12h6",
  checklist: "M9 5h11M9 12h11M9 19h11M3 5l1 1 2-3M3 12l1 1 2-3M3 19l1 1 2-3",
  chart: "M4 3v17h17M8 15v-4M13 15V7M18 15V4",
  shield: "M12 3 3 6v6c0 5 9 9 9 9s9-4 9-9V6L12 3ZM8 12l3 3 5-6",
  settings:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM9 3h6l1 3 3 1 2 4v2l-2 4-3 1-1 3H9l-1-3-3-1-2-4v-2l2-4 3-1 1-3Z",
  download: "M12 3v12M7 10l5 5 5-5M4 17v4h16v-4",
  upload: "M12 16V4M7 9l5-5 5 5M4 17v4h16v-4",
  sparkle: "m12 3 2.7 6.3L21 12l-6.3 2.7L12 21l-2.7-6.3L3 12l6.3-2.7L12 3Z",
  search: "M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM15 15l6 6",
  refresh: "M20 7a9 9 0 0 0-15-2L2 8m0-5v5h5M4 17a9 9 0 0 0 15 2l3-3m0 5v-5h-5",
  check: "m5 12 4 4L19 6",
  close: "m6 6 12 12M18 6 6 18",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 7v5l3 2",
  link: "m10 8 3-3a4 4 0 0 1 6 6l-3 3M14 16l-3 3a4 4 0 0 1-6-6l3-3M8 16l8-8",
  phone:
    "M5 3h4l2 5-3 2c1 3 3 5 6 6l2-3 5 2v4c0 2-3 3-5 2A22 22 0 0 1 3 8c-1-2 0-5 2-5Z",
  flag: "M5 21V3c5-3 9 3 14 0v10c-5 3-9-3-14 0",
  arrow: "M5 12h14m-5-5 5 5-5 5",
  plus: "M12 5v14M5 12h14",
  file: "M6 3h8l4 4v14H6V3Zm8 0v5h4M9 12h6M9 16h6",
  info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 11v6M12 7v1",
};
const icon = (name, cls = "") =>
  `<svg class="${esc(cls)}" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.info}"></path></svg>`;
document
  .querySelectorAll("[data-icon]")
  .forEach((el) => (el.innerHTML = icon(el.dataset.icon)));
let state = { records: [], checklist: null, open_appeals: 0 },
  settings = {},
  selected = null,
  detail = null,
  view = "dialogs",
  busy = false,
  draft = null,
  toastTimer;
let jobsState = { jobs: [], counts: {} },
  jobsHash = "",
  jobsConnectionError = null,
  pollBusy = false,
  needsDetailRefresh = false,
  pendingBatch = [];
const jobLabels = {
  queued: "Ожидает",
  running: "Обрабатывается",
  waiting_key: "Нужен ключ",
  completed: "Готово",
  failed: "Ошибка",
  interrupted: "Прервано",
  cancelled: "Отменено",
  paused: "Приостановлено",
};
const fmt = (value) =>
  value == null
    ? "—"
    : Number(value).toLocaleString("ru-RU", { maximumFractionDigits: 2 });
const roles = {
  operator: "Оператор",
  client: "Клиент",
  bot: "AI-ассистент",
  system: "Событие",
};
async function api(path, body) {
  const response = await fetch(
    "/api/" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error || "Не удалось выполнить запрос");
  return data;
}
function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = "toast show" + (error ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("show"), 5500);
}
function fail(error) {
  toast(error.message || String(error), true);
}
function modelName() {
  return settings.provider === "rules"
    ? "Проверка правил"
    : settings.model || "Модель не выбрана";
}
async function refresh() {
  state = await api("state");
  renderStats();
  renderBanner();
  renderList();
  if (view === "analytics") renderAnalytics();
}
function renderStats() {
  const channel = view === "dialogs" ? $("#channel").value : "";
  const records = state.records.filter(r => !channel || r.channel === channel);
  const totals = records.filter((r) => r.score != null),
    evaluated = records.filter((r) => r.evaluated),
    calls = records.filter((r) => r.channel === "voice call").length;
  const average = totals.length
    ? totals.reduce((s, r) => s + r.score, 0) / totals.length
    : null;
  const stats = [
    [
      channel === "voice call" ? "Всего звонков" : channel === "agent chat" ? "Всего чатов" : "Всего диалогов",
      records.length,
      `${records.length - calls} чатов · ${calls} звонков`,
      "messages",
    ],
    [
      "Есть итоговая оценка",
      totals.length,
      `${evaluated.length - totals.length} черновиков на пересмотр`,
      "checklist",
    ],
    [
      "Средний итоговый балл",
      fmt(average),
      totals.length
        ? `По ${totals.length} полным оценкам`
        : "Появится после полной оценки",
      "chart",
    ],
    [
      "Апелляции во всём наборе",
      state.open_appeals,
      "Решения сохраняются в истории",
      "shield",
    ],
  ];
  $("#stats").innerHTML = stats
    .map(
      ([label, value, note, image]) =>
        `<article class="stat"><div><div class="stat-label">${esc(label)}</div><div class="stat-value">${esc(value)}${label.includes("балл") && average != null ? "<small>/ 100</small>" : ""}</div><div class="stat-note">${esc(note)}</div></div><div class="stat-icon">${icon(image)}</div></article>`,
    )
    .join("");
  $("#nav-count").textContent = state.records.length;
}
function renderBanner() {
  if (
    settings.provider !== "rules" &&
    settings.provider !== "ollama" &&
    !settings.key_configured
  ) {
    $("#model-banner").innerHTML =
      `${icon("info")}<span><strong>Ключ модели не задан.</strong> Задания сохранятся в очереди и дождутся подключения.</span><button data-action="settings">Добавить ключ</button>`;
    return;
  }
  $("#model-banner").innerHTML =
    settings.provider === "rules"
      ? `${icon("info")}<span><strong>Режим проверки правил.</strong> Смысловые критерии требуют модели или пересмотра человеком. Неполные оценки не входят в средний балл.</span><button data-action="settings">Подключить AI ${icon("arrow")}</button>`
      : `${icon("sparkle")}<span><strong>${esc(modelName())}</strong> · результаты проходят проверку допустимых оценок и точности цитат.</span><button data-action="settings">Настроить</button>`;
}
function filtered() {
  const search = $("#search").value.trim().toLowerCase(),
    lang = $("#language").value,
    channel = $("#channel").value,
    status = $("#status").value;
  return state.records.filter(
    (r) =>
      (!search ||
        (r.conversation_id + " " + r.preview).toLowerCase().includes(search)) &&
      (!lang || r.language === lang) &&
      (!channel || r.channel === channel) &&
      (!status ||
        (status === "new" && !r.evaluated) ||
        (status === "done" && r.score != null) ||
        (status === "review" && r.evaluated && r.needs_review > 0) ||
        (status === "gross" && r.gross_error)),
  );
}
function renderList() {
  renderChannelTabs();
  const records = filtered();
  $("#filtered-count").textContent = records.length;
  $("#conversation-list").innerHTML = records.length
    ? records
        .map(
          (r) =>
            `<button class="conversation-item ${r.conversation_id === selected ? "selected" : ""}" data-action="select" data-id="${esc(r.conversation_id)}" aria-pressed="${r.conversation_id === selected}"><div class="conv-top"><span class="conv-id">${esc(r.conversation_id)}</span><span class="conv-language">${esc(r.language)}</span><span class="conv-icon">${icon(r.channel === "voice call" ? "phone" : "messages")}</span></div><div class="conv-preview">${esc(r.preview)}</div><div class="conv-bottom"><span class="conv-state ${r.score != null ? "done" : ""}">${r.stale ? "Чек-лист изменён" : r.evaluated ? (r.score != null ? "Есть итог" : "Черновик") : "Новый диалог"}</span><span class="conv-score ${r.gross_error ? "alert" : ""}">${r.gross_error ? "⚑ " : ""}${r.score != null ? fmt(r.score) + "/100" : r.messages + " реплик"}</span></div></button>`,
        )
        .join("")
    : '<div class="empty-state"><p>Нет диалогов по выбранным фильтрам.</p></div>';
}
function renderChannelTabs() {
  const selectedChannel = $("#channel").value;
  $("#channel-tabs").innerHTML = [["","Все диалоги","messages"],["agent chat","Чаты","messages"],["voice call","Звонки","phone"]].map(([value,label,image]) => `<button role="tab" aria-selected="${selectedChannel === value}" class="channel-tab ${selectedChannel === value ? "active" : ""}" data-action="channel-tab" data-channel="${value}">${icon(image)}${label}<span>${state.records.filter(r => !value || r.channel === value).length}</span></button>`).join("");
}
async function chooseChannel(channel) {
  $("#channel").value = channel;
  renderList();renderStats();
  const records = filtered();
  if (records.length && !records.some(r => r.conversation_id === selected)) await selectConversation(records[0].conversation_id);
  if (channel === "voice call" && detail?.record.channel === "voice call") {resultsMode="audio";renderResults();}
}
let selectionSerial = 0;
let resultsMode = "text";
async function selectConversation(id) {
  const serial = ++selectionSerial;
  $("#audio-player")?.pause?.();
  if (typeof audioPreviewEnd !== "undefined") audioPreviewEnd = null;
  selected = id;
  resultsMode = "text";
  detail = null;
  renderList();
  $("#transcript-panel").innerHTML =
    '<div class="empty-state">Загрузка диалога…</div>';
  $("#results-panel").innerHTML =
    '<div class="empty-state">Загрузка результата…</div>';
  $("#transcript-panel").classList.add("loading");
  try {
    const incoming = await api("conversations/" + encodeURIComponent(id));
    if (serial !== selectionSerial) return;
    detail = incoming;
    renderDetail();
    history.replaceState(null, "", "#" + encodeURIComponent(id));
  } finally {
    if (serial === selectionSerial)
      $("#transcript-panel").classList.remove("loading");
  }
}
function safeUrl(value) {
  try {
    const u = new URL(value);
    return ["https:", "http:"].includes(u.protocol) ? u.href : null;
  } catch {
    return null;
  }
}
function renderDetail() {
  if (!detail) return;
  renderTranscript();
  renderResults();
  renderQueueBanner();
}
let showContext = true;
function renderTranscript() {
  const r = detail.record,
    e = detail.evaluation,
    url = r.channel === "voice call" && r.audio_url ? "/api/audio/" + encodeURIComponent(r.conversation_id) : null;
  const previousAudio = $("#audio-player");
  $("#transcript-panel").innerHTML =
    `<div class="transcript-heading"><span class="channel-avatar">${icon(r.channel === "voice call" ? "phone" : "messages")}</span><div><h2>${esc(r.conversation_id)}</h2><p>${r.channel === "voice call" ? "Телефонный разговор" : "Переписка с поддержкой"} · ${esc(r.language)} · ${r.transcript.length} реплик</p></div><div class="transcript-actions"><span class="badge green">${esc(detail.dataset_group || "DEV")}</span></div></div>${url ? `<div class="audio-box"><audio id="audio-player" data-cid="${esc(r.conversation_id)}" controls preload="metadata" src="${url}"></audio><div id="audio-status" class="audio-status">Получаем запись и длительность…</div><button class="button text small" data-action="audio-info">Проверить запись</button><p>Время плеера начинается с 0:00 записи. Связь с ISO-метками транскрипта отдельно не подтверждена.</p></div>` : ""}<div class="transcript-tools"><span>Исходный транскрипт</span><label class="toggle"><input type="checkbox" id="context-toggle" ${showContext ? "checked" : ""}>Бот и события</label></div><div class="transcript-messages" id="messages">${r.transcript
      .map((t, i) => ({ t, i }))
      .filter(({ t }) => showContext || !["bot", "system"].includes(t.speaker))
      .map(
        ({ t, i }) =>
          `<article class="message ${esc(t.speaker)}" id="message-${i + 1}">${t.speaker !== "system" ? `<div class="message-header"><span class="message-role">${roles[t.speaker] || esc(t.speaker)}</span><span>${esc(t.timestamp)}</span><span class="message-num">#${i + 1}</span></div>` : ""}<div class="message-body">${t.speaker === "system" ? `${esc(t.timestamp)} · ` : ""}${esc(t.text)}</div></article>`,
      )
      .join(
        "",
      )}<div class="transcript-end">Конец предоставленного транскрипта</div></div>`;
  if (url) {
    if (previousAudio?.dataset.cid === r.conversation_id) $("#audio-player").replaceWith(previousAudio);
    loadAudioInfo().catch(() => {});
  }
}
const audioEventLabels = {cough:"Кашель",throat_clear:"Прочищение горла",laugh:"Смех",filled_pause:"Пауза с заполнителем",repetition:"Повтор звука или слова",unintelligible:"Неразборчивый фрагмент",overlap:"Одновременная речь",long_pause:"Длительная пауза",volume_change:"Изменение громкости",intonation_change:"Изменение интонации",rate_change:"Изменение темпа",background_noise:"Фоновый шум"};
const audioRoles = {operator:"Вероятно оператор",client:"Вероятно клиент",bot:"Вероятно автоответчик / IVR",unknown:"Говорящий не определён"};
const audioCheckLabels = {detected:"Есть кандидат",not_detected:"Не замечено моделью",uncertain:"Неоднозначно",not_assessable:"Не удалось оценить"};
const audioInfo = new Map();
let audioPreviewEnd = null;
function audioTime(value) {
  if (!Number.isFinite(value) || value < 0) return "—";
  const seconds = Math.floor(value);
  return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,"0")}`;
}
function resultModeTabs() {
  return detail?.record.channel === "voice call" ? `<div class="result-mode-tabs" role="tablist" aria-label="Вид анализа звонка"><button role="tab" aria-selected="${resultsMode === "text"}" data-action="result-mode" data-mode="text">Чек-лист</button><button role="tab" aria-selected="${resultsMode === "audio"}" data-action="result-mode" data-mode="audio">${icon("phone")}Звук</button></div>` : "";
}
async function loadAudioInfo() {
  const cid = detail?.record.conversation_id, serial = selectionSerial;
  if (!cid || detail.record.channel !== "voice call") return;
  try {
    const info = await api("audio-info/" + encodeURIComponent(cid));
    if (selected !== cid || selectionSerial !== serial) return;
    const previousMatch = audioInfo.get(cid)?.analysis_matches_audio;
    audioInfo.set(cid,info);
    const node = $("#audio-status");
    if (node) node.textContent = `${audioTime(info.duration_seconds)} · ${info.channels === 1 ? "Моно" : "Стерео"} · ${(info.size_bytes/1048576).toFixed(1)} МБ`;
    if (detail.audio_analysis && previousMatch !== info.analysis_matches_audio && resultsMode === "audio") renderAudioResults();
  } catch (error) {
    if (selected === cid && selectionSerial === serial && $("#audio-status")) $("#audio-status").textContent = error.message;
  }
}
function seekAudio(start,end) {
  const player = $("#audio-player");
  if (!player || player.dataset.cid !== selected || !Number.isFinite(start) || start < 0) return;
  audioPreviewEnd = Number.isFinite(end) ? Math.min(end+1.5,Math.max(0,start-1)+20) : null;
  const play = () => {
    if (player.dataset.cid !== selected) return;
    player.currentTime = Math.min(Math.max(0,start-1),Number.isFinite(player.duration) ? player.duration : start);
    player.play().catch(() => toast("Нажмите Play на плеере, чтобы прослушать фрагмент."));
  };
  if (player.readyState >= 1) play();
  else {player.addEventListener("loadedmetadata",play,{once:true});player.load();}
}
function renderAudioResults() {
  const analysis = detail.audio_analysis, job = activeJob("audio");
  const button = `<button class="button primary" data-action="analyze-audio" ${job ? "disabled" : ""}>${icon(job ? "clock" : "sparkle")}${job ? esc(jobLabels[job.status]) : analysis ? "Проанализировать звук заново" : "Проанализировать звук"}</button>`;
  let body = `<div class="audio-analysis-intro"><span class="badge">Отдельно от официального балла</span><p>Gemini получает саму аудиозапись. События и интонационные наблюдения — кандидаты для прослушивания и ручной проверки. Медицинские причины и диагнозы не определяются.</p>${button}${settings.provider !== "gemini" ? '<p class="submission-warning">Для звука выберите Gemini в настройках модели.</p>' : ""}</div><p id="audio-job-status" class="submission-warning"></p>`;
  if (!analysis) body += '<div class="empty-state"><h3>Звук ещё не анализировался</h3><p>Можно проверить кашель, прочищение горла, паузы, повторы, одновременную речь, шум и изменения звучания.</p></div>';
  else {
    const r = analysis.result, labels = {slow:"Медленный",steady:"Ровный",fast:"Быстрый",variable:"Меняется",not_assessable:"Не оценено",even:"Ровная",varied:"Разнообразная"};
    const review = index => analysis.event_reviews?.[String(index)];
    const checked = Object.values(analysis.event_reviews || {});
    body += `<p class="review-note">${esc(analysis.meta.model)} · ${esc(analysis.meta.prompt_version)} · ${audioTime(r.audio.duration_seconds)} · ${fmt(analysis.meta.elapsed_seconds)} с обработки. Временные отметки приблизительные, от начала аудио.</p>${audioInfo.get(selected)?.analysis_matches_audio === false ? '<p class="submission-warning">Сохранённый анализ относится к другой версии аудиофайла. Нужен новый запуск.</p>' : ""}${r.validation?.status === "partial" ? `<div class="audio-validation-warning"><strong>Частичный результат</strong><p>Часть ответа требует проверки. Исключено событий с неверным временем: ${r.validation.discarded_events}; описаний звучания: ${r.validation.discarded_delivery}; противоречий категорий: ${r.validation.contradictory_checks || 0}. Список фрагментов может быть неполным.</p><details><summary>Причины исключения</summary>${r.validation.warnings.map(w => `<p>${esc(w)}</p>`).join("")}</details></div>` : ""}<h3>Как звучит разговор</h3><p>${esc(r.overview)}</p><p class="review-note">Слышимость: ${{clear:"хорошая",mixed:"неоднородная",poor:"низкая"}[r.quality.audibility]}. ${r.quality.limitations.map(esc).join(" · ")}</p>${r.delivery.map(d => `<article class="audio-event"><span class="badge">${audioRoles[d.speaker]}</span><p>Темп: ${labels[d.pace]}; интонация: ${labels[d.intonation]}.</p><p>${esc(d.description)}</p><button class="button text small" data-action="audio-seek" data-start="${d.start_seconds}" data-end="${d.end_seconds}">Слушать ≈${audioTime(d.start_seconds)}–${audioTime(d.end_seconds)}</button></article>`).join("")}<h3>Ответ модели по категориям</h3><p class="review-note">«Не замечено» не гарантирует отсутствие события. Уверенность модели не является измеренной вероятностью.</p><div class="audio-checks">${r.checks.map(c => `<details><summary><span>${audioEventLabels[c.type]}</span><span class="badge ${c.status === "detected" ? "amber" : ""}">${c.consistency_warning ? "Противоречие" : audioCheckLabels[c.status]}</span></summary><p>${esc(c.comment)}</p>${c.consistency_warning ? `<p class="submission-warning">Исходный статус AI: ${audioCheckLabels[c.status]}. ${esc(c.consistency_warning)}</p>` : ""}${c.timing_warning ? '<p class="submission-warning">Модель отметила событие, но его временная привязка не прошла проверку. Нужен ручной поиск в записи.</p>' : ""}</details>`).join("")}</div><h3>Фрагменты для проверки · ${r.events.length}</h3><p class="review-note">Подтверждено: ${checked.filter(v => v.verdict === "confirmed").length}; отклонено: ${checked.filter(v => v.verdict === "rejected").length}; не проверено: ${r.events.length-checked.length}. Кнопки ниже сохраняют решение отдельно от AI-наблюдения.</p>${r.events.length ? r.events.map((e,index) => `<article class="audio-event ${review(index)?.verdict === "rejected" ? "event-rejected" : ""}"><div class="example-head"><strong>${audioEventLabels[e.type]}</strong><span class="badge">≈${audioTime(e.start_seconds)}–${audioTime(e.end_seconds)}</span></div><p><small>${audioRoles[e.speaker]} · уверенность AI: ${{low:"низкая",medium:"средняя",high:"высокая"}[e.confidence]}</small></p><p>${esc(e.description)}</p><button class="button secondary small" data-action="audio-seek" data-start="${e.start_seconds}" data-end="${e.end_seconds}">▶ Прослушать фрагмент</button><div class="audio-verdict">${review(index) ? `<span class="badge ${review(index).verdict === "confirmed" ? "green" : ""}">Решение проверяющего: ${review(index).verdict === "confirmed" ? "подтверждено" : "отклонено"}</span>` : '<span class="badge amber">Не проверено человеком</span>'}<button class="button text small" data-action="audio-review" data-analysis="${analysis.id}" data-event="${index}" data-verdict="confirmed">Подтвердить</button><button class="button text small" data-action="audio-review" data-analysis="${analysis.id}" data-event="${index}" data-verdict="rejected">Отклонить</button></div></article>`).join("") : '<p>Модель не отметила отдельных событий. Это не доказывает их отсутствие.</p>'}<details class="audio-history"><summary>История аудиозапусков · ${(detail.audio_history || []).length}</summary>${(detail.audio_history || []).map(a => `<p>#${a.id} · ${esc(a.meta.model)} · ${a.result.events.length} событий · ${esc(new Date(a.created_at).toLocaleString("ru-RU"))}</p>`).join("")}</details>`;
  }
  $("#results-panel").innerHTML = `<div class="results-header"><h2>Анализ звука</h2><span class="badge">AI-наблюдения</span></div>${resultModeTabs()}<div class="result-scroll audio-results">${body}</div>`;
}
async function analyzeAudio() {
  if (detail?.record.channel !== "voice call") return;
  const cid = selected, serial = selectionSerial;
  const result = await api("jobs",{conversation_ids:[cid],kind:"audio"});
  await pollJobs();
  if (selected === cid && selectionSerial === serial && detail?.record.conversation_id === cid && resultsMode === "audio") renderAudioResults();
  toast(result.created.length ? "Аудиоанализ добавлен в очередь" : "Аудиоанализ уже находится в очереди");
}
async function reviewAudio(button) {
  const cid = selected, serial = selectionSerial;
  await api("audio-reviews",{analysis_id:Number(button.dataset.analysis),event_index:Number(button.dataset.event),verdict:button.dataset.verdict});
  const incoming = await api("conversations/" + encodeURIComponent(cid));
  if (selected !== cid || serial !== selectionSerial) return;
  detail = incoming;renderAudioResults();
  toast("Решение по событию сохранено");
}
function renderAudioOverview(data) {
  if (!data?.total_calls) return "";
  return `<div class="section-card"><h2>Аудиособытия в звонках</h2><p>Проанализировано по звуку: ${data.analyzed_calls}/${data.total_calls}; частичных результатов: ${data.partial_analyses || 0}. Кандидатов: ${data.events.length}; подтверждено проверяющим: ${data.confirmed}; отклонено: ${data.rejected}; не проверено: ${data.unreviewed}. Эти признаки не меняют официальный балл.</p>${data.events.length ? `<div class="audio-overview-events">${data.events.map(e => `<button class="button secondary small" data-action="open-audio-event" data-id="${esc(e.conversation_id)}" data-start="${e.start_seconds}" data-end="${e.end_seconds}">${esc(e.conversation_id)} · ${audioEventLabels[e.type]} · ≈${audioTime(e.start_seconds)}${e.verdict === "confirmed" ? " · подтверждено" : e.verdict === "rejected" ? " · отклонено" : " · проверить"}</button>`).join("")}</div>` : '<p>Аудионаблюдения появятся после отдельного запуска во вкладке «Звонки → Звук».</p>'}</div>`;
}
document.addEventListener("timeupdate",event => {
  const player = event.target;
  if (player.id === "audio-player" && audioPreviewEnd != null && player.currentTime >= audioPreviewEnd) {audioPreviewEnd=null;player.pause();}
},true);
document.addEventListener("pause",event => {if (event.target.id === "audio-player") audioPreviewEnd = null;},true);
document.addEventListener("error",event => {
  if (event.target.id === "audio-player" && $("#audio-status")) $("#audio-status").textContent = "Не удалось воспроизвести запись. Нажмите «Проверить запись», чтобы уточнить доступность.";
},true);
function renderResults() {
  if (!detail) return;
  const r = detail.record,
    e = detail.evaluation;
  if (r.channel === "voice call" && resultsMode === "audio") {renderAudioResults();return;}
  if (!e) {
    $("#results-panel").innerHTML =
      `<div class="results-header"><h2>${r.channel === "voice call" ? "Оценка по транскрипту" : "Оценка чата"}</h2><span class="badge">Не проверен</span></div>${resultModeTabs()}<div class="empty-state">${icon("sparkle")}<h3>От разговора к выводам</h3><p>Запустите проверку по текущему чек-листу. Для каждого вывода будет показано объяснение и основание.</p><button class="button primary" data-action="evaluate" ${busy ? "disabled" : ""}>${icon(busy ? "refresh" : "sparkle", busy ? "spinner" : "")}${busy ? "Проверяем…" : "Проверить диалог"}</button><span class="badge">${esc(modelName())} · v${state.checklist.version}</span></div>`;
    return;
  }
  const s = e.final_score,
    unknown = e.answers.filter((a) => a.value == null).length,
    grossUnknown = e.checklist.criteria.some(
      (c) =>
        c.is_gross &&
        e.answers.find((a) => a.criterion_id === c.id)?.value == null,
    );
  $("#results-panel").innerHTML =
    `<div class="results-header"><h2>${r.channel === "voice call" ? "Оценка по транскрипту" : "Оценка чата"}</h2><span class="badge ${s.complete ? "green" : "amber"}">${s.complete ? "С итогом" : "На пересмотр"}</span></div>${resultModeTabs()}${e.checklist.version !== detail.current_version ? '<div class="stale-note">Чек-лист изменён. Оценка сохранена по версии ' + e.checklist.version + ". Запустите новую проверку.</div>" : ""}<div class="result-scroll"><div class="score-block"><div class="score-line"><div><div class="score-number">${fmt(s.total)} <small>/ 100</small></div><div class="score-caption">${s.complete ? "Итог с учётом решений проверяющего" : `Осталось оценить ${unknown} из ${e.answers.length} критериев`}</div></div><div class="score-annotation"><strong>${e.meta.provider === "rules" ? "Черновая проверка" : esc(e.meta.model)}</strong>${s.gross_error ? '<span class="badge red">Грубая ошибка</span>' : grossUnknown ? "Грубые ошибки: не проверены" : "Грубые ошибки: нет"}</div></div><progress max="100" value="${s.total ?? 0}" aria-label="Итоговый балл"></progress><div class="score-footnote"><span>Чек-лист v${e.checklist.version}</span><span>${s.complete ? `Применимый вес: ${fmt(s.applicable_weight)}` : "Неполная оценка не суммируется"}</span></div>${e.original_score.total !== s.total ? `<div class="review-note">Исходная оценка: ${fmt(e.original_score.total)} → после пересмотра: ${fmt(s.total)}</div>` : ""}</div>${renderSectionScores(s)}${renderInsights(e)}<div class="criteria-heading"><strong>Критерии оценки</strong><span>${e.answers.length} критериев</span></div>${e.checklist.criteria
      .map((c) =>
        criterionCard(
          c,
          e.answers.find((a) => a.criterion_id === c.id),
          e,
        ),
      )
      .join(
        "",
      )}${renderHistory(e)}</div><div class="results-bottom"><span>${e.meta.calls || 0} вызовов · ${e.meta.elapsed_seconds || 0} с${e.meta.cost_usd != null ? " · $" + e.meta.cost_usd.toFixed(5) : ""}</span><button class="button text" data-action="evaluate" ${busy ? "disabled" : ""}>${icon("refresh", busy ? "spinner" : "")}${busy ? "Проверяем…" : "Проверить заново"}</button></div>`;
}
function renderSectionScores(s) {
  return `<div class="section-scores">${Object.entries(s.sections)
    .map(
      ([name, value]) =>
        `<div class="section-score"><span>${esc(name)}</span><strong>${fmt(value)}</strong></div>`,
    )
    .join("")}</div>`;
}
function criterionCard(c, a, e) {
  if (!a) return "";
  const pending = a.value == null,
    no =
      (a.value === "Нет" && !c.is_gross) ||
      (a.value === "Да" && c.is_gross) ||
      a.value === 0;
  const appeals = e.appeals.filter((p) => p.criterion_id === c.id);
  return `<article class="criterion"><div class="criterion-top"><span class="criterion-dot ${pending ? "pending" : no ? "no" : ""}">${icon(pending ? "clock" : no ? "close" : "check")}</span><span class="criterion-name">${esc(c.name)}</span><span class="criterion-value ${no ? "no" : ""}">${pending ? "Не оценён" : esc(a.value)}${typeof a.value === "number" ? " / " + c.scale_max : ""}<small class="criterion-weight">${c.is_gross ? "Отдельный флаг" : "Вес " + c.weight}</small></span></div><p class="criterion-reason">${esc(a.reason)}</p>${a.evidence.map((ev) => `<button class="evidence-link" data-action="evidence" data-index="${ev.message_index}" data-end="${ev.end_message_index || ev.message_index}" aria-label="Перейти к сообщению ${ev.message_index}">${icon("link")}<span class="evidence-quote">#${ev.message_index}${ev.end_message_index > ev.message_index ? "–" + ev.end_message_index : ""} · «${esc(ev.quote)}»</span></button>`).join("")}${a.review_reason ? `<div class="review-note">${icon("shield")} Решение проверяющего: ${esc(a.review_reason)}</div>` : ""}${appeals
    .filter((p) => p.status === "open")
    .map(
      (p) =>
        `<div class="appeal-card"><strong>Открытая апелляция</strong><p>${esc(p.comment)}</p><button class="button secondary small" data-action="resolve" data-id="${p.id}">Рассмотреть</button></div>`,
    )
    .join(
      "",
    )}<div class="criterion-footer"><span>${a.review_reason ? "Решение проверяющего" : a.needs_review ? "Нужна проверка" : "Цитата проверена по транскрипту"}</span><button class="appeal-button" data-action="appeal" data-id="${c.id}">${pending ? "Заполнить при пересмотре" : "Оспорить оценку"}</button></div></article>`;
}
function renderHistory(e) {
  return `<div class="section-card"><details><summary>История решений · ${e.appeals.length}</summary><div class="timeline">${e.appeals.length ? e.appeals.map((a) => `<div class="timeline-item"><strong>Критерий ${a.criterion_id} · ${a.status === "open" ? "Апелляция открыта" : "Решение сохранено"}</strong>${esc(a.comment)}${a.reason ? `<br>Решение: ${esc(a.value ? JSON.parse(a.value) : "")} · ${esc(a.reason)}` : ""}<br><small>${esc(new Date(a.created_at).toLocaleString("ru-RU"))}</small></div>`).join("") : "<p>Решений пока нет.</p>"}</div></details>${detail.history.length ? `<details><summary>Предыдущие проверки · ${detail.history.length}</summary>${detail.history.map((h) => `<p>Проверка #${h.id} · v${h.checklist.version} · ${esc(h.meta.model)} · ${fmt(h.final_score.total)}/100</p>`).join("")}</details>` : ""}</div>`;
}
function jumpEvidence(index, end) {
  if (!showContext) {
    showContext = true;
    renderTranscript();
  }
  document
    .querySelectorAll(".message.highlight")
    .forEach((n) => n.classList.remove("highlight"));
  for (let i = index; i <= end; i++)
    $("#message-" + i)?.classList.add("highlight");
  const message = $("#message-" + index);
  const pane = $("#messages");
  if (message && pane) {
    const offset =
      message.getBoundingClientRect().top - pane.getBoundingClientRect().top;
    pane.scrollTo({
      top: pane.scrollTop + offset - pane.clientHeight / 3,
      behavior: "smooth",
    });
  }
}
async function evaluateSelected() {
  if (
    !selected ||
    !detail ||
    detail.record.conversation_id !== selected ||
    busy
  )
    return;
  busy = true;
  try {
    const result = await api("jobs", { conversation_ids: [selected] });
    await pollJobs();
    toast(
      result.created.length
        ? "Диалог добавлен в очередь. Можно продолжать работу."
        : "Этот диалог уже ожидает обработки.",
    );
  } finally {
    busy = false;
    if (detail) {
      renderResults();
      renderQueueBanner();
    }
  }
}
async function batch() {
  if (busy) return;
  const records = filtered();
  if (!records.length) return toast("Нет диалогов для проверки");
  pendingBatch = records.map((r) => r.conversation_id);
  modal(
    "Поставить выборку в очередь",
    `<p>По текущим фильтрам найдено ${records.length} диалогов. Каждый выбранный диалог вызовет модель один раз. Версия чек-листа и настройки модели фиксируются при добавлении.</p><label class="field">Сколько диалогов обработать<input id="batch-limit" type="number" min="1" max="${records.length}" value="${Math.min(3, records.length)}"></label><div class="form-help">Можно обновлять страницу: обработка выполняется на сервере. При ошибке запрос не повторяется автоматически.</div>`,
    `<button class="button secondary" data-action="close-modal">Отмена</button><button class="button primary" data-action="submit-batch">Добавить задания</button>`,
  );
}
async function submitBatch() {
  const limit = Number($("#batch-limit").value);
  if (!Number.isInteger(limit) || limit < 1 || limit > pendingBatch.length)
    throw new Error("Укажите допустимое количество диалогов");
  const result = await api("jobs", {
    conversation_ids: pendingBatch.slice(0, limit),
  });
  $("#modal").close();
  await pollJobs();
  switchView("queue");
  toast(
    `Добавлено: ${result.created.length}. Уже в очереди: ${result.existing.length}.`,
  );
}
function switchView(next) {
  view = next;
  document
    .querySelectorAll(".view")
    .forEach((el) => el.classList.toggle("active", el.id === "view-" + next));
  document
    .querySelectorAll("[data-view]")
    .forEach((el) => el.classList.toggle("active", el.dataset.view === next));
  const titles = {
    dialogs: [
      "Диалоги",
      "Качество начинается с диалога",
      "Оценивайте работу оператора. Проверяйте доказательства. Принимайте взвешенные решения.",
    ],
    checklist: [
      "Чек-лист",
      "Правила, которые можно изменить",
      "Настройте критерии и сохраните новую версию. Предыдущие оценки останутся в истории.",
    ],
    analytics: [
      "Обзор качества",
      "Видеть общую картину",
      "Темы обращений, повторные затруднения и сравнение запусков с переходом к исходным репликам.",
    ],
    queue: [
      "Очередь",
      "Обработка продолжается в фоне",
      "Задания сохраняются на сервере. Обновление страницы не прерывает проверку.",
    ],
    help: [
      "Как пользоваться",
      "От первого запуска до защиты",
      "Пошаговая инструкция, устройство системы и честные формулировки для презентации.",
    ],
    submission: [
      "Сдача жюри",
      "Результаты в официальном формате",
      "JSON 1.0: все ID набора, исходные оценки AI и явные ошибки обработки.",
    ],
  };
  $("#breadcrumb").textContent = titles[next][0];
  $("#page-title").innerHTML = esc(titles[next][1]) + "<span>.</span>";
  $("#page-description").textContent = titles[next][2];
  $(".heading-actions").classList.toggle("hidden", next !== "dialogs");
  if (next === "checklist") {
    draft = structuredClone(state.checklist);
    renderChecklist();
  }
  renderStats();
  if (next === "analytics") renderAnalytics();
  if (next === "queue") renderQueue();
  if (next === "help") renderHelp();
  if (next === "submission")
    loadSubmission().catch((error) => toast(error.message));
}
function activeJob(kind = "text") {
  return jobsState.jobs.find(
    (j) =>
      j.conversation_id === selected && (j.kind || "text") === kind &&
      ["queued", "running", "waiting_key", "paused"].includes(j.status),
  );
}
function renderQueueBanner() {
  const c = jobsState.counts,
    active = (c.queued || 0) + (c.running || 0) + (c.waiting_key || 0),
    problem = queueProblem();
  $("#queue-count").textContent = active;
  $("#queue-banner").classList.toggle("hidden", !active && !problem);
  $("#queue-banner").classList.toggle("queue-warning", !!problem);
  $("#queue-banner").innerHTML =
    `${icon(problem ? "info" : c.running ? "refresh" : "clock", c.running ? "spinner" : "")}<span>${problem ? esc(problem) : `В работе: <strong>${c.running || 0}</strong> · ожидают: <strong>${c.queued || 0}</strong> · нужен ключ: <strong>${c.waiting_key || 0}</strong>`}</span><button class="button text" data-view="queue">Открыть очередь →</button>`;
  if (detail) {
    const audioJob = activeJob("audio");
    document.querySelectorAll('[data-action="analyze-audio"]').forEach(b => {
      b.disabled = !!audioJob;
      b.innerHTML = icon(audioJob ? "clock" : "sparkle") + (audioJob ? esc(jobLabels[audioJob.status]) : detail.audio_analysis ? "Проанализировать звук заново" : "Проанализировать звук");
    });
    const latestAudioJob = jobsState.jobs.find(j => j.conversation_id === selected && j.kind === "audio");
    const audioMessage = $("#audio-job-status");
    if (audioMessage) audioMessage.textContent = latestAudioJob && ["failed","interrupted"].includes(latestAudioJob.status) ? latestAudioJob.error : "";
    const job = activeJob();
    document.querySelectorAll('[data-action="evaluate"]').forEach((b) => {
      b.disabled = !!job || busy;
      if (job) b.innerHTML = icon("clock") + esc(jobLabels[job.status]);
    });
  }
}
function queueProblem() {
  if (jobsConnectionError)
    return "Не удалось обновить очередь. " + jobsConnectionError;
  const worker = jobsState.worker;
  if (!worker) return null;
  if (!worker.alive)
    return "Обработчик очереди остановлен. Перезапустите сервер; ожидающие задания сохранены.";
  return worker.error || null;
}
function renderQueue() {
  const c = jobsState.counts;
  $("#view-queue").innerHTML =
    `<div class="section-card"><div class="editor-header"><div><h2>Задания обработки</h2><p>Счётчики за всё время. Показаны последние 300 заданий. Выполняется один запрос модели одновременно.</p></div><button class="button secondary" data-action="refresh-jobs">${icon("refresh")}Обновить</button></div><p class="${queueProblem() ? "submission-warning" : ""}">${esc(queueProblem() || (jobsState.worker ? "Обработчик работает. Задания выполняются последовательно." : "Получаем состояние обработчика…"))}</p><div class="queue-counters">${["queued", "running", "waiting_key", "completed", "failed", "interrupted", "paused"].map((s) => `<span class="badge ${["failed", "interrupted"].includes(s) ? "red" : s === "completed" ? "green" : ""}">${jobLabels[s]}: ${c[s] || 0}</span>`).join("")}</div><div class="table-scroll"><table class="data-table"><thead><tr><th>ЗАДАНИЕ / ДИАЛОГ</th><th>СТАТУС</th><th>МОДЕЛЬ / ЧЕК-ЛИСТ</th><th>ПОДРОБНОСТИ</th><th>ДЕЙСТВИЯ</th></tr></thead><tbody>${jobsState.jobs.length ? jobsState.jobs.map((j) => `<tr><td>#${j.id}<br><button data-action="open-result" data-id="${esc(j.conversation_id)}">${esc(j.conversation_id)}</button></td><td><span class="badge ${j.status === "completed" ? "green" : ["failed", "interrupted"].includes(j.status) ? "red" : "amber"}">${esc(jobLabels[j.status] || j.status)}</span></td><td>${esc(j.model || "Правила")}<br><small>${j.kind === "audio" ? "Звук · отдельный анализ" : "Чек-лист v" + j.checklist_version} · попыток ${j.attempts}</small></td><td class="job-error">${esc(j.error || (j.audio_analysis_id ? "Аудиоанализ #" + j.audio_analysis_id : j.evaluation_id ? "Результат #" + j.evaluation_id : "Создано " + new Date(j.created_at).toLocaleString("ru-RU")))}</td><td>${["failed", "interrupted"].includes(j.status) ? `<button class="button secondary small" data-action="retry-job" data-id="${j.id}">Повторить</button>` : ""}${["queued", "waiting_key", "paused", "failed", "interrupted"].includes(j.status) ? `<button class="button text" data-action="cancel-job" data-id="${j.id}">Отменить</button>` : ""}${j.status === "waiting_key" ? '<button class="button text" data-action="settings">Добавить ключ</button>' : ""}${j.status === "running" ? "Запрос уже отправлен" : ""}${j.status === "paused" ? '<button class="button text" data-action="resume-jobs">Возобновить очередь</button>' : ""}</td></tr>`).join("") : '<tr><td colspan="5">Очередь пуста. Выберите диалог и нажмите «Проверить диалог».</td></tr>'}</tbody></table></div></div>`;
}
async function pollJobs() {
  if (pollBusy) return;
  pollBusy = true;
  try {
    const next = await api("jobs"),
      worker = next.worker,
      hash = JSON.stringify({
        jobs: next.jobs,
        counts: next.counts,
        worker: worker
          ? {
              alive: worker.alive,
              state: worker.state,
              error: worker.error,
              job_id: worker.job_id,
            }
          : null,
      }),
      wasDisconnected = !!jobsConnectionError;
    jobsConnectionError = null;
    if (hash !== jobsHash || wasDisconnected) {
      const previous = new Map(jobsState.jobs.map((j) => [j.id, j.status]));
      jobsState = next;
      jobsHash = hash;
      if (
        next.jobs.some(
          (j) =>
            j.conversation_id === selected &&
            j.status === "completed" &&
            previous.get(j.id) !== "completed",
        )
      )
        needsDetailRefresh = true;
      await refresh();
      if (view === "queue") renderQueue();
      renderQueueBanner();
    }
    if (needsDetailRefresh && !$("#modal").open && selected) {
      const id = selected,
        serial = selectionSerial;
      const incoming = await api("conversations/" + encodeURIComponent(id));
      if (id !== selected || serial !== selectionSerial || $("#modal").open)
        return;
      detail = incoming;
      needsDetailRefresh = false;
      renderDetail();
      renderQueueBanner();
    }
  } catch (error) {
    jobsConnectionError = error.message;
    renderQueueBanner();
    if (view === "queue") renderQueue();
  } finally {
    pollBusy = false;
  }
}
function evidenceButtons(items) {
  return (items || [])
    .map(
      (ev) =>
        `<button class="evidence-link" data-action="evidence" data-index="${ev.message_index}" data-end="${ev.end_message_index || ev.message_index}" aria-label="Перейти к сообщению ${ev.message_index}">${icon("link")}<span class="evidence-quote">#${ev.message_index} · «${esc(ev.quote)}»</span></button>`,
    )
    .join("");
}
function renderRequestAnalysis(e) {
  const items = e.meta.request_analysis || [];
  const labels = {answered:"Оператор ответил",follow_up:"Обещано продолжение",unanswered:"Остался без ответа",not_enough_data:"Недостаточно данных"};
  const warning = e.meta.outcome_conflict ? '<p class="submission-warning">Общий итог и отдельные вопросы расходятся. Проверьте выводы модели по репликам.</p>' : "";
  return items.length ? `<section class="insights"><details open><summary>Отдельные вопросы клиента · ${items.length}</summary><p class="review-note">AI-разбор может пропускать вопросы: проверьте полноту по исходному тексту. Подтверждение банковской операции требует внешних данных.</p>${warning}${items.map(r => `<article class="recommendation"><span class="badge ${r.status === "answered" ? "green" : "amber"}">${labels[r.status]}</span><p><strong>${esc(r.request)}</strong></p>${evidenceButtons(r.request_evidence)}${evidenceButtons(r.answer_evidence)}</article>`).join("")}</details></section>` : (e.meta.requests_error ? `<p class="review-note">Разбор вопросов не прошёл проверку: ${esc(e.meta.requests_error)}. Оценки критериев сохранены.</p>` : "");
}
function renderInsights(e) {
  const requests = renderRequestAnalysis(e);
  if (!e.insights)
    return `<div class="insight-empty">${icon("info")}<span>${e.meta.insights_error ? "Резюме и рекомендации не прошли проверку: " + esc(e.meta.insights_error) + ". Оценки критериев сохранены." : "В этой проверке нет резюме и рекомендаций. Они формируются при новом запуске модели."}</span></div>${requests}`;
  const s = e.insights.summary,
    labels = {
      resolved: "Вопрос решён",
      follow_up: "Ожидается продолжение",
      unresolved: "Вопрос не решён",
      not_enough_data: "Недостаточно данных",
    };
  return `<section class="insights"><p class="review-note">AI-резюме и советы: проверьте выводы по исходным репликам.</p><details open><summary>Суть разговора <span class="badge ${s.status === "resolved" ? "green" : "amber"}">${labels[s.status]}</span></summary><dl><dt>Запрос клиента</dt><dd>${esc(s.request)}</dd><dt>Действия оператора</dt><dd>${esc(s.actions)}</dd><dt>Результат</dt><dd>${esc(s.outcome)}</dd></dl><details class="insight-sources"><summary>Основания резюме</summary>${evidenceButtons(s.evidence)}</details></details><details class="recommendations" ${e.insights.recommendations.length ? "open" : ""}><summary>Рекомендации · ${e.insights.recommendations.length}</summary>${e.appeals.some((a) => a.status === "resolved") ? '<p class="review-note">Советы сформированы по исходной AI-оценке. Сопоставьте их с последующими решениями проверяющего.</p>' : ""}${e.insights.recommendations.length ? e.insights.recommendations.map((r) => `<article class="recommendation"><span class="badge">Критерий ${r.criterion_id}</span><p><strong>Проблема:</strong> ${esc(r.issue)}</p><p><strong>Что улучшить:</strong> ${esc(r.action)}</p>${evidenceButtons(r.evidence)}</article>`).join("") : '<p class="review-note">По исходной оценке нарушений не обнаружено. Это не заменяет независимую проверку.</p>'}</details></section>${requests}`;
}
function renderHelp() {
  $("#view-help").innerHTML =
    `<div class="help-grid"><article class="section-card"><span class="eyebrow">01 · НАЧАЛО РАБОТЫ</span><h2>Подключите данные и модель</h2><ol><li>В «Настройки модели» выберите Gemini, укажите ключ и сохраните. После перезапуска сервера ключ вводится заново.</li><li>«Загрузить данные» принимает JSON или получает группу DEV / контроль через API организаторов.</li><li>В списке найдите диалог по ID или тексту запроса. Фильтры ограничивают будущую выборку.</li></ol></article><article class="section-card"><span class="eyebrow">02 · ПРОВЕРКА</span><h2>Запустите и проверьте результат</h2><ol><li>«Проверить диалог» создаёт фоновое задание. «Проверить выборку» позволяет выбрать количество отфильтрованных диалогов.</li><li>В «Очередь» видны прогресс и ошибки. Можно обновлять страницу. Сервер должен продолжать работать.</li><li>В карточке появятся балл, резюме, рекомендации и оценки критериев. Нажатие на цитату выделяет исходные реплики.</li></ol></article><article class="section-card"><span class="eyebrow">03 · ПЕРЕСМОТР</span><h2>Оспорьте оценку</h2><ol><li>Нажмите «Оспорить оценку» рядом с критерием и опишите причину.</li><li>Нажмите «Рассмотреть», выберите ответ и напишите обоснование решения.</li><li>Итог пересчитается. Исходная оценка и все решения останутся в истории; рекомендации относятся к исходному анализу.</li></ol></article><article class="section-card"><span class="eyebrow">04 · НАСТРОЙКИ</span><h2>Измените чек-лист и сохраните результат</h2><ol><li>В «Чек-лист» меняйте правило, вес, ступени и доступность N/A, добавляйте критерии. Сохранение создаёт новую версию.</li><li>Запустите новую проверку: готовые оценки и уже поставленные задания сохраняют прежнюю версию.</li><li>«Обзор качества» показывает карту тем и нарушений. Нажмите ячейку, чтобы открыть диалоги и цитаты. Сравнение запусков находится ниже. Кнопка экспорта сверху сохраняет JSON с оценками, резюме, рекомендациями и решениями.</li></ol></article><article class="section-card"><h2>Как система получает результат</h2><p>API организаторов → исходный транскрипт → очередь → модель с текущим чек-листом → проверка значений и цитат → расчёт баллов кодом → сохранение в SQLite → интерфейс и апелляции.</p><p>Мы используем готовую модель. Собственные части проекта — интерфейс, очередь, редактор правил, проверка ответа, расчёт, хранение и процесс пересмотра.</p></article><article class="section-card"><h2>Что честно сказать жюри</h2><p>Начальная проверка: 6 диалогов, 48 ответов, 45 совпадений с предварительной разметкой ассистента. Это не точность на эталоне жюри. A/B ещё не завершён.</p><p>Цитаты проверяются по существованию и точности текста, но их смысловую достаточность проверяет человек. Тарифы без базы знаний и интонацию без аудио система не должна выдумывать. Очередь повышает надёжность, а не гарантирует ускорение модели.</p></article></div>`;
}
function renderChecklist() {
  if (!draft) return;
  $("#view-checklist").innerHTML =
    `<div class="section-card"><div class="editor-header"><div><input id="checklist-name" aria-label="Название чек-листа" value="${esc(draft.name)}"><span class="badge">Текущая версия: ${draft.version}</span></div><div class="editor-actions"><button class="button secondary" data-action="add-criterion">${icon("plus")}Добавить критерий</button><button class="button primary" data-action="save-checklist">${icon("check")}Сохранить версию</button></div></div><div class="editor-grid">${draft.criteria.map((c) => `<article class="criterion-editor" data-criterion="${c.id}"><div class="criterion-editor-head"><strong>КРИТЕРИЙ ${c.id}</strong><button class="icon-button" data-action="remove-criterion" data-id="${c.id}" aria-label="Удалить критерий ${c.id}">${icon("close")}</button></div><label class="field">Название<input data-field="name" value="${esc(c.name)}"></label><label class="field">Правило оценки и условие N/A<textarea data-field="description" rows="4">${esc(c.description)}</textarea></label><div class="form-row"><label class="field">Вес<input data-field="weight" type="number" min="0" max="100" step="0.5" value="${c.weight}"></label><label class="field">Ответы через запятую<input data-field="allowed" value="${esc(c.allowed_values.join(", "))}"><small>Да, Нет, N/A или 0, 5, 10, 15, 20</small></label></div><label class="field">Секция<input data-field="section" value="${esc(c.section || "Общее")}"></label><label class="toggle"><input type="checkbox" data-field="is_gross" ${c.is_gross ? "checked" : ""}>Отдельный флаг грубой ошибки (вес 0)</label></article>`).join("")}</div><div class="editor-foot">${icon("info")}Вес N/A пропорционально перераспределяется. Обновлённый критерий применяется при новой проверке.</div></div>`;
}
function collectChecklist() {
  draft.name = $("#checklist-name").value.trim();
  document.querySelectorAll("[data-criterion]").forEach((node) => {
    const c = draft.criteria.find(
      (c) => c.id === Number(node.dataset.criterion),
    );
    for (const field of ["name", "description", "section"])
      c[field] = node.querySelector(`[data-field="${field}"]`).value.trim();
    c.weight = Number(node.querySelector('[data-field="weight"]').value);
    c.is_gross = node.querySelector('[data-field="is_gross"]').checked;
    c.allowed_values = node
      .querySelector('[data-field="allowed"]')
      .value.split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map((s) => (/^\d+(\.\d+)?$/.test(s) ? Number(s) : s));
    const nums = c.allowed_values.filter((v) => typeof v === "number");
    c.scale_max = nums.length ? Math.max(...nums) : null;
  });
  return draft;
}
async function saveChecklist() {
  collectChecklist();
  await api("checklist", draft);
  await refresh();
  draft = structuredClone(state.checklist);
  renderChecklist();
  if (selected) {
    detail = await api("conversations/" + encodeURIComponent(selected));
    renderDetail();
  }
  toast("Новая версия сохранена. Примените её новой проверкой диалога.");
}
let analyticsData = null, analyticsRequest = 0;
const analyticsFilters = {dataset_group: "", language: "", channel: ""};
let analyticsSelection = {topic: "", criterion: null, outcome: "", friction: false};
const outcomeLabels = {resolved: "Вопрос решён по тексту", follow_up: "Обещано продолжение", unresolved: "Остались вопросы", not_enough_data: "Недостаточно данных", not_analyzed: "Без AI-резюме"};
async function renderAnalytics() {
  const request = ++analyticsRequest;
  if (!analyticsData) $("#view-analytics").innerHTML = '<div class="section-card"><p>Загружаем карту проблем…</p></div>';
  try {
    const data = await api("analytics?" + new URLSearchParams(analyticsFilters));
    if (request !== analyticsRequest || view !== "analytics") return;
    analyticsData = data;
    renderAnalyticsData();
  } catch (error) {
    if (request !== analyticsRequest || view !== "analytics") return;
    $("#view-analytics").innerHTML = `<div class="section-card"><h2>Аналитика недоступна</h2><p>${esc(error.message)}</p><button class="button secondary" data-action="analytics-refresh">Повторить</button></div>`;
  }
}
function analyticsEvidence(cid, items) {
  return (items || []).map(ev => `<button class="evidence-link" data-action="open-evidence" data-id="${esc(cid)}" data-index="${ev.message_index}" data-end="${ev.end_message_index || ev.message_index}">#${ev.message_index} · «${esc(ev.quote)}» ↗</button>`).join("");
}
function renderAnalyticsData() {
  const d = analyticsData, c = d.coverage, sel = analyticsSelection;
  const chosenTopic = d.topics.find(t => t.id === sel.topic);
  const chosenCriterion = d.criteria.find(t => t.id === sel.criterion);
  const rows = d.rows.filter(r => (!sel.topic || r.topics.some(t => t.id === sel.topic)) && (sel.criterion == null || r.failed.some(f => f.id === sel.criterion)) && (!sel.outcome || r.outcome === sel.outcome) && (!sel.friction || r.friction.length));
  const label = [chosenTopic?.label, chosenCriterion && "Нарушение К" + chosenCriterion.id, sel.outcome && outcomeLabels[sel.outcome], sel.friction && "Признаки затруднений"].filter(Boolean).join(" · ") || "Все диалоги выборки";
  const comparison = d.comparison;
  const groupName = id => {const g = comparison.groups.find(g => g.id === id); return g ? `${g.model} · ${g.prompt_version} · ${g.variant} · ${g.reasoning_effort || "default"}` : "—";};
  $("#view-analytics").innerHTML = `
    <div class="section-card analytics-intro"><div class="editor-header"><div><h2>От оценки к причине</h2><p>Карта по исходным AI-оценкам актуального чек-листа. Нажмите на тему или ячейку, чтобы проверить конкретные диалоги.</p></div><button class="button secondary" data-action="analytics-refresh">${icon("refresh")}Обновить</button></div>
    <div class="analytics-filters">${[["dataset_group","Набор данных"],["language","Язык"],["channel","Канал"]].map(([key,name]) => `<label class="field">${name}<select data-analytics-filter="${key}" aria-label="Аналитика: ${name}"><option value="">Все</option>${d.options[key].map(v => `<option value="${esc(v)}" ${analyticsFilters[key] === v ? "selected" : ""}>${esc(key === "channel" ? ({"agent chat":"Чаты","voice call":"Звонки"}[v] || v) : v)}</option>`).join("")}</select></label>`).join("")}</div></div>
    <div class="analytics-grid analytics-coverage"><article class="section-card"><span class="eyebrow">ПОКРЫТИЕ ОЦЕНКОЙ</span><h2>${c.evaluated} <small>/ ${c.total}</small></h2><p>Полные AI-оценки текущих правил. Без оценки: ${c.total-c.evaluated}; устаревших: ${c.stale}.</p></article><article class="section-card"><span class="eyebrow">РАЗБОР ВОПРОСОВ</span><h2>${c.requests} <small>/ ${c.total}</small></h2><p>Диалоги с AI-разбором вопросов. Резюме: ${c.summaries}. Полноту разбора проверяет человек.</p></article><article class="section-card"><span class="eyebrow">СИГНАЛЫ ЗАТРУДНЕНИЙ</span><h2>${c.friction} <small>/ ${c.total}</small></h2><p>Повторы после оператора и явное непонимание. Проверяемая эвристика, без штрафа за длину.</p><button class="button text" data-action="analytics-friction">Показать диалоги ↘</button></article></div>
    <div class="section-card"><h2>Темы × нарушения критериев</h2><p>Темы определяются по словам в репликах клиента на RU / KZ / EN; у диалога может быть несколько тем. Ячейка: нарушения / применимые оценки, N/A исключены. «—» означает отсутствие оценок. К${d.criteria.find(x=>x.is_gross)?.id ?? "8"} — отдельный флаг грубой ошибки.</p><div class="table-scroll"><table class="data-table problem-map"><thead><tr><th>ТЕМА / ДИАЛОГИ</th>${d.criteria.map(x => `<th title="${esc(x.name)}">К${x.id}<span>${esc(x.name)}</span></th>`).join("")}</tr></thead><tbody>${d.topics.map(t => `<tr><td><button class="topic-link" data-action="analytics-cell" data-topic="${t.id}">${esc(t.label)}</button><small>${t.total} диалогов · оценено ${t.evaluated}</small></td>${t.cells.map(cell => `<td><button class="map-cell ${cell.failed ? "has-failures" : ""}" data-action="analytics-cell" data-topic="${t.id}" data-criterion="${cell.criterion_id}" ${cell.failed ? "" : "disabled"} aria-label="${esc(t.label)}, критерий ${cell.criterion_id}: нарушений ${cell.failed} из ${cell.applicable}">${cell.applicable ? `${cell.failed} / ${cell.applicable}` : "—"}</button></td>`).join("")}</tr>`).join("")}</tbody></table></div></div>
    <div class="section-card"><h2>Итог разговора по тексту</h2><p>AI-резюме отражает только транскрипт. Обещанный следующий шаг ещё не подтверждает решение в банковской системе.</p><div class="outcome-filters">${Object.entries(outcomeLabels).map(([key,name]) => `<button class="button secondary ${sel.outcome === key ? "selected-filter" : ""}" data-action="analytics-outcome" data-outcome="${key}">${name} · ${d.outcomes[key] || 0}</button>`).join("")}</div></div>
    <div class="section-card" id="analytics-drilldown"><div class="editor-header"><div><h2>${esc(label)}</h2><p>Найдено: ${rows.length}. Цитаты открывают исходный транскрипт.</p></div><button class="button text" data-action="analytics-reset">Сбросить отбор</button></div><div class="analytics-examples">${rows.length ? rows.map(r => `<article class="analytics-example"><div class="example-head"><button data-action="open-result" data-id="${esc(r.conversation_id)}">${esc(r.conversation_id)} ↗</button><span class="badge">${esc(r.language)} · ${esc(r.channel)}</span><span class="badge ${r.evaluated ? "green" : ""}">${r.evaluated ? fmt(r.score) + " / 100" : "Без актуальной AI-оценки"}</span></div><p>${esc(r.preview)}</p><small>${r.topics.map(t => esc(t.label)).join(" · ")} · ${outcomeLabels[r.outcome]}</small>${r.outcome_conflict ? '<p class="submission-warning">Резюме и разбор отдельных вопросов расходятся — нужен пересмотр.</p>' : ""}${sel.criterion != null ? r.failed.filter(f => f.id === sel.criterion).map(f => analyticsEvidence(r.conversation_id,f.evidence)).join("") : chosenTopic ? analyticsEvidence(r.conversation_id,r.topics.find(t => t.id === sel.topic)?.evidence.slice(0,1)) : ""}${r.friction.map(f => `<details><summary>${esc(f.label)} · проверить</summary>${analyticsEvidence(r.conversation_id,f.evidence)}</details>`).join("")}</article>`).join("") : '<p>Диалогов с таким сочетанием фильтров нет.</p>'}</div></div>
    ${renderAudioOverview(d.audio)}
    <div class="section-card"><h2>Сравнение запусков модели</h2><p>Группы учитывают модель, версию промпта, вариант, режим рассуждения и чек-лист. Успех означает прохождение проверки критериев по структуре и цитатам, а не подтверждённую правильность. Дополнительные блоки могут отсутствовать. Это наблюдение, а не завершённый A/B-тест. Журнал всех попыток ведётся с версии 0.5; для старых запусков известны только сохранённые ответы.</p><div class="table-scroll"><table class="data-table comparison-table"><thead><tr><th>КОНФИГУРАЦИЯ</th><th>СОХРАНЕНО / ДИАЛОГОВ</th><th>НОВЫЙ ЖУРНАЛ</th><th>СРЕДНЕЕ ВРЕМЯ</th><th>ТОКЕНЫ ВХОД / ВЫХОД</th><th>ИЗВЕСТНЫЙ РАСХОД</th></tr></thead><tbody>${comparison.groups.map(g => `<tr><td><strong>${esc(g.model)}</strong><br>${esc(g.provider)} · ${esc(g.prompt_version)} · ${esc(g.variant)}<br><small>${esc(g.reasoning_effort || "default")} · правила ${esc((g.checklist_hash || "?").slice(0,8))}</small></td><td>${g.saved_evaluations} / ${g.unique_conversations}<br><small>Старых ответов: ${g.legacy_saved}</small></td><td>Успех: ${g.completed}; ошибки: ${g.failed}<br><small>Прервано: ${g.interrupted}; в работе: ${g.running}; всего: ${g.traced_attempts}</small></td><td>${fmt(g.mean_seconds)} с<br><small>Измерено: ${g.latency_known}/${g.traced_attempts}</small></td><td>${g.usage_known ? fmt(g.input_tokens) + " / " + fmt(g.output_tokens) : "—"}<br><small>Расход известен: ${g.usage_known}/${g.traced_attempts}</small></td><td>${g.known_cost_usd == null ? "—" : "$" + g.known_cost_usd}<br><small>Цена и токены известны: ${g.cost_known}/${g.traced_attempts}</small></td></tr>`).join("") || '<tr><td colspan="6">Нет запусков модели.</td></tr>'}</tbody></table></div>
    <h3>Одни диалоги, разные конфигурации</h3><p>Сравниваем последние сохранённые ответы каждой конфигурации на общих ID при одинаковом чек-листе. Расхождение не определяет, какая модель права.</p>${comparison.paired.map(pair => `<details class="paired-comparison"><summary>${esc(groupName(pair.left))} ↔ ${esc(groupName(pair.right))}</summary><p>Общих диалогов: ${pair.conversations}; расхождений по критериям: ${pair.different} / ${pair.criteria}.</p>${pair.examples.map(ex => `<button class="button secondary small" data-action="compare-example" data-id="${esc(ex.conversation_id)}" data-left="${ex.left_evaluation_id}" data-right="${ex.right_evaluation_id}">${esc(ex.conversation_id)} · К${ex.criteria.join(", К")}</button>`).join("")}</details>`).join("") || '<p>Пока нет общих диалогов у разных конфигураций.</p>'}</div>
    <div class="section-card"><h2>Границы выводов</h2><p>Это анализ предоставленного набора, в котором чаты синтетические. Частоты описывают эту выборку. В данных нет CRM-результатов, CSAT и идентификатора клиента: FCR, отток, денежный эффект и склейка сессий здесь не измеряются. Апелляции доступны в карточке диалога; эта карта использует исходную AI-оценку.</p></div>`;
}
async function compareExample(button) {
  const d = await api("conversations/" + encodeURIComponent(button.dataset.id));
  const history = [d.evaluation,...d.history].filter(Boolean);
  const left = history.find(e => e.id === Number(button.dataset.left));
  const right = history.find(e => e.id === Number(button.dataset.right));
  if (!left || !right) throw new Error("Сохранённые оценки не найдены");
  const blocks = left.original_answers.filter(a => a.value !== right.original_answers.find(b => b.criterion_id === a.criterion_id)?.value).map(a => {
    const b = right.original_answers.find(b => b.criterion_id === a.criterion_id);
    return `<article class="recommendation"><h3>К${a.criterion_id}</h3>${[[left,a],[right,b]].map(([e,x]) => `<p><strong>${esc(e.meta.model)} · ${esc(e.meta.prompt_version || "legacy")} · ${esc(e.meta.reasoning_effort || "default")}: ${esc(String(x.value))}</strong></p><p>${esc(x.reason)}</p>${analyticsEvidence(d.record.conversation_id,x.evidence)}`).join("")}</article>`;
  }).join("");
  modal("Расхождения: " + d.record.conversation_id, `<p>Это сравнение исходных ответов, без решений по апелляциям.</p>${blocks}`);
}
function modal(title, body, footer = "") {
  const dialog = $("#modal");
  $("#modal-content").innerHTML =
    `<div class="modal-heading"><h2>${esc(title)}</h2><button class="icon-button" data-action="close-modal" aria-label="Закрыть">${icon("close")}</button></div><div class="modal-body">${body}<div id="modal-error" class="modal-error" role="alert"></div></div>${footer ? `<div class="modal-footer">${footer}</div>` : ""}`;
  dialog.showModal();
}
async function settingsModal() {
  settings = await api("settings");
  modal(
    "Подключение модели",
    `<p>Ключ используется только сервером и хранится в памяти до его перезапуска. В экспорт и базу данных он не попадает.</p><form id="settings-form"><label class="field">Провайдер<select id="provider">${[
      ["rules", "Проверка правил — без модели"],
      ["gemini", "Gemini · Google AI Studio"],
      ["openai", "OpenAI Responses API"],
      ["compatible", "Совместимый Chat Completions API"],
      ["ollama", "Локальная модель · Ollama"],
    ]
      .map(
        ([v, n]) =>
          `<option value="${v}" ${settings.provider === v ? "selected" : ""}>${n}</option>`,
      )
      .join(
        "",
      )}</select></label><label class="field">Режим Gemini для текста<select id="reasoning-effort"><option value="low" ${!["default","medium","high"].includes(settings.reasoning_effort) ? "selected" : ""}>Быстрый — low</option><option value="medium" ${settings.reasoning_effort === "medium" ? "selected" : ""}>Подробный — medium</option><option value="high" ${settings.reasoning_effort === "high" ? "selected" : ""}>Подробный — high</option><option value="default" ${settings.reasoning_effort === "default" ? "selected" : ""}>Стандартный режим модели</option></select><small>Влияет на рассуждение Gemini. Скорость и качество нужно проверять на данных.</small></label><label class="field">Базовый URL<input id="base-url" type="url" required value="${esc(settings.base_url)}"></label><label class="field">Название модели<input id="model-name" placeholder="Точное имя модели у провайдера" value="${esc(settings.model)}"></label><label class="field">API-ключ<input id="api-key" type="password" autocomplete="off" placeholder="${settings.key_configured ? "Ключ уже задан; оставьте пустым для сохранения" : "Ключ доступа к модели"}"><small>Для локальной Ollama ключ обычно не нужен.</small></label><div class="form-row"><label class="field">Вход, $ за 1 млн токенов<input id="input-price" type="number" min="0" step="0.001" value="${settings.input_price ?? ""}" placeholder="Неизвестно"></label><label class="field">Выход, $ за 1 млн токенов<input id="output-price" type="number" min="0" step="0.001" value="${settings.output_price ?? ""}" placeholder="Неизвестно"></label></div><div class="form-help">Текстовая проверка отправляет модели транскрипт и чек-лист. Кнопка «Проанализировать звук» отправляет саму запись в Gemini. Цены в этих полях используются для текстовых проверок; стоимость аудио пока не вычисляется. Без модели доступны прослушивание и ручной пересмотр.</div></form>`,
    `<button class="button secondary" data-action="close-modal">Отмена</button><button class="button primary" data-action="save-settings">Сохранить настройки</button>`,
  );
}
async function saveSettings() {
  const body = {
    provider: $("#provider").value,
    base_url: $("#base-url").value.trim(),
    model: $("#model-name").value.trim(),
    reasoning_effort: $("#reasoning-effort").value,
    input_price:
      $("#input-price").value === "" ? null : Number($("#input-price").value),
    output_price:
      $("#output-price").value === "" ? null : Number($("#output-price").value),
  };
  const key = $("#api-key").value.trim();
  if (key) body.api_key = key;
  settings = await api("settings", body);
  $("#api-key").value = "";
  $("#modal").close();
  renderBanner();
  if (detail) renderResults();
  toast("Настройки сохранены");
}
function importModal() {
  modal(
    "Загрузить диалоги",
    `<div class="form-row"><label class="field">Группа API организаторов<input id="dataset-group" value="DEV" placeholder="DEV или group_id контроля"></label><button class="button secondary small" data-action="sync-group">Получить через API</button></div><p>Для контроля введите group_id, который сообщат организаторы. Или загрузите ответ API файлом / текстом.</p><label class="field">Файл JSON<input id="import-file" type="file" accept=".json,application/json"></label><label class="field">Ответ API<textarea id="import-json" rows="5" placeholder='{"data":{"records":[...]}}'></textarea></label>`,
    `<button class="button secondary" data-action="close-modal">Отмена</button><button class="button primary" data-action="do-import">Загрузить JSON</button>`,
  );
}
async function doImport() {
  let raw = $("#import-json").value;
  const f = $("#import-file").files[0];
  if (f) {
    if (f.size > 15_000_000) throw new Error("Файл больше 15 МБ");
    raw = await f.text();
  }
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    throw new Error("Не удалось прочитать JSON");
  }
  const result = await api("import", payload);
  $("#modal").close();
  await refresh();
  if (!selected && state.records.length)
    await selectConversation(state.records[0].conversation_id);
  toast(`Загружено диалогов: ${result.imported}`);
}
async function syncGroup() {
  const group = $("#dataset-group").value.trim();
  const button = document.querySelector('[data-action="sync-group"]');
  button.disabled = true;
  try {
    const result = await api("sync", { group_id: group });
    $("#modal").close();
    await refresh();
    toast(`Группа ${group}: загружено ${result.imported} диалогов`);
  } finally {
    button.disabled = false;
  }
}
function appealModal(cid) {
  const e = detail.evaluation,
    c = e.checklist.criteria.find((c) => c.id === cid),
    a = e.answers.find((a) => a.criterion_id === cid);
  modal(
    a.value == null ? "Передать на ручную оценку" : "Апелляция по критерию",
    `<div class="read-only"><strong>${esc(c.name)}</strong><br>Текущая оценка: ${a.value == null ? "Не определена" : esc(a.value)}<br>${esc(a.reason)}</div><label class="field">Комментарий<textarea id="appeal-comment" rows="4" placeholder="Что нужно проверить и на какие реплики обратить внимание?" maxlength="5000"></textarea></label>`,
    `<button class="button secondary" data-action="close-modal">Отмена</button><button class="button primary" data-action="submit-appeal" data-id="${cid}">Сохранить обращение</button>`,
  );
}
async function submitAppeal(cid) {
  await api("appeals", {
    evaluation_id: detail.evaluation.id,
    criterion_id: cid,
    comment: $("#appeal-comment").value,
  });
  $("#modal").close();
  await refresh();
  await selectConversation(selected);
  toast("Апелляция сохранена. Проверяющий может принять решение.");
}
function resolveModal(aid) {
  const e = detail.evaluation,
    a = e.appeals.find((a) => a.id === aid),
    c = e.checklist.criteria.find((c) => c.id === a.criterion_id),
    answer = e.answers.find((x) => x.criterion_id === c.id);
  modal(
    "Решение проверяющего",
    `<div class="read-only"><strong>${esc(c.name)}</strong><br>${esc(c.description)}<br><br>Обращение: ${esc(a.comment)}<br>Исходная оценка: ${answer.value == null ? "Не определена" : esc(answer.value)}</div><label class="field">Подтвердить или изменить оценку<select id="resolve-value">${c.allowed_values.map((v, i) => `<option value="${i}" ${v === answer.value ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label><label class="field">Причина решения<textarea id="resolve-reason" rows="4" placeholder="Объясните решение и укажите номера реплик" maxlength="5000"></textarea></label>`,
    `<button class="button secondary" data-action="close-modal">Отмена</button><button class="button primary" data-action="submit-resolve" data-id="${aid}">Сохранить решение</button>`,
  );
}
async function submitResolve(aid) {
  const e = detail.evaluation,
    a = e.appeals.find((a) => a.id === aid),
    c = e.checklist.criteria.find((c) => c.id === a.criterion_id);
  await api(`appeals/${aid}/resolve`, {
    value: c.allowed_values[Number($("#resolve-value").value)],
    reason: $("#resolve-reason").value,
  });
  $("#modal").close();
  await refresh();
  await selectConversation(selected);
  toast("Решение сохранено. Итог пересчитан, исходная оценка сохранена.");
}
let submissionCatalog = [],
  submissionDocument = null,
  submissionGeneration = 0;
async function loadSubmission() {
  const catalog = await api("submission/catalog");
  submissionCatalog = catalog.groups;
  submissionDocument = null;
  $("#view-submission").innerHTML =
    `<div class="section-card"><h2>Подготовка файлов для жюри</h2><p>DEV: 60 чатов и 5 звонков. Контроль: 10 чатов из отдельной группы. Все диалоги попадут в файл; неоценённые сохраняются со статусом error.</p><div class="submission-fields"><label class="field">Название команды<input id="submission-team" maxlength="100" placeholder="Как в регистрации" value="${esc(catalog.team_name)}"></label><label class="field">Набор<select id="submission-set"><option value="dev">DEV — 65 диалогов</option><option value="prod">Контроль — 10 чатов</option></select></label><label class="field">Группа исходных данных<select id="submission-group"></select></label></div><div class="form-help">Для сравнения с эталоном используются исходные ответы модели. Решения по апелляциям, персональные настройки, ключи и полные транскрипты в этот файл не включаются. Обычная выгрузка истории доступна по кнопке сверху.</div><div class="submission-actions"><button class="button secondary" data-action="preview-submission">${icon("check")}Проверить готовность</button><button class="button primary" data-action="save-submission">${icon("download")}Сохранить файл для жюри</button></div><div id="submission-report" aria-live="polite"></div></div><div class="section-card"><h2>После сохранения</h2><p>Файлы сохраняются в корне этого проекта: <code>results/dev/results.json</code> и <code>results/prod/results.json</code>. Резервная копия прежнего файла остаётся в локальной папке data.</p><p>Сохранение не отправляет работу организаторам. До стоп-кода нужны commit и push в открытый репозиторий, ссылка на который передана организаторам. На получение и обработку контрольного набора, проверку и отправку даётся один час.</p><p>Если контроль ещё не получен, его файл не создаётся. Нельзя заменять его DEV-диалогами или вымышленными ID.</p></div>`;
  updateSubmissionGroups();
}
function updateSubmissionGroups() {
  const kind = $("#submission-set").value;
  const groups = submissionCatalog.filter((g) =>
    kind === "prod" ? g.id.toUpperCase() !== "DEV" : true,
  );
  $("#submission-group").innerHTML = groups.length
    ? groups
        .map(
          (g) =>
            `<option value="${esc(g.id)}" ${kind === "dev" && g.id === "DEV" ? "selected" : ""}>${esc(g.id)} · ${g.total} диалогов (${g.chats} чатов, ${g.calls} звонков)</option>`,
        )
        .join("")
    : '<option value="">Контрольный набор ещё не импортирован</option>';
  clearSubmissionReport();
}
function clearSubmissionReport() {
  submissionGeneration++;
  submissionDocument = null;
  $("#submission-report").innerHTML = "";
}
function submissionInput() {
  return {
    set: $("#submission-set").value,
    group: $("#submission-group").value,
    team_name: $("#submission-team").value.trim(),
  };
}
function showSubmissionReport(report, savedPath = null) {
  $("#submission-report").innerHTML =
    `<div class="submission-result"><h3>${savedPath ? "Файл сохранён локально" : "Проверка формата пройдена"}</h3><p><strong>${esc(report.relative_path)}</strong> · ${report.total} записей · ok: ${report.ok} · error: ${report.errors.length}</p><p>${esc(report.model.name)} · ${esc(report.model.mode)} · чек-лист v${report.checklist_version}</p>${report.errors.length ? '<p class="submission-warning">Файл соответствует схеме, но часть диалогов не оценена. Это ошибки обработки, а не нулевые баллы. Для улучшения результата выполните недостающие проверки.</p>' : "<p>Все диалоги имеют полные оценки. Это проверка формата, а не измерение точности модели.</p>"}${report.needs_review_criteria ? `<p>Критериев с отметкой «нужна проверка»: ${report.needs_review_criteria}. Совпадение цитаты не гарантирует правильность вывода.</p>` : ""}${report.errors.length ? `<details><summary>Причины error · ${report.errors.length}</summary><div class="submission-errors"><table class="data-table"><thead><tr><th>ID</th><th>ПРИЧИНА</th></tr></thead><tbody>${report.errors.map((r) => `<tr><td>${esc(r.conversation_id)}</td><td>${esc(r.error)}</td></tr>`).join("")}</tbody></table></div></details>` : ""}${savedPath ? `<p class="saved-path">${esc(savedPath)}</p><p>Проверьте commit и push в открытый репозиторий перед сдачей.</p><button class="button secondary" data-action="download-submission">Скачать копию JSON</button>` : ""}</div>`;
}
async function prepareSubmission(save) {
  const generation = ++submissionGeneration;
  const response = await api(
    save ? "submission/export" : "submission/preview",
    submissionInput(),
  );
  if (generation !== submissionGeneration || view !== "submission") {
    if (save)
      toast(
        "Сохранён " +
          response.report.relative_path +
          "; выбранные параметры уже изменены.",
      );
    return;
  }
  submissionDocument = response.document || null;
  showSubmissionReport(response.report, response.path);
  if (save)
    toast("Файл для жюри сохранён в проекте. Следующий шаг — commit и push.");
}
function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2) + "\n"], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
async function exportResults() {
  const data = await api("export");
  const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json",
    }),
    url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = "cqa-results-" + new Date().toISOString().slice(0, 10) + ".json";
  a.click();
  URL.revokeObjectURL(url);
  toast("Результаты и история выгружены в JSON");
}
document.addEventListener("click", async (event) => {
  const nav = event.target.closest("[data-view]");
  if (nav) {
    switchView(nav.dataset.view);
    return;
  }
  const button = event.target.closest("[data-action]");
  if (!button || button.disabled) return;
  const action = button.dataset.action;
  try {
    switch (action) {
      case "channel-tab":
        await chooseChannel(button.dataset.channel);
        break;
      case "result-mode":
        resultsMode = button.dataset.mode;
        renderResults();
        break;
      case "audio-info":
        await loadAudioInfo();
        break;
      case "analyze-audio":
        await analyzeAudio();
        break;
      case "audio-seek":
        seekAudio(Number(button.dataset.start),Number(button.dataset.end));
        break;
      case "audio-review":
        await reviewAudio(button);
        break;
      case "open-audio-event":
        $("#channel").value = "voice call";
        switchView("dialogs");
        await selectConversation(button.dataset.id);
        resultsMode = "audio";renderResults();
        seekAudio(Number(button.dataset.start),Number(button.dataset.end));
        break;
      case "select":
        await selectConversation(button.dataset.id);
        break;
      case "open-result":
        switchView("dialogs");
        await selectConversation(button.dataset.id);
        break;
      case "open-evidence":
        $("#modal").close();
        switchView("dialogs");
        await selectConversation(button.dataset.id);
        jumpEvidence(Number(button.dataset.index),Number(button.dataset.end));
        break;
      case "analytics-refresh":
        await renderAnalytics();
        break;
      case "analytics-cell":
        analyticsSelection = {topic: button.dataset.topic, criterion: button.dataset.criterion ? Number(button.dataset.criterion) : null, outcome: "", friction: false};
        renderAnalyticsData();
        $("#analytics-drilldown").scrollIntoView({behavior:"smooth",block:"start"});
        break;
      case "analytics-outcome":
        analyticsSelection.outcome = analyticsSelection.outcome === button.dataset.outcome ? "" : button.dataset.outcome;
        renderAnalyticsData();
        $("#analytics-drilldown").scrollIntoView({behavior:"smooth",block:"start"});
        break;
      case "analytics-friction":
        analyticsSelection = {topic:"",criterion:null,outcome:"",friction:true};
        renderAnalyticsData();
        $("#analytics-drilldown").scrollIntoView({behavior:"smooth",block:"start"});
        break;
      case "analytics-reset":
        analyticsSelection = {topic:"",criterion:null,outcome:"",friction:false};
        renderAnalyticsData();
        break;
      case "compare-example":
        await compareExample(button);
        break;
      case "evaluate":
        await evaluateSelected();
        break;
      case "batch":
        await batch();
        break;
      case "submit-batch":
        await submitBatch();
        break;
      case "refresh-jobs":
        await pollJobs();
        renderQueue();
        break;
      case "retry-job":
        await api(`jobs/${button.dataset.id}/retry`, {});
        await pollJobs();
        break;
      case "cancel-job":
        await api(`jobs/${button.dataset.id}/cancel`, {});
        await pollJobs();
        break;
      case "resume-jobs":
        await api("jobs/resume", {});
        await pollJobs();
        break;
      case "evidence":
        jumpEvidence(Number(button.dataset.index), Number(button.dataset.end));
        break;
      case "settings":
        await settingsModal();
        break;
      case "save-settings":
        await saveSettings();
        break;
      case "close-modal":
        $("#modal").close();
        break;
      case "import":
        importModal();
        break;
      case "do-import":
        await doImport();
        break;
      case "sync-group":
        await syncGroup();
        break;
      case "sync":
        button.disabled = true;
        try {
          const result = await api("sync", {});
          await refresh();
          toast(`API: получено ${result.imported} диалогов`);
        } finally {
          button.disabled = false;
        }
        break;
      case "export":
        await exportResults();
        break;
      case "preview-submission":
      case "save-submission":
        button.disabled = true;
        try {
          await prepareSubmission(action === "save-submission");
        } finally {
          button.disabled = false;
        }
        break;
      case "download-submission":
        if (submissionDocument)
          downloadJson(submissionDocument, "results.json");
        break;
      case "appeal":
        appealModal(Number(button.dataset.id));
        break;
      case "submit-appeal":
        await submitAppeal(Number(button.dataset.id));
        break;
      case "resolve":
        resolveModal(Number(button.dataset.id));
        break;
      case "submit-resolve":
        await submitResolve(Number(button.dataset.id));
        break;
      case "save-checklist":
        await saveChecklist();
        break;
      case "add-criterion":
        collectChecklist();
        draft.criteria.push({
          id: Math.max(0, ...draft.criteria.map((c) => c.id)) + 1,
          name: "Новый критерий",
          description:
            "Опишите, что считать выполнением критерия и когда он неприменим.",
          weight: 10,
          scale_max: null,
          allowed_values: ["Да", "Нет"],
          section: "Дополнительные критерии",
          is_gross: false,
        });
        renderChecklist();
        break;
      case "remove-criterion":
        collectChecklist();
        draft.criteria = draft.criteria.filter(
          (c) => c.id !== Number(button.dataset.id),
        );
        renderChecklist();
        break;
    }
  } catch (error) {
    const target = $("#modal[open] #modal-error");
    if (target) target.textContent = error.message;
    else fail(error);
  }
});
document.addEventListener("change", (event) => {
  if (event.target.dataset.analyticsFilter) {
    analyticsFilters[event.target.dataset.analyticsFilter] = event.target.value;
    analyticsSelection = {topic:"",criterion:null,outcome:"",friction:false};
    renderAnalytics();
  }
  if (event.target.id === "channel") renderStats();
  if (event.target.id === "submission-set") updateSubmissionGroups();
  if (["submission-group", "submission-team"].includes(event.target.id))
    clearSubmissionReport();
  if (["language", "channel", "status"].includes(event.target.id)) renderList();
  if (event.target.id === "context-toggle") {
    showContext = event.target.checked;
    renderTranscript();
  }
  if (event.target.id === "provider") {
    const value = event.target.value;
    if (value === "gemini") $("#model-name").value = "gemini-3.8-flash";
    $("#base-url").value =
      value === "gemini"
        ? "https://generativelanguage.googleapis.com/v1beta/openai"
        : value === "ollama"
          ? "http://127.0.0.1:11434"
          : value === "openai"
            ? "https://api.openai.com/v1"
            : value === "compatible"
              ? "https://api.example.com/v1"
              : $("#base-url").value;
  }
});
document.addEventListener("input", (event) => {
  if (event.target.id === "submission-team") clearSubmissionReport();
});
$("#search").addEventListener("input", renderList);
$("#modal").addEventListener("click", (event) => {
  if (event.target === $("#modal")) $("#modal").close();
});
async function init() {
  try {
    [state, settings] = await Promise.all([api("state"), api("settings")]);
    renderStats();
    renderBanner();
    renderList();
    const hash = decodeURIComponent(location.hash.slice(1));
    const id = state.records.some((r) => r.conversation_id === hash)
      ? hash
      : state.records[0]?.conversation_id;
    if (id) await selectConversation(id);
    await pollJobs();
    setInterval(pollJobs, 2000);
  } catch (error) {
    fail(error);
    $("#transcript-panel").innerHTML =
      '<div class="empty-state"><h3>Не удалось загрузить данные</h3><p>Проверьте, что сервер запущен, и обновите страницу.</p></div>';
  }
}
init();

"use strict";

const DAY_MS = 24 * 60 * 60 * 1000;
const INTERVALS = [1, 3, 7, 14, 30, 60];
const MAX_RECORDING_MS = 30 * 1000;

const elements = {
  dashboard: document.querySelector("#dashboard-screen"),
  practice: document.querySelector("#practice-screen"),
  completion: document.querySelector("#completion-screen"),
  homeButton: document.querySelector("#home-button"),
  saveState: document.querySelector("#save-state"),
  dueCount: document.querySelector("#due-count"),
  practisedCount: document.querySelector("#practised-count"),
  deckCount: document.querySelector("#deck-count"),
  reviewCount: document.querySelector("#review-count"),
  sessionSize: document.querySelector("#session-size"),
  repetitions: document.querySelector("#repetitions"),
  playbackSpeed: document.querySelector("#playback-speed"),
  voiceMode: document.querySelector("#voice-mode"),
  recordMode: document.querySelector("#record-mode"),
  startButton: document.querySelector("#start-button"),
  sessionNote: document.querySelector("#session-note"),
  exitSession: document.querySelector("#exit-session"),
  cardPosition: document.querySelector("#card-position"),
  progressFill: document.querySelector("#progress-fill"),
  lessonChip: document.querySelector("#lesson-chip"),
  focusList: document.querySelector("#focus-list"),
  scenarioText: document.querySelector("#scenario-text"),
  answerBlock: document.querySelector("#answer-block"),
  chineseText: document.querySelector("#chinese-text"),
  pinyinText: document.querySelector("#pinyin-text"),
  englishText: document.querySelector("#english-text"),
  playButton: document.querySelector("#play-button"),
  playLabel: document.querySelector("#play-label"),
  turnStatus: document.querySelector("#turn-status"),
  repeatDots: document.querySelector("#repeat-dots"),
  revealButton: document.querySelector("#reveal-button"),
  pinyinButton: document.querySelector("#pinyin-button"),
  translationButton: document.querySelector("#translation-button"),
  replayButton: document.querySelector("#replay-button"),
  recordingPanel: document.querySelector("#recording-panel"),
  recordingCopy: document.querySelector("#recording-copy"),
  recordingTimer: document.querySelector("#recording-timer"),
  recordButton: document.querySelector("#record-button"),
  recordLabel: document.querySelector("#record-label"),
  skipRecording: document.querySelector("#skip-recording"),
  comparisonPanel: document.querySelector("#comparison-panel"),
  recordingSaveStatus: document.querySelector("#recording-save-status"),
  playReference: document.querySelector("#play-reference"),
  playMine: document.querySelector("#play-mine"),
  recordAnother: document.querySelector("#record-another"),
  recordingHistory: document.querySelector("#recording-history"),
  recordingHistoryCount: document.querySelector("#recording-history-count"),
  recordingHistoryList: document.querySelector("#recording-history-list"),
  ratingPanel: document.querySelector("#rating-panel"),
  ratingButtons: [...document.querySelectorAll("[data-rating]")],
  completionCopy: document.querySelector("#completion-copy"),
  sessionResults: document.querySelector("#session-results"),
  finishButton: document.querySelector("#finish-button"),
  toast: document.querySelector("#toast"),
};

const state = {
  deck: [],
  progress: null,
  queue: [],
  currentIndex: 0,
  currentItem: null,
  audio: new Audio(),
  sequenceActive: false,
  ratingReady: false,
  repetitionsPlayed: 0,
  pauseTimer: null,
  sessionRatings: { again: 0, hard: 0, good: 0, easy: 0 },
  completedInSession: 0,
  plannedSessionCount: 0,
  audioOrder: [],
  currentAudio: null,
  lastReferenceAudio: null,
  attemptAudio: new Audio(),
  recordingPhase: false,
  mediaRecorder: null,
  mediaStream: null,
  recordingChunks: [],
  recordingStartedAt: 0,
  recordingTimer: null,
  recordingLimitTimer: null,
  discardRecording: false,
  recordings: [],
  currentAttempt: null,
  localRecordingUrl: null,
  recordingSession: null,
};

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body.error) message = body.error;
    } catch (_) {
      // Keep the HTTP message.
    }
    throw new Error(message);
  }
  return response.json();
}

function showScreen(name) {
  elements.dashboard.classList.toggle("hidden", name !== "dashboard");
  elements.practice.classList.toggle("hidden", name !== "practice");
  elements.completion.classList.toggle("hidden", name !== "completion");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.remove("hidden");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => elements.toast.classList.add("hidden"), 4500);
}

function updateSaveState(kind, label) {
  elements.saveState.classList.remove("saving", "error");
  if (kind) elements.saveState.classList.add(kind);
  elements.saveState.querySelector("span:last-child").textContent = label;
}

async function saveProgress() {
  updateSaveState("saving", "Saving…");
  try {
    state.progress = await fetchJson("/api/progress", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.progress),
    });
    updateSaveState("", "Saved locally");
    return true;
  } catch (error) {
    updateSaveState("error", "Save failed");
    showToast(`Progress was not saved: ${error.message}`);
    return false;
  }
}

function cardIsDue(sentence, now = Date.now()) {
  const card = state.progress.cards[sentence.id];
  if (!card) return true;
  return new Date(card.next_due).getTime() <= now;
}

function readySentences() {
  const now = Date.now();
  const due = [];
  const fresh = [];
  const future = [];
  for (const sentence of state.deck) {
    const card = state.progress.cards[sentence.id];
    if (!card) {
      fresh.push(sentence);
    } else if (new Date(card.next_due).getTime() <= now) {
      due.push(sentence);
    } else {
      future.push(sentence);
    }
  }
  due.sort((a, b) => {
    const aDue = state.progress.cards[a.id].next_due;
    const bDue = state.progress.cards[b.id].next_due;
    return aDue.localeCompare(bDue) || b.priority - a.priority;
  });
  future.sort((a, b) => {
    const aDue = state.progress.cards[a.id].next_due;
    const bDue = state.progress.cards[b.id].next_due;
    return aDue.localeCompare(bDue);
  });
  return { due, fresh, future };
}

function shuffled(items) {
  const result = [...items];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [result[index], result[swapIndex]] = [result[swapIndex], result[index]];
  }
  return result;
}

function renderDashboard() {
  const { due, fresh } = readySentences();
  const practised = Object.keys(state.progress.cards).length;
  const ready = due.length + fresh.length;
  elements.dueCount.textContent = String(ready);
  elements.practisedCount.textContent = String(practised);
  elements.deckCount.textContent = String(state.deck.length);
  elements.reviewCount.textContent = String(state.progress.stats.total_reviews);
  elements.sessionSize.value = String(state.progress.settings.session_size);
  elements.repetitions.value = String(state.progress.settings.repetitions);
  elements.playbackSpeed.value = String(state.progress.settings.playback_speed);
  elements.voiceMode.value = state.progress.settings.voice_mode || "original";
  elements.recordMode.value = state.progress.settings.record_after_sequence === false ? "off" : "on";
  elements.startButton.disabled = state.deck.length === 0;
  if (ready > 0) {
    elements.sessionNote.textContent = `${ready} sentence${ready === 1 ? " is" : "s are"} ready. Highest-priority patterns come first.`;
    elements.startButton.firstChild.textContent = "Start practice ";
  } else {
    elements.sessionNote.textContent = "Nothing is due yet. You can practise the next scheduled sentences early.";
    elements.startButton.firstChild.textContent = "Practice early ";
  }
}

async function saveSettings() {
  state.progress.settings.session_size = Number(elements.sessionSize.value);
  state.progress.settings.repetitions = Number(elements.repetitions.value);
  state.progress.settings.playback_speed = Number(elements.playbackSpeed.value);
  state.progress.settings.voice_mode = elements.voiceMode.value;
  state.progress.settings.record_after_sequence = elements.recordMode.value === "on";
  await saveProgress();
  renderDashboard();
}

function buildSessionQueue() {
  const { due, fresh, future } = readySentences();
  const size = state.progress.settings.session_size;
  let selected = [...due, ...shuffled(fresh)].slice(0, size);
  if (selected.length === 0) selected = future.slice(0, size);
  return selected.map((sentence) => ({ sentence, retried: false }));
}

function stopPlayback() {
  window.clearTimeout(state.pauseTimer);
  state.pauseTimer = null;
  state.sequenceActive = false;
  state.audio.pause();
  state.audio.currentTime = 0;
  elements.playButton.classList.remove("active");
}

function renderRepeatDots() {
  const repetitions = state.progress.settings.repetitions;
  elements.repeatDots.replaceChildren();
  for (let index = 0; index < repetitions; index += 1) {
    const dot = document.createElement("span");
    dot.className = `repeat-dot${index < state.repetitionsPlayed ? " done" : ""}`;
    elements.repeatDots.append(dot);
  }
  elements.repeatDots.setAttribute(
    "aria-label",
    `${state.repetitionsPlayed} of ${repetitions} repetitions complete`,
  );
}

function revealAnswer() {
  elements.answerBlock.classList.remove("concealed");
  elements.revealButton.textContent = "Sentence revealed";
  elements.revealButton.disabled = true;
}

function togglePinyin() {
  revealAnswer();
  const willShow = elements.pinyinText.classList.contains("hidden");
  elements.pinyinText.classList.toggle("hidden", !willShow);
  elements.pinyinButton.textContent = willShow ? "Hide pinyin" : "Show pinyin";
  elements.pinyinButton.setAttribute("aria-pressed", String(willShow));
}

function toggleTranslation() {
  revealAnswer();
  const willShow = elements.englishText.classList.contains("hidden");
  elements.englishText.classList.toggle("hidden", !willShow);
  elements.translationButton.textContent = willShow ? "Hide translation" : "Show translation";
  elements.translationButton.setAttribute("aria-pressed", String(willShow));
}

function clearRecordingTimers() {
  window.clearInterval(state.recordingTimer);
  window.clearTimeout(state.recordingLimitTimer);
  state.recordingTimer = null;
  state.recordingLimitTimer = null;
}

function releaseRecordingSession(session) {
  session?.stream?.getTracks().forEach((track) => track.stop());
  if (state.mediaStream === session?.stream) state.mediaStream = null;
  if (state.mediaRecorder === session?.recorder) state.mediaRecorder = null;
  if (state.recordingSession === session) state.recordingSession = null;
}

function cancelActiveRecording() {
  const session = state.recordingSession;
  if (!session) return;
  session.discarded = true;
  clearRecordingTimers();
  if (session.recorder.state !== "inactive") session.recorder.stop();
  else releaseRecordingSession(session);
}

function stopAttemptPlayback() {
  state.attemptAudio.pause();
  state.attemptAudio.currentTime = 0;
}

function resetRecordingState() {
  cancelActiveRecording();
  stopAttemptPlayback();
  if (state.localRecordingUrl) URL.revokeObjectURL(state.localRecordingUrl);
  state.localRecordingUrl = null;
  state.recordingPhase = false;
  state.recordings = [];
  state.currentAttempt = null;
  elements.recordingPanel.classList.add("hidden");
  elements.comparisonPanel.classList.add("hidden");
  elements.recordingHistory.classList.add("hidden");
  elements.recordingHistoryList.replaceChildren();
  elements.recordButton.classList.remove("recording");
  elements.recordButton.disabled = false;
  elements.recordLabel.textContent = "Start recording";
  elements.recordingTimer.classList.add("hidden");
  elements.skipRecording.disabled = false;
  elements.skipRecording.classList.remove("hidden");
}

function recordingSupported() {
  return Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
}

function selectedRecordingMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/mp4",
    "audio/ogg;codecs=opus",
    "audio/webm",
  ];
  return candidates.find((type) => MediaRecorder.isTypeSupported?.(type)) || "";
}

function formatRecordingTime(milliseconds) {
  const seconds = Math.floor(milliseconds / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function updateRecordingTimer() {
  const elapsed = Math.min(MAX_RECORDING_MS, Date.now() - state.recordingStartedAt);
  elements.recordingTimer.textContent = `${formatRecordingTime(elapsed)} / 0:30`;
}

function setRatingReady(message) {
  state.ratingReady = true;
  elements.playButton.disabled = false;
  elements.playLabel.textContent = "Repeat sequence";
  elements.replayButton.disabled = false;
  elements.turnStatus.textContent = message;
  revealAnswer();
  elements.ratingPanel.classList.remove("hidden");
}

function formatAttemptDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Saved attempt";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

async function playAttempt(attempt) {
  if (!attempt?.audio_url) return;
  state.audio.pause();
  stopAttemptPlayback();
  state.attemptAudio.src = attempt.audio_url;
  try {
    await state.attemptAudio.play();
    elements.turnStatus.textContent = "Listening to your recording.";
  } catch (error) {
    showToast(`Recording could not play: ${error.message}`);
  }
}

async function playReferenceComparison() {
  stopAttemptPlayback();
  elements.turnStatus.textContent = "Listening to the reference.";
  try {
    await playAudio(state.lastReferenceAudio || state.currentAudio);
  } catch (error) {
    showToast(`Reference could not play: ${error.message}`);
  }
}

function renderRecordingHistory() {
  elements.recordingHistoryList.replaceChildren();
  elements.recordingHistoryCount.textContent = `(${state.recordings.length})`;
  elements.recordingHistory.classList.toggle("hidden", state.recordings.length === 0);
  for (const attempt of state.recordings) {
    const row = document.createElement("div");
    row.className = "recording-history-item";

    const date = document.createElement("span");
    date.className = "recording-history-date";
    date.textContent = `${formatAttemptDate(attempt.created_at)} · ${formatRecordingTime(attempt.duration_ms)}`;

    const play = document.createElement("button");
    play.className = "history-play";
    play.type = "button";
    play.textContent = "Play";
    play.addEventListener("click", () => playAttempt(attempt));

    const remove = document.createElement("button");
    remove.className = "history-delete";
    remove.type = "button";
    remove.textContent = "Delete";
    remove.addEventListener("click", () => deleteAttempt(attempt));

    row.append(date, play, remove);
    elements.recordingHistoryList.append(row);
  }
}

async function loadRecordingHistory(sentenceId) {
  try {
    const result = await fetchJson(`/api/recordings?sentence_id=${encodeURIComponent(sentenceId)}`);
    if (!state.recordingPhase || state.currentItem?.sentence.id !== sentenceId) return;
    state.recordings = result.attempts;
    renderRecordingHistory();
  } catch (error) {
    showToast(`Recording history could not load: ${error.message}`);
  }
}

async function deleteAttempt(attempt) {
  if (!window.confirm(`Delete the recording from ${formatAttemptDate(attempt.created_at)}?`)) return;
  try {
    await fetchJson(`/api/recordings/${encodeURIComponent(attempt.id)}`, { method: "DELETE" });
    state.recordings = state.recordings.filter((item) => item.id !== attempt.id);
    if (state.currentAttempt?.id === attempt.id) {
      stopAttemptPlayback();
      state.currentAttempt = null;
      elements.comparisonPanel.classList.add("hidden");
    }
    renderRecordingHistory();
    showToast("Recording deleted.");
  } catch (error) {
    showToast(`Recording could not be deleted: ${error.message}`);
  }
}

async function uploadRecording(blob, sentenceId, durationMs) {
  return fetchJson(`/api/recordings?sentence_id=${encodeURIComponent(sentenceId)}`, {
    method: "POST",
    headers: {
      "Content-Type": blob.type || "audio/webm",
      "X-Recording-Duration-Ms": String(durationMs),
    },
    body: blob,
  });
}

async function finishCapturedRecording(session) {
  clearRecordingTimers();
  releaseRecordingSession(session);
  elements.recordButton.classList.remove("recording");
  elements.recordLabel.textContent = "Start recording";
  elements.recordingTimer.classList.add("hidden");
  elements.recordButton.disabled = false;
  elements.skipRecording.disabled = false;
  if (session.discarded || state.currentItem?.sentence.id !== session.sentenceId) return;

  const durationMs = Math.min(MAX_RECORDING_MS, Date.now() - session.startedAt);
  const blob = new Blob(session.chunks, { type: session.recorder.mimeType || "audio/webm" });
  if (blob.size < 128) {
    elements.recordingCopy.textContent = "Nothing was captured. Please try recording again.";
    showToast("The recording was empty.");
    return;
  }

  if (state.localRecordingUrl) URL.revokeObjectURL(state.localRecordingUrl);
  state.localRecordingUrl = URL.createObjectURL(blob);
  state.currentAttempt = {
    created_at: new Date().toISOString(),
    duration_ms: durationMs,
    audio_url: state.localRecordingUrl,
  };
  elements.comparisonPanel.classList.remove("hidden");
  elements.recordingSaveStatus.textContent = "Saving locally…";
  elements.recordingCopy.textContent = "Listen to both versions, then rate the sentence.";

  try {
    const saved = await uploadRecording(blob, session.sentenceId, durationMs);
    if (!state.recordingPhase || state.currentItem?.sentence.id !== session.sentenceId) return;
    if (state.localRecordingUrl) URL.revokeObjectURL(state.localRecordingUrl);
    state.localRecordingUrl = null;
    state.currentAttempt = saved;
    state.recordings = [saved, ...state.recordings.filter((item) => item.id !== saved.id)];
    elements.recordingSaveStatus.textContent = "Saved locally. Listen side by side.";
    renderRecordingHistory();
  } catch (error) {
    if (!state.recordingPhase || state.currentItem?.sentence.id !== session.sentenceId) return;
    elements.recordingSaveStatus.textContent = "Available for comparison, but not saved.";
    showToast(`Recording was not saved: ${error.message}`);
  }
  elements.skipRecording.classList.add("hidden");
  setRatingReady("Compare both versions, then rate the sentence.");
}

async function startRecording() {
  if (!state.recordingPhase || state.recordingSession) return;
  if (!recordingSupported()) {
    elements.recordingCopy.textContent = "This browser does not support microphone recording.";
    elements.recordButton.disabled = true;
    return;
  }
  stopPlayback();
  stopAttemptPlayback();
  state.ratingReady = false;
  elements.ratingPanel.classList.add("hidden");
  elements.comparisonPanel.classList.add("hidden");
  elements.skipRecording.classList.remove("hidden");
  elements.recordButton.disabled = true;
  elements.recordLabel.textContent = "Allow microphone…";
  const sentenceId = state.currentItem.sentence.id;

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (error) {
    elements.recordButton.disabled = false;
    elements.recordLabel.textContent = "Try microphone again";
    elements.recordingCopy.textContent = "Microphone access was not granted. You can retry or skip.";
    showToast(`Microphone unavailable: ${error.message}`);
    return;
  }
  if (!state.recordingPhase || state.currentItem?.sentence.id !== sentenceId) {
    stream.getTracks().forEach((track) => track.stop());
    return;
  }

  const mimeType = selectedRecordingMimeType();
  let recorder;
  try {
    recorder = new MediaRecorder(stream, {
      ...(mimeType ? { mimeType } : {}),
      audioBitsPerSecond: 64000,
    });
  } catch (_) {
    recorder = new MediaRecorder(stream);
  }
  const session = {
    recorder,
    stream,
    sentenceId,
    chunks: [],
    startedAt: Date.now(),
    discarded: false,
  };
  state.recordingSession = session;
  state.mediaRecorder = recorder;
  state.mediaStream = stream;
  state.recordingStartedAt = session.startedAt;
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size > 0) session.chunks.push(event.data);
  });
  recorder.addEventListener("stop", () => finishCapturedRecording(session));
  recorder.start();
  elements.recordButton.disabled = false;
  elements.recordButton.classList.add("recording");
  elements.recordLabel.textContent = "Stop recording";
  elements.recordingTimer.classList.remove("hidden");
  elements.recordingCopy.textContent = "Recording now—say the whole sentence.";
  elements.skipRecording.disabled = true;
  elements.turnStatus.textContent = "Recording your voice…";
  updateRecordingTimer();
  state.recordingTimer = window.setInterval(updateRecordingTimer, 250);
  state.recordingLimitTimer = window.setTimeout(stopRecording, MAX_RECORDING_MS);
}

function stopRecording() {
  const session = state.recordingSession;
  if (!session || session.recorder.state === "inactive") return;
  elements.recordButton.disabled = true;
  elements.recordLabel.textContent = "Finishing…";
  session.recorder.stop();
}

function handleRecordButton() {
  if (state.recordingSession?.recorder.state === "recording") stopRecording();
  else startRecording();
}

function enterRecordingPhase() {
  state.sequenceActive = false;
  state.ratingReady = false;
  state.recordingPhase = true;
  elements.playButton.disabled = false;
  elements.playLabel.textContent = "Repeat sequence";
  elements.replayButton.disabled = false;
  elements.recordingPanel.classList.remove("hidden");
  elements.comparisonPanel.classList.add("hidden");
  elements.recordButton.disabled = !recordingSupported();
  elements.recordLabel.textContent = "Start recording";
  elements.skipRecording.disabled = false;
  elements.skipRecording.classList.remove("hidden");
  elements.recordingCopy.textContent = recordingSupported()
    ? "Say the complete sentence, then compare it with the reference."
    : "Recording is unavailable in this browser. You can continue without it.";
  elements.turnStatus.textContent = "Now record your version, or skip this time.";
  revealAnswer();
  loadRecordingHistory(state.currentItem.sentence.id);
}

function skipRecordingPrompt() {
  cancelActiveRecording();
  state.recordingPhase = false;
  elements.recordingPanel.classList.add("hidden");
  setRatingReady("Recording skipped. Rate how automatic the structure felt.");
}

function prepareCurrentCard() {
  stopPlayback();
  resetRecordingState();
  state.currentItem = state.queue[state.currentIndex];
  state.repetitionsPlayed = 0;
  state.ratingReady = false;
  const sentence = state.currentItem.sentence;
  const variants = Array.isArray(sentence.audio_variants) && sentence.audio_variants.length
    ? [...sentence.audio_variants]
    : [{ key: "original", name: "Original voice", audio: sentence.audio, primary: true }];
  if (state.progress.settings.voice_mode === "varied") {
    for (let index = variants.length - 1; index > 0; index -= 1) {
      const swapIndex = Math.floor(Math.random() * (index + 1));
      [variants[index], variants[swapIndex]] = [variants[swapIndex], variants[index]];
    }
  } else {
    variants.splice(0, variants.length, variants.find((variant) => variant.primary) || variants[0]);
  }
  state.audioOrder = variants;
  state.currentAudio = variants[0];
  state.lastReferenceAudio = variants[0];

  elements.cardPosition.textContent = `${state.currentIndex + 1} of ${state.queue.length}`;
  elements.progressFill.style.width = `${(state.completedInSession / Math.max(1, state.queue.length)) * 100}%`;
  const lessons = [...new Set(sentence.sources.map((source) => source.lesson))];
  const lessonLabel = lessons.length === 1 ? `Lesson ${lessons[0]}` : `${lessons.length} lessons`;
  const levelLabel = sentence.level ? `Berlitz ${sentence.level}` : "Berlitz";
  elements.lessonChip.textContent = `${lessonLabel} · ${levelLabel}`;
  elements.focusList.textContent = sentence.focus.join(" · ");
  elements.scenarioText.textContent = sentence.scenario;
  elements.chineseText.textContent = sentence.chinese;
  elements.pinyinText.textContent = sentence.pinyin;
  elements.englishText.textContent = sentence.english_hint;
  elements.answerBlock.classList.add("concealed");
  elements.pinyinText.classList.add("hidden");
  elements.englishText.classList.add("hidden");
  elements.revealButton.disabled = false;
  elements.revealButton.textContent = "Reveal sentence";
  elements.pinyinButton.disabled = false;
  elements.pinyinButton.textContent = "Show pinyin";
  elements.pinyinButton.setAttribute("aria-pressed", "false");
  elements.translationButton.textContent = "Show translation";
  elements.translationButton.setAttribute("aria-pressed", "false");
  elements.replayButton.disabled = true;
  elements.ratingPanel.classList.add("hidden");
  elements.playButton.disabled = false;
  elements.playLabel.textContent = "Play and repeat";
  elements.turnStatus.textContent = "Listen, then repeat aloud.";
  renderRepeatDots();

  state.audio.src = state.currentAudio.audio;
  state.audio.playbackRate = state.progress.settings.playback_speed;
  state.audio.load();
}

function repetitionPauseMs() {
  const duration = Number.isFinite(state.audio.duration) ? state.audio.duration : 2.5;
  // Longer source audio gets a proportionally longer speaking window.
  return Math.max(4500, duration * 1350 + 2000);
}

async function playAudio(variant = state.currentAudio) {
  if (variant && state.audio.getAttribute("src") !== variant.audio) {
    state.audio.src = variant.audio;
    state.audio.load();
  }
  state.currentAudio = variant;
  state.audio.currentTime = 0;
  state.audio.playbackRate = state.progress.settings.playback_speed;
  await state.audio.play();
}

async function playSequenceRound() {
  if (!state.sequenceActive) return;
  elements.playButton.classList.add("active");
  elements.playButton.disabled = true;
  elements.playLabel.textContent = "Listen";
  const variant = state.audioOrder[state.repetitionsPlayed % state.audioOrder.length];
  state.lastReferenceAudio = variant;
  elements.turnStatus.textContent = state.progress.settings.voice_mode === "varied"
    ? `Round ${state.repetitionsPlayed + 1}: listen to ${variant.name}.`
    : `Round ${state.repetitionsPlayed + 1}: listen carefully.`;
  try {
    await playAudio(variant);
  } catch (error) {
    stopPlayback();
    elements.playButton.disabled = false;
    elements.playLabel.textContent = "Try again";
    elements.turnStatus.textContent = "Audio could not play.";
    showToast(`Audio error: ${error.message}`);
  }
}

function finishRepetitionRound() {
  if (!state.sequenceActive) return;
  state.repetitionsPlayed += 1;
  renderRepeatDots();
  elements.playButton.classList.remove("active");
  elements.turnStatus.textContent = "Your turn—say the whole sentence aloud. Take your time.";
  const repetitions = state.progress.settings.repetitions;
  if (
    state.repetitionsPlayed >= repetitions
    && state.progress.settings.record_after_sequence !== false
  ) {
    enterRecordingPhase();
    return;
  }
  state.pauseTimer = window.setTimeout(() => {
    if (!state.sequenceActive) return;
    if (state.repetitionsPlayed < repetitions) {
      playSequenceRound();
      return;
    }
    state.sequenceActive = false;
    setRatingReady("Rate how automatic the structure felt.");
  }, repetitionPauseMs());
}

function startSequence() {
  if (state.sequenceActive || state.recordingSession) return;
  stopAttemptPlayback();
  state.recordingPhase = false;
  elements.recordingPanel.classList.add("hidden");
  state.repetitionsPlayed = 0;
  state.sequenceActive = true;
  state.ratingReady = false;
  elements.ratingPanel.classList.add("hidden");
  renderRepeatDots();
  playSequenceRound();
}

async function replayOnce() {
  if (state.sequenceActive || state.recordingSession) return;
  elements.replayButton.disabled = true;
  elements.turnStatus.textContent = "Listen once more.";
  try {
    await playAudio();
  } catch (error) {
    showToast(`Audio error: ${error.message}`);
  }
}

function reviewInterval(rating, currentBox) {
  if (rating === "again") return { box: 0, days: 1, streak: 0 };
  if (rating === "hard") return { box: Math.max(1, currentBox), days: 1, streak: null };
  const increase = rating === "easy" ? 2 : 1;
  const box = Math.min(INTERVALS.length - 1, currentBox + increase);
  return { box, days: INTERVALS[box], streak: null };
}

async function rateCurrent(rating) {
  if (!state.ratingReady || !state.currentItem) return;
  state.ratingReady = false;
  elements.ratingButtons.forEach((button) => { button.disabled = true; });
  const sentence = state.currentItem.sentence;
  const previous = state.progress.cards[sentence.id] || {
    seen: 0,
    box: 0,
    streak: 0,
    ratings: { again: 0, hard: 0, good: 0, easy: 0 },
  };
  const schedule = reviewInterval(rating, previous.box);
  const now = new Date();
  const nextDue = new Date(now.getTime() + schedule.days * DAY_MS);
  state.progress.cards[sentence.id] = {
    seen: previous.seen + 1,
    box: schedule.box,
    streak: schedule.streak === 0 ? 0 : previous.streak + 1,
    last_rating: rating,
    last_reviewed: now.toISOString(),
    next_due: nextDue.toISOString(),
    ratings: {
      again: previous.ratings.again + (rating === "again" ? 1 : 0),
      hard: previous.ratings.hard + (rating === "hard" ? 1 : 0),
      good: previous.ratings.good + (rating === "good" ? 1 : 0),
      easy: previous.ratings.easy + (rating === "easy" ? 1 : 0),
    },
  };
  state.progress.stats.total_reviews += 1;
  state.sessionRatings[rating] += 1;
  state.completedInSession += 1;
  if (rating === "again" && !state.currentItem.retried) {
    state.queue.push({ sentence, retried: true });
  }
  await saveProgress();
  elements.ratingButtons.forEach((button) => { button.disabled = false; });

  state.currentIndex += 1;
  if (state.currentIndex >= state.queue.length) {
    await completeSession();
  } else {
    prepareCurrentCard();
  }
}

function startSession() {
  state.queue = buildSessionQueue();
  if (state.queue.length === 0) {
    showToast("There are no sentences available.");
    return;
  }
  state.currentIndex = 0;
  state.completedInSession = 0;
  state.plannedSessionCount = state.queue.length;
  state.sessionRatings = { again: 0, hard: 0, good: 0, easy: 0 };
  showScreen("practice");
  prepareCurrentCard();
}

async function completeSession() {
  stopPlayback();
  resetRecordingState();
  state.progress.stats.sessions_completed += 1;
  state.progress.stats.last_session = new Date().toISOString();
  await saveProgress();
  const uniqueCount = state.plannedSessionCount;
  elements.completionCopy.textContent = `${uniqueCount} sentence${uniqueCount === 1 ? "" : "s"} completed. Every rating was saved to this Mac.`;
  elements.sessionResults.replaceChildren();
  for (const rating of ["again", "hard", "good", "easy"]) {
    const item = document.createElement("div");
    item.className = "result-pill";
    item.innerHTML = `<strong>${state.sessionRatings[rating]}</strong><span>${rating}</span>`;
    elements.sessionResults.append(item);
  }
  showScreen("completion");
}

function goHome() {
  stopPlayback();
  resetRecordingState();
  renderDashboard();
  showScreen("dashboard");
}

function handleKeyboard(event) {
  if (elements.practice.classList.contains("hidden")) return;
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
  if (event.code === "Space") {
    event.preventDefault();
    if (state.recordingSession || (state.recordingPhase && !state.ratingReady)) return;
    if (!state.sequenceActive) {
      if (state.ratingReady) replayOnce();
      else startSequence();
    }
    return;
  }
  if (event.key.toLowerCase() === "r") {
    revealAnswer();
    return;
  }
  if (event.key.toLowerCase() === "p") {
    togglePinyin();
    return;
  }
  if (event.key.toLowerCase() === "t") {
    toggleTranslation();
    return;
  }
  const ratingByKey = { "1": "again", "2": "hard", "3": "good", "4": "easy" };
  if (ratingByKey[event.key]) rateCurrent(ratingByKey[event.key]);
}

function bindEvents() {
  elements.startButton.addEventListener("click", startSession);
  elements.homeButton.addEventListener("click", goHome);
  elements.exitSession.addEventListener("click", goHome);
  elements.finishButton.addEventListener("click", goHome);
  elements.playButton.addEventListener("click", startSequence);
  elements.revealButton.addEventListener("click", revealAnswer);
  elements.pinyinButton.addEventListener("click", togglePinyin);
  elements.translationButton.addEventListener("click", toggleTranslation);
  elements.replayButton.addEventListener("click", replayOnce);
  elements.recordButton.addEventListener("click", handleRecordButton);
  elements.skipRecording.addEventListener("click", skipRecordingPrompt);
  elements.playReference.addEventListener("click", playReferenceComparison);
  elements.playMine.addEventListener("click", () => playAttempt(state.currentAttempt));
  elements.recordAnother.addEventListener("click", startRecording);
  elements.ratingButtons.forEach((button) => {
    button.addEventListener("click", () => rateCurrent(button.dataset.rating));
  });
  for (const select of [elements.sessionSize, elements.repetitions, elements.playbackSpeed, elements.voiceMode, elements.recordMode]) {
    select.addEventListener("change", saveSettings);
  }
  state.audio.addEventListener("ended", () => {
    if (state.sequenceActive) finishRepetitionRound();
    else if (state.recordingPhase && !state.ratingReady) {
      elements.replayButton.disabled = false;
      elements.turnStatus.textContent = "Now record your version, or skip this time.";
    }
    else if (state.ratingReady) {
      elements.replayButton.disabled = false;
      elements.turnStatus.textContent = "Rate how automatic the structure felt.";
    }
  });
  state.attemptAudio.addEventListener("ended", () => {
    elements.turnStatus.textContent = state.ratingReady
      ? "Compare both versions, then rate the sentence."
      : "Now record your version, or skip this time.";
  });
  document.addEventListener("keydown", handleKeyboard);
}

async function initialize() {
  bindEvents();
  try {
    const [deck, progress] = await Promise.all([
      fetchJson("/api/deck"),
      fetchJson("/api/progress"),
    ]);
    state.deck = deck.sentences;
    state.progress = progress;
    renderDashboard();
  } catch (error) {
    elements.sessionNote.textContent = `Could not load the app: ${error.message}`;
    updateSaveState("error", "App unavailable");
    showToast(error.message);
  }
}

initialize();

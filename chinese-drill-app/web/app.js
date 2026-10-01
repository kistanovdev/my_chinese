"use strict";

const DAY_MS = 24 * 60 * 60 * 1000;
const INTERVALS = [1, 3, 7, 14, 30, 60];

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
  replayButton: document.querySelector("#replay-button"),
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
  fresh.sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id));
  future.sort((a, b) => {
    const aDue = state.progress.cards[a.id].next_due;
    const bDue = state.progress.cards[b.id].next_due;
    return aDue.localeCompare(bDue);
  });
  return { due, fresh, future };
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
  await saveProgress();
  renderDashboard();
}

function buildSessionQueue() {
  const { due, fresh, future } = readySentences();
  const size = state.progress.settings.session_size;
  let selected = [...due, ...fresh].slice(0, size);
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

function showPinyin() {
  revealAnswer();
  elements.pinyinText.classList.remove("hidden");
  elements.pinyinButton.textContent = "Pinyin shown";
  elements.pinyinButton.disabled = true;
}

function prepareCurrentCard() {
  stopPlayback();
  state.currentItem = state.queue[state.currentIndex];
  state.repetitionsPlayed = 0;
  state.ratingReady = false;
  const sentence = state.currentItem.sentence;

  elements.cardPosition.textContent = `${state.currentIndex + 1} of ${state.queue.length}`;
  elements.progressFill.style.width = `${(state.completedInSession / Math.max(1, state.queue.length)) * 100}%`;
  const lessons = [...new Set(sentence.sources.map((source) => source.lesson))];
  elements.lessonChip.textContent = lessons.length === 1 ? `Lesson ${lessons[0]}` : `${lessons.length} lessons`;
  elements.focusList.textContent = sentence.focus.join(" · ");
  elements.scenarioText.textContent = sentence.scenario;
  elements.chineseText.textContent = sentence.chinese;
  elements.pinyinText.textContent = sentence.pinyin;
  elements.englishText.textContent = sentence.english_hint;
  elements.answerBlock.classList.add("concealed");
  elements.pinyinText.classList.add("hidden");
  elements.revealButton.disabled = false;
  elements.revealButton.textContent = "Reveal sentence";
  elements.pinyinButton.disabled = false;
  elements.pinyinButton.textContent = "Show pinyin";
  elements.replayButton.disabled = true;
  elements.ratingPanel.classList.add("hidden");
  elements.playButton.disabled = false;
  elements.playLabel.textContent = "Play and repeat";
  elements.turnStatus.textContent = "Listen, then repeat aloud.";
  renderRepeatDots();

  state.audio.src = sentence.audio;
  state.audio.playbackRate = state.progress.settings.playback_speed;
  state.audio.load();
}

function repetitionPauseMs() {
  const duration = Number.isFinite(state.audio.duration) ? state.audio.duration : 2.5;
  // Longer source audio gets a proportionally longer speaking window.
  return Math.max(4500, duration * 1350 + 2000);
}

async function playAudio() {
  state.audio.currentTime = 0;
  state.audio.playbackRate = state.progress.settings.playback_speed;
  await state.audio.play();
}

async function playSequenceRound() {
  if (!state.sequenceActive) return;
  elements.playButton.classList.add("active");
  elements.playButton.disabled = true;
  elements.playLabel.textContent = "Listen";
  elements.turnStatus.textContent = `Round ${state.repetitionsPlayed + 1}: listen carefully.`;
  try {
    await playAudio();
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
  state.pauseTimer = window.setTimeout(() => {
    if (!state.sequenceActive) return;
    if (state.repetitionsPlayed < repetitions) {
      playSequenceRound();
      return;
    }
    state.sequenceActive = false;
    state.ratingReady = true;
    elements.playButton.disabled = false;
    elements.playLabel.textContent = "Repeat sequence";
    elements.replayButton.disabled = false;
    elements.turnStatus.textContent = "Rate how automatic the structure felt.";
    revealAnswer();
    elements.ratingPanel.classList.remove("hidden");
  }, repetitionPauseMs());
}

function startSequence() {
  if (state.sequenceActive) return;
  state.repetitionsPlayed = 0;
  state.sequenceActive = true;
  state.ratingReady = false;
  elements.ratingPanel.classList.add("hidden");
  renderRepeatDots();
  playSequenceRound();
}

async function replayOnce() {
  if (state.sequenceActive) return;
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
  renderDashboard();
  showScreen("dashboard");
}

function handleKeyboard(event) {
  if (elements.practice.classList.contains("hidden")) return;
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
  if (event.code === "Space") {
    event.preventDefault();
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
    showPinyin();
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
  elements.pinyinButton.addEventListener("click", showPinyin);
  elements.replayButton.addEventListener("click", replayOnce);
  elements.ratingButtons.forEach((button) => {
    button.addEventListener("click", () => rateCurrent(button.dataset.rating));
  });
  for (const select of [elements.sessionSize, elements.repetitions, elements.playbackSpeed]) {
    select.addEventListener("change", saveSettings);
  }
  state.audio.addEventListener("ended", () => {
    if (state.sequenceActive) finishRepetitionRound();
    else if (state.ratingReady) {
      elements.replayButton.disabled = false;
      elements.turnStatus.textContent = "Rate how automatic the structure felt.";
    }
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

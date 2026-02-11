const apiBase = (window.API_BASE || "").replace(/\/+$/, "");
const identifyUrl = apiBase ? `${apiBase}/identify` : "/identify";

const toggleBtn = document.getElementById("toggleBtn");
const songValue = document.getElementById("songValue");
const timeValue = document.getElementById("timeValue");
const confidenceValue = document.getElementById("confidenceValue");
const confidenceFill = document.getElementById("confidenceFill");
const bars = document.getElementById("bars");

const matchBadge = document.getElementById("matchBadge");
const confetti = document.getElementById("confetti");
const songsList = document.getElementById("songsList");
const songsEmpty = document.getElementById("songsEmpty");

let audioContext;
let mediaStream;
let processor;
let input;
let chunks = [];
let totalSamples = 0;
let pollingTimer = null;
let inFlight = false;
let isRecording = false;
let displayTimer = null;
let displayBaseTime = 0;
let displayStart = 0;

async function fetchSongs() {
  if (!songsList || !songsEmpty) return;
  try {
    songsEmpty.textContent = "Loading...";
    songsEmpty.classList.remove("error");
    const url = apiBase ? `${apiBase}/songs` : "/songs";
    const res = await fetch(url);
    const data = await res.json();
    const songs = data.songs || [];
    songsList.innerHTML = "";
    if (!songs.length) {
      songsEmpty.textContent = "No songs yet.";
      songsEmpty.classList.remove("error");
      return;
    }
    songsEmpty.textContent = "";
    songsEmpty.classList.remove("error");
    for (const song of songs) {
      const li = document.createElement("li");
      li.textContent = song.name || song.song_id || String(song);
      songsList.appendChild(li);
    }
  } catch (err) {
    songsEmpty.textContent = "Backend does not seem to be live right now.";
    songsEmpty.classList.add("error");
  }
}

function floatTo16BitPCM(float32Array) {
  const buffer = new ArrayBuffer(float32Array.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < float32Array.length; i++) {
    let s = Math.max(-1, Math.min(1, float32Array[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buffer;
}

function encodeWav(samples, sampleRate) {
  const numChannels = 1;
  const bytesPerSample = 2;
  const blockAlign = numChannels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataBuffer = floatTo16BitPCM(samples);
  const buffer = new ArrayBuffer(44 + dataBuffer.byteLength);
  const view = new DataView(buffer);

  function writeString(offset, str) {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  }

  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataBuffer.byteLength, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, dataBuffer.byteLength, true);

  new Uint8Array(buffer, 44).set(new Uint8Array(dataBuffer));
  return new Blob([buffer], { type: "audio/wav" });
}

function createBars(count = 64) {
  bars.innerHTML = "";
  for (let i = 0; i < count; i++) {
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.style.height = "4px";
    bars.appendChild(bar);
  }
}

function clearBars() {
  for (const bar of bars.children) {
    bar.style.height = "4px";
  }
}

function updateBars(level) {
  const maxHeight = window.innerHeight * 0.5;
  const base = 4;
  const target = base + maxHeight * Math.min(1, Math.max(0, level));
  const children = Array.from(bars.children);
  for (let i = 0; i < children.length; i++) {
    const jitter = 0.6 + (Math.random() * 0.4);
    const scale = (i + 1) / children.length;
    const height = base + (target - base) * (0.35 + 0.65 * scale) * jitter;
    children[i].style.height = `${height}px`;
  }
}


const questionSvg = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 5"/><circle cx="12" cy="19" r="1"/></svg>';
const checkSvg = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>';
let lastConfident = false;

function setBadge(confident) {
  matchBadge.innerHTML = confident ? checkSvg : questionSvg;
  matchBadge.classList.toggle("ok", confident);
}


setBadge(false);
createBars();
window.addEventListener("load", () => {
  fetchSongs();
});

function burstConfetti() {
  confetti.innerHTML = "";
  const colors = ["#00f5d4", "#4361ee", "#ffb703", "#f15bb5"];
  for (let i = 0; i < 32; i++) {
    const piece = document.createElement("div");
    piece.className = "confetti-piece";
    piece.style.left = Math.random() * 100 + "%";
    piece.style.top = (Math.random() * 30) + "%";
    piece.style.background = colors[i % colors.length];
    piece.style.animationDelay = (Math.random() * 120) + "ms";
    confetti.appendChild(piece);
  }
  setTimeout(() => {
    confetti.innerHTML = "";
  }, 1200);
}

async function stopRecording() {
  if (!isRecording) return;
  isRecording = false;
  toggleBtn.textContent = "Listen for music";
  toggleBtn.classList.remove("secondary");

  if (processor) processor.disconnect();
  if (input) input.disconnect();
  if (mediaStream) {
    mediaStream.getTracks().forEach((t) => t.stop());
  }
  if (audioContext) {
    await audioContext.close();
  }
  if (pollingTimer) {
    clearInterval(pollingTimer);
    pollingTimer = null;
  }
}
function formatTime(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function startDisplayTimer(baseSeconds) {
  displayBaseTime = baseSeconds;
  displayStart = Date.now();
  if (displayTimer) clearInterval(displayTimer);
  displayTimer = setInterval(() => {
    const elapsed = (Date.now() - displayStart) / 1000;
    timeValue.textContent = `Timestamp: ${formatTime(displayBaseTime + elapsed)}`;
  }, 1000);
}

function stopDisplayTimer() {
  if (displayTimer) {
    clearInterval(displayTimer);
    displayTimer = null;
  }
}

toggleBtn.addEventListener("click", async () => {
  if (isRecording) {
    await stopRecording();
    return;
  }

  songValue.textContent = "--";
  timeValue.textContent = "Timestamp: --";
  stopDisplayTimer();
  confidenceValue.textContent = "Confidence: --%";
  confidenceFill.style.width = "0%";
  setBadge(false);
  lastConfident = false;
  clearBars();
  chunks = [];
  totalSamples = 0;
  try {
    toggleBtn.textContent = "Requesting mic...";
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaStream = stream;
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    input = audioContext.createMediaStreamSource(mediaStream);
    processor = audioContext.createScriptProcessor(4096, 1, 1);

    processor.onaudioprocess = (e) => {
      if (!isRecording) return;
      const channelData = e.inputBuffer.getChannelData(0);
      chunks.push(new Float32Array(channelData));
      totalSamples += channelData.length;
      const maxSamples = (audioContext ? audioContext.sampleRate : 44100) * 8;
      while (totalSamples > maxSamples && chunks.length) {
        const removed = chunks.shift();
        totalSamples -= removed.length;
      }
      let peak = 0;
      for (let i = 0; i < channelData.length; i++) {
        const v = Math.abs(channelData[i]);
        if (v > peak) peak = v;
      }
      updateBars(peak);
    };

    input.connect(processor);
    processor.connect(audioContext.destination);
    isRecording = true;
    toggleBtn.textContent = "Stop listening";
    toggleBtn.classList.add("secondary");

    if (pollingTimer) clearInterval(pollingTimer);
    pollingTimer = setInterval(() => {
      if (!isRecording || inFlight || chunks.length === 0) return;
      sendIdentifyRequest();
    }, 2000);
  } catch (err) {
    toggleBtn.textContent = "Listen for music";
    toggleBtn.classList.remove("secondary");
    songValue.textContent = "Mic access failed";
    timeValue.textContent = "Timestamp: --";
    confidenceValue.textContent = "Confidence: --%";
    confidenceFill.style.width = "0%";
    setBadge(false);
    lastConfident = false;
  }
});

async function sendIdentifyRequest() {
  if (!chunks.length) {
    return;
  }
  inFlight = true;
  const sampleRate = audioContext ? audioContext.sampleRate : 44100;
  const samples = new Float32Array(totalSamples);
  let offset = 0;
  for (const c of chunks) {
    samples.set(c, offset);
    offset += c.length;
  }

  const wavBlob = encodeWav(samples, sampleRate);
  const formData = new FormData();
  formData.append("file", wavBlob, "sample.wav");
  try {
    const res = await fetch(identifyUrl, {
      method: "POST",
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Request failed");
    }
    if (!data.match) {
      songValue.textContent = "No match";
      timeValue.textContent = "Timestamp: --";
      stopDisplayTimer();
      confidenceValue.textContent = "Confidence: --%";
      confidenceFill.style.width = "0%";
      setBadge(false);
      lastConfident = false;
    } else {
    const song = data.match.song_name ?? "Unknown";
      const time = Math.round(data.match.timestamp_seconds);
      const conf = data.match.certainty ?? 0;
      songValue.textContent = song;
      timeValue.textContent = `Timestamp: ${formatTime(time)}`;
      startDisplayTimer(time);
      confidenceValue.textContent = `Confidence: ${conf}%`;
      confidenceFill.style.width = `${Math.max(0, Math.min(100, conf))}%`;
      const confident = conf >= 90;
      setBadge(confident);
      if (confident && !lastConfident) {
        burstConfetti();
        lastConfident = true;
        await stopRecording();
      } else if (!confident) {
        lastConfident = false;
      }
    }
  } catch (err) {
    songValue.textContent = "Error";
    timeValue.textContent = "Timestamp: --";
    confidenceValue.textContent = "Confidence: --%";
    confidenceFill.style.width = "0%";
    setBadge(false);
    lastConfident = false;
  } finally {
    inFlight = false;
  }
}

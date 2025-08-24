/*
 * Client-side logic for the Habit Tracker app.
 *
 * This script handles fetching and creating habits, displaying progress
 * bars, and sending speech or text summaries to the API. The UI
 * updates automatically after each operation.
 */

const habitContainer = document.getElementById('habits-container');
const habitForm = document.getElementById('habit-form');
const speechTextArea = document.getElementById('speech-text');
const speakBtn = document.getElementById('speak-btn');
const submitSpeechBtn = document.getElementById('submit-speech');
const speechStatus = document.getElementById('speech-status');

// API helper functions
async function fetchHabits() {
  const res = await fetch('/habits');
  return res.json();
}

async function fetchProgressBars(dateStr) {
  const res = await fetch(`/progress/bars/${dateStr}`);
  return res.json();
}

async function createHabit(name, timeBlock, targetMinutes) {
  const res = await fetch('/habits', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, time_block: timeBlock, target_minutes: targetMinutes }),
  });
  return res.json();
}

async function submitSpeech(text) {
  const res = await fetch('/speech', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  return res.json();
}

// Render habits with progress bars
async function renderHabits() {
  const habits = await fetchHabits();
  const today = new Date().toISOString().split('T')[0];
  const bars = await fetchProgressBars(today);
  // Create a map from habit_id to progress ratio
  const ratioMap = {};
  bars.forEach((bar) => {
    ratioMap[bar.habit_id] = bar.progress_ratio;
  });
  habitContainer.innerHTML = '';
  habits.forEach((habit) => {
    const ratio = ratioMap[habit.id] || 0;
    const item = document.createElement('div');
    item.className = 'habit-item';
    const header = document.createElement('div');
    header.className = 'habit-header';
    header.innerHTML = `<strong>${habit.name}</strong><span>${habit.time_block}</span>`;
    const progressBar = document.createElement('div');
    progressBar.className = 'progress-bar';
    const progressFill = document.createElement('div');
    progressFill.className = 'progress-fill';
    progressFill.style.width = `${ratio * 100}%`;
    progressBar.appendChild(progressFill);
    item.appendChild(header);
    item.appendChild(progressBar);
    habitContainer.appendChild(item);
  });
}

// Handle habit form submission
habitForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = document.getElementById('habit-name').value.trim();
  const timeBlock = document.getElementById('habit-block').value;
  const targetMinutes = parseInt(document.getElementById('habit-minutes').value, 10);
  if (name && targetMinutes > 0) {
    await createHabit(name, timeBlock, targetMinutes);
    habitForm.reset();
    await renderHabits();
  }
});

// Vosk Speech Recognition Setup
let voskModel = null;
let voskRecognizer = null;
let mediaRecorder = null;
let recordedChunks = [];

// Initialize Vosk when available
async function initializeVosk() {
  if (typeof Vosk === 'undefined') {
    console.log('Vosk not loaded, falling back to Web Speech API');
    return initializeWebSpeechAPI();
  }

  try {
    const modelStatus = document.getElementById('model-status');
    const modelProgress = document.getElementById('model-progress');
    const modelProgressBar = document.getElementById('model-progress-bar');
    
    modelStatus.style.display = 'block';
    speechStatus.textContent = 'Loading speech recognition model...';
    
    // Load Vosk model (39MB download, cached after first load)
    voskModel = await Vosk.createModel('/static/models/vosk-model-small-en-us-0.15');
    voskRecognizer = new voskModel.KaldiRecognizer(16000);
    
    modelStatus.style.display = 'none';
    speechStatus.textContent = 'Speech recognition ready (Vosk)';
    speechBtn.disabled = false;
    
    return true;
  } catch (error) {
    console.error('Vosk initialization failed:', error);
    speechStatus.textContent = 'Vosk failed, trying Web Speech API...';
    return initializeWebSpeechAPI();
  }
}

// Fallback to Web Speech API
function initializeWebSpeechAPI() {
  if ('webkitSpeechRecognition' in window) {
    const recognition = new webkitSpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';
    
    recognition.onstart = () => {
      speechStatus.textContent = 'Listening...';
    };
    
    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      speechTextArea.value = transcript;
      speechStatus.textContent = 'Transcription complete (Web Speech API)';
    };
    
    recognition.onerror = (event) => {
      speechStatus.textContent = 'Error: ' + event.error;
    };
    
    recognition.onend = () => {
      if (!speechStatus.textContent.startsWith('Error')) {
        speechStatus.textContent = 'Ready (Web Speech API)';
      }
    };
    
    speechBtn.addEventListener('click', () => {
      speechStatus.textContent = '';
      recognition.start();
    });
    
    speechBtn.disabled = false;
    speechStatus.textContent = 'Speech recognition ready (Web Speech API)';
    return true;
  } else {
    speechBtn.disabled = true;
    speechStatus.textContent = 'Speech recognition not supported in this browser';
    return false;
  }
}

// Vosk audio recording and processing
async function startVoskRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordedChunks = [];
    
    mediaRecorder = new MediaRecorder(stream, { 
      mimeType: 'audio/webm;codecs=opus'
    });
    
    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        recordedChunks.push(event.data);
      }
    };
    
    mediaRecorder.onstop = async () => {
      const audioBlob = new Blob(recordedChunks, { type: 'audio/webm' });
      await processAudioWithVosk(audioBlob);
      stream.getTracks().forEach(track => track.stop());
    };
    
    mediaRecorder.start();
    speechStatus.textContent = 'Recording... (click again to stop)';
    speechBtn.textContent = '⏹️ Stop';
    
  } catch (error) {
    console.error('Error starting recording:', error);
    speechStatus.textContent = 'Error: Could not access microphone';
  }
}

function stopVoskRecording() {
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    mediaRecorder.stop();
    speechBtn.textContent = '🎤 Speak';
    speechStatus.textContent = 'Processing audio...';
  }
}

// Process audio with Vosk
async function processAudioWithVosk(audioBlob) {
  try {
    // Convert blob to ArrayBuffer
    const arrayBuffer = await audioBlob.arrayBuffer();
    
    // Create AudioContext and decode audio
    const audioContext = new AudioContext({ sampleRate: 16000 });
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
    
    // Convert to 16kHz mono PCM
    const audioData = audioBuffer.getChannelData(0);
    const samples = new Float32Array(audioData.length);
    samples.set(audioData);
    
    // Send to Vosk recognizer
    voskRecognizer.acceptWaveform(samples);
    const result = voskRecognizer.finalResult();
    
    if (result && result.text) {
      speechTextArea.value = result.text;
      speechStatus.textContent = 'Transcription complete (Vosk)';
    } else {
      speechStatus.textContent = 'No speech detected, try again';
    }
    
  } catch (error) {
    console.error('Error processing audio:', error);
    speechStatus.textContent = 'Error processing audio';
  }
}

// Main speech button click handler
speakBtn.addEventListener('click', () => {
  if (voskRecognizer) {
    // Use Vosk
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      stopVoskRecording();
    } else {
      startVoskRecording();
    }
  }
  // Web Speech API is handled by its own event listener
});

// Initialize speech recognition when page loads
initializeVosk();

// Handle speech summary submission
submitSpeechBtn.addEventListener('click', async () => {
  const text = speechTextArea.value.trim();
  if (!text) return;
  await submitSpeech(text);
  speechTextArea.value = '';
  speechStatus.textContent = 'Progress updated!';
  await renderHabits();
});

// Initial render
renderHabits();
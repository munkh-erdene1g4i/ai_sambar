let mediaRecorder;
let audioChunks = [];
let isRecording = false;
let isProcessing = false;

const orbContainer = document.getElementById('orbContainer');
const statusText = document.getElementById('statusText');
const chatBox = document.getElementById('chatBox');
const userQuestion = document.getElementById('userQuestion');
const aiAnswer = document.getElementById('aiAnswer');
const adminModal = document.getElementById('adminModal');
const schoolContextInput = document.getElementById('schoolContextInput');
const datetimeDisplay = document.getElementById('datetimeDisplay');

const audioPlayer = new Audio();

// =========================================================
// АРЫН ДЭВСГЭРИЙН CANVAS VISUALIZER АНИМАЦИ (Web Audio API)
// =========================================================
const canvas = document.getElementById('bgCanvas');
const ctx = canvas.getContext('2d');

function resizeCanvas() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
}
window.addEventListener('resize', resizeCanvas);
resizeCanvas();

// Арын дэвсгэрийн бөөмс (particles)
let particles = [];
for (let i = 0; i < 70; i++) {
    particles.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        radius: Math.random() * 2 + 1,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
        alpha: Math.random() * 0.5 + 0.2
    });
}

// Web Audio API холболт
let audioCtx;
let analyser;
let dataArray;
let isAudioContextSetup = false;

function setupAudioContext() {
    if (isAudioContextSetup) return;
    try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;

        const source = audioCtx.createMediaElementSource(audioPlayer);
        source.connect(analyser);
        analyser.connect(audioCtx.destination);

        dataArray = new Uint8Array(analyser.frequencyBinCount);
        isAudioContextSetup = true;
    } catch (e) {
        console.warn("AudioContext тохируулахад анхааруулга:", e);
    }
}

// Canvas-ийн хувьсагчид
let wavePhase = 0;

function renderBackground() {
    requestAnimationFrame(renderBackground);
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const isSpeaking = orbContainer && orbContainer.classList.contains('speaking');
    let avgFreq = 0;

    if (isSpeaking && analyser && dataArray) {
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
            sum += dataArray[i];
        }
        avgFreq = sum / dataArray.length;
    }

    wavePhase += isSpeaking ? 0.06 : 0.015;

    // 1. Арын дэвсгэрийн гэрэлтэгч синусоид долгионууд (Visualizer Waves)
    const waveLines = 3;
    for (let w = 0; w < waveLines; w++) {
        ctx.beginPath();
        ctx.lineWidth = isSpeaking ? 2.5 + w : 1.5;

        let strokeGradient = ctx.createLinearGradient(0, 0, canvas.width, 0);
        if (isSpeaking) {
            strokeGradient.addColorStop(0, 'rgba(0, 242, 254, 0.7)');
            strokeGradient.addColorStop(0.5, 'rgba(79, 172, 254, 0.9)');
            strokeGradient.addColorStop(1, 'rgba(0, 210, 255, 0.7)');
        } else {
            strokeGradient.addColorStop(0, 'rgba(0, 210, 255, 0.15)');
            strokeGradient.addColorStop(0.5, 'rgba(58, 123, 213, 0.25)');
            strokeGradient.addColorStop(1, 'rgba(0, 210, 255, 0.15)');
        }
        ctx.strokeStyle = strokeGradient;

        for (let x = 0; x < canvas.width; x += 6) {
            let freqValue = 0;
            if (isSpeaking && dataArray) {
                let index = Math.floor((x / canvas.width) * (dataArray.length / 2));
                freqValue = (dataArray[index] || 0) * 0.7;
            }

            let amplitude = isSpeaking ? 25 + freqValue : 12;
            let y = (canvas.height / 2) + Math.sin(x * 0.004 + wavePhase + w * 0.9) * amplitude;

            if (x === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();
    }

    // 2. Хөвөгч бөөмсүүдийн анимаци
    particles.forEach(p => {
        p.x += p.vx * (isSpeaking ? 2.2 : 1);
        p.y += p.vy * (isSpeaking ? 2.2 : 1);

        if (p.x < 0) p.x = canvas.width;
        if (p.x > canvas.width) p.x = 0;
        if (p.y < 0) p.y = canvas.height;
        if (p.y > canvas.height) p.y = 0;

        ctx.beginPath();
        let currentRadius = isSpeaking ? p.radius + (avgFreq * 0.035) : p.radius;
        ctx.arc(p.x, p.y, currentRadius, 0, Math.PI * 2);
        ctx.fillStyle = isSpeaking
            ? `rgba(0, 242, 254, ${Math.min(1, p.alpha + 0.3)})`
            : `rgba(0, 210, 255, ${p.alpha})`;
        ctx.fill();
    });
}
renderBackground();

// =========================================================
// ЦАГ, ОН САР ХАРУУЛАХ ФУНКЦ
// =========================================================
function updateDateTime() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');

    const daysMn = ["Ням", "Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба"];
    const dayName = daysMn[now.getDay()];

    if (datetimeDisplay) {
        datetimeDisplay.innerText = `📅 ${year}.${month}.${day} (${dayName}) 🕒 ${hours}:${minutes}:${seconds}`;
    }
}
setInterval(updateDateTime, 1000);
updateDateTime();

// =========================================================
// АУДИО ТОГЛОЖ ЭХЛЭХ БОЛОН ДУУСАХ ЭВЕНТҮҮД
// =========================================================
audioPlayer.addEventListener('play', () => {
    setupAudioContext();
    if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume();
    }
    if (orbContainer) orbContainer.classList.add('speaking');
});

audioPlayer.addEventListener('ended', () => {
    if (orbContainer) orbContainer.classList.remove('speaking');
});

audioPlayer.addEventListener('pause', () => {
    if (orbContainer) orbContainer.classList.remove('speaking');
});

// =========================================================
// SPACE ТОВЧЛУУРЫН ЭВЕНТҮҮД (PUSH TO TALK)
// =========================================================
window.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    if (e.code === 'Space' && !e.repeat) {
        e.preventDefault();
        setupAudioContext();
        if (!isRecording && !isProcessing) {
            audioPlayer.pause();
            if ('speechSynthesis' in window) window.speechSynthesis.cancel();
            startRecording();
        }
    }
});

window.addEventListener('keyup', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    if (e.code === 'Space' && isRecording) {
        e.preventDefault();
        stopRecording();
    }
});

// Яриа бичиж эхлэх
async function startRecording() {
    audioChunks = [];
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);

        mediaRecorder.ondataavailable = event => {
            if (event.data.size > 0) {
                audioChunks.push(event.data);
            }
        };

        mediaRecorder.onstop = async () => {
            if (audioChunks.length > 0) {
                const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                await sendAudioToServer(audioBlob);
            }
        };

        mediaRecorder.start();
        isRecording = true;

        if (orbContainer) {
            orbContainer.classList.remove('speaking');
            orbContainer.classList.add('recording');
        }
        if (statusText) {
            statusText.innerHTML = '🎙️ Сонсож байна... (Товчоо суллахад хариулна)';
        }
    } catch (err) {
        alert('Микрофонд холбогдоход алдаа гарлаа: ' + err);
    }
}

// Бичиж дуусах
function stopRecording() {
    if (mediaRecorder && isRecording) {
        isRecording = false;
        mediaRecorder.stop();
        mediaRecorder.stream.getTracks().forEach(track => track.stop());

        if (orbContainer) orbContainer.classList.remove('recording');
        if (statusText) {
            statusText.innerHTML = '⏳ Хариулт бэлдэж байна... Түр хүлээнэ үү';
        }
    }
}

// Сервер рүү илгээж хариулт авах
async function sendAudioToServer(blob) {
    isProcessing = true;
    const formData = new FormData();
    formData.append('audio', blob, 'voice.wav');

    try {
        const res = await fetch('/api/process-voice', {
            method: 'POST',
            body: formData
        });

        const data = await res.json();

        if (res.ok) {
            if (chatBox) chatBox.style.display = 'block';
            if (userQuestion) userQuestion.innerText = "❓ " + data.question;
            if (aiAnswer) aiAnswer.innerText = "🤖 " + data.answer;

            playResponseAudio(data.audio_url, data.answer);
        } else {
            alert('Алдаа: ' + (data.error || 'Үл мэдэгдэх алдаа'));
        }
    } catch (err) {
        alert('Сервертэй холбогдоход алдаа гарлаа: ' + err);
    } finally {
        isProcessing = false;
        if (statusText) {
            statusText.innerHTML = '<span class="key-badge">SPACE</span> товчийг дарж байгаад яриарай';
        }
    }
}

// Аудио тоглуулах
function playResponseAudio(audioUrl, fallbackText) {
    if (audioUrl) {
        audioPlayer.src = audioUrl + '?t=' + new Date().getTime();
        audioPlayer.play().catch(err => {
            console.warn("Браузер аудиог блоклосон тул нөөц аргаар уншиж байна:", err);
            speakNative(fallbackText);
        });
    } else {
        speakNative(fallbackText);
    }
}

// Браузерын өөрийн уншигч (Fallback)
function speakNative(text) {
    if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'mn-MN';

        utterance.onstart = () => {
            if (orbContainer) orbContainer.classList.add('speaking');
        };
        utterance.onend = () => {
            if (orbContainer) orbContainer.classList.remove('speaking');
        };

        window.speechSynthesis.speak(utterance);
    }
}

// Админ цонхны функцүүд
function openAdmin() {
    if (adminModal) adminModal.style.display = 'flex';
    loadData();
}

function closeAdmin() {
    if (adminModal) adminModal.style.display = 'none';
}

async function loadData() {
    try {
        const res = await fetch('/api/school-data');
        const data = await res.json();
        if (schoolContextInput) schoolContextInput.value = data.data || '';
    } catch (e) {
        console.error('Мэдээлэл татахад алдаа гарлаа', e);
    }
}

async function saveData() {
    try {
        const res = await fetch('/api/school-data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ data: schoolContextInput.value })
        });
        const data = await res.json();
        alert(data.message || 'Хадгалагдлаа');
        closeAdmin();
    } catch (e) {
        alert('Хадгалахад алдаа гарлаа!');
    }
}
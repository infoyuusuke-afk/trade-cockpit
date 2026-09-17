(() => {
  let generation = 0;
  let currentAudio = null;
  const endpoint = 'http://127.0.0.1:5000';
  const normalize = text => String(text).replaceAll('キオクシア', 'きおくしあ')
    .replaceAll('VWAP', 'ぶいわっぷ').replaceAll('OR15', 'おーあーる、じゅうご')
    .replaceAll('EMA', 'いーえむえー').replaceAll('GU', 'ぎゃっぷあっぷ')
    .replaceAll('GD', 'ぎゃっぷだうん').replaceAll('%', 'パーセント');
  const chunks = text => {
    const result = [];
    for (const part of text.match(/[^。！？、]*[。！？、]?/gu) || []) {
      if (!part) continue;
      for (let i = 0; i < part.length; i += 90) result.push(part.slice(i, i + 90));
    }
    return result;
  };
  const status = route => document.dispatchEvent(new CustomEvent('cockpitVoiceRoute', {detail: {route}}));
  const fallback = (text, sequence) => {
    if (sequence !== generation || !('speechSynthesis' in window)) return;
    status('Windows・ブラウザー音声');
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'ja-JP';
    utterance.rate = 1.05;
    window.speechSynthesis.speak(utterance);
  };
  window.cockpitVoice = {
    cancel() {
      generation++;
      if (currentAudio) { currentAudio.pause(); currentAudio.dispatchEvent(new Event('ended')); currentAudio = null; }
      if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    },
    async speak(message) {
      this.cancel();
      const sequence = generation;
      const text = normalize(message);
      const parts = chunks(text);
      let spoken = 0;
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 2500);
        try {
          const response = await fetch(`${endpoint}/status`, {signal: controller.signal, cache: 'no-store'});
          if (!response.ok) throw new Error('SBV2 unavailable');
        } finally { clearTimeout(timer); }
        if (sequence !== generation) return;
        status('SBV2・あみたろ');
        for (const part of parts) {
          if (sequence !== generation) return;
          const query = new URLSearchParams({text: part, model_name: 'amitaro', speaker_name: 'あみたろ',
            language: 'JP', length: '1.2', auto_split: 'true', split_interval: '0.7', style: 'Neutral', style_weight: '0.4'});
          const response = await fetch(`${endpoint}/voice?${query}`);
          if (!response.ok) throw new Error('SBV2 voice failed');
          const url = URL.createObjectURL(await response.blob());
          try {
            if (sequence !== generation) return;
            currentAudio = new Audio(url);
            const finished = new Promise((resolve, reject) => {
              currentAudio.onended = resolve;
              currentAudio.onerror = reject;
            });
            await currentAudio.play();
            await finished;
            spoken++;
          } finally {
            currentAudio = null;
            URL.revokeObjectURL(url);
          }
        }
      } catch {
        fallback(parts.slice(spoken).join(''), sequence);
      }
    }
  };
})();

(() => {
  async function pollEvents() {
    try {
      const response = await fetch('/local/events/poll');
      if (!response.ok) return;
      const data = await response.json();
      for (const event of data.events || []) {
        if (typeof window.addAssistant === 'function') {
          window.addAssistant(event.message || 'Reminder', event.card || null);
        }
      }
    } catch (_) {
      // Keep chat usable if the event poll briefly fails.
    }
  }
  setInterval(pollEvents, 5000);
  setTimeout(pollEvents, 1000);
})();

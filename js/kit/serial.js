// USB connection to the ESP32 field kit with the Web Serial API (Chrome or Edge on a computer).
// The kit sends one JSON object per line at 115200 baud; lines starting with '#' are messages.

export const serialSupported = () => 'serial' in navigator && window.isSecureContext;

export class SerialKit {
  constructor({ onLine, onState }) {
    this.onLine = onLine;
    this.onState = onState;
    this.port = null;
    this.reader = null;
    this.writer = null;
    this.closing = false;
  }

  get connected() { return !!this.port; }

  async connect() {
    // Must be called from a click: the browser shows its own "choose a port" window.
    const port = await navigator.serial.requestPort();
    await port.open({ baudRate: 115200, bufferSize: 8192 });
    // Release the ESP32's reset/boot lines so the board starts normally.
    try { await port.setSignals({ dataTerminalReady: false, requestToSend: false }); } catch { /* not all adapters support it */ }
    this.port = port;
    this.closing = false;
    port.addEventListener('disconnect', () => this.cleanup('unplugged'));
    this.writer = port.writable.getWriter();
    this.onState('connected');
    this.readLoop();
    // Give the board a moment after any reset, then send the clock and ask for its status.
    setTimeout(() => {
      this.send(`TIME ${Math.floor(Date.now() / 1000)}`);
      this.send('INFO');
    }, 1500);
  }

  async readLoop() {
    const decoder = new TextDecoder();
    let buffer = '';
    while (this.port && this.port.readable && !this.closing) {
      this.reader = this.port.readable.getReader();
      let failed = false;
      try {
        for (;;) {
          const { value, done } = await this.reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let cut;
          while ((cut = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0, cut).replace(/\r$/, '').trim();
            buffer = buffer.slice(cut + 1);
            if (line) this.onLine(line);
          }
          if (buffer.length > 8192) buffer = ''; // protect against a stream without newlines
        }
      } catch (err) {
        // A framing, parity, break or overrun error (e.g. while the ESP32 resets) ends only this
        // reader: the port then offers a new readable stream and the loop goes on. After a fatal
        // error port.readable is null and the loop ends.
        failed = true;
        buffer = ''; // the half line before the error may be garbled
        if (!this.closing) this.onState('error', err);
      } finally {
        try { this.reader.releaseLock(); } catch { /* already released */ }
      }
      if (failed) await new Promise((resolve) => { setTimeout(resolve, 100); });
    }
  }

  async send(text) {
    if (!this.writer) return;
    try {
      await this.writer.write(new TextEncoder().encode(`${text}\n`));
    } catch (err) {
      this.onState('error', err);
    }
  }

  async disconnect() {
    this.closing = true;
    try { await this.reader?.cancel(); } catch { /* ignore */ }
    await this.cleanup('disconnected');
  }

  async cleanup(reason) {
    const port = this.port;
    if (!port) return;
    this.port = null;
    try { this.writer?.releaseLock(); } catch { /* ignore */ }
    this.writer = null;
    try { await port.close(); } catch { /* ignore */ }
    this.onState(reason);
  }
}

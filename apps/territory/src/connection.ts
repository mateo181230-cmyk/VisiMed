/** A network failure must not look like an empty panel or an expired session. */
export class ConnectionError extends Error {
  constructor() {
    super('No pudimos conectar con Novamed. Reintenta en un momento. Tus datos guardados en este dispositivo se conservan.');
    this.name = 'ConnectionError';
  }
}

export async function request(url: string, init: RequestInit = {}, timeoutMs = 25_000): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch {
    throw new ConnectionError();
  } finally {
    clearTimeout(timer);
  }
}

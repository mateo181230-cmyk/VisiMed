/** Permiso del micrófono, pedido ANTES de crear la conversación (no se gasta una visita sin audio). */
export type MicCheck = 'ok' | 'denied' | 'unavailable' | 'insecure'

export async function checkMicrophone(): Promise<MicCheck> {
  if (!window.isSecureContext) return 'insecure'
  if (!navigator.mediaDevices?.getUserMedia) return 'unavailable'
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    stream.getTracks().forEach((track) => track.stop())
    return 'ok'
  } catch (error) {
    const name = (error as DOMException | undefined)?.name
    return name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'unavailable'
  }
}

export function micHelp(problem: Exclude<MicCheck, 'ok'>): string {
  if (problem === 'insecure') return 'El micrófono solo funciona con una conexión segura (https). Abre UNO desde su dirección oficial.'
  if (problem === 'unavailable') return 'Este teléfono no tiene un micrófono disponible para el navegador. Revisa que otra app no lo esté usando.'
  const iphone = /iPad|iPhone|iPod/.test(navigator.userAgent)
  return iphone
    ? 'Permite el micrófono: en Safari toca «aA» › Configuración del sitio web › Micrófono › Permitir, y vuelve a intentarlo.'
    : 'Permite el micrófono: toca el candado junto a la dirección › Permisos › Micrófono › Permitir, y vuelve a intentarlo.'
}

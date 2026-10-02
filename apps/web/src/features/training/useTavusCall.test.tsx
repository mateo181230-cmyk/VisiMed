import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { discardPreparedCall, prepareDailyCall } from './dailyClient'
import { useTavusCall } from './useTavusCall'

const daily = vi.hoisted(() => ({ createCallObject: vi.fn() }))
vi.mock('@daily-co/daily-js', () => ({ default: daily }))

function mockCall() {
  const listeners = new Map<string, Array<(event?: unknown) => void>>()
  const emit = (name: string, event?: unknown) => listeners.get(name)?.forEach((handler) => handler(event))
  return {
    emit,
    load: vi.fn(async () => {}),
    on: vi.fn((name: string, handler: (event?: unknown) => void) => {
      listeners.set(name, [...(listeners.get(name) ?? []), handler])
    }),
    join: vi.fn(async () => { emit('joined-meeting') }),
    participants: vi.fn<() => Record<string, unknown>>(() => ({})),
    leave: vi.fn(async () => { emit('left-meeting') }),
    destroy: vi.fn(async () => {}),
    setLocalAudio: vi.fn(),
  }
}

let call: ReturnType<typeof mockCall>

function Harness() {
  const media = useTavusCall('https://tavus.daily.co/test', () => {})
  return <>
    <output data-testid="state">{media.state}</output>
    <output data-testid="video-ready">{String(media.doctorVideo)}</output>
    <video ref={media.videoRef} data-testid="video" />
    <audio ref={media.audioRef} />
    {media.error && <p role="alert">{media.error}</p>}
    {media.needsAudioGesture && <button onClick={() => void media.activateAudio()}>Activar audio</button>}
    <button onClick={media.reconnect}>Reconectar</button>
  </>
}

beforeEach(() => {
  call = mockCall()
  daily.createCallObject.mockReset().mockImplementation(() => call)
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  vi.stubGlobal('MediaStream', class {
    constructor(private tracks: MediaStreamTrack[]) {}
    getTracks() { return this.tracks }
  })
})

afterEach(async () => {
  await discardPreparedCall()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('Conexión con Tavus', () => {
  it('reutiliza el cliente precargado sin dispositivos y activa solo el micrófono al entrar', async () => {
    await prepareDailyCall()
    expect(call.load).toHaveBeenCalledOnce()
    expect(call.join).not.toHaveBeenCalled()
    expect(daily.createCallObject).toHaveBeenCalledWith(expect.objectContaining({ audioSource: false, videoSource: false }))
    render(<Harness />)
    await waitFor(() => expect(call.join).toHaveBeenCalledWith(expect.objectContaining({ audioSource: true, videoSource: false })))
    expect(daily.createCallObject).toHaveBeenCalledOnce()
  })

  it('recupera las pistas de un médico que ya estaba en la sala y espera al primer fotograma', async () => {
    const track = { kind: 'video' } as MediaStreamTrack
    call.participants.mockReturnValue({ doctor: { local: false, tracks: {
      video: { state: 'playable', persistentTrack: track }, audio: { state: 'off' },
    } } })
    render(<Harness />)
    await waitFor(() => expect(call.join).toHaveBeenCalled())
    const video = screen.getByTestId('video') as HTMLVideoElement
    expect((video.srcObject as MediaStream).getTracks()).toContain(track)
    expect(screen.getByTestId('video-ready')).toHaveTextContent('false')
    fireEvent.playing(video)
    expect(screen.getByTestId('video-ready')).toHaveTextContent('true')
    expect(screen.getByTestId('state')).toHaveTextContent('live')
  })

  it('muestra el fallo del motor de videollamada en lugar de dejar una carga infinita', async () => {
    call.load.mockRejectedValue(new Error('Network failure'))
    render(<Harness />)
    expect(await screen.findByRole('alert')).toHaveTextContent('No pudimos cargar la videollamada')
    expect(call.join).not.toHaveBeenCalled()
    await waitFor(() => expect(call.destroy).toHaveBeenCalledOnce())
  })

  it('limita la espera sin medios y vuelve a entrar en la misma sala', async () => {
    vi.useFakeTimers()
    render(<Harness />)
    await act(async () => { await vi.advanceTimersByTimeAsync(50) })
    expect(screen.getByTestId('state')).toHaveTextContent('waiting')
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
    expect(screen.getByRole('alert')).toHaveTextContent('El teléfono no logró conectar')
    expect(call.destroy).toHaveBeenCalledOnce()
    const next = mockCall()
    daily.createCallObject.mockReturnValue(next)
    fireEvent.click(screen.getByRole('button', { name: 'Reconectar' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(50) })
    expect(next.join).toHaveBeenCalledWith(expect.objectContaining({ url: 'https://tavus.daily.co/test' }))
  })

  it('permite activar el audio con un toque cuando el navegador bloquea su reproducción', async () => {
    vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValueOnce(new DOMException('Gesture required', 'NotAllowedError'))
    render(<Harness />)
    await waitFor(() => expect(call.join).toHaveBeenCalled())
    await act(async () => { call.emit('track-started', { participant: { local: false }, track: { kind: 'audio' } }) })
    fireEvent.click(await screen.findByRole('button', { name: 'Activar audio' }))
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('live'))
    expect(screen.queryByRole('button', { name: 'Activar audio' })).not.toBeInTheDocument()
  })

  it('no destruye el cliente compartido durante el montaje doble de React StrictMode', async () => {
    render(<StrictMode><Harness /></StrictMode>)
    await waitFor(() => expect(call.join).toHaveBeenCalledOnce())
    expect(call.destroy).not.toHaveBeenCalled()
  })

  it('agota la precarga sin abrir una sala cuando el motor no responde', async () => {
    vi.useFakeTimers()
    call.load.mockImplementation(() => new Promise(() => {}))
    const result = prepareDailyCall().catch((error: Error) => error.message)
    await vi.advanceTimersByTimeAsync(15_001)
    expect(await result).toContain('No pudimos cargar la videollamada')
    expect(call.join).not.toHaveBeenCalled()
    expect(call.destroy).toHaveBeenCalledOnce()
  })
})

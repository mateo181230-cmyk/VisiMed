import Dexie, { type Table } from "dexie";
import { legacyIdentity } from "./legacy-session";
import { request } from "./connection";
export type User = { id: string; name: string; role: string; demo_mode?: boolean };
export type Pending = {
  id: string;
  actor_id: string;
  type: string;
  payload: any;
  expected_version: number;
  created_at: number;
  error?: string;
};
class Store extends Dexie {
  commands!: Table<Pending, string>;
  snapshots!: Table<{ id: string; data: any }, string>;
  constructor() {
    super("visimed-territory-v1");
    this.version(1).stores({
      commands: "id,actor_id,created_at",
      snapshots: "id",
    });
  }
}
export const db = new Store();
let token = "";
let user: User | null = null;
let refreshing: Promise<User> | null = null;
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function session(): Promise<User> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    const r = await request("/v1/auth/refresh", {
      method: "POST",
      credentials: "same-origin",
    });
    if (!r.ok) {
      token = "";
      if (r.status === 401) localStorage.removeItem("territory-last-user");
      throw new ApiError(r.status, "Inicia sesión en VisiMed para continuar");
    }
    const d = await r.json();
    token = d.access_token;
    user = { id: d.user.id, name: d.user.full_name, role: d.user.role, demo_mode:d.user.demo_mode };
    localStorage.setItem("territory-last-user", JSON.stringify(user));
    return user;
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}
export async function login(phone: string, pin: string) {
  const legacy = await legacyIdentity();
  const normalized = phone.replace(/[\s().-]/g, "").replace(/^\+?57/, "");
  if (legacy && legacy.phone.replace(/^\+57/, "") !== normalized)
    throw new ApiError(
      409,
      "Hay otra cuenta abierta en VisiMed. Cierra su sesión desde la app antes de cambiar de visitador.",
    );
  const r = await request("/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone, pin }),
    credentials: "same-origin",
  });
  const d = await r.json();
  if (!r.ok)
    throw new ApiError(
      r.status,
      d.detail?.message || "No se pudo iniciar sesión",
    );
  token = d.access_token;
  user = { id: d.user.id, name: d.user.full_name, role: d.user.role, demo_mode:d.user.demo_mode };
  localStorage.setItem("territory-last-user", JSON.stringify(user));
  return user;
}
export function cachedUser(): User | null {
  try {
    return JSON.parse(localStorage.getItem("territory-last-user") || "null");
  } catch {
    return null;
  }
}
export async function libraryFile(path: string, file?: File) {
  await session();
  const r = await fetch('/v1/territory/library/' + path, {
    method: file ? 'POST' : 'GET',
    headers: { Authorization: 'Bearer ' + token }, body: file,
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail?.message || 'No se pudo procesar el archivo');
  }
  return file ? r.json() : r.blob();
}
export async function api<T = any>(
  path: string,
  body?: any,
  retry = true,
  base = "/v1/territory",
): Promise<T> {
  const r = await request(base + path, {
    method: body ? "POST" : "GET",
    headers: {
      Authorization: "Bearer " + token,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  }, body ? 90_000 : 25_000);
  if (r.status === 401 && retry) {
    const previous = user?.id;
    const current = await session();
    if (previous && current.id !== previous)
      throw new ApiError(
        409,
        "La sesión cambió. Reabre el territorio antes de continuar.",
      );
    return api(path, body, false, base);
  }
  const d = await r.json();
  if (!r.ok)
    throw new ApiError(
      r.status,
      d.detail?.message ||
        String(d.detail || "No se pudo completar la solicitud"),
    );
  return d;
}
const stateRequests = new Map<string, Promise<any>>();
export async function readStudyState(current: User) {
  const key = current.id + ':study-visits';
  try {
    const result = await api('/me/state', undefined, true, '/v1');
    const data = {doctors: result.doctors, visits: result.visits};
    await db.snapshots.put({id: key, data});
    return data;
  } catch (e) {
    if (e instanceof ApiError && e.status < 500) throw e;
    const saved = await db.snapshots.get(key);
    if (saved) return {...saved.data, cached: true};
    throw new Error('No pudimos consultar tus visitas. Reintenta cuando recuperes la conexión.');
  }
}
export function readState(current: User, rep?: string): Promise<any> {
  const key = current.id + ":" + (rep || current.id);
  const active = stateRequests.get(key);
  if (active) return active;
  const pending = loadState(current, rep).finally(() => stateRequests.delete(key));
  stateRequests.set(key, pending);
  return pending;
}
async function loadState(current: User, rep?: string) {
  const key = current.id + ":" + (rep || current.id);
  try {
    const data = await api("/state" + (rep ? "?representative_id=" + rep : ""));
    await db.snapshots.put({ id: key, data });
    return data;
  } catch (e) {
    if (e instanceof ApiError && e.status < 500) throw e;
    const saved = await db.snapshots.get(key);
    if (saved) return { ...saved.data, cached: true };
    throw new Error(
      "Necesitas conexión para descargar tu territorio por primera vez",
    );
  }
}
export async function downloadReport(path: string, retry=true): Promise<Blob> {
  const r=await fetch('/v1/territory'+path,{headers:{Authorization:'Bearer '+token},credentials:'same-origin'});
  if(r.status===401&&retry){await session();return downloadReport(path,false)}
  if(!r.ok){const d=await r.json().catch(()=>({}));throw new Error(d.detail?.message||'No se pudo generar el PDF')}
  return r.blob();
}
export async function send(
  current: User,
  type: string,
  payload: any,
  expected_version = 0,
) {
  const command: Pending = {
    id: crypto.randomUUID(),
    actor_id: current.id,
    type,
    payload,
    expected_version,
    created_at: Date.now(),
  };
  // Guardar antes de enviar: cerrar la pestaña nunca pierde una operación.
  const earlier = await db.commands
    .where("actor_id")
    .equals(current.id)
    .count();
  await db.commands.put(command);
  if (!navigator.onLine || earlier > 0 || flushing) return { queued: true };
  try {
    const result = await deliver(command);
    await db.commands.delete(command.id);
    return result;
  } catch (e) {
    if (e instanceof ApiError) {
      await db.commands.delete(command.id);
      throw e;
    }
    return { queued: true };
  }
}
async function deliver(item: Pending) {
  if (item.type === "voice.report.sync") {
    const result = await api("/sync", item.payload, true, "/v1");
    const rejected = result.results.find((x: any) => !["applied", "duplicate"].includes(x.status));
    if (rejected) throw new ApiError(409, "No se guardó el reporte: " + rejected.reason);
    return result;
  }
  return api("/commands", {id:item.id,type:item.type,payload:item.payload,expected_version:item.expected_version});
}
let flushing: Promise<void> | null = null;
export async function flush(current: User) {
  if (flushing) return flushing;
  flushing = (async () => {
    if (!navigator.onLine) return;
    const pending = (
      await db.commands.where("actor_id").equals(current.id).toArray()
    ).sort((a, b) => a.created_at - b.created_at);
    if (!pending.length) return;
    const actual = await session();
    if (actual.id !== current.id)
      throw new Error(
        "La sesión cambió. Vuelve a abrir tu territorio antes de sincronizar.",
      );
    for (const item of pending) {
      if (item.error) break;
      try {
        await deliver(item);
        await db.commands.delete(item.id);
      } catch (e) {
        if (e instanceof ApiError && e.status < 500 && e.status !== 429)
          await db.commands.update(item.id, { error: e.message });
        break;
      }
    }
  })().finally(() => {
    flushing = null;
  });
  return flushing;
}
export function locate(): Promise<{
  lat: number;
  lng: number;
  accuracy_m: number;
}> {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("Este navegador no dispone de ubicación"));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (p) =>
        resolve({
          lat: p.coords.latitude,
          lng: p.coords.longitude,
          accuracy_m: p.coords.accuracy,
        }),
      () =>
        reject(
          new Error(
            "No se obtuvo la ubicación. Puedes seleccionar el punto en el mapa.",
          ),
        ),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 },
    );
  });
}

export async function commercialFile(file: File, source: string) {
  await session();
  const r = await fetch('/v1/territory/commercial/preview?filename='+encodeURIComponent(file.name)+'&source='+encodeURIComponent(source), {method:'POST',headers:{Authorization:'Bearer '+token},body:file});
  const d=await r.json();if(!r.ok)throw new ApiError(r.status,d.detail?.message||'No se pudo importar el archivo');return d;
}

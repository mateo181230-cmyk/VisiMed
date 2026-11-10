/** Read identity only. The existing app owns its database and offline outbox. */
export function legacyIdentity(): Promise<{
  id: string;
  phone: string;
} | null> {
  return new Promise((resolve) => {
    const request = indexedDB.open("uno-visitas");
    request.onupgradeneeded = () => {
      request.transaction?.abort();
    };
    request.onerror = () => resolve(null);
    request.onsuccess = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains("meta")) {
        database.close();
        resolve(null);
        return;
      }
      const tx = database.transaction("meta", "readonly");
      const read = tx.objectStore("meta").get("user");
      read.onsuccess = () => resolve(read.result?.value || null);
      read.onerror = () => resolve(null);
      tx.oncomplete = () => database.close();
    };
  });
}

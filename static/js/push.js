/* Push subscription registration script */
/* Expects an endpoint GET /vapid_public_key that returns { publicKey: '...' } */
(function(){
  'use strict';

  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  async function registerServiceWorker() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      console.warn('[push] ServiceWorker or PushManager not available');
      return null;
    }
    try {
      // Log existing registrations for debugging
      try {
        const regs = await navigator.serviceWorker.getRegistrations();
        console.log('[push] existing SW registrations:', regs.map(r=>r.scope));
      } catch(e) {}

      // Register the service worker at the site root so it can control all pages.
      // Use explicit scope '/' as a strong hint to the browser.
      const reg = await navigator.serviceWorker.register('/service-worker.js', {scope: '/'});
      console.log('[push] service worker registered', reg, 'scope=', reg.scope);
      return reg;
    } catch (e) {
      console.error('[push] sw registration failed', e);
      try {
        // fallback: try static path
        const reg2 = await navigator.serviceWorker.register('/static/service-worker.js');
        console.log('[push] service worker registered (fallback)', reg2, 'scope=', reg2.scope);
        return reg2;
      } catch (err) {
        console.error('[push] sw registration fallback failed', err);
        return null;
      }
    }
  }

  async function getVapidPublicKey(){
    try{
      const r = await fetch('/vapid_public_key', {credentials: 'same-origin'});
      if(!r.ok) return null;
      const j = await r.json();
      return j && j.publicKey;
    }catch(e){ console.error('[push] failed to fetch vapid key', e); return null; }
  }

  async function subscribeForPush(){
    try {
      console.log('[push] requesting notification permission');
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        console.log('[push] permission not granted', permission);
        return;
      }

      // Ensure the service worker is registered and ready
      let reg = await registerServiceWorker();
      if (!reg) reg = await navigator.serviceWorker.ready;
      if (!reg) throw new Error('service worker registration unavailable');
      console.log('[push] serviceWorker ready:', reg);

      const publicKey = await getVapidPublicKey();
      console.log('[push] fetched publicKey:', !!publicKey);
      if (!publicKey) {
        console.warn('[push] no public key available');
        return;
      }

      // Subscribe with a timeout so UI doesn't hang indefinitely
      const subscribePromise = reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey)
      });

      const timeout = new Promise((_, reject) => setTimeout(() => reject(new Error('push.subscribe timeout')), 15000));
      let subscription;
      try {
        subscription = await Promise.race([subscribePromise, timeout]);
      } catch (err) {
        console.error('[push] subscribe failed or timed out', err);
        return;
      }

      console.log('[push] subscription obtained:', subscription);

      // send subscription to server (debug logging)
      try {
        const resp = await fetch('/subscribe', {
          method: 'POST',
          credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(subscription)
        });
        console.log('[push] /subscribe response', resp.status);
      } catch (err) {
        console.error('[push] failed to POST subscription', err);
      }

    } catch (e) {
      console.error('[push] subscribe error', e);
    }
  }

  // Expose a global helper for manual subscription (e.g., Bound to a button)
  window.pushHelper = {
    init: async function(){
      await registerServiceWorker();
    },
    // Diagnostic helper to list and optionally unregister service workers
    async resetServiceWorkers(unregister = false) {
      try {
        const regs = await navigator.serviceWorker.getRegistrations();
        console.log('[push] registrations:', regs.map(r=>r.scope));
        if (unregister) {
          for (const r of regs) {
            console.log('[push] unregistering', r.scope);
            await r.unregister();
          }
        }
        return regs;
      } catch (e) { console.error('[push] resetServiceWorkers error', e); return null; }
    },
    subscribe: subscribeForPush
  };

  // Auto-init in background (non-blocking)
  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    registerServiceWorker();
  } else {
    window.addEventListener('DOMContentLoaded', registerServiceWorker);
  }

  // Auto-request Notification permission for all users once only.
  // Use localStorage flag 'pushPermissionAsked' to avoid re-prompting.
  try {
    if (window.Notification) {
      const asked = localStorage.getItem('pushPermissionAsked');
      if (Notification.permission === 'default' && !asked) {
        // Ask after a short delay so it doesn't trigger immediately on cold load
        setTimeout(() => {
          try {
            Notification.requestPermission().then(p => {
              console.log('[push] notification permission:', p);
              // mark that we've asked so we don't repeatedly annoy users
              try { localStorage.setItem('pushPermissionAsked', '1'); } catch(e){}
            }).catch(()=>{ try{ localStorage.setItem('pushPermissionAsked','1'); }catch(e){} });
          } catch(e) { try{ localStorage.setItem('pushPermissionAsked','1'); }catch(e){} }
        }, 1500);
      }
    }
  } catch(e) { /* ignore */ }

})();

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

      // send subscription to server (debug logging). Use toJSON() to ensure serializable payload.
      try {
        const payload = (typeof subscription.toJSON === 'function') ? subscription.toJSON() : subscription;
        const resp = await fetch('/subscribe', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        let text = '';
        try { text = await resp.text(); } catch(e){}
        console.log('[push] /subscribe response', resp.status, text);
        return resp.status >= 200 && resp.status < 300;
      } catch (err) {
        console.error('[push] failed to POST subscription', err);
        return false;
      }

    } catch (e) {
      console.error('[push] subscribe error', e);
      return false;
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
              // If granted, attempt to subscribe immediately (useful for mobile users)
              if (p === 'granted') {
                try {
                  // wait a moment for service worker readiness
                  setTimeout(() => { try { window.pushHelper.subscribe(); } catch(e) { console.error('[push] auto-subscribe failed', e); } }, 800);
                } catch(e) { console.error('[push] auto-subscribe schedule failed', e); }
              }
            }).catch(()=>{ try{ localStorage.setItem('pushPermissionAsked','1'); }catch(e){} });
          } catch(e) { try{ localStorage.setItem('pushPermissionAsked','1'); }catch(e){} }
        }, 1500);
      }
    }
  } catch(e) { /* ignore */ }

})();

// Additional logic: ensure subscription with retries when permission is granted
(function(){
  'use strict';
  async function ensureSubscribed() {
    try {
      await window.pushHelper.init();
      const reg = await navigator.serviceWorker.ready;
      if (!reg) return false;

      // if already subscribed, ensure server has a copy
      try {
        const existing = await reg.pushManager.getSubscription();
        if (existing) {
          try {
            const payload = (typeof existing.toJSON === 'function') ? existing.toJSON() : existing;
            const r = await fetch('/subscribe', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
            if (r.status >= 200 && r.status < 300) return true;
          } catch(e) { console.error('[push ensure] resend existing failed', e); }
        }
      } catch(e){ console.error('[push ensure] getSubscription failed', e); }

      // quick retries
      for (let i=0;i<5;i++){
        const ok = await window.pushHelper.subscribe();
        if (ok) return true;
        await new Promise(r=>setTimeout(r, 1000*(i+1)));
      }

      // schedule periodic retry
      const interval = setInterval(async ()=>{
        try {
          const ok = await window.pushHelper.subscribe();
          if (ok) clearInterval(interval);
        } catch(e){ console.error('[push ensure] periodic retry failed', e); }
      }, 1000*60*5);

      return false;
    } catch(e) { console.error('[push ensure] error', e); return false; }
  }

  if (window.Notification && Notification.permission === 'granted') {
    setTimeout(()=>ensureSubscribed(), 500);
  }

  // hook permission changes via polling (some browsers don't fire events)
  setInterval(()=>{
    try{
      if (window.Notification && Notification.permission === 'granted') {
        ensureSubscribed();
      }
    }catch(e){}
  }, 1000*30);
})();

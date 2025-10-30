/* Service Worker for handling Web Push notifications */
'use strict';

self.addEventListener('install', event => {
  console.log('[sw] install');
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', event => {
  console.log('[sw] activate');
  event.waitUntil(self.clients.claim());
});

function _safeParseEventData(event) {
  try {
    if (event.data) return event.data.json();
  } catch (e) {
    try { return JSON.parse(event.data.text()); } catch (e) { return null; }
  }
  return null;
}

self.addEventListener('push', event => {
  console.log('[sw] push event received');
  const payload = _safeParseEventData(event) || { title: 'WC 2026', body: 'You have a notification', data: {} };

  // If the payload includes HTML we open a safe viewer window on click to render it
  const title = payload.title || 'WC 2026';
  const options = {
    body: payload.body || '',
    icon: '/static/favicon/web-app-manifest-192x192.png',
    badge: '/static/favicon/web-app-manifest-192x192.png',
    data: payload.data || {},
  };

  // If HTML is present, include flags so that on click we open the viewer
  if (payload.data && payload.data.html) {
    options.data.hasHtml = true;
    // Copy the html and allow_js flag into notification data so click handler
    // can forward them. NOTE: Some browsers may truncate large payloads.
    options.data.html = payload.data.html;
    if (payload.data.allow_js) options.data.allow_js = true;
  }

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', event => {
  console.log('[sw] notificationclick', event.notification && event.notification.data);
  event.notification.close();
  const data = (event.notification && event.notification.data) || {};

  // If payload included HTML, open the push viewer route with the HTML encoded in the URL
  if (data.hasHtml && data.html) {
    // Prefer direct html data if present (some browsers include it in notification data)
    const encoded = encodeURIComponent(data.html);
    const viewerUrl = `/push-viewer?html=${encoded}${data.allow_js ? '&allow_js=1' : ''}`;
    event.waitUntil(self.clients.openWindow(viewerUrl));
    return;
  }

  // If data.html wasn't stored directly, but server provided URL, open it
  const urlToOpen = data.url || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      for (let i = 0; i < windowClients.length; i++) {
        const client = windowClients[i];
        if (client.url === urlToOpen && 'focus' in client) {
          return client.focus();
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(urlToOpen);
      }
    })
  );
});

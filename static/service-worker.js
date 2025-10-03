// A minimal service worker to make the app installable.
// This is a "network-first" service worker. It tries to fetch from the network,
// and if that fails (e.g., offline), it does nothing.
// For a real offline experience, you would add caching logic here.

self.addEventListener('fetch', (event) => {
  event.respondWith(
    fetch(event.request)
  );
});
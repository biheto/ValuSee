chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === 'VALUSee_OPEN_APP') chrome.tabs.create({ url: 'http://127.0.0.1:8200/' });
});

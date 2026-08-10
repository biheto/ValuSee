chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === 'VALUSee_OPEN_APP') {
    chrome.storage.local.get({ appUrl: 'https://valusee.com' }, ({ appUrl }) => chrome.tabs.create({ url: appUrl }));
  }
});

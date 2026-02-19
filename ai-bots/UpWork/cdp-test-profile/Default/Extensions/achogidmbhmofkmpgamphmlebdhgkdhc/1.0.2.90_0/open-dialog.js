
const button = document.querySelector("#goToSettings");
button.addEventListener("click", function () {
  const extensionId = chrome.runtime.id;

  chrome.windows.getCurrent({}, function (win) {
    const id = win.id;
    const selectedText = 'Allow access to file URLs';

    const url = `chrome://extensions/?id=${extensionId}#options-section:~:text=${selectedText}`;

    const width = 752;
    const height = 670;

    const options = {
      'url': url,
      'type': 'popup',
      'width': width,
      'height': height,
      'left': win.left,
      'top': win.top,
      'focused': true
    };

    chrome.windows.create(options, function (window) {

      const createdWindow = window.id;
      if (createdWindow) {
        chrome.runtime.sendMessage({ message_key: 'open_dialog_tab_id', message_value: createdWindow });
      }

    });

    setTimeout(x => {
      chrome.windows.remove(id);
    }, 500)
  });
});

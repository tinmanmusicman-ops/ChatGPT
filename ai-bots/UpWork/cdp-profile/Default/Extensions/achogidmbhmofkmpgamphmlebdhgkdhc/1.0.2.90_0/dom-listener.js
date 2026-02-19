/******/ (() => { // webpackBootstrap
/******/ 	"use strict";
/*!*******************************************!*\
  !*** ./extension-scripts/dom-listener.ts ***!
  \*******************************************/

const body = document.querySelector('body');
if (body) {
    const observer = new MutationObserver((mutations, observer) => {
        const button = body.querySelector('.button-extension');
        if (button) {
            button.setAttribute('id', 'installed-extension');
            button.addEventListener('click', () => {
                try {
                    chrome.runtime.sendMessage({ message_key: 'notification' });
                }
                catch (e) {
                    //
                }
            });
            observer.disconnect();
        }
    });
    observer.observe(body, { childList: true, subtree: true });
}

/******/ })()
;
//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoicGRmLWJyb3dzZXItZXh0ZW5zaW9uL2Jyb3dzZXIvZG9tLWxpc3RlbmVyLmpzIiwibWFwcGluZ3MiOiI7Ozs7OztBQUNBLE1BQU0sSUFBSSxHQUFHLFFBQVEsQ0FBQyxhQUFhLENBQUMsTUFBTSxDQUFDLENBQUM7QUFFNUMsSUFBSSxJQUFJLEVBQUUsQ0FBQztJQUNULE1BQU0sUUFBUSxHQUFHLElBQUksZ0JBQWdCLENBQUMsQ0FBQyxTQUFTLEVBQUUsUUFBUSxFQUFFLEVBQUU7UUFDNUQsTUFBTSxNQUFNLEdBQUcsSUFBSSxDQUFDLGFBQWEsQ0FBQyxtQkFBbUIsQ0FBQyxDQUFDO1FBQ3ZELElBQUksTUFBTSxFQUFFLENBQUM7WUFDWCxNQUFNLENBQUMsWUFBWSxDQUFDLElBQUksRUFBRSxxQkFBcUIsQ0FBQyxDQUFDO1lBQ2pELE1BQU0sQ0FBQyxnQkFBZ0IsQ0FBQyxPQUFPLEVBQUUsR0FBRyxFQUFFO2dCQUNwQyxJQUFJLENBQUM7b0JBQ0gsTUFBTSxDQUFDLE9BQU8sQ0FBQyxXQUFXLENBQUMsRUFBRSxXQUFXLEVBQUUsY0FBYyxFQUFFLENBQUMsQ0FBQztnQkFDOUQsQ0FBQztnQkFBQyxPQUFPLENBQUMsRUFBRSxDQUFDO29CQUNiLEVBQUU7Z0JBQ0YsQ0FBQztZQUdILENBQUMsQ0FBQyxDQUFDO1lBRUgsUUFBUSxDQUFDLFVBQVUsRUFBRSxDQUFDO1FBQ3hCLENBQUM7SUFDSCxDQUFDLENBQUMsQ0FBQztJQUVILFFBQVEsQ0FBQyxPQUFPLENBQUMsSUFBSSxFQUFFLEVBQUUsU0FBUyxFQUFFLElBQUksRUFBRSxPQUFPLEVBQUUsSUFBSSxFQUFFLENBQUMsQ0FBQztBQUM3RCxDQUFDIiwic291cmNlcyI6WyJ3ZWJwYWNrOi8vcGRmLWJyb3dzZXItZXh0ZW5zaW9uLy4vZXh0ZW5zaW9uLXNjcmlwdHMvZG9tLWxpc3RlbmVyLnRzIl0sInNvdXJjZXNDb250ZW50IjpbIlxuY29uc3QgYm9keSA9IGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3IoJ2JvZHknKTtcblxuaWYgKGJvZHkpIHtcbiAgY29uc3Qgb2JzZXJ2ZXIgPSBuZXcgTXV0YXRpb25PYnNlcnZlcigobXV0YXRpb25zLCBvYnNlcnZlcikgPT4ge1xuICAgIGNvbnN0IGJ1dHRvbiA9IGJvZHkucXVlcnlTZWxlY3RvcignLmJ1dHRvbi1leHRlbnNpb24nKTtcbiAgICBpZiAoYnV0dG9uKSB7XG4gICAgICBidXR0b24uc2V0QXR0cmlidXRlKCdpZCcsICdpbnN0YWxsZWQtZXh0ZW5zaW9uJyk7XG4gICAgICBidXR0b24uYWRkRXZlbnRMaXN0ZW5lcignY2xpY2snLCAoKSA9PiB7XG4gICAgICAgIHRyeSB7XG4gICAgICAgICAgY2hyb21lLnJ1bnRpbWUuc2VuZE1lc3NhZ2UoeyBtZXNzYWdlX2tleTogJ25vdGlmaWNhdGlvbicgfSk7XG4gICAgICAgIH0gY2F0Y2ggKGUpIHtcbiAgICAgICAgLy9cbiAgICAgICAgfVxuXG5cbiAgICAgIH0pO1xuXG4gICAgICBvYnNlcnZlci5kaXNjb25uZWN0KCk7XG4gICAgfVxuICB9KTtcblxuICBvYnNlcnZlci5vYnNlcnZlKGJvZHksIHsgY2hpbGRMaXN0OiB0cnVlLCBzdWJ0cmVlOiB0cnVlIH0pO1xufVxuIl0sIm5hbWVzIjpbXSwic291cmNlUm9vdCI6IiJ9
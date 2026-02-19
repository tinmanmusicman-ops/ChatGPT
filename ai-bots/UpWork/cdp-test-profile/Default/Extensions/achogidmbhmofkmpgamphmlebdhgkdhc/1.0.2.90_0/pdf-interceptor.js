/******/ (() => { // webpackBootstrap
/******/ 	"use strict";
/*!**********************************************!*\
  !*** ./extension-scripts/pdf-interceptor.ts ***!
  \**********************************************/

if (document.contentType === 'application/pdf') {
    const pdfUrl = window.location.href;
    chrome.runtime.sendMessage({ pdfUrl: pdfUrl });
}

/******/ })()
;
//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoicGRmLWJyb3dzZXItZXh0ZW5zaW9uL2Jyb3dzZXIvcGRmLWludGVyY2VwdG9yLmpzIiwibWFwcGluZ3MiOiI7Ozs7OztBQUNBLElBQUksUUFBUSxDQUFDLFdBQVcsS0FBSyxpQkFBaUIsRUFBRSxDQUFDO0lBRS9DLE1BQU0sTUFBTSxHQUFHLE1BQU0sQ0FBQyxRQUFRLENBQUMsSUFBSSxDQUFDO0lBQ3BDLE1BQU0sQ0FBQyxPQUFPLENBQUMsV0FBVyxDQUFDLEVBQUUsTUFBTSxFQUFFLE1BQU0sRUFBRSxDQUFDLENBQUM7QUFDakQsQ0FBQyIsInNvdXJjZXMiOlsid2VicGFjazovL3BkZi1icm93c2VyLWV4dGVuc2lvbi8uL2V4dGVuc2lvbi1zY3JpcHRzL3BkZi1pbnRlcmNlcHRvci50cyJdLCJzb3VyY2VzQ29udGVudCI6WyJcbmlmIChkb2N1bWVudC5jb250ZW50VHlwZSA9PT0gJ2FwcGxpY2F0aW9uL3BkZicpIHtcblxuICBjb25zdCBwZGZVcmwgPSB3aW5kb3cubG9jYXRpb24uaHJlZjtcbiAgY2hyb21lLnJ1bnRpbWUuc2VuZE1lc3NhZ2UoeyBwZGZVcmw6IHBkZlVybCB9KTtcbn1cbiJdLCJuYW1lcyI6W10sInNvdXJjZVJvb3QiOiIifQ==
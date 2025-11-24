import imaplib
from gmail_search_utils import (
    IMAP_HOST, search_unseen_uids, fetch_headers_peek,
    mark_seen_by_uid, DedupeCache, stable_identity
)

# ====== CONFIG ======
USER = "tinmanmusicman@gmail.com"              # <-- your Gmail address
APP_PASSWORD = "jwhk piox dqnt jxqc"    # <-- 16-char app password (no spaces)
SUBJECT_TERM = "672-7323"             # <-- term to match in Subject
INCLUDE_ALL_MAIL = True               # search All Mail if INBOX is empty
PROCESS_LIMIT = 5                     # safety cap per run
# ====================

def main():
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    imap.login(USER, APP_PASSWORD)
    cache = DedupeCache("processed_ids.json")

    try:
        uids = search_unseen_uids(imap, SUBJECT_TERM, include_all_mail=INCLUDE_ALL_MAIL)
        if not uids:
            print("No matching UNSEEN messages found.")
            return

        print(f"Found {len(uids)} matching UNSEEN message(s).")
        count = 0
        for uid in uids:
            if count >= PROCESS_LIMIT:
                break

            subject, sender, msgid = fetch_headers_peek(imap, uid)
            ident = stable_identity(imap, uid, msgid)

            print(f"- UID {uid.decode()} :: {subject} | {sender}")
            if ident and cache.seen(ident):
                print("  -> already processed (dedupe). Skipping.")
                continue

            # ===== PROCESS YOUR MESSAGE HERE =====
            # (e.g., parse body, write to Google Sheet, etc.)

            # Mark as read
            mark_seen_by_uid(imap, uid)
            print("  -> marked as read.")

            if ident:
                cache.add(ident)
                print("  -> stored dedupe fingerprint.")

            count += 1

        print("Done.")
    finally:
        imap.logout()

if __name__ == "__main__":
    main()

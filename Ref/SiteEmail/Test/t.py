import imaplib, email, datetime

IMAP_HOST = "imap.gmail.com"
USER = "tinmanmusicman@gmail.com"
APP_PASSWORD = "jwhk piox dqnt jxqc"
TERM = "672-7323"

def sel(imap, box):
    typ, data = imap.select(box, readonly=True)
    print(f"SELECT {box} -> {typ} {data}")
    return typ == "OK"

def count(imap, label, *args):
    typ, data = imap.uid("SEARCH", *args)
    ids = data[0].split() if typ == "OK" and data and data[0] else []
    print(f"{label}: {typ} count={len(ids)}")
    return ids

def peek_subject(imap, uid):
    typ, data = imap.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)] X-GM-LABELS)")
    if typ != "OK" or not data or not data[0]:
        return "<?>"
    try:
        hdr = data[0][1]
        msg = email.message_from_bytes(hdr)
        return msg.get("Subject", "").strip()
    except Exception:
        return "<parse-error>"

def main():
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    imap.login(USER, APP_PASSWORD)

    try:
        for box in ("INBOX", '"[Gmail]/All Mail"'):
            if not sel(imap, box):
                continue

            count(imap, f"{box} RAW primary+unread",
                  "X-GM-RAW", f'"category:primary subject:{TERM} is:unread"')

            count(imap, f"{box} RAW unread (no category)",
                  "X-GM-RAW", f'"subject:{TERM} is:unread"')

            count(imap, f"{box} IMAP UNSEEN SUBJECT",
                  None, f'(UNSEEN SUBJECT {TERM})')

            ids_all = count(imap, f"{box} IMAP SUBJECT (seen+unseen)",
                            None, f'(SUBJECT {TERM})')

            for uid in ids_all[-5:]:
                print(f"  {box} uid={uid.decode()} subj={peek_subject(imap, uid)}")

        if sel(imap, '"[Gmail]/All Mail"'):
            since = (datetime.date.today() - datetime.timedelta(days=21)).strftime("%d-%b-%Y")
            ids = count(imap, 'All Mail SINCE + SUBJECT', None, f'(SINCE {since} SUBJECT {TERM})')
            for uid in ids[-5:]:
                print(f'  All Mail uid={uid.decode()} subj={peek_subject(imap, uid)}')

    finally:
        imap.logout()

if __name__ == "__main__":
    main()

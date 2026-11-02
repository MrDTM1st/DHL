"""
Which spreadsheets in the mailbox hold orders to email.

The Haulier Extract, and the batch files named by their file or their email's subject (BS Batch, BS Ack, BS OITS). And
the Master sheets a batch comes to the planners as - "Master - Synergy_DHL_Haulier_Extract_ 261027 - BS.xlsx", and "...
- INF.xlsx" for its Inframat lines. They were skipped as "processed output, never a source", but an order can be on
nothing else: of 16 Region 2 orders on them in the 60 days to 02/11, 10 were on no other sheet and had been emailed by
hand, and the two nobody had got to went unemailed (his 02/11: "we haven't emailed this order, even though we have the
Excel sheet in our emails"). Any other file called Master is still ignored.
"""
MASTER = "master - "


def is_wanted(filename, subject, source_prefix, markers):
    low = (filename or "").lower()
    if low.startswith("master"):
        return low.startswith(MASTER + source_prefix)
    if low.startswith(source_prefix):
        return True
    if low.endswith((".xlsx", ".xlsm")):
        subj = (subject or "").lower()
        return any(m in low or m in subj for m in markers)
    return False

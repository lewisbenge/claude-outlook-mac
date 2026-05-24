on run argv
  set messageLimit to 50
  set previewMax to 500
  if (count of argv) > 0 then set messageLimit to item 1 of argv as integer
  if (count of argv) > 1 then set previewMax to item 2 of argv as integer

  tell application "Microsoft Outlook"
    set inboxFolder to inbox of default account
    set inboxMessages to messages of inboxFolder
    set maxCount to count of inboxMessages
    if maxCount is 0 then return "[]"
    if messageLimit < maxCount then set maxCount to messageLimit

    set jsonRows to "["
    repeat with i from 1 to maxCount
      set msg to item i of inboxMessages
      set msgPreview to ""
      try
        set msgPreview to content of msg as text
      end try
      if (length of msgPreview) > previewMax then set msgPreview to text 1 thru previewMax of msgPreview
      set row to "{\"message_id\":\"" & (id of msg as text) & "\",\"subject\":\"" & my e(subject of msg as text) & "\",\"sender\":\"" & my e(sender of msg as text) & "\",\"recipients\":\"\",\"cc\":\"\",\"received_at\":\"" & my e(time received of msg as text) & "\",\"folder\":\"Inbox\",\"body_preview\":\"" & my e(msgPreview) & "\"}"
      if i > 1 then set jsonRows to jsonRows & ","
      set jsonRows to jsonRows & row
    end repeat
    return jsonRows & "]"
  end tell
end run

on e(s)
  set s to my r("\\", "\\\\", s)
  set s to my r("\"", "\\\"", s)
  set s to my r(return, " ", s)
  set s to my r(linefeed, " ", s)
  return s
end e

on r(f, t, subj)
  set AppleScript's text item delimiters to f
  set parts to text items of subj
  set AppleScript's text item delimiters to t
  set subj to parts as text
  set AppleScript's text item delimiters to ""
  return subj
end r

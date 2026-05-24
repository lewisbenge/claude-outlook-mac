on run argv
  set messageLimit to 25
  set previewMax to 500
  set sinceDays to -1
  set unreadOnly to false
  if (count of argv) > 0 then set messageLimit to item 1 of argv as integer
  if (count of argv) > 1 then set previewMax to item 2 of argv as integer
  if (count of argv) > 2 then set sinceDays to item 3 of argv as integer
  if (count of argv) > 3 then set unreadOnly to ((item 4 of argv as text) is "true")

  tell application "Microsoft Outlook"
    set inboxFolder to inbox of default account
    set inboxMessages to messages of inboxFolder
    set cutoffDate to (current date) - (sinceDays * days)

    set jsonRows to "["
    set emitted to 0
    repeat with msg in inboxMessages
      if emitted ≥ messageLimit then exit repeat
      set includeMsg to true
      if sinceDays ≥ 0 then
        try
          if (time received of msg) < cutoffDate then set includeMsg to false
        on error
          set includeMsg to false
        end try
      end if
      if unreadOnly then
        try
          if read status of msg is true then set includeMsg to false
        on error
          -- if unsupported, keep as include
        end try
      end if

      if includeMsg then
        set msgPreview to ""
        try
          set msgPreview to content of msg as text
        end try
        if (length of msgPreview) > previewMax then set msgPreview to text 1 thru previewMax of msgPreview
        set toLine to ""
        set ccLine to ""
        try
          set toLine to my e((to recipients of msg) as text)
        end try
        try
          set ccLine to my e((cc recipients of msg) as text)
        end try

        set row to "{\"message_id\":\"" & (id of msg as text) & "\",\"subject\":\"" & my e(subject of msg as text) & "\",\"sender\":\"" & my e(sender of msg as text) & "\",\"recipients\":\"" & toLine & "\",\"cc\":\"" & ccLine & "\",\"received_at\":\"" & my e(time received of msg as text) & "\",\"folder\":\"Inbox\",\"body_preview\":\"" & my e(msgPreview) & "\"}"
        if emitted > 0 then set jsonRows to jsonRows & ","
        set jsonRows to jsonRows & row
        set emitted to emitted + 1
      end if
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

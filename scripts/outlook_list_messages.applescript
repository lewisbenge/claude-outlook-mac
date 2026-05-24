on run argv
  set messageLimit to 50
  if (count of argv) > 0 then
    set messageLimit to item 1 of argv as integer
  end if

  tell application "Microsoft Outlook"
    set inboxFolder to inbox of default account
    set inboxMessages to messages of inboxFolder
    set maxCount to (count of inboxMessages)
    if messageLimit < maxCount then
      set maxCount to messageLimit
    end if

    set jsonRows to "["
    repeat with i from 1 to maxCount
      set msg to item i of inboxMessages
      set msgId to id of msg as text
      set msgSubject to subject of msg as text
      set msgSender to sender of msg as text
      set msgRecipients to ""
      set msgCC to ""
      set msgDate to time received of msg as text
      set msgPreview to content of msg as text
      if (length of msgPreview) > 220 then
        set msgPreview to text 1 thru 220 of msgPreview
      end if

      set escapedSubject to my escape_json(msgSubject)
      set escapedSender to my escape_json(msgSender)
      set escapedRecipients to my escape_json(msgRecipients)
      set escapedCC to my escape_json(msgCC)
      set escapedDate to my escape_json(msgDate)
      set escapedPreview to my escape_json(msgPreview)

      set row to "{\"message_id\":\"" & msgId & "\",\"subject\":\"" & escapedSubject & "\",\"sender\":\"" & escapedSender & "\",\"recipients\":\"" & escapedRecipients & "\",\"cc\":\"" & escapedCC & "\",\"received_at\":\"" & escapedDate & "\",\"folder\":\"Inbox\",\"body_preview\":\"" & escapedPreview & "\"}"

      if i > 1 then
        set jsonRows to jsonRows & ","
      end if
      set jsonRows to jsonRows & row
    end repeat
    set jsonRows to jsonRows & "]"
    return jsonRows
  end tell
end run

on escape_json(s)
  set s to my replace_text("\\", "\\\\", s)
  set s to my replace_text("\"", "\\\"", s)
  set s to my replace_text(return, " ", s)
  set s to my replace_text(linefeed, " ", s)
  return s
end escape_json

on replace_text(find, repl, subj)
  set AppleScript's text item delimiters to find
  set parts to text items of subj
  set AppleScript's text item delimiters to repl
  set subj to parts as text
  set AppleScript's text item delimiters to ""
  return subj
end replace_text

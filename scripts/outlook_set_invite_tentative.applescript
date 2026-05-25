on run argv
  if (count of argv) is 0 then return "unsupported"
  set targetId to item 1 of argv as text
  try
    tell application "Microsoft Outlook"
      set inboxFolder to inbox of default account
      set inboxMessages to messages of inboxFolder
      repeat with msg in inboxMessages
        if (id of msg as text) is targetId then
          try
            set meeting response of msg to tentative meeting response
            return "ok"
          on error
            return "unsupported"
          end try
        end if
      end repeat
    end tell
  on error
    return "unsupported"
  end try
  return "unsupported"
end run

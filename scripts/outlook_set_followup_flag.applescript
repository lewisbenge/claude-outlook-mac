on run argv
  if (count of argv) < 1 then
    return "UNSUPPORTED"
  end if
  set msgId to item 1 of argv
  tell application "Microsoft Outlook"
    set targetMsg to missing value
    repeat with aMsg in messages of inbox
      try
        if (id of aMsg as string) is equal to msgId then
          set targetMsg to aMsg
          exit repeat
        end if
      end try
    end repeat
    if targetMsg is missing value then
      return "UNSUPPORTED"
    end if

    try
      set flag status of targetMsg to flagged
      return "OK"
    on error
      return "UNSUPPORTED"
    end try
  end tell
end run

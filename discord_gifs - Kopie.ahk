#Requires AutoHotkey v2.0
; ======================================
; Discord Zeilen-Sender
; Taste: I
; Pro Druck: nächste 4 Zeilen als EINE Nachricht
; Am Ende: Hinweis "Fertig!" und zurück auf Anfang
; ======================================
GIF_FILE := "D:\geiloderso\ahk\discord_favoriten_gifs.txt"
global currentIndex := 1

i::
{
    global currentIndex

    if !FileExist(GIF_FILE) {
        MsgBox("Datei nicht gefunden:`n" GIF_FILE)
        return
    }

    content := FileRead(GIF_FILE)

    ; Alle nicht-leeren Zeilen einlesen
    lines := []
    for line in StrSplit(content, "`n", "`r") {
        if Trim(line) != ""
            lines.Push(Trim(line))
    }

    if lines.Length = 0 {
        MsgBox("Keine Zeilen in der Datei gefunden!")
        return
    }

    ; Die nächsten 4 Zeilen zu EINER Nachricht zusammenbauen
    message := ""
    loop 4 {
        if currentIndex > lines.Length
            break
        message .= lines[currentIndex] . "`n"
        currentIndex++
    }

    ; Senden
    A_Clipboard := RTrim(message, "`n")
    Sleep(50)
    Send("^v")
    Sleep(50)
    Send("{Enter}")

    ; Prüfen ob das die letzte Nachricht war
    if currentIndex > lines.Length {
        currentIndex := 1
        MsgBox("Fertig! Das war die letzte Nachricht. Es geht beim nächsten Druck wieder von vorne los.")
    }
}
import subprocess
import sys
import time
import os

RESTART_DELAY = 5
MAX_RESTARTS = 100
restart_count = 0

def main():
    global restart_count
    
    while restart_count < MAX_RESTARTS:
        restart_count += 1
        print(f"[Restart] Bot gestartet (Versuch {restart_count}/{MAX_RESTARTS})")
        
        try:
            process = subprocess.run(
                [sys.executable, "bot.py"],
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            exit_code = process.returncode
            print(f"[Restart] Bot beendet mit Code {exit_code}")
        except KeyboardInterrupt:
            print("[Restart] Manueller Abbruch")
            sys.exit(0)
        except Exception as e:
            print(f"[Restart] Fehler: {e}")
            exit_code = 1
        
        if exit_code == 0:
            print("[Restart] Sauberes Ende - kein Restart noetig")
            break
        
        print(f"[Restart] Neustart in {RESTART_DELAY} Sekunden...")
        time.sleep(RESTART_DELAY)
    
    if restart_count >= MAX_RESTARTS:
        print(f"[Restart] Maximale Anzahl an Restarts erreicht ({MAX_RESTARTS})")

if __name__ == "__main__":
    main()

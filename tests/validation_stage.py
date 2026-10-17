"""Validation-only child gate. Start commands only after lifecycle Job assignment."""
import json
import subprocess
import sys

if __name__=='__main__':
    command=json.load(sys.stdin)
    if not isinstance(command,list) or not command or not all(isinstance(v,str) for v in command):
        raise SystemExit('Invalid validation command')
    result=subprocess.run(command)
    raise SystemExit(result.returncode)
